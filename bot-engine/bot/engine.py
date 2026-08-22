"""
Bot Engine - The brain that ties strategy + trader together.

Runs in a background thread per symbol, polls klines on the configured interval,
runs the strategy, and executes trades based on the signal.

Supports:
- Multi-symbol trading (parallel threads, one per coin)
- Amount mode: 'fixed' USDT  OR  'percent' of wallet balance
- Emits events via Flask-SocketIO for the UI to consume.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from .strategy import EMAQuadStrategy, Signal, StrategyResult
from .trader import BinanceFuturesTrader
from .notifier import Notifier

logger = logging.getLogger(__name__)


def get_trader(config: dict):
    """Factory: return the correct trader based on config['exchange']."""
    exchange = (config.get("exchange") or "binance").lower()
    if exchange == "weex":
        from .weex_trader import WEEXFuturesTrader
        return WEEXFuturesTrader(
            api_key=config["api_key"],
            api_secret=config["api_secret"],
            passphrase=config.get("api_passphrase", ""),
            testnet=config.get("testnet", True),
        )
    # Default: Binance
    return BinanceFuturesTrader(
        api_key=config["api_key"],
        api_secret=config["api_secret"],
        testnet=config.get("testnet", True),
    )


class SymbolWorker(threading.Thread):
    """One worker per symbol. Runs strategy loop independently."""

    def __init__(self, engine, symbol: str, config: dict, leverage_ready: threading.Event = None):
        super().__init__(daemon=True, name=f"worker-{symbol}")
        self.engine = engine
        self.symbol = symbol
        self.config = config
        self.stop_event = threading.Event()
        self.last_signal = Signal.HOLD
        self.candles_processed = 0
        self.trades_today = 0
        self._last_trade_date = datetime.now(timezone.utc).date()
        self.last_check = None
        # Strict mode: bot only trades on FRESH crosses.
        self.waiting_for_new_cross = True
        # Track what position we THINK is open (for sync detection).
        self.expected_pos_side = None
        # ===== SOFTWARE SL/TP WATCHDOG STATE =====
        # When a position is open, these store the SL/TP prices.
        # Bot polls mark_price every tick and closes position if hit.
        # This works on ALL exchanges (no exchange-specific order types needed).
        self.sl_price = None       # Stop Loss price (None = no SL active)
        self.tp_price = None       # Take Profit price (None = no fixed-TP active)
        self.entry_price = None    # Entry price of current position
        self.position_side = None  # "LONG" / "SHORT" / None
        # ===== TP MODE STATE =====
        # tp_mode controls how Take Profit triggers:
        #   'fixed'        -> TP = entry +/- (SL% x 3)  [classic 1:3 RR]
        #   'ema_reversal' -> TP when EMA55 flips to OPPOSITE extreme
        #                     (LONG opened at EMA55 BOTTOM -> TP when EMA55 TOP)
        #   'both'         -> whichever triggers FIRST (fixed price OR EMA flip)
        # `entry_signal` remembers the signal that opened the current position
        # (BUY or SELL) so we can detect the opposite flip on later ticks.
        self.tp_mode = "both"             # updated from cfg on entry
        self.entry_signal = None          # Signal.BUY / Signal.SELL / None
        self.ema_reversal_tp_fired = False  # one-shot guard per position
        # After an EMA-reversal TP, we must re-enter the OPPOSITE side
        # immediately — even if the exchange hasn't cleared the old position
        # yet (API lag). This flag forces that re-entry on the next tick.
        self.reversal_pending_side = None  # "LONG" / "SHORT" / None
        self._last_df = None  # Cache last klines DataFrame for instant chart update
        self._last_mark_price = None  # Cache last mark price
        self._last_cross_time = 0  # Timestamp of last cross (prevent rapid crosses)
        # Per-worker strategy instance — CRITICAL FIX: prevents multi-coin workers
        # from overwriting each other's cross detection and reversal state.
        self.strategy = EMAQuadStrategy()
        # Leverage readiness event — workers wait on this before trading
        self._leverage_ready = leverage_ready

    def run(self):
        poll_seconds = BotEngine._poll_seconds(self.config["timeframe"])
        self.engine._emit("log", {
            "level": "info",
            "msg": f"[{self.symbol}] Worker started. Polling every {poll_seconds}s."
        })
        # Wait for leverage to be set before starting the main loop
        if self._leverage_ready is not None:
            self.engine._emit("log", {
                "level": "info",
                "msg": f"[{self.symbol}] Waiting for leverage to be configured..."
            })
            self._leverage_ready.wait(timeout=30)
            if not self._leverage_ready.is_set():
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"[{self.symbol}] Leverage setup timed out (30s). Proceeding with default leverage."
                })
        try:
            # Pre-seed: fetch klines once to set strategy state
            df = self.engine.trader.get_klines(self.symbol, interval=self.config["timeframe"], limit=200)
            self._last_df = df
            if df is not None and len(df) >= 60:
                seed_result = self.strategy.analyze(df)
                if seed_result:
                    self.engine._emit("log", {
                        "level": "info",
                        "msg": (f"[{self.symbol}] Startup: signal={seed_result.signal.value}, "
                                f"candles={len(df)}. Waiting for FRESH cross.")
                    })
                    # Emit chart data immediately for active symbol
                    if self.engine.active_symbol == self.symbol:
                        self.engine._emit("chart_data", {
                            "symbol": self.symbol,
                            "candles": self._candles_to_list(df),
                            "emas": self._emas_to_list(df),
                        })
                        indicators = self.strategy.latest_indicators(df)
                        try:
                            mp = self.engine.trader.get_mark_price(self.symbol)
                        except Exception:
                            mp = float(df.iloc[-1]["close"])
                        self.engine._emit("indicators", {
                            "symbol": self.symbol,
                            **indicators,
                            "mark_price": mp,
                        })
                        self.engine._emit("log", {
                            "level": "success",
                            "msg": f"[{self.symbol}] ✅ Chart data sent ({len(df)} candles)"
                        })
            else:
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"[{self.symbol}] Not enough candles ({len(df) if df is not None else 0}). Need 60+."
                })
        except Exception as e:
            logger.error(f"[{self.symbol}] Pre-seed FAILED: {e}")
            self.engine._emit("log", {
                "level": "error",
                "msg": f"[{self.symbol}] Pre-seed failed: {str(e)[:100]}"
            })

        while not self.stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.exception(f"[{self.symbol}] tick error")
                self.engine._emit("log", {
                    "level": "error",
                    "msg": f"[{self.symbol}] tick error: {str(e)[:100]}"
                })
            for _ in range(poll_seconds):
                if self.stop_event.is_set():
                    break
                time.sleep(1)

        self.engine._emit("log", {
            "level": "info",
            "msg": f"[{self.symbol}] Worker stopped."
        })

    def _tick(self):
        cfg = self.config
        symbol = self.symbol
        timeframe = cfg["timeframe"]

        # Safety: if trader is None (after force stop), skip tick
        if self.engine.trader is None:
            return

        # ===== RESET trades_today AT MIDNIGHT UTC =====
        today = datetime.now(timezone.utc).date()
        if today != self._last_trade_date:
            if self.trades_today > 0:
                self.engine._emit("log", {
                    "level": "info",
                    "msg": f"[{symbol}] 📅 New UTC day — trades_today reset from {self.trades_today} to 0"
                })
            self.trades_today = 0
            self._last_trade_date = today

        # 1. Fetch klines (with auto-retry inside trader)
        try:
            df = self.engine.trader.get_klines(symbol, interval=timeframe, limit=200)
            self._last_df = df  # Cache for instant chart update
        except Exception as e:
            logger.error(f"[{symbol}] Failed to fetch klines after retries: {e}")
            # Don't spam logs every tick - only log every 12th tick (~1 min)
            if self.candles_processed % 12 == 0:
                self.engine._emit("log", {
                    "level": "error",
                    "msg": f"[{symbol}] Klines fetch fail: {str(e)[:100]}. Chart empty - API error."
                })
            # Try to use cached df if available
            if self._last_df is not None:
                df = self._last_df
            else:
                return  # No cached data, skip this tick

        self.candles_processed += 1
        self.last_check = datetime.now(timezone.utc).isoformat()

        # 2. Compute indicators
        indicators = self.strategy.latest_indicators(df)
        # Get mark price - use close price as fallback (mark price API may fail)
        try:
            mark_price = self.engine.trader.get_mark_price(symbol)
            if mark_price is None or mark_price <= 0:
                mark_price = float(df.iloc[-1]["close"]) if df is not None and len(df) else 0.0
            self._last_mark_price = mark_price
        except Exception as e:
            logger.warning(f"[{symbol}] mark_price fetch failed: {e}, using close price")
            mark_price = self._last_mark_price or float(df.iloc[-1]["close"]) if df is not None and len(df) else 0.0

        # 3. Push indicator update (ALWAYS for active symbol, even if bot just started)
        is_active = (self.engine.active_symbol == symbol or self.engine.active_symbol is None)
        if is_active:
            self.engine._emit("indicators", {
                "symbol": symbol,
                **indicators,
                "mark_price": mark_price,
            })

        # 4. Push chart data for the active/selected coin (EVERY TICK = live update)
        if is_active:
            candles = self._candles_to_list(df)
            emas = self._emas_to_list(df)
            if candles:
                self.engine._emit("chart_data", {
                    "symbol": symbol,
                    "candles": candles,
                    "emas": emas,
                })

        # 5. Position update
        try:
            pos = self.engine.trader.get_position(symbol)
        except Exception as e:
            logger.warning(f"[{symbol}] get_position failed: {e}")
            class DefaultPos:
                side = "NONE"; size = 0; entry_price = 0; mark_price = mark_price if 'mark_price' in dir() else 0.0
                unrealized_pnl = 0; leverage = 1
            pos = DefaultPos()

        # 5.5 Strategy analysis — done EARLY (before SL/TP check) so we can
        # detect EMA55 reversal-style TP triggers. `result` is reused below
        # for entry logic too (no second analyze() call — strategy has state).
        result = self.strategy.analyze(df)
        if result is None:
            self.engine._emit("log", {
                "level": "warn",
                "msg": f"[{symbol}] Not enough data yet (need >= {self.strategy.ema_long + 5} candles)."
            })
            # Still emit position so UI stays in sync
            self.engine._emit("position", {
                "symbol": symbol,
                "side": pos.side,
                "size": pos.size,
                "entry_price": pos.entry_price,
                "mark_price": pos.mark_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "leverage": pos.leverage,
            })
            return

        signal = result.signal
        e8, e13, e21, e55 = result.ema_8, result.ema_13, result.ema_21, result.ema_55

        # ===== SOFTWARE SL/TP WATCHDOG CHECK =====
        # Check if SL or TP has been hit BEFORE doing anything else.
        # This runs on every tick (5s) - fast enough to catch price moves.
        # Pass `result` so we can detect EMA55-reversal TP (signal flipped
        # to the OPPOSITE of the entry signal).
        if pos.side != "NONE" and pos.size != 0 and pos.mark_price > 0:
            # ===== DEBUG LOG: show position state every ~30s (6 ticks at 5s) =====
            # This helps the user see that the reversal logic is working.
            if self.candles_processed % 6 == 0:
                entry_sig_str = self.entry_signal.value if self.entry_signal else "N/A"
                cur_sig_str = result.signal.value
                # Check if reversal condition is met (for visibility)
                reversal_pending = False
                reversal_reason = ""
                if self.entry_signal is not None:
                    if pos.side == "LONG" and self.entry_signal == Signal.BUY and result.signal == Signal.SELL:
                        reversal_pending = True
                        reversal_reason = "EMA55 flipped to TOP, LONG should close + SHORT open"
                    elif pos.side == "SHORT" and self.entry_signal == Signal.SELL and result.signal == Signal.BUY:
                        reversal_pending = True
                        reversal_reason = "EMA55 flipped to BOTTOM, SHORT should close + LONG open"

                if reversal_pending:
                    self.engine._emit("log", {
                        "level": "warn",
                        "msg": (f"[{symbol}] 🔄 REVERSAL PENDING | "
                                f"Pos={pos.side} (entry_sig={entry_sig_str}) | "
                                f"Current signal={cur_sig_str} | "
                                f"Will close + open opposite THIS TICK")
                    })
                else:
                    self.engine._emit("log", {
                        "level": "info",
                        "msg": (f"[{symbol}] 📊 Position monitor | "
                                f"Pos={pos.side} (entry_sig={entry_sig_str}) | "
                                f"Current signal={cur_sig_str} | "
                                f"Mark={pos.mark_price:.4f} Entry={self.entry_price:.4f} | "
                                f"SL={self.sl_price:.4f} TP={self.tp_price if self.tp_price else 'EMA-flip'} | "
                                f"No reversal yet (signal same as entry)")
                    })

            sl_hit, tp_hit, reason = self._check_software_sl_tp(pos, result)
            if sl_hit or tp_hit:
                # Detect EMA-reversal TP (reason contains "EMA55")
                is_ema_reversal_tp = (tp_hit and "EMA55" in reason)
                tp_kind = "EMA-REVERSAL" if is_ema_reversal_tp else "FIXED"
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"[{symbol}] ⚡ {reason} -> closing position @ {pos.mark_price:.4f}"
                })
                # Calculate PnL
                entry = self.entry_price or pos.entry_price
                if pos.side == "LONG":
                    pnl_pct = (pos.mark_price - entry) / entry * 100 if entry > 0 else 0
                else:
                    pnl_pct = (entry - pos.mark_price) / entry * 100 if entry > 0 else 0
                close_side_label = pos.side
                # Close position
                close = self.engine.trader.close_position(symbol)
                self._log_order(close, f"[{symbol}] {reason}")
                if close.get("success"):
                    self.trades_today += 1
                    # Reset SL/TP state
                    self.sl_price = None
                    self.tp_price = None
                    self.entry_price = None
                    self.position_side = None
                    self.entry_signal = None
                    self.ema_reversal_tp_fired = False
                    self.expected_pos_side = None
                    self.waiting_for_new_cross = True
                    # ===== REVERSAL LOGIC =====
                    # If EMA55 just flipped (reversal TP), the signal has
                    # ALREADY crossed to the opposite side. We want the bot
                    # to immediately open the opposite position on the next
                    # tick — NOT wait for EMA55 to go to HOLD first.
                    # So we use reset_for_reversal() instead of reset_cross_state().
                    if is_ema_reversal_tp:
                        self.strategy.reset_for_reversal()
                        # Clear the 30s cross cooldown so the reversal
                        # is NOT blocked (the EMA55 flip is a real cross,
                        # not a false positive).
                        self._last_cross_time = 0
                        opposite_side = "LONG" if close_side_label == "SHORT" else "SHORT"
                        # Force immediate re-entry on the next tick, even if the
                        # exchange hasn't fully cleared the old position yet.
                        self.reversal_pending_side = opposite_side
                        self.engine._emit("log", {
                            "level": "info",
                            "msg": (f"[{symbol}] 🔄 EMA55 REVERSAL detected — bot will open "
                                    f"{opposite_side} on next tick (immediate reversal, no waiting)")
                        })
                    else:
                        # SL or fixed-TP: require fresh cross (wait for HOLD first)
                        self.strategy.reset_cross_state()
                    # Notification
                    try:
                        if sl_hit:
                            self.engine.notifier.notify_sl(
                                symbol, close_side_label, entry, pos.mark_price, pnl_pct
                            )
                        elif tp_hit:
                            self.engine.notifier.notify_tp(
                                symbol, close_side_label, entry, pos.mark_price, pnl_pct,
                                {"ema_8": e8, "ema_13": e13,
                                 "ema_21": e21, "ema_55": e55}
                            )
                    except Exception as e:
                        logger.error("SL/TP notification failed: %s", e)
                # Position closed - emit signal for UI and return
                self.engine._emit("signal", {
                    "symbol": symbol,
                    "signal": result.signal.value,
                    "reason": result.reason,
                    "emas": {"ema_8": e8, "ema_13": e13,
                             "ema_21": e21, "ema_55": e55},
                })
                return

        # ===== POSITION SYNC CHECK =====
        actual_side = pos.side if (pos.side in ("LONG", "SHORT") and pos.size != 0) else "NONE"
        if actual_side != self.expected_pos_side:
            if self.expected_pos_side is not None and actual_side == "NONE":
                # Bot expected a position but it's gone now (user closed or SL/TP hit on exchange)
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": (f"[{symbol}] ⚠️ Position closed (SL/TP hit on exchange or manual close). "
                            f"Bot expected {self.expected_pos_side} but found NONE. "
                            f"Waiting for NEW cross before next trade.")
                })
                self.expected_pos_side = None
                self.waiting_for_new_cross = True  # Strict mode: must wait for fresh cross
                self.strategy.reset_cross_state()
            elif actual_side != "NONE" and self.expected_pos_side != actual_side and self.reversal_pending_side is None:
                # Position flipped or new opposite position opened externally
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": (f"[{symbol}] ⚠️ External trade detected! "
                            f"Bot expected {self.expected_pos_side or 'NONE'} but found {actual_side}. "
                            f"Syncing state to {actual_side}.")
                })
                self.expected_pos_side = actual_side
                try:
                    self.engine.notifier.send(
                        f"⚠️ External Trade Detected - {symbol}",
                        f"Position changed externally!\n\n"
                        f"Symbol: {symbol}\n"
                        f"Bot expected: {self.expected_pos_side or 'NONE'}\n"
                        f"Actual: {actual_side}\n"
                        f"Size: {pos.size}\n\n"
                        f"Bot state synced."
                    )
                except Exception as e:
                    logger.error("External trade notification failed: %s", e)

        # ===== AUTO-RESTORE SL/TP ON STARTUP =====
        # If there's an open position but SL/TP is not set (e.g., after bot restart),
        # automatically set SL/TP based on entry price from exchange.
        # Respects `tp_mode` from config:
        #   - For 'ema_reversal' we still need entry_signal to detect the flip.
        #     Since we don't know the original entry signal after a restart,
        #     we infer it from `actual_side` (LONG -> BUY, SHORT -> SELL).
        #     This is correct because LONG positions are only opened on BUY
        #     signals and SHORT positions only on SELL signals in this strategy.
        if actual_side != "NONE" and self.sl_price is None and self.tp_price is None and self.reversal_pending_side is None:
            entry = pos.entry_price
            if entry > 0:
                sl_pct_val = float(cfg.get("stop_loss_pct", 2))
                tp_pct_val = sl_pct_val * 3
                tp_mode_val = (cfg.get("tp_mode") or "both").lower()
                if tp_mode_val not in ("fixed", "ema_reversal", "both"):
                    tp_mode_val = "both"
                # Infer original entry signal from current side (see comment above)
                inferred_entry_signal = Signal.BUY if actual_side == "LONG" else Signal.SELL
                self._set_software_sl_tp(
                    symbol, actual_side, entry, sl_pct_val, tp_pct_val,
                    tp_mode=tp_mode_val,
                    entry_signal=inferred_entry_signal,
                )
                # Build a TP description for the log
                if tp_mode_val == "ema_reversal":
                    tp_log = "TP=EMA55-REVERSAL"
                elif tp_mode_val == "both":
                    tp_log = f"TP=BOTH (fixed {self.tp_price:.4f} OR EMA55-flip)"
                else:
                    tp_log = f"TP={self.tp_price:.4f}"
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": (f"[{symbol}] ⚠️ AUTO-RESTORED SL/TP for existing {actual_side} position | "
                            f"Entry={entry:.4f} | SL={self.sl_price:.4f} | {tp_log} | "
                            f"tp_mode={tp_mode_val} | SL/TP auto-restored after bot restart.")
                })

        self.engine._emit("position", {
            "symbol": symbol,
            "side": pos.side,
            "size": pos.size,
            "entry_price": pos.entry_price,
            "mark_price": pos.mark_price,
            "unrealized_pnl": pos.unrealized_pnl,
            "leverage": pos.leverage,
        })

        # (Strategy analysis was already done above — `result`, `signal`,
        #  `e8/e13/e21/e55` are all available. No second analyze() call.)

        mode = cfg.get("mode", "both")

        # Emit signal to UI (for indicator panel) - but DON'T spam logs
        # Only emit if signal changed from last tick
        signal_changed = (signal != self.last_signal)
        self.engine._emit("signal", {
            "symbol": symbol,
            "signal": signal.value,
            "reason": result.reason,
            "emas": {"ema_8": e8, "ema_13": e13, "ema_21": e21, "ema_55": e55},
            "just_crossed": result.just_crossed,
        })

        # Signal notification ONLY on FRESH cross (instant, no delay)
        if result.just_crossed and signal in (Signal.BUY, Signal.SELL) and signal_changed:
            self.engine._emit("log", {
                "level": "info",
                "msg": (f"[{symbol}] 📊 FRESH {signal.value} CROSS detected! "
                        f"EMA55 {'BOTTOM' if signal == Signal.BUY else 'TOP'} | "
                        f"EMA8={e8:.4f} EMA13={e13:.4f} EMA21={e21:.4f} EMA55={e55:.4f}")
            })
            try:
                self.engine.notifier.notify_signal(
                    symbol, signal.value, result.reason,
                    {"ema_8": e8, "ema_13": e13, "ema_21": e21, "ema_55": e55}
                )
            except Exception as e:
                logger.error("Signal notification failed: %s", e)

        # ===================================================================
        # STRICT MODE ENTRY LOGIC (SILENT when waiting)
        # ===================================================================
        # Rules:
        # 1. Bot ONLY trades on a FRESH cross (just_crossed = True)
        # 2. If bot just started and line is already crossed → NO TRADE (wait silently)
        # 3. After a trade closes (SL/TP hit), waiting_for_new_cross = True
        # 4. Once a fresh cross happens, waiting_for_new_cross = False → trade allowed
        # 5. SL and TP set immediately via software watchdog (1:3 RR)
        # 6. Bot is SILENT while waiting - no spam logs
        # ===================================================================

        # === ENTRY ALLOWED? ===
        # A position already open blocks a NEW entry UNLESS an immediate
        # reversal is pending (EMA55 just flipped): in that case the old
        # position is being closed and we must re-enter the opposite side
        # right away, even if the exchange still shows the old side (API lag).
        pending_reversal = self.reversal_pending_side is not None
        if pos.side != "NONE" and pos.size != 0 and not pending_reversal:
            return

        if pending_reversal:
            target_side = self.reversal_pending_side
            desired_sig = Signal.BUY if target_side == "LONG" else Signal.SELL
            if signal != desired_sig:
                # Signal drifted before re-entry — give up forced reversal,
                # wait for a fresh cross like normal.
                return
            if pos.side != "NONE" and pos.size != 0 and pos.side == target_side:
                # Target position already open — just clear the pending flag.
                self.reversal_pending_side = None
                return
            # Close any lingering OLD (opposite) position, then enter.
            if pos.side != "NONE" and pos.size != 0 and pos.side != target_side:
                try:
                    self.engine.trader.close_position(symbol)
                except Exception as e:
                    logger.warning(f"[{symbol}] Reversal cleanup close failed: {e}")
            self.reversal_pending_side = None
            self.waiting_for_new_cross = False
            if hasattr(self, '_waiting_logged'):
                delattr(self, '_waiting_logged')
        else:
            # No position. Check if we should enter a new trade.
            # STRICT: Only enter on a FRESH cross.
            if not result.just_crossed:
                # SILENT: Don't log anything when waiting (no spam!)
                # Only log ONCE when transitioning to waiting state
                if self.waiting_for_new_cross and not hasattr(self, '_waiting_logged'):
                    self._waiting_logged = True
                    self.engine._emit("log", {
                        "level": "info",
                        "msg": (f"[{symbol}] ⏳ Waiting for FRESH cross before entering trade... (silent mode)")
                    })
                return

            # Fresh cross happened! Check cooldown (min 30s between crosses)
            now = time.time()
            if now - self._last_cross_time < 30:
                # Too soon after last cross - ignore (prevents rapid false crosses)
                return
            self._last_cross_time = now

            # Clear waiting state.
            self.waiting_for_new_cross = False
            if hasattr(self, '_waiting_logged'):
                delattr(self, '_waiting_logged')

        # Check mode allows this trade
        if signal == Signal.BUY and mode not in ("long", "both"):
            self.engine._emit("log", {
                "level": "info",
                "msg": f"[{symbol}] Fresh BUY cross but mode is '{mode}' - skipping LONG entry."
            })
            return
        if signal == Signal.SELL and mode not in ("short", "both"):
            self.engine._emit("log", {
                "level": "info",
                "msg": f"[{symbol}] Fresh SELL cross but mode is '{mode}' - skipping SHORT entry."
            })
            return

        # Compute trade size
        trade_size = self._compute_trade_size(mark_price, cfg.get("leverage", 10))
        if trade_size <= 0:
            if self.candles_processed % 12 == 0:
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"[{symbol}] Trade size 0 - wallet balance too low for 1% trade. Use Fixed USDT mode instead."
                })
            return

        # Check minimum quantity for this symbol
        try:
            filters = self.engine.trader.get_symbol_filters(symbol)
            min_qty = filters.get("min_qty", 0.001)
            if trade_size < min_qty:
                if self.candles_processed % 12 == 0:
                    self.engine._emit("log", {
                        "level": "warn",
                        "msg": f"[{symbol}] Quantity {trade_size:.6f} below min {min_qty}. Increase amount or use Fixed USDT."
                    })
                return
        except Exception:
            pass  # If we can't check filters, try anyway

        # ===================================================================
        # ENTER TRADE + PLACE SL/TP IMMEDIATELY
        # ===================================================================
        # SL is HARDCODED - user cannot disable it. Min 0.5%, default 2%.
        # TP depends on `tp_mode` config:
        #   - 'fixed'        : TP = SL x 3 (1:3 RR) — exchange + software
        #   - 'ema_reversal' : TP = when EMA55 flips to opposite extreme
        #                      (software-only — no exchange TP order)
        #   - 'both'         : both active, whichever triggers first
        # ===================================================================
        STRICT_SL_MIN = 0.5
        # Get SL from config - don't use 'or' because 0 is valid input
        sl_pct = cfg.get("stop_loss_pct", 2)
        try:
            sl_pct = float(sl_pct)
        except (TypeError, ValueError):
            sl_pct = 2.0
        if sl_pct < STRICT_SL_MIN:
            sl_pct = STRICT_SL_MIN
            self.engine._emit("log", {
                "level": "warn",
                "msg": f"[{symbol}] SL too low (was {sl_pct}%), set to minimum {STRICT_SL_MIN}%"
            })
        # Hardcoded 1:3 RR for the FIXED-TP portion (used in 'fixed' and 'both')
        tp_pct = sl_pct * 3

        # Read TP mode from config (default = 'both' for backward-compat with
        # users who upgraded without re-saving settings)
        tp_mode = (cfg.get("tp_mode") or "both").lower()
        if tp_mode not in ("fixed", "ema_reversal", "both"):
            tp_mode = "both"

        # Helper: build a short label string for log messages
        def _tp_log_label():
            if tp_mode == "ema_reversal":
                return "TP=EMA55-REVERSAL (no fixed TP)"
            if tp_mode == "both":
                return f"TP=BOTH (fixed {tp_pct}% OR EMA55-flip)"
            return f"TP={tp_pct}% STRICT 1:3 RR"

        if signal == Signal.BUY:
            # Open LONG
            # Calculate SL price (always sent to exchange — capital protection)
            sl_price_long = mark_price * (1 - sl_pct / 100)
            # Fixed-TP price — only sent to exchange when mode is 'fixed' or 'both'
            if tp_mode in ("fixed", "both"):
                tp_price_long = mark_price * (1 + tp_pct / 100)
            else:
                tp_price_long = None  # EMA-reversal-only -> no exchange TP
            self.engine._emit("log", {
                "level": "info",
                "msg": (f"[{symbol}] 🟢 FRESH BUY cross -> opening LONG qty={trade_size:.6f} @ ~{mark_price:.4f} | "
                        f"SL={sl_pct}% ({sl_price_long:.4f}) | {_tp_log_label()} | "
                        f"EMA8={e8:.4f} EMA13={e13:.4f} EMA21={e21:.4f} EMA55={e55:.4f}")
            })
            # Pass SL/TP prices to open_long — WEEX will attach them to the order
            # Binance will place separate STOP_MARKET orders after fill
            try:
                order = self.engine.trader.open_long(symbol, trade_size,
                                                     sl_price=sl_price_long,
                                                     tp_price=tp_price_long)
            except TypeError:
                # Fallback for old trader signature (no sl_price/tp_price params)
                order = self.engine.trader.open_long(symbol, trade_size)
            actual_qty = order.get("quantity", trade_size)
            self._log_order(order, f"[{symbol}] OPEN LONG qty={actual_qty:.6f}")
            if order.get("success"):
                self.trades_today += 1
                self.last_signal = Signal.BUY
                self.expected_pos_side = "LONG"
                self.reversal_pending_side = None
                # Get ACTUAL entry price from position (not mark_price)
                actual_entry = self._get_actual_entry_price(symbol, mark_price)
                # Set software watchdog (always — this is the source of truth
                # for SL/TP exits, including EMA-reversal mode)
                self._set_software_sl_tp(symbol, "LONG", actual_entry, sl_pct, tp_pct,
                                         tp_mode=tp_mode, entry_signal=Signal.BUY)
                # Log exchange SL/TP status
                if order.get("sl_price") or order.get("tp_price"):
                    self.engine._emit("log", {
                        "level": "success",
                        "msg": (f"[{symbol}] ✅ Exchange SL/TP attached | "
                                f"SL={order.get('sl_price', 'N/A')} | "
                                f"TP={order.get('tp_price', 'N/A')} | "
                                f"(+ software watchdog backup active)")
                    })
                try:
                    self.engine.notifier.notify_trade_open(
                        symbol, "LONG", actual_qty, actual_entry,
                        {"ema_8": e8, "ema_13": e13, "ema_21": e21, "ema_55": e55}
                    )
                except Exception as e:
                    logger.error("Trade open notification failed: %s", e)

        elif signal == Signal.SELL:
            # Open SHORT
            # For SHORT: SL above entry, TP below entry
            sl_price_short = mark_price * (1 + sl_pct / 100)
            if tp_mode in ("fixed", "both"):
                tp_price_short = mark_price * (1 - tp_pct / 100)
            else:
                tp_price_short = None  # EMA-reversal-only -> no exchange TP
            self.engine._emit("log", {
                "level": "info",
                "msg": (f"[{symbol}] 🔴 FRESH SELL cross -> opening SHORT qty={trade_size:.6f} @ ~{mark_price:.4f} | "
                        f"SL={sl_pct}% ({sl_price_short:.4f}) | {_tp_log_label()} | "
                        f"EMA8={e8:.4f} EMA13={e13:.4f} EMA21={e21:.4f} EMA55={e55:.4f}")
            })
            try:
                order = self.engine.trader.open_short(symbol, trade_size,
                                                      sl_price=sl_price_short,
                                                      tp_price=tp_price_short)
            except TypeError:
                order = self.engine.trader.open_short(symbol, trade_size)
            actual_qty = order.get("quantity", trade_size)
            self._log_order(order, f"[{symbol}] OPEN SHORT qty={actual_qty:.6f}")
            if order.get("success"):
                self.trades_today += 1
                self.last_signal = Signal.SELL
                self.expected_pos_side = "SHORT"
                self.reversal_pending_side = None
                # Get ACTUAL entry price from position (not mark_price)
                actual_entry = self._get_actual_entry_price(symbol, mark_price)
                # Set software watchdog
                self._set_software_sl_tp(symbol, "SHORT", actual_entry, sl_pct, tp_pct,
                                         tp_mode=tp_mode, entry_signal=Signal.SELL)
                # Log exchange SL/TP status
                if order.get("sl_price") or order.get("tp_price"):
                    self.engine._emit("log", {
                        "level": "success",
                        "msg": (f"[{symbol}] ✅ Exchange SL/TP attached | "
                                f"SL={order.get('sl_price', 'N/A')} | "
                                f"TP={order.get('tp_price', 'N/A')} | "
                                f"(+ software watchdog backup active)")
                    })
                try:
                    self.engine.notifier.notify_trade_open(
                        symbol, "SHORT", actual_qty, actual_entry,
                        {"ema_8": e8, "ema_13": e13, "ema_21": e21, "ema_55": e55}
                    )
                except Exception as e:
                    logger.error("Trade open notification failed: %s", e)

    def _get_actual_entry_price(self, symbol: str, fallback: float) -> float:
        """Get actual entry price from Binance position after order fill."""
        try:
            pos = self.engine.trader.get_position(symbol)
            if pos.entry_price > 0:
                return pos.entry_price
        except Exception as e:
            logger.warning(f"[{symbol}] Could not fetch actual entry price: {e}")
        return fallback

    def _set_software_sl_tp(self, symbol: str, side: str, entry_price: float,
                            sl_pct: float, tp_pct: float,
                            tp_mode: str = "both",
                            entry_signal: Optional[Signal] = None):
        """Set SL/TP prices in memory (software watchdog).

        Parameters
        ----------
        sl_pct, tp_pct : float
            Percentages for SL and fixed-TP. `tp_pct` is ignored when
            tp_mode == 'ema_reversal' (no fixed TP is set in that case).
        tp_mode : str
            'fixed' | 'ema_reversal' | 'both'. Controls which TP triggers
            are active for this position.
        entry_signal : Signal | None
            The strategy signal (BUY/SELL) that opened this position.
            Required when tp_mode in ('ema_reversal', 'both') so we can
            detect the opposite flip later.
        """
        if entry_price <= 0:
            self.engine._emit("log", {
                "level": "error",
                "msg": f"[{symbol}] ❌ Cannot set SL/TP - invalid entry price"
            })
            return

        # Normalize + persist tp_mode for this position
        tp_mode = (tp_mode or "both").lower()
        if tp_mode not in ("fixed", "ema_reversal", "both"):
            tp_mode = "both"
        self.tp_mode = tp_mode
        self.entry_signal = entry_signal
        self.ema_reversal_tp_fired = False  # reset one-shot guard

        # SL is ALWAYS price-based (capital protection first)
        if side == "LONG":
            self.sl_price = entry_price * (1 - sl_pct / 100)
        else:  # SHORT
            self.sl_price = entry_price * (1 + sl_pct / 100)

        # Fixed-TP is only set when mode is 'fixed' or 'both'.
        # For 'ema_reversal', tp_price stays None and the EMA55-flip
        # check in _check_software_sl_tp handles the exit.
        if tp_mode in ("fixed", "both"):
            if side == "LONG":
                self.tp_price = entry_price * (1 + tp_pct / 100)
            else:  # SHORT
                self.tp_price = entry_price * (1 - tp_pct / 100)
        else:
            self.tp_price = None  # EMA-reversal-only mode

        self.entry_price = entry_price
        self.position_side = side

        # Human-readable summary
        if tp_mode == "ema_reversal":
            tp_desc = f"TP=EMA55-REVERSAL (opposite flip; entry_sig={entry_signal.value if entry_signal else 'N/A'})"
        elif tp_mode == "both":
            tp_desc = (f"TP=BOTH (fixed {self.tp_price:.4f} OR EMA55-reversal, "
                       f"whichever first; entry_sig={entry_signal.value if entry_signal else 'N/A'})")
        else:  # fixed
            tp_desc = f"TP={self.tp_price:.4f} ({tp_pct}%) FIXED 1:3 RR"

        self.engine._emit("log", {
            "level": "success",
            "msg": (f"[{symbol}] ✅ Software SL/TP set | "
                    f"Entry={entry_price:.4f} | "
                    f"SL={self.sl_price:.4f} ({sl_pct}%) | "
                    f"{tp_desc} | Side={side}")
        })

    def _check_software_sl_tp(self, pos, result) -> tuple:
        """Check if software SL or TP has been hit.

        Parameters
        ----------
        pos : Position
            Current exchange position (has .side, .mark_price, .entry_price).
        result : StrategyResult
            Latest strategy result (has .signal, .ema_*). Used to detect
            EMA55-reversal TP — i.e. signal has flipped to the OPPOSITE
            of the entry signal.

        Returns
        -------
        (sl_hit: bool, tp_hit: bool, reason: str)

        TP triggers depend on `self.tp_mode`:
            'fixed'        -> only fixed price TP (SL x 3) is checked
            'ema_reversal' -> only EMA55 opposite-flip is checked
            'both'         -> whichever triggers FIRST
        SL is ALWAYS price-based (no mode override — capital protection first).
        """
        if self.sl_price is None:
            # No SL set means no position-tracking state at all -> nothing to check
            return (False, False, "")

        mark = pos.mark_price
        side = pos.side

        # CRITICAL: If mark_price is 0 or invalid, skip SL/TP check
        # (prevents false SL trigger when mark_price fetch fails)
        if mark is None or mark <= 0:
            return (False, False, "")

        # ---------- 1) STOP-LOSS CHECK (always price-based, always active) ----------
        if side == "LONG":
            if mark <= self.sl_price:
                pnl_pct = (mark - self.entry_price) / self.entry_price * 100 if self.entry_price > 0 else 0
                return (True, False, f"⚡ SL HIT (price {mark:.4f} <= SL {self.sl_price:.4f}, PnL={pnl_pct:+.2f}%)")
        else:  # SHORT
            if mark >= self.sl_price:
                pnl_pct = (self.entry_price - mark) / self.entry_price * 100 if self.entry_price > 0 else 0
                return (True, False, f"⚡ SL HIT (price {mark:.4f} >= SL {self.sl_price:.4f}, PnL={pnl_pct:+.2f}%)")

        # ---------- 2) FIXED-TP CHECK (only for 'fixed' and 'both' modes) ----------
        if self.tp_mode in ("fixed", "both") and self.tp_price is not None:
            if side == "LONG":
                if mark >= self.tp_price:
                    pnl_pct = (mark - self.entry_price) / self.entry_price * 100 if self.entry_price > 0 else 0
                    return (False, True,
                            f"⚡ FIXED-TP HIT (price {mark:.4f} >= TP {self.tp_price:.4f}, PnL={pnl_pct:+.2f}%)")
            else:  # SHORT
                if mark <= self.tp_price:
                    pnl_pct = (self.entry_price - mark) / self.entry_price * 100 if self.entry_price > 0 else 0
                    return (False, True,
                            f"⚡ FIXED-TP HIT (price {mark:.4f} <= TP {self.tp_price:.4f}, PnL={pnl_pct:+.2f}%)")

        # ---------- 3) EMA-REVERSAL CHECK (ALWAYS ACTIVE — strategy feature) ----------
        # This is NOT a TP-mode option — it's a core strategy rule.
        # If EMA55 has flipped to the OPPOSITE extreme (signal changed
        # from BUY->SELL or SELL->BUY), the position must be closed
        # immediately and the opposite position opened on the next tick.
        #
        # This runs REGARDLESS of tp_mode:
        #   - tp_mode='fixed'        -> reversal STILL fires (strategy rule)
        #   - tp_mode='ema_reversal' -> reversal fires (this is the only TP)
        #   - tp_mode='both'         -> reversal fires (whichever first)
        #
        #   LONG  (entry_signal=BUY)  -> close when current signal == SELL
        #                                (EMA55 became the TOP line)
        #   SHORT (entry_signal=SELL) -> close when current signal == BUY
        #                                (EMA55 became the BOTTOM line)
        if not self.ema_reversal_tp_fired and result is not None and self.entry_signal is not None:
            cur_sig = result.signal
            if side == "LONG" and self.entry_signal == Signal.BUY and cur_sig == Signal.SELL:
                pnl_pct = (mark - self.entry_price) / self.entry_price * 100 if self.entry_price > 0 else 0
                self.ema_reversal_tp_fired = True  # one-shot
                return (False, True,
                        f"⚡ EMA55-REVERSAL (LONG->EMA55 now TOP, PnL={pnl_pct:+.2f}%)")
            if side == "SHORT" and self.entry_signal == Signal.SELL and cur_sig == Signal.BUY:
                pnl_pct = (self.entry_price - mark) / self.entry_price * 100 if self.entry_price > 0 else 0
                self.ema_reversal_tp_fired = True  # one-shot
                return (False, True,
                        f"⚡ EMA55-REVERSAL (SHORT->EMA55 now BOTTOM, PnL={pnl_pct:+.2f}%)")

        return (False, False, "")

    def _compute_trade_size(self, price: float, leverage: int) -> float:
        """
        Compute base-asset quantity based on amount_mode and leverage:
        - 'fixed'  : use cfg['amount'] as USDT margin, scaled by leverage for total notional exposure
        - 'percent': use (balance * amount_pct / 100) as USDT margin, scaled by leverage for total notional exposure

        Fetches the REAL step_size from the exchange so compute_quantity rounds correctly.
        """
        cfg = self.config
        amount_mode = cfg.get("amount_mode", "fixed")
        lev = max(1, int(leverage or cfg.get("leverage", 10)))

        if amount_mode == "percent":
            try:
                balance = self.engine.trader.get_balance()
            except Exception:
                balance = 0.0
            pct = float(cfg.get("amount_pct", 10))
            margin = balance * pct / 100.0
            notional = margin * lev
        else:
            margin = float(cfg.get("amount", 100))
            notional = margin * lev

        # Fetch real step_size from exchange for accurate rounding
        qty_step = 0.001  # safe fallback
        try:
            filters = self.engine.trader.get_symbol_filters(self.symbol)
            qty_step = filters.get("step_size", 0.001)
        except Exception:
            pass

        return self.engine.trader.compute_quantity(notional, price, lev, qty_step=qty_step)

    def _candles_to_list(self, df, n=200):
        """Convert df candles to list of dicts for UI chart."""
        if df is None or len(df) == 0:
            return []
        tail = df.tail(n)
        out = []
        for ts, row in tail.iterrows():
            out.append({
                "time": int(ts.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
        return out

    def _emas_to_list(self, df, n=200):
        """Convert EMA columns to dict of lists for UI chart."""
        enriched = self.strategy.indicators.compute(df)
        tail = enriched.tail(n)
        out = {}
        for col, key in [("ema_8", "ema8"), ("ema_13", "ema13"),
                         ("ema_21", "ema21"), ("ema_55", "ema55")]:
            out[key] = [
                {"time": int(ts.timestamp()), "value": float(v)}
                for ts, v in zip(tail.index, tail[col])
                if not (v != v)  # filter NaN
            ]
        return out

    def _log_order(self, result, label):
        if result.get("success"):
            order = result.get("order", {})
            oid = order.get("orderId", "?") if isinstance(order, dict) else "?"
            self.engine._emit("log", {
                "level": "success",
                "msg": f"{label} OK | orderId={oid}"
            })
        else:
            self.engine._emit("log", {
                "level": "error",
                "msg": f"{label} FAILED | {result.get('error')}"
            })


class MonitorThread(threading.Thread):
    """Always-on background thread that fetches live data (balance, mark_price,
    chart, indicators) for the active symbol — even when the bot is STOPPED.

    This means as soon as user saves settings (with API keys), they see:
    - Real WEEX/Binance balance (e.g. 20,000 USDT on WEEX demo)
    - Live mark price for the selected coin
    - Live chart with EMA indicators
    - Open positions (if any)

    The thread polls every 5s for prices/indicators, 10s for balance,
    60s for chart refresh.
    """

    def __init__(self, engine, config: dict):
        super().__init__(daemon=True, name="monitor")
        self.engine = engine
        self.config = config
        self.stop_event = threading.Event()
        self._last_chart_emit = 0

    def run(self):
        exchange = (self.config.get("exchange") or "binance").upper()
        env_label = "DEMO" if exchange == "WEEX" and self.config.get("testnet") else \
                    ("TESTNET" if self.config.get("testnet") else "MAINNET")
        self.engine._emit("log", {
            "level": "info",
            "msg": f"🔌 MONITOR connected to {exchange} ({env_label}) — live data is now flowing"
        })

        first_run = True
        while not self.stop_event.is_set():
            try:
                self._tick(first_run)
                first_run = False
            except Exception as e:
                logger.error(f"Monitor tick error: {e}")
                if first_run:
                    self.engine._emit("log", {
                        "level": "error",
                        "msg": f"❌ MONITOR error: {str(e)[:120]}. Check API keys/Passphrase."
                    })
                    first_run = False
            # Poll every 5s (compromise between responsiveness and rate limits)
            for _ in range(5):
                if self.stop_event.is_set():
                    break
                time.sleep(1)

        self.engine._emit("log", {
            "level": "info",
            "msg": "🔌 MONITOR disconnected"
        })

    def _tick(self, first_run=False):
        """One polling iteration. Fetches data for the active symbol only."""
        cfg = self.config
        symbol = self.engine.active_symbol or cfg.get("symbol", "BTCUSDT")
        timeframe = cfg.get("timeframe", "5m")

        if self.engine.monitor_trader is None:
            return

        # 1. Fetch balance (every tick — it's fast and shows real-time state)
        try:
            balance = self.engine.monitor_trader.get_balance()
            self.engine._emit("balance", {
                "balance": float(balance),
                "exchange": cfg.get("exchange", "binance"),
                "testnet": cfg.get("testnet", True),
            })
        except Exception as e:
            if first_run:
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"⚠️ Balance fetch failed: {str(e)[:100]}"
                })

        # 2. Fetch klines + indicators + mark price for active symbol
        try:
            df = self.engine.monitor_trader.get_klines(symbol, interval=timeframe, limit=200)
        except Exception as e:
            if first_run:
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"⚠️ Chart fetch failed for {symbol}: {str(e)[:100]}"
                })
            return

        if df is None or len(df) == 0:
            return

        # Mark price (prefer mark_price API, fallback to last close)
        try:
            mark_price = self.engine.monitor_trader.get_mark_price(symbol)
            if mark_price is None or mark_price <= 0:
                mark_price = float(df.iloc[-1]["close"])
        except Exception:
            mark_price = float(df.iloc[-1]["close"])

        # Indicators (EMA 8, 13, 21, 55)
        try:
            indicators = self.engine.strategy.latest_indicators(df)
        except Exception:
            indicators = {"ema_8": 0, "ema_13": 0, "ema_21": 0, "ema_55": 0}

        # Emit indicators
        self.engine._emit("indicators", {
            "symbol": symbol,
            **indicators,
            "mark_price": mark_price,
        })

        # Emit chart data (throttle to every 30s — klines don't change fast)
        now = time.time()
        if now - self._last_chart_emit > 30 or first_run:
            candles = self._candles_to_list(df)
            emas = self._emas_to_list(df)
            if candles:
                self.engine._emit("chart_data", {
                    "symbol": symbol,
                    "candles": candles,
                    "emas": emas,
                })
                self._last_chart_emit = now

        # Emit position info for active symbol
        try:
            pos = self.engine.monitor_trader.get_position(symbol)
            self.engine._emit("position", {
                "symbol": symbol,
                "side": pos.side,
                "size": pos.size,
                "entry_price": pos.entry_price,
                "mark_price": pos.mark_price if pos.mark_price > 0 else mark_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "leverage": pos.leverage,
            })
        except Exception:
            pass

    def _candles_to_list(self, df, n=200):
        if df is None or len(df) == 0:
            return []
        tail = df.tail(n)
        out = []
        for ts, row in tail.iterrows():
            out.append({
                "time": int(ts.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
        return out

    def _emas_to_list(self, df, n=200):
        try:
            enriched = self.engine.strategy.indicators.compute(df)
        except Exception:
            return {}
        tail = enriched.tail(n)
        out = {}
        for col, key in [("ema_8", "ema8"), ("ema_13", "ema13"),
                         ("ema_21", "ema21"), ("ema_55", "ema55")]:
            out[key] = [
                {"time": int(ts.timestamp()), "value": float(v)}
                for ts, v in zip(tail.index, tail[col])
                if not (v != v)  # filter NaN
            ]
        return out


class BotEngine:
    """Background trading engine supporting multi-symbol trading."""

    def __init__(self, socketio, config: dict):
        self.socketio = socketio
        self.config = config
        self.trader: Optional[BinanceFuturesTrader] = None
        self.strategy = EMAQuadStrategy()
        self.notifier = Notifier(config)
        self.workers: dict[str, SymbolWorker] = {}
        self.lock = threading.Lock()
        self.is_running = False
        self.active_symbol = None  # Which coin the UI is currently viewing
        # ===== MONITOR MODE =====
        # Always-on background thread that fetches balance, mark_price, chart
        # for the active symbol. Works even when bot is STOPPED, so user can
        # see live data immediately after saving settings.
        self.monitor_thread: Optional[MonitorThread] = None
        self.monitor_trader = None  # separate trader instance for monitor

    # ---------- Lifecycle ----------

    # ===== MONITOR MODE METHODS =====
    # Monitor = always-on background thread that fetches live data (balance,
    # mark_price, chart) for the active symbol. Works even when bot is STOPPED.
    # Triggered automatically after user saves settings (see /api/config POST).

    def start_monitor(self, config: dict) -> dict:
        """Start (or restart) the monitor with the given config.

        Called automatically by app.py after /api/config POST (Save button).
        Also called when user switches exchange or demo/live toggle.

        If API keys are missing, returns success=False (no monitor started).
        If monitor is already running, stops it first then starts new one.
        """
        # Stop existing monitor if any
        self.stop_monitor()

        # Check API credentials
        api_key = config.get("api_key", "").strip()
        api_secret = config.get("api_secret", "").strip()
        if not api_key or not api_secret:
            return {"success": False, "error": "API keys not set — monitor not started"}
        if config.get("exchange") == "weex":
            if not config.get("api_passphrase", "").strip():
                return {"success": False, "error": "WEEX Passphrase not set — monitor not started"}

        # Create monitor trader (separate from trading trader)
        try:
            self.monitor_trader = get_trader(config)
        except Exception as e:
            logger.error(f"Monitor trader creation failed: {e}")
            self.monitor_trader = None
            return {"success": False, "error": f"Exchange connection failed: {e}"}

        # Start monitor thread
        self.monitor_thread = MonitorThread(self, config)
        self.monitor_thread.start()
        return {"success": True, "message": "Monitor started"}

    def stop_monitor(self):
        """Stop the monitor thread if running."""
        if self.monitor_thread is not None:
            self.monitor_thread.stop_event.set()
            try:
                self.monitor_thread.join(timeout=8)
            except Exception:
                pass
            self.monitor_thread = None
        self.monitor_trader = None

    def start(self, config: dict):
        """Start the bot with the given config."""
        # ZOMBIE STATE CHECK
        if self.is_running:
            alive_workers = [w for w in self.workers.values() if w.is_alive()]
            if not alive_workers:
                logger.warning("Zombie state detected: is_running=True but no alive workers. Auto-resetting.")
                self.is_running = False
                self.workers.clear()
                self._emit("log", {
                    "level": "warn",
                    "msg": "⚠️ Zombie state detected (bot was stuck). Auto-reset done. You can START again."
                })
            else:
                return {"success": False, "error": "Bot already running"}

        self.config = config
        self.notifier.update_config(config)
        try:
            self.trader = get_trader(config)
        except Exception as e:
            logger.error("Failed to connect to exchange: %s", e)
            return {"success": False, "error": f"Exchange connection failed: {e}"}

        # Get symbols and leverage
        symbols = self._symbols_list()
        lev = config.get("leverage", 10)
        if not symbols:
            return {"success": False, "error": "No symbols added. Please add coins."}

        # ===== LEVERAGE RACE CONDITION FIX =====
        # Create a leverage-ready event that workers will wait on BEFORE trading.
        # Leverage is still set in a background thread (non-blocking for /api/start)
        # but workers block until it completes (with a 30s timeout).
        leverage_ready = threading.Event()

        def _set_leverage_bg():
            try:
                for sym in symbols:
                    r = self.trader.set_leverage(sym, lev)
                    if r["success"]:
                        actual_lev = r.get("leverage", lev)
                        if r.get("adjusted"):
                            self._emit("log", {
                                "level": "warn",
                                "msg": f"[{sym}] Leverage auto-adjusted: {lev}x → {actual_lev}x (max allowed)"
                            })
                        else:
                            self._emit("log", {
                                "level": "info",
                                "msg": f"[{sym}] Leverage set: {actual_lev}x"
                            })
                    else:
                        err = str(r.get("error", ""))
                        if "-2015" in err or "Invalid API-key" in err or "-1044" in err or "401" in err:
                            self._emit("log", {
                                "level": "error",
                                "msg": f"[{sym}] ❌ API AUTH FAILED (-2015): Your API Key is REJECTED by Binance! 1) Check 'Enable Futures'. 2) If IP restricted, whitelist your VPS IP. 3) Ensure it's a Futures key, not Spot!"
                            })
                            # Stop the bot
                            self.is_running = False
                            return
                        elif "-4141" in err or "Symbol is closed" in err or "band" in err:
                            self._emit("log", {
                                "level": "warn",
                                "msg": f"[{sym}] ⚠️ Symbol is delisted/closed - skipping."
                            })
                        else:
                            # Don't block bot over leverage errors — trades will use default
                            self._emit("log", {
                                "level": "warn",
                                "msg": f"[{sym}] ⚠️ Could not set leverage: {err[:80]}. Using exchange default."
                            })
            finally:
                leverage_ready.set()

        _bg_thread = threading.Thread(target=_set_leverage_bg, daemon=True)
        _bg_thread.start()

        self.is_running = True

        # Set active_symbol BEFORE spawning workers (prevents race condition)
        if symbols:
            self.active_symbol = symbols[0]

        # Spawn one worker per symbol (STAGGERED to avoid API rate limits)
        with self.lock:
            for i, sym in enumerate(symbols):
                w = SymbolWorker(self, sym, config, leverage_ready=leverage_ready)
                self.workers[sym] = w
                # Stagger start: each worker starts 0.5s apart
                stagger_delay = min(i * 0.5, 10)  # max 10s spread
                if stagger_delay > 0:
                    threading.Timer(stagger_delay, w.start).start()
                else:
                    w.start()

        self._emit("status", {"running": True, "message": "Bot started"})
        sl_info = f"SL={config.get('stop_loss_pct', 0)}%" if config.get("stop_loss_pct", 0) else "SL=OFF"
        # TP info depends on tp_mode
        _tp_mode = (config.get("tp_mode") or "both").lower()
        if _tp_mode == "ema_reversal":
            tp_info = "TP=EMA55-REVERSAL (opposite flip)"
        elif _tp_mode == "both":
            tp_info = f"TP=BOTH (fixed {config.get('take_profit_pct', 0)}% OR EMA55-flip)"
        else:
            tp_info = f"TP={config.get('take_profit_pct', 0)}% (fixed 1:3 RR)"
        exchange = (config.get("exchange") or "binance").upper()
        env_label = "DEMO" if exchange == "WEEX" and config.get("testnet") else \
                    ("TESTNET" if config.get("testnet") else "MAINNET")
        self._emit("log", {
            "level": "info",
            "msg": (f"Bot STARTED | Exchange={exchange} | Symbols={','.join(symbols)} | "
                    f"TF={config['timeframe']} | Lev={config['leverage']}x | "
                    f"Mode={config.get('mode','both')} | Amount={self._amount_desc()} | "
                    f"{sl_info} | {tp_info} | Env={env_label}")
        })
        # Send notification
        try:
            self.notifier.notify_bot_start(config)
        except Exception as e:
            logger.error("Bot start notification failed: %s", e)
        return {"success": True, "message": "Bot started"}

    def stop(self):
        """Stop all workers."""
        if not self.is_running:
            return {"success": False, "error": "Bot not running"}

        with self.lock:
            for sym, w in self.workers.items():
                w.stop_event.set()
            for sym, w in self.workers.items():
                w.join(timeout=10)
            self.workers.clear()

        self.is_running = False
        self._emit("status", {"running": False, "message": "Bot stopped"})
        self._emit("log", {"level": "info", "msg": "Bot STOPPED by user"})
        # Send notification
        try:
            self.notifier.notify_bot_stop()
        except Exception as e:
            logger.error("Bot stop notification failed: %s", e)
        return {"success": True, "message": "Bot stopped"}

    def force_stop(self):
        """Force stop - always resets state, even if workers are dead (zombie recovery)."""
        logger.warning("Force stop requested - resetting all state.")
        with self.lock:
            for sym, w in self.workers.items():
                try:
                    w.stop_event.set()
                    w.join(timeout=5)
                except Exception:
                    pass
            self.workers.clear()
        self.is_running = False
        self.trader = None
        # NOTE: Do NOT stop the monitor or clear active_symbol.
        # Monitor keeps running so user still sees live data after force stop.
        # active_symbol stays so chart stays populated.
        self._emit("status", {"running": False, "message": "Force stopped"})
        self._emit("log", {
            "level": "warn",
            "msg": "⚠️ FORCE STOP done. Trading state reset. Monitor still running (live data active)."
        })
        return {"success": True, "message": "Force stop done - trading state reset"}

    def set_active_symbol(self, symbol: str):
        """Set which coin the UI is currently viewing. Only this coin's
        chart data will be sent via WebSocket (prevents flooding).

        Also tells the monitor thread to switch to this symbol — so the chart
        updates immediately even when the bot is STOPPED.
        """
        self.active_symbol = symbol
        logger.info(f"Active symbol set to: {symbol}")
        # If bot is running and this symbol has a worker, trigger an immediate
        # chart_data emit so the chart populates instantly (not after 3-5s wait)
        if self.is_running and symbol in self.workers:
            try:
                worker = self.workers[symbol]
                if hasattr(worker, '_last_df') and worker._last_df is not None:
                    df = worker._last_df
                    candles = worker._candles_to_list(df)
                    emas = worker._emas_to_list(df)
                    indicators = self.strategy.latest_indicators(df)
                    try:
                        mark_price = self.trader.get_mark_price(symbol)
                    except Exception:
                        mark_price = float(df.iloc[-1]["close"]) if df is not None and len(df) else 0.0
                    self._emit("chart_data", {
                        "symbol": symbol,
                        "candles": candles,
                        "emas": emas,
                    })
                    self._emit("indicators", {
                        "symbol": symbol,
                        **indicators,
                        "mark_price": mark_price,
                    })
                    logger.info(f"Sent chart data for {symbol} ({len(candles)} candles)")
            except Exception as e:
                logger.warning(f"Could not send immediate chart data for {symbol}: {e}")
        return {"success": True}

    # ---------- Helpers ----------

    def _symbols_list(self) -> list:
        """Get list of symbols to trade (supports multi-symbol).

        CRITICAL FIX: Previously this read `config['symbol']` which is always
        just the FIRST symbol from symbols_list. This meant only ONE worker
        was spawned even when user added 10 coins. Multi-coin was broken!

        Now: reads `config['symbols_list']` (the full list) first,
        falls back to `config['symbol']` (legacy single-string) only if
        symbols_list is missing or empty.
        """
        # Preferred: symbols_list (the full multi-coin list)
        sl = self.config.get("symbols_list")
        if isinstance(sl, list):
            parts = [str(x).strip().upper() for x in sl if x and str(x).strip()]
            if parts:
                return parts
        elif isinstance(sl, str) and sl.strip():
            parts = [x.strip().upper() for x in sl.split(",") if x.strip()]
            if parts:
                return parts
        # Legacy fallback: single symbol string
        s = self.config.get("symbol", "BTCUSDT")
        if isinstance(s, list):
            return [x.strip().upper() for x in s if x and x.strip()]
        if isinstance(s, str):
            parts = [x.strip().upper() for x in s.split(",") if x and x.strip()]
            return parts if parts else ["BTCUSDT"]
        return ["BTCUSDT"]

    def _amount_desc(self) -> str:
        m = self.config.get("amount_mode", "fixed")
        if m == "percent":
            return f"{self.config.get('amount_pct', 10)}% of wallet"
        return f"${self.config.get('amount', 100)}"

    def _emit(self, event: str, data: dict):
        """Emit a socketio event AND log to terminal (dual output for debugging)."""
        try:
            # Also log to terminal so we can see what's happening
            if event == "log":
                level = (data.get("level") or "info").upper()
                msg = data.get("msg", "")
                if level == "ERROR":
                    logger.error(msg)
                elif level == "WARN" or level == "WARNING":
                    logger.warning(msg)
                elif level == "SUCCESS":
                    logger.info(f"[SUCCESS] {msg}")
                else:
                    logger.info(msg)
            # Emit to browser via Socket.IO
            if self.socketio:
                self.socketio.emit(event, data, namespace="/")
        except Exception as e:
            logger.error("Socket emit failed: %s", e)

    @staticmethod
    def _poll_seconds(timeframe: str) -> int:
        """How often to re-check the strategy and SL/TP.
        Faster polling = SL/TP triggers faster."""
        mapping = {
            "1m": 3, "3m": 3, "5m": 3, "15m": 5,
            "30m": 5, "1h": 10, "2h": 15, "4h": 30,
            "1d": 60, "1w": 120,
        }
        return mapping.get(timeframe, 3)

    def status(self) -> dict:
        symbols = self._symbols_list() if self.is_running else []
        # ZOMBIE CHECK: if is_running but no alive workers, report as NOT running
        alive_count = sum(1 for w in self.workers.values() if w.is_alive())
        if self.is_running and alive_count == 0 and self.workers:
            # Workers all dead but flag still True - report as not running
            # and auto-reset so user can start again
            self.is_running = False
            self.workers.clear()
        return {
            "running": self.is_running,
            "exchange": self.config.get("exchange", "binance"),
            "symbols": symbols,
            "timeframe": self.config.get("timeframe"),
            "leverage": self.config.get("leverage"),
            "amount_mode": self.config.get("amount_mode", "fixed"),
            "amount": self.config.get("amount"),
            "amount_pct": self.config.get("amount_pct", 10),
            "stop_loss_pct": self.config.get("stop_loss_pct", 2),
            "take_profit_pct": self.config.get("take_profit_pct", 6),
            "tp_mode": self.config.get("tp_mode", "both"),
            "mode": self.config.get("mode", "both"),
            "testnet": self.config.get("testnet", True),
            "workers": {
                sym: {
                    "candles_processed": w.candles_processed,
                    "trades_today": w.trades_today,
                    "last_signal": w.last_signal.value,
                    "last_trade_side": getattr(w, "last_trade_side", None),
                    "last_check": w.last_check,
                    "alive": w.is_alive(),
                }
                for sym, w in self.workers.items()
            },
        }

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
from .history import TradeHistoryManager

logger = logging.getLogger(__name__)


def get_trader(config: dict):
    """Factory: return the correct trader based on config['exchange']."""
    exchange = (config.get("exchange") or "binance").lower()
    if exchange == "primexbt":
        from .primexbt_trader import PrimeXBTTrader
        return PrimeXBTTrader(config)
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
        # STRICT RULE: On startup, must wait for a genuine FRESH crossover before trading
        self.waiting_for_new_cross = True
        self.partial_tp_done = False      # Partial 50% TP closed
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
        self.tp_mode = "fixed"            # strict 1:1 TP & SL with auto-reversal
        self.entry_signal = None          # Signal.BUY / Signal.SELL / None
        self.ema_reversal_tp_fired = False  # one-shot guard per position
        # Trailing TP / Breakeven SL state (True 1:1 margin-scaled target)
        self.tp_stage = 1                 # 1 = +100% ROE, 2 = +200% ROE, ...
        self.r_distance = 0.0             # Price distance for target_roe_pct
        self.target_roe_pct = 100.0       # Default: 100% ROE profit before trailing (1:1 with margin)
        self.initial_sl_price = None
        self._exchange_tp_cleaned = False # Guard to purge rogue fixed TP orders on startup
        # After an EMA-reversal TP, we must re-enter the OPPOSITE side
        # immediately — even if the exchange hasn't cleared the old position
        # yet (API lag). This flag forces that re-entry on the next tick.
        self.reversal_pending_side = None  # "LONG" / "SHORT" / None
        self._last_df = None  # Cache last klines DataFrame for instant chart update
        self._last_mark_price = None  # Cache last mark price
        self._last_cross_time = 0  # Timestamp of last cross (prevent rapid crosses)
        # Per-worker strategy instance — CRITICAL FIX: prevents multi-coin workers
        # from overwriting each other's cross detection and reversal state.
        min_spread = float(self.config.get("min_ema_spread", 0.15))
        self.strategy = EMAQuadStrategy(min_spread_pct=min_spread)
        # Leverage readiness event — workers wait on this before trading
        self._leverage_ready = leverage_ready
        # Settlement cooldown tracking to prevent race conditions on close
        self._last_close_timestamp = 0.0

    def _get_effective_leverage(self, symbol: str) -> int:
        """Get the true active leverage for this symbol from config (or active open position)."""
        cfg_lev = max(1, int(self.config.get("leverage", 75)))
        try:
            trader = self.engine.trader or self.engine.monitor_trader
            if trader:
                pos = trader.get_position(symbol)
                # Only use exchange position leverage if there is an ACTUAL OPEN POSITION!
                if pos and pos.side != "NONE" and pos.size != 0 and pos.leverage and int(pos.leverage) > 1:
                    return int(pos.leverage)
        except Exception:
            pass
        return cfg_lev

    def _update_exchange_sl(self, side: str, new_sl: float, qty: float):
        """Update exchange stop loss order to lock in profit or break-even, and cancel any rogue TP orders."""
        try:
            trader = self.engine.trader or self.engine.monitor_trader
            if trader and hasattr(trader, "cancel_open_orders") and hasattr(trader, "place_stop_loss"):
                trader.cancel_open_orders(self.symbol)
                close_side = "SELL" if side == "LONG" else "BUY"
                resp = trader.place_stop_loss(self.symbol, close_side, new_sl, qty)
                logger.info(f"[{self.symbol}] Exchange SL updated to {new_sl} ({close_side} {qty}): {resp}")
        except Exception as e:
            logger.warning(f"[{self.symbol}] Exchange SL sync notice: {e} (software watchdog remains active)")

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
                    # STRICT RULE: Seed startup state so bot NEVER enters on startup without a fresh crossover!
                    self.strategy.seed_startup_state(seed_result.signal)
                    self.waiting_for_new_cross = True
                    self.last_signal = seed_result.signal
                    self.engine._emit("signal", {
                        "symbol": self.symbol,
                        "signal": seed_result.signal.value,
                        "reason": seed_result.reason,
                        "emas": {"ema_8": seed_result.ema_8, "ema_13": seed_result.ema_13,
                                 "ema_21": seed_result.ema_21, "ema_55": seed_result.ema_55},
                        "just_crossed": False,
                    })
                    self.engine._emit("log", {
                        "level": "info",
                        "msg": (f"[{self.symbol}] Startup: signal={seed_result.signal.value} "
                                f"({seed_result.reason}). Waiting for a genuine FRESH crossover before taking any trade.")
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
            if not self.engine.is_running:
                break
            try:
                self._tick()
            except Exception as e:
                logger.exception(f"[{self.symbol}] tick error")
                self.engine._emit("log", {
                    "level": "error",
                    "msg": f"[{self.symbol}] tick error: {str(e)[:100]}"
                })
            for _ in range(poll_seconds):
                if self.stop_event.is_set() or not self.engine.is_running:
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
            err_msg = str(e)
            logger.error(f"[{symbol}] Failed to fetch klines after retries: {err_msg}")
            is_rate_limit = any(x in err_msg.lower() for x in ["418", "429", "-1003", "too many requests", "banned"])
            if is_rate_limit:
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"[{symbol}] ⚠️ Binance rate limit / IP temporary ban hit. Pausing requests for 60s to let limit clear..."
                })
                for _ in range(60):
                    if self.stop_event.is_set() or not self.engine.is_running:
                        break
                    time.sleep(1)
                return
            # Don't spam logs every tick - only log every 12th tick (~1 min)
            if self.candles_processed % 12 == 0:
                self.engine._emit("log", {
                    "level": "error",
                    "msg": f"[{symbol}] Klines fetch fail: {err_msg[:100]}. Chart empty - API error."
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
            effective_lev = pos.leverage if (pos.side != "NONE" and pos.size != 0 and pos.leverage and int(pos.leverage) > 1) else self._get_effective_leverage(symbol)
            self.engine._emit("position", {
                "symbol": symbol,
                "side": pos.side,
                "size": pos.size,
                "entry_price": pos.entry_price,
                "mark_price": pos.mark_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "leverage": effective_lev,
                "tp_stage": self.tp_stage if pos.side != "NONE" else 0,
                "tp_price": self.tp_price if (pos.side != "NONE" and self.tp_price) else 0.0,
                "sl_price": self.sl_price if (pos.side != "NONE" and self.sl_price) else 0.0,
                "target_roe": getattr(self, "target_roe_pct", 100.0),
                "tp_mode": self.tp_mode,
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
            # ===== Position monitor log every ~30s =====
            if self.candles_processed % 6 == 0:
                entry_sig_str = self.entry_signal.value if self.entry_signal else "N/A"
                cur_sig_str = result.signal.value
                sl_fmt = f"{self.sl_price:.4f}" if self.sl_price else "0.0"
                tp_fmt = f"{self.tp_price:.4f}" if self.tp_price else "0.0"
                entry_val = self.entry_price or pos.entry_price or 0.0
                self.engine._emit("log", {
                    "level": "info",
                    "msg": (f"[{symbol}] 📊 Position monitor | "
                            f"Pos={pos.side} (entry_sig={entry_sig_str}) | "
                            f"Current signal={cur_sig_str} | "
                            f"Mark={pos.mark_price:.4f} Entry={entry_val:.4f} | "
                            f"SL={sl_fmt} TP={tp_fmt} | "
                            f"1:1 TP & Auto-Reversal Active")
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
                # Verify if position is already flat on exchange if initial close response was unsuccessful
                if not close.get("success"):
                    try:
                        latest_p = self.engine.trader.get_position(symbol)
                        if latest_p.side == "NONE" or abs(latest_p.size) <= 0:
                            close = {"success": True, "message": "Position verified closed on exchange"}
                    except Exception:
                        pass

                if close.get("success"):
                    self._last_close_timestamp = time.time()
                    self.trades_today += 1
                    # Record close in Trade History!
                    try:
                        trade_qty = abs(pos.size) if (pos and pos.size) else 0.0
                        trade_lev = pos.leverage if (pos and pos.leverage and pos.leverage > 1) else self._get_effective_leverage(symbol)
                        trade_margin = (entry * trade_qty) / trade_lev if (trade_lev > 0 and entry > 0 and trade_qty > 0) else 0.0
                        if close_side_label == "LONG":
                            calc_pnl = (pos.mark_price - entry) * trade_qty
                        else:
                            calc_pnl = (entry - pos.mark_price) * trade_qty
                        calc_roe = (calc_pnl / trade_margin * 100.0) if trade_margin > 0 else 0.0
                        calc_fees = (entry + pos.mark_price) * trade_qty * 0.0006
                        self.engine.history.record_close(
                            symbol=symbol,
                            exit_price=pos.mark_price,
                            reason=reason,
                            pnl=calc_pnl,
                            roe_pct=calc_roe,
                            fee_est=calc_fees,
                            leverage=trade_lev,
                            qty=trade_qty,
                        )
                        self.engine._emit("trades_updated", {
                            "trades": self.engine.history.get_trades(limit=50),
                            "stats": self.engine.history.get_stats(),
                        })
                    except Exception as he:
                        logger.error("Failed to record trade close in history: %s", he)

                    # Cancel any open orders on exchange
                    try:
                        if hasattr(self.engine.trader, "cancel_open_orders"):
                            self.engine.trader.cancel_open_orders(symbol)
                    except Exception:
                        pass
                    # Reset SL/TP state
                    self.sl_price = None
                    self.tp_price = None
                    self.entry_price = None
                    self.position_side = None
                    self.entry_signal = None
                    self.ema_reversal_tp_fired = False
                    self.expected_pos_side = None
                    self.be_sl_set = False
                    self.partial_tp_done = False
                    self.tp_stage = 1
                    self.r_distance = 0.0
                    self.initial_sl_price = None
                    # ===== REVERSAL / EXIT LOGIC =====
                    # Position exit complete. Always require a confirmed fresh crossover
                    # on a closed candle with minimum spread (>=0.15%) before entering next trade.
                    # This prevents the whipsaw trap of immediately blindly buying into a chop reversal.
                    self.waiting_for_new_cross = True
                    self.reversal_pending_side = None
                    if is_ema_reversal_tp:
                        self.strategy.reset_for_reversal()
                        self.engine._emit("log", {
                            "level": "info",
                            "msg": (f"[{symbol}] 🔄 EMA55 REVERSAL exit processed. "
                                    f"Position closed @ {pos.mark_price:.4f}. Waiting for fresh candle confirmation.")
                        })
                    else:
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
                else:
                    logger.warning("[%s] Close order did not succeed: %s. Resetting one-shot flags to allow retry.", symbol, close)
                    if is_ema_reversal_tp:
                        self.ema_reversal_tp_fired = False

                # Position closed or exit attempted - emit signal for UI and return
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
        is_settling = (time.time() - getattr(self, "_last_close_timestamp", 0.0) < 20.0)
        if not is_settling and actual_side != self.expected_pos_side:
            if self.expected_pos_side is not None and actual_side == "NONE":
                # Bot expected a position but it's gone now (user closed or SL/TP hit on exchange)
                mp = 0.0
                try:
                    mp = float(self.engine.trader.get_mark_price(symbol) or 0.0)
                except Exception:
                    pass
                if mp <= 0:
                    mp = float(self.entry_price or 0.0)

                # Fetch active open trade if exists in history to compute real PnL & leverage
                open_trade = None
                for t in self.engine.history.trades:
                    if t.get("symbol") == symbol.upper() and t.get("status") == "OPEN":
                        open_trade = t
                        break

                trade_lev = self._get_effective_leverage(symbol)
                trade_qty = 0.0
                calc_pnl = 0.0
                calc_roe = 0.0
                calc_fees = 0.0
                if open_trade:
                    t_entry = float(open_trade.get("entry_price") or mp)
                    trade_qty = float(open_trade.get("qty") or 0.0)
                    t_side = open_trade.get("side", self.expected_pos_side)
                    trade_lev = max(int(open_trade.get("leverage") or trade_lev), 1)
                    t_margin = float(open_trade.get("margin") or 0.0)
                    if t_margin <= 0 and t_entry > 0 and trade_qty > 0:
                        t_margin = (t_entry * trade_qty) / trade_lev
                    if t_side == "LONG":
                        calc_pnl = (mp - t_entry) * trade_qty
                    else:
                        calc_pnl = (t_entry - mp) * trade_qty
                    calc_roe = (calc_pnl / t_margin * 100.0) if t_margin > 0 else 0.0
                    calc_fees = (t_entry + mp) * trade_qty * 0.0006

                if self.engine.history.has_open_trade(symbol):
                    try:
                        self.engine.history.record_close(
                            symbol=symbol,
                            exit_price=mp,
                            reason="👤 Manual Close (Exchange / SL-TP Hit)",
                            pnl=calc_pnl,
                            roe_pct=calc_roe,
                            fee_est=calc_fees,
                            leverage=trade_lev,
                            qty=trade_qty,
                        )
                        self.engine._emit("trades_updated", {
                            "trades": self.engine.history.get_trades(limit=50),
                            "stats": self.engine.history.get_stats(),
                        })
                    except Exception as he:
                        logger.error("Failed to record external close in history: %s", he)

                self.engine._emit("log", {
                    "level": "warn",
                    "msg": (f"[{symbol}] ⚠️ Position closed (SL/TP hit on exchange or manual close). "
                            f"Bot expected {self.expected_pos_side} but found NONE. "
                            f"Waiting for NEW cross before next trade.")
                })
                self.expected_pos_side = None
                self.position_side = None
                self.entry_price = None
                self.waiting_for_new_cross = True  # Strict mode: must wait for fresh cross
                self.strategy.reset_cross_state()
                self._exchange_tp_cleaned = False
                self.sl_price = None
                self.tp_price = None
                self.tp_stage = 0
                try:
                    if hasattr(self.engine.trader, "cancel_open_orders"):
                        self.engine.trader.cancel_open_orders(symbol)
                except Exception:
                    pass
            elif actual_side != "NONE" and self.expected_pos_side != actual_side and self.reversal_pending_side is None:
                # Genuine position opened externally or on startup
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": (f"[{symbol}] ⚠️ External trade detected! "
                            f"Bot expected {self.expected_pos_side or 'NONE'} but found {actual_side}. "
                            f"Syncing state to {actual_side}.")
                })
                self.expected_pos_side = actual_side
                if not self.engine.history.has_open_trade(symbol):
                    try:
                        lev = pos.leverage if (pos.leverage and int(pos.leverage) > 1) else self._get_effective_leverage(symbol)
                        self.engine.history.record_open(
                            symbol=symbol,
                            side=actual_side,
                            entry_price=pos.entry_price or pos.mark_price,
                            qty=abs(pos.size),
                            leverage=lev,
                            initial_sl=self.sl_price,
                            initial_tp=self.tp_price,
                        )
                        self.engine._emit("trades_updated", {
                            "trades": self.engine.history.get_trades(limit=50),
                            "stats": self.engine.history.get_stats(),
                        })
                    except Exception as he:
                        logger.error("Failed to auto-register existing position in history: %s", he)
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

        # ===== AUTO-RESTORE / MIGRATE SL/TP FOR ACTIVE POSITION =====
        # If there's an open position:
        # 1. Enforce pure 'trailing' mode (migrate any legacy 'both' / 'fixed' modes)
        # 2. Purge any unscaled 6% / 750% ROI fixed TP orders from Binance
        # 3. Establish true 1:1 symmetrical trailing SL/TP
        if actual_side != "NONE" and self.reversal_pending_side is None:
            entry = pos.entry_price
            needs_init = (self.sl_price is None or self.tp_price is None)

            if entry > 0 and needs_init:
                sl_pct_val = float(cfg.get("stop_loss_pct", 2))
                tp_pct_val = sl_pct_val  # Strict 1:1
                inferred_entry_signal = Signal.BUY if actual_side == "LONG" else Signal.SELL
                self._set_software_sl_tp(
                    symbol, actual_side, entry, sl_pct_val, tp_pct_val,
                    tp_mode="fixed",
                    entry_signal=inferred_entry_signal,
                    actual_leverage=pos.leverage,
                )
                # Auto-register in trade history if not already open
                if not self.engine.history.has_open_trade(symbol) and abs(pos.size) > 0:
                    try:
                        lev = pos.leverage if (pos.leverage and int(pos.leverage) > 1) else self._get_effective_leverage(symbol)
                        self.engine.history.record_open(
                            symbol=symbol,
                            side=actual_side,
                            entry_price=entry,
                            qty=abs(pos.size),
                            leverage=lev,
                            initial_sl=self.sl_price,
                            initial_tp=self.tp_price,
                        )
                    except Exception as he:
                        logger.error("Failed to auto-register restored trade in history: %s", he)

                # Purge any legacy 6% fixed TP orders on exchange & sync SL to safe level
                if self.sl_price and self.sl_price > 0:
                    self._update_exchange_sl(actual_side, self.sl_price, abs(pos.size))
                self._exchange_tp_cleaned = True
                tp_log = f"TP=STRICT 1:1 (+{self.target_roe_pct:.0f}% ROE target=${self.tp_price:.4f})"
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": (f"[{symbol}] ⚠️ AUTO-RESTORED SL/TP for {actual_side} position | "
                            f"Entry={entry:.4f} | SL={self.sl_price:.4f} | {tp_log} | "
                            f"Lev={self._get_effective_leverage(symbol)}x")
                })
            elif not getattr(self, "_exchange_tp_cleaned", False) and self.tp_mode == "trailing":
                # Ensure rogue exchange TP orders are purged once on active position
                if self.sl_price and self.sl_price > 0:
                    self._update_exchange_sl(actual_side, self.sl_price, abs(pos.size))
                self._exchange_tp_cleaned = True

        effective_lev = pos.leverage if (pos.side != "NONE" and pos.size != 0 and pos.leverage and int(pos.leverage) > 1) else self._get_effective_leverage(symbol)
        self.engine._emit("position", {
            "symbol": symbol,
            "side": pos.side,
            "size": pos.size,
            "entry_price": pos.entry_price,
            "mark_price": pos.mark_price,
            "unrealized_pnl": pos.unrealized_pnl,
            "leverage": effective_lev,
            "tp_stage": self.tp_stage if pos.side != "NONE" else 0,
            "tp_price": self.tp_price if (pos.side != "NONE" and self.tp_price) else 0.0,
            "sl_price": self.sl_price if (pos.side != "NONE" and self.sl_price) else 0.0,
            "target_roe": getattr(self, "target_roe_pct", 100.0),
            "tp_mode": self.tp_mode,
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
                # Signal drifted (e.g. went to HOLD briefly) before re-entry.
                # CRITICAL FIX: Clear reversal_pending_side so it doesn't get
                # stuck forever. Fall through to normal fresh-cross logic below.
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": (f"[{symbol}] ⚠️ Reversal signal drifted — "
                            f"expected {desired_sig.value}, got {signal.value}. "
                            f"Clearing reversal flag, waiting for fresh cross.")
                })
                self.reversal_pending_side = None
                self.waiting_for_new_cross = True
                self.strategy.reset_cross_state()
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
            # No position open for this symbol.
            # If signal is HOLD -> wait for BUY or SELL
            if signal == Signal.HOLD:
                return

            # CONCURRENT ACTIVE TRADES CONTROL:
            # User can choose 1, 2, or 3 simultaneous active coin trades (default: 3).
            can_open, reason = self.engine.can_open_new_trade(symbol)
            if not can_open:
                now = time.time()
                if now - getattr(self, '_last_locked_log_time', 0) > 60:
                    self.engine._emit("log", {
                        "level": "info",
                        "msg": f"[{symbol}] In {signal.value} setup, but {reason}. Holding until an active trade slot frees up."
                    })
                    self._last_locked_log_time = now
                return

            # If waiting_for_new_cross is True (startup or after trade closed), must wait for fresh crossover!
            if self.waiting_for_new_cross:
                if not result.just_crossed:
                    return

            # Active signal & fresh cross! Guard against multiple entries on same closed candle
            candle_id = str(df.index[-2]) if len(df) >= 2 else str(time.time())
            if getattr(self, '_last_trade_candle_id', None) == candle_id:
                return

            now = time.time()
            if now - self._last_cross_time < 30:
                # Too soon after last cross - ignore (prevents rapid false crosses)
                return

            # Acquire thread-safe entry lock to prevent simultaneous entry collisions
            with self.engine._trade_entry_lock:
                can_open, _ = self.engine.can_open_new_trade(symbol)
                if not can_open:
                    return
                self._last_cross_time = now
                self._last_trade_candle_id = candle_id
                self.waiting_for_new_cross = False
                if hasattr(self, '_waiting_logged'):
                    delattr(self, '_waiting_logged')
                self.strategy.mark_trade_entered()

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
        # User explicitly requested 1:1 Fixed Take Profit (no trailing, no multiple stages)
        tp_mode = (cfg.get("tp_mode") or "fixed").lower()
        if tp_mode not in ("fixed", "trailing", "ema_reversal"):
            tp_mode = "fixed"

        # Determine effective leverage from user config
        lev = self._get_effective_leverage(symbol)
        try:
            if hasattr(self.engine.trader, "set_leverage"):
                self.engine.trader.set_leverage(symbol, lev)
        except Exception:
            pass

        # 1:1 Fixed TP: TP distance exactly matches Stop Loss distance (1:1 Risk/Reward)
        safe_sl_roe = min(sl_pct * lev, 80.0)
        sl_dist = mark_price * ((safe_sl_roe / lev) / 100.0)
        tp_dist = sl_dist  # EXACT 1:1 RATIO!
        tp_pct = sl_pct
        r_dist = sl_dist
        target_roe_val = safe_sl_roe

        # Helper: build a short label string for log messages
        def _tp_log_label():
            return f"TP=STRICT 1:1 (+{target_roe_val:.0f}% ROE, Exit 100% on 1:1 Target)"

        # Fee safety check: TP distance must be >= MIN_FEE_BUFFER_PCT (0.15% price move)
        # to ensure profit is greater than 2x taker fees + slippage (~0.15%)
        MIN_FEE_BUFFER_PCT = 0.15
        tp_dist_pct = (r_dist / mark_price) * 100.0 if mark_price > 0 else 0.0
        if tp_dist_pct < MIN_FEE_BUFFER_PCT:
            self.engine._emit("log", {
                "level": "warn",
                "msg": (f"[{symbol}] ⚠️ Fee safety check: TP distance ({tp_dist_pct:.3f}%) < "
                        f"{MIN_FEE_BUFFER_PCT}% (2x taker fees + slippage buffer). Trade skipped to protect net profit.")
            })
            return

        order_type_cfg = cfg.get("order_type", "maker").lower()

        if signal == Signal.BUY:
            # Open LONG
            # Calculate SL price (always sent to exchange — capital protection)
            sl_price_long = mark_price - sl_dist

            # In 'fixed' mode, attach exact 1:1 Take Profit. In trailing or ema_reversal mode, software manages it.
            tp_price_long = mark_price + tp_dist if tp_mode == "fixed" else None
            self.engine._emit("log", {
                "level": "info",
                "msg": (f"[{symbol}] 🟢 FRESH BUY cross -> opening LONG ({order_type_cfg.upper()}) qty={trade_size:.6f} @ ~{mark_price:.4f} | "
                        f"SL={sl_price_long:.4f} | {_tp_log_label()} | "
                        f"EMA8={e8:.4f} EMA13={e13:.4f} EMA21={e21:.4f} EMA55={e55:.4f} | Lev={lev}x")
            })
            # Pass SL price and order_type to open_long
            try:
                order = self.engine.trader.open_long(symbol, trade_size,
                                                     sl_price=sl_price_long,
                                                     tp_price=tp_price_long,
                                                     order_type=order_type_cfg,
                                                     price=mark_price)
            except TypeError:
                try:
                    order = self.engine.trader.open_long(symbol, trade_size,
                                                         sl_price=sl_price_long,
                                                         tp_price=tp_price_long)
                except TypeError:
                    order = self.engine.trader.open_long(symbol, trade_size)
            actual_qty = order.get("quantity", trade_size)
            self._log_order(order, f"[{symbol}] OPEN LONG ({order_type_cfg.upper()}) qty={actual_qty:.6f}")
            if order.get("success"):
                self.trades_today += 1
                self.last_signal = Signal.BUY
                self.expected_pos_side = "LONG"
                self.reversal_pending_side = None
                self.waiting_for_new_cross = False
                self.be_sl_set = False
                self.partial_tp_done = False
                self.strategy.mark_trade_entered()
                # Get ACTUAL entry price from position (not mark_price)
                actual_entry = self._get_actual_entry_price(symbol, mark_price)
                # Set software watchdog (always — this is the source of truth
                # for SL/TP exits, including 1:1 TP & SL)
                self._set_software_sl_tp(symbol, "LONG", actual_entry, sl_pct, tp_pct,
                                         tp_mode=tp_mode, entry_signal=Signal.BUY,
                                         actual_leverage=lev)

                # Record in trade history!
                try:
                    target_tp = actual_entry + (self.target_roe_pct / lev / 100.0 * actual_entry) if (self.target_roe_pct and lev) else None
                    self.engine.history.record_open(
                        symbol=symbol,
                        side="LONG",
                        entry_price=actual_entry,
                        qty=actual_qty,
                        leverage=lev,
                        initial_sl=sl_price_long,
                        initial_tp=target_tp,
                        order_type=order_type_cfg,
                    )
                    self.engine._emit("trades_updated", {
                        "trades": self.engine.history.get_trades(limit=50),
                        "stats": self.engine.history.get_stats(),
                    })
                except Exception as he:
                    logger.error("Failed to record trade open in history: %s", he)

                # Log exchange SL status
                if order.get("sl_price"):
                    self.engine._emit("log", {
                        "level": "success",
                        "msg": (f"[{symbol}] ✅ Exchange SL attached | "
                                f"SL={order.get('sl_price', 'N/A')} | "
                                f"(Target=Strict 1:1 TP)")
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
            sl_price_short = mark_price + sl_dist

            # In 'fixed' mode, attach exact 1:1 Take Profit. In trailing or ema_reversal mode, software manages it.
            tp_price_short = mark_price - tp_dist if tp_mode == "fixed" else None
            self.engine._emit("log", {
                "level": "info",
                "msg": (f"[{symbol}] 🔴 FRESH SELL cross -> opening SHORT ({order_type_cfg.upper()}) qty={trade_size:.6f} @ ~{mark_price:.4f} | "
                        f"SL={sl_price_short:.4f} | {_tp_log_label()} | "
                        f"EMA8={e8:.4f} EMA13={e13:.4f} EMA21={e21:.4f} EMA55={e55:.4f} | Lev={lev}x")
            })
            try:
                order = self.engine.trader.open_short(symbol, trade_size,
                                                      sl_price=sl_price_short,
                                                      tp_price=tp_price_short,
                                                      order_type=order_type_cfg,
                                                      price=mark_price)
            except TypeError:
                try:
                    order = self.engine.trader.open_short(symbol, trade_size,
                                                          sl_price=sl_price_short,
                                                          tp_price=tp_price_short)
                except TypeError:
                    order = self.engine.trader.open_short(symbol, trade_size)
            actual_qty = order.get("quantity", trade_size)
            self._log_order(order, f"[{symbol}] OPEN SHORT ({order_type_cfg.upper()}) qty={actual_qty:.6f}")
            if order.get("success"):
                self.trades_today += 1
                self.last_signal = Signal.SELL
                self.expected_pos_side = "SHORT"
                self.reversal_pending_side = None
                self.waiting_for_new_cross = False
                self.be_sl_set = False
                self.partial_tp_done = False
                self.strategy.mark_trade_entered()
                # Get ACTUAL entry price from position (not mark_price)
                actual_entry = self._get_actual_entry_price(symbol, mark_price)
                # Set software watchdog
                self._set_software_sl_tp(symbol, "SHORT", actual_entry, sl_pct, tp_pct,
                                         tp_mode=tp_mode, entry_signal=Signal.SELL,
                                         actual_leverage=lev)

                # Record in trade history!
                try:
                    target_tp = actual_entry - (self.target_roe_pct / lev / 100.0 * actual_entry) if (self.target_roe_pct and lev) else None
                    self.engine.history.record_open(
                        symbol=symbol,
                        side="SHORT",
                        entry_price=actual_entry,
                        qty=actual_qty,
                        leverage=lev,
                        initial_sl=sl_price_short,
                        initial_tp=target_tp,
                        order_type=order_type_cfg,
                    )
                    self.engine._emit("trades_updated", {
                        "trades": self.engine.history.get_trades(limit=50),
                        "stats": self.engine.history.get_stats(),
                    })
                except Exception as he:
                    logger.error("Failed to record trade open in history: %s", he)

                # Log exchange SL status
                if order.get("sl_price"):
                    self.engine._emit("log", {
                        "level": "success",
                        "msg": (f"[{symbol}] ✅ Exchange SL attached | "
                                f"SL={order.get('sl_price', 'N/A')} | "
                                f"(Target=Strict 1:1 TP)")
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
                            sl_pct: float = 2.0, tp_pct: float = 6.0,
                            tp_mode: str = "trailing",
                            entry_signal: Optional[Signal] = None,
                            actual_leverage: Optional[int] = None):
        """Set SL/TP prices in memory (software watchdog).

        Parameters
        ----------
        sl_pct, tp_pct : float
            Percentages for SL and fixed-TP.
        tp_mode : str
            'trailing' | 'fixed' | 'ema_reversal' | 'both'.
        entry_signal : Signal | None
            The strategy signal (BUY/SELL) that opened this position.
        actual_leverage : int | None
            Explicit leverage override if known.
        """
        if entry_price <= 0:
            self.engine._emit("log", {
                "level": "error",
                "msg": f"[{symbol}] ❌ Cannot set SL/TP - invalid entry price"
            })
            return

        # Normalize + persist tp_mode for this position
        tp_mode = (tp_mode or "fixed").lower()
        if tp_mode not in ("fixed", "trailing", "ema_reversal"):
            tp_mode = "fixed"
        self.tp_mode = tp_mode
        self.entry_signal = entry_signal
        self.ema_reversal_tp_fired = False  # reset one-shot guard
        self.be_sl_set = False
        self.partial_tp_done = False
        self.tp_stage = 1

        # Effective leverage from position/exchange or override or config
        lev = actual_leverage if (actual_leverage and actual_leverage > 1) else self._get_effective_leverage(symbol)
        
        # Calculate SL distance from sl_pct (capped at 80% ROE for liquidation safety at ultra-high leverage)
        sl_roe = sl_pct * lev
        safe_sl_roe = min(sl_roe, 80.0)
        sl_dist = entry_price * ((safe_sl_roe / lev) / 100.0)
        
        self.target_roe_pct = safe_sl_roe
        self.r_distance = sl_dist

        # In trailing mode: Exact 1:1 Risk-to-Reward.
        # Distance to TP1 (1R reward) = self.r_distance (100% ROE = equal to margin investment).
        # Safe against liquidation (at 125x, SL triggers at -80% ROE BEFORE 100% liquidation).
        # Pure 1:1 Risk-to-Reward (TP distance == SL distance)
        if side == "LONG":
            self.sl_price = entry_price - sl_dist
            self.tp_price = entry_price + sl_dist
            self.initial_sl_price = self.sl_price
        else:  # SHORT
            self.sl_price = entry_price + sl_dist
            self.tp_price = entry_price - sl_dist
            self.initial_sl_price = self.sl_price

        self.entry_price = entry_price
        self.position_side = side

        tp_desc = f"TP={self.tp_price:.4f} (Strict 1:1 / +{safe_sl_roe:.0f}% ROE 🎯)"
        sl_info = f"SL={self.sl_price:.4f} (-{safe_sl_roe:.0f}% ROE 🛡️)"

        self.engine._emit("log", {
            "level": "success",
            "msg": (f"[{symbol}] ✅ Software SL/TP set | "
                    f"Entry={entry_price:.4f} | "
                    f"{sl_info} | "
                    f"{tp_desc} | Side={side} | Lev={lev}x")
        })

    def _check_software_sl_tp(self, pos, result) -> tuple:
        """Check if software SL or TP has been hit.

        Parameters
        ----------
        pos : Position
            Current exchange position (has .side, .mark_price, .entry_price).
        result : StrategyResult
            Latest strategy result.

        Returns
        -------
        (sl_hit: bool, tp_hit: bool, reason: str)
        """
        if self.sl_price is None:
            return (False, False, "")

        mark = pos.mark_price
        side = pos.side

        # CRITICAL: If mark_price is 0 or invalid, skip SL/TP check
        if mark is None or mark <= 0:
            return (False, False, "")

        lev = pos.leverage if (pos and pos.leverage and pos.leverage > 1) else self._get_effective_leverage(self.symbol)
        if side == "LONG":
            price_pnl_pct = (mark - self.entry_price) / self.entry_price * 100 if self.entry_price > 0 else 0
        else:
            price_pnl_pct = (self.entry_price - mark) / self.entry_price * 100 if self.entry_price > 0 else 0
        cur_roe = price_pnl_pct * lev

        # ---------- 1) EMA-REVERSAL / FLIP CHECK (Always Active) ----------
        # If position is open (e.g. LONG) and a confirmed OPPOSITE signal (SELL) occurs:
        # Immediately exit trade and flip!
        if not self.ema_reversal_tp_fired and result is not None and self.entry_signal is not None:
            cur_sig = result.signal
            if side == "LONG" and self.entry_signal == Signal.BUY and cur_sig == Signal.SELL:
                pnl_pct = (mark - self.entry_price) / self.entry_price * 100 if self.entry_price > 0 else 0
                self.ema_reversal_tp_fired = True  # one-shot
                return (False, True,
                        f"⚡ EMA55-REVERSAL (LONG->EMA55 now TOP, PnL={pnl_pct:+.2f}%, Live ROE={cur_roe:+.1f}%)")
            if side == "SHORT" and self.entry_signal == Signal.SELL and cur_sig == Signal.BUY:
                pnl_pct = (self.entry_price - mark) / self.entry_price * 100 if self.entry_price > 0 else 0
                self.ema_reversal_tp_fired = True  # one-shot
                return (False, True,
                        f"⚡ EMA55-REVERSAL (SHORT->EMA55 now BOTTOM, PnL={pnl_pct:+.2f}%, Live ROE={cur_roe:+.1f}%)")

        # ---------- 2) STOP-LOSS CHECK (Strict 1:1 Risk) ----------
        sl_hit = False
        if side == "LONG" and mark <= self.sl_price:
            sl_hit = True
        elif side == "SHORT" and mark >= self.sl_price:
            sl_hit = True

        if sl_hit:
            reason = f"⚡ 1:1 SL HIT (price {mark:.4f}, SL {self.sl_price:.4f}, Live ROE={cur_roe:+.1f}%)"
            return (True, False, reason)

        # ---------- 3) TAKE-PROFIT CHECK (Strict 1:1 Reward Exit) ----------
        if self.tp_price is not None:
            if side == "LONG" and mark >= self.tp_price:
                pnl_pct = (mark - self.entry_price) / self.entry_price * 100 if self.entry_price > 0 else 0
                return (False, True,
                        f"🎯 1:1 TAKE PROFIT HIT (price {mark:.4f} >= TP {self.tp_price:.4f}, PnL={pnl_pct:+.2f}%, Live ROE={cur_roe:+.1f}%)")
            elif side == "SHORT" and mark <= self.tp_price:
                pnl_pct = (self.entry_price - mark) / self.entry_price * 100 if self.entry_price > 0 else 0
                return (False, True,
                        f"🎯 1:1 TAKE PROFIT HIT (price {mark:.4f} <= TP {self.tp_price:.4f}, PnL={pnl_pct:+.2f}%, Live ROE={cur_roe:+.1f}%)")

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
            # Poll every 10s (protects exchange API rate limits)
            for _ in range(10):
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
            worker = self.engine.workers.get(symbol)
            tp_stage = worker.tp_stage if (worker and pos.side != "NONE") else 0
            tp_price = worker.tp_price if (worker and pos.side != "NONE" and worker.tp_price) else 0.0
            sl_price = worker.sl_price if (worker and pos.side != "NONE" and worker.sl_price) else 0.0
            tp_mode = worker.tp_mode if worker else (self.engine.config.get("tp_mode") or "fixed")
            target_roe = getattr(worker, "target_roe_pct", 100.0) if worker else 100.0
            effective_lev = pos.leverage if (pos.leverage and int(pos.leverage) > 1) else (
                getattr(worker, "_get_effective_leverage", lambda s: int(self.engine.config.get("leverage", 125)))(symbol)
            )
            self.engine._emit("position", {
                "symbol": symbol,
                "side": pos.side,
                "size": pos.size,
                "entry_price": pos.entry_price,
                "mark_price": pos.mark_price if pos.mark_price > 0 else mark_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "leverage": effective_lev,
                "tp_stage": tp_stage,
                "tp_price": tp_price,
                "sl_price": sl_price,
                "target_roe": target_roe,
                "tp_mode": tp_mode,
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
        self.history = TradeHistoryManager()
        self.workers: dict[str, SymbolWorker] = {}
        self.lock = threading.Lock()
        self._trade_entry_lock = threading.Lock()
        self.is_running = False
        self.active_symbol = None  # Which coin the UI is currently viewing
        # ===== MONITOR MODE =====
        # Always-on background thread that fetches balance, mark_price, chart
        # for the active symbol. Works even when bot is STOPPED, so user can
        # see live data immediately after saving settings.
        self.monitor_thread: Optional[MonitorThread] = None
        self.monitor_trader = None  # separate trader instance for monitor

    def get_active_positions(self) -> list[str]:
        """Return list of symbols that currently have an active open position."""
        active = []
        for sym, worker in self.workers.items():
            is_active = (
                getattr(worker, "position_side", None) in ("LONG", "SHORT") or
                getattr(worker, "expected_pos_side", None) in ("LONG", "SHORT") or
                (getattr(worker, "entry_price", None) is not None and getattr(worker, "entry_price", 0) > 0)
            )
            if is_active:
                active.append(sym)
        return list(dict.fromkeys(active))

    def has_any_active_position(self) -> tuple[bool, Optional[str]]:
        """Check if ANY monitored symbol worker currently has an active open trade."""
        active = self.get_active_positions()
        return (len(active) > 0, active[0] if active else None)

    def can_open_new_trade(self, symbol: str) -> tuple[bool, str]:
        """Check if a new trade can be opened for symbol, respecting max_concurrent_trades (1, 2, or 3)."""
        active_symbols = self.get_active_positions()
        # If this symbol itself already has a position open, do not re-enter
        if symbol in active_symbols:
            return False, f"[{symbol}] already has an active position"

        # User configurable max concurrent trades: 1, 2, or 3 (default: 3)
        try:
            max_trades = int(self.config.get("max_concurrent_trades", 3))
        except (ValueError, TypeError):
            max_trades = 3
        max_trades = max(1, min(3, max_trades))

        if len(active_symbols) >= max_trades:
            return False, f"limit of {max_trades} simultaneous coin trades reached ({', '.join(active_symbols)})"
        return True, ""

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

    def apply_leverage(self, leverage: int, symbol: Optional[str] = None) -> dict:
        """Apply leverage to symbol(s) on exchange and update config, running workers, and UI."""
        symbols = [symbol.strip().upper()] if symbol else self._symbols_list()
        if not symbols:
            symbols = [str(self.config.get("symbol", "BTCUSDT")).strip().upper()]

        self.config["leverage"] = leverage
        # Update running workers
        with self.lock:
            for w in self.workers.values():
                w.config["leverage"] = leverage

        results = {}
        active_trader = self.trader or self.monitor_trader
        if not active_trader:
            try:
                active_trader = get_trader(self.config)
            except Exception as e:
                logger.warning("Could not instantiate trader for apply_leverage: %s", e)
                active_trader = None

        if active_trader:
            for sym in symbols:
                try:
                    r = active_trader.set_leverage(sym, leverage)
                    results[sym] = r
                    actual = r.get("leverage", leverage) if r.get("success") else leverage
                    if r.get("adjusted"):
                        self._emit("log", {
                            "level": "warn",
                            "msg": f"[{sym}] ⚠️ Binance Official Limit: {sym} par maximum allowed leverage {actual}x hai ({leverage}x Binance allow nahi karta). Set to {actual}x."
                        })
                    elif r.get("success"):
                        self._emit("log", {
                            "level": "success",
                            "msg": f"[{sym}] ⚡ Leverage set to {actual}x on {self.config.get('exchange', 'binance').upper()}"
                        })
                    else:
                        self._emit("log", {
                            "level": "warn",
                            "msg": f"[{sym}] ⚠️ Leverage notice: {r.get('error', 'unknown')}"
                        })
                except Exception as e:
                    logger.error("Failed to set leverage for %s: %s", sym, e)
                    results[sym] = {"success": False, "error": str(e)}

        # Emit updated position event for the active symbol so UI updates immediately
        cur_sym = self.active_symbol or (symbols[0] if symbols else "BTCUSDT")
        try:
            if active_trader:
                pos = active_trader.get_position(cur_sym)
                worker = self.workers.get(cur_sym)
                tp_stage = worker.tp_stage if (worker and pos.side != "NONE") else 0
                tp_price = worker.tp_price if (worker and pos.side != "NONE" and worker.tp_price) else 0.0
                sl_price = worker.sl_price if (worker and pos.side != "NONE" and worker.sl_price) else 0.0
                tp_mode = worker.tp_mode if worker else (self.config.get("tp_mode") or "fixed")
                target_roe = getattr(worker, "target_roe_pct", 100.0) if worker else 100.0
                self._emit("position", {
                    "symbol": cur_sym,
                    "side": pos.side,
                    "size": pos.size,
                    "entry_price": pos.entry_price,
                    "mark_price": pos.mark_price,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "leverage": pos.leverage,
                    "tp_stage": tp_stage,
                    "tp_price": tp_price,
                    "sl_price": sl_price,
                    "target_roe": target_roe,
                    "tp_mode": tp_mode,
                })
            else:
                self._emit("position", {
                    "symbol": cur_sym,
                    "side": "NONE",
                    "size": 0,
                    "entry_price": 0,
                    "mark_price": 0,
                    "unrealized_pnl": 0,
                    "leverage": leverage,
                })
        except Exception:
            pass

        target_sym = cur_sym if cur_sym in results else (symbols[0] if symbols else None)
        effective_actual_lev = results.get(target_sym, {}).get("leverage", leverage) if target_sym else leverage
        is_adjusted = results.get(target_sym, {}).get("adjusted", False) if target_sym else False
        return {
            "success": True, 
            "leverage": effective_actual_lev, 
            "requested": leverage, 
            "adjusted": is_adjusted, 
            "results": results
        }

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
        self.stop_monitor()  # Stop background monitor while trading workers are running to avoid hitting rate limits
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
                    if r.get("success"):
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
                        # Emit position immediately with actual leverage
                        try:
                            pos = self.trader.get_position(sym)
                            worker = self.workers.get(sym)
                            tp_stage = worker.tp_stage if (worker and pos.side != "NONE") else 0
                            tp_price = worker.tp_price if (worker and pos.side != "NONE" and worker.tp_price) else 0.0
                            sl_price = worker.sl_price if (worker and pos.side != "NONE" and worker.sl_price) else 0.0
                            tp_mode = worker.tp_mode if worker else (self.config.get("tp_mode") or "fixed")
                            target_roe = getattr(worker, "target_roe_pct", 100.0) if worker else 100.0
                            self._emit("position", {
                                "symbol": sym,
                                "side": pos.side,
                                "size": pos.size,
                                "entry_price": pos.entry_price,
                                "mark_price": pos.mark_price,
                                "unrealized_pnl": pos.unrealized_pnl,
                                "leverage": pos.leverage,
                                "tp_stage": tp_stage,
                                "tp_price": tp_price,
                                "sl_price": sl_price,
                                "target_roe": target_roe,
                                "tp_mode": tp_mode,
                            })
                        except Exception:
                            pass
                    else:
                        err = str(r.get("error", ""))
                        is_binance = self.config.get("exchange", "binance").lower() == "binance"
                        if is_binance and ("-2015" in err or "Invalid API-key" in err or "401" in err):
                            self._emit("log", {
                                "level": "error",
                                "msg": f"[{sym}] ❌ API AUTH FAILED (-2015): Your API Key is REJECTED by Binance! 1) Check 'Enable Futures'. 2) If IP restricted, whitelist your VPS IP. 3) Ensure it's a Futures key, not Spot!"
                            })
                            # Stop the bot completely and kill all threads
                            self.is_running = False
                            for w in self.workers.values():
                                w.stop_event.set()
                            return
                        elif not is_binance and ("-1044" in err or "401" in err or "signature" in err.lower()):
                            self._emit("log", {
                                "level": "warn",
                                "msg": f"[{sym}] ⚠️ WEEX leverage notice: {err[:80]}. Continuing with effective leverage."
                            })
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
        sl_pct_val = config.get("stop_loss_pct", 2)
        sl_info = f"SL={sl_pct_val}%" if sl_pct_val else "SL=OFF"
        tp_info = f"TP=STRICT 1:1 ({sl_pct_val}%) + AUTO-REVERSAL"
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

    def sync_config(self, new_config: dict):
        """Dynamically update running workers when user saves settings without needing stop/start."""
        self.config = new_config
        self.notifier.update_config(new_config)
        if not self.is_running:
            return

        new_symbols = set(self._symbols_list())
        with self.lock:
            current_symbols = set(self.workers.keys())

            # Stop and remove deleted symbols
            to_remove = current_symbols - new_symbols
            for sym in to_remove:
                w = self.workers.pop(sym, None)
                if w:
                    w.stop_event.set()
                    self._emit("log", {"level": "info", "msg": f"[{sym}] ⏹️ Removed from active trading watchlist. Worker stopped."})

            # Start new symbols
            to_add = new_symbols - current_symbols
            for sym in to_add:
                w = SymbolWorker(self, sym, new_config)
                self.workers[sym] = w
                w.start()
                self._emit("log", {"level": "info", "msg": f"[{sym}] ▶️ Added to active trading watchlist. Worker started."})

            # Update config on surviving workers
            for sym in (current_symbols & new_symbols):
                w = self.workers.get(sym)
                if w:
                    w.config = new_config

        if new_symbols and self.active_symbol not in new_symbols:
            self.set_active_symbol(list(new_symbols)[0])

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
        try:
            self.start_monitor(self.config)
        except Exception:
            pass
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
        try:
            self.start_monitor(self.config)
        except Exception:
            pass
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
            "1m": 5, "3m": 8, "5m": 12, "15m": 20,
            "30m": 30, "1h": 45, "2h": 60, "4h": 90,
            "1d": 120, "1w": 300,
        }
        return mapping.get(timeframe, 12)

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

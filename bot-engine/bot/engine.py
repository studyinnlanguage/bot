"""
Bot Engine — Pure EMA (8, 13, 21, 55) + Pure EMA55 Reversal Execution.

Runs one background worker thread per symbol across Binance (Mainnet/Testnet),
WEEX (Mainnet/Demo), and PrimeXBT (Live/Demo).

Rules:
- NO spread filter, NO 2-candle waiting, NO startup waiting, NO re-entry cooldown.
- NO Stop Loss, NO Take Profit, NO Trailing, NO Breakeven Lock.
- Entry:
    * EMA55 at BOTTOM (< EMA 8, 13, 21) -> LONG
    * EMA55 at TOP    (> EMA 8, 13, 21) -> SHORT
- Exit & Reversal:
    * LONG open & EMA55 flips to TOP    -> Close LONG & immediately open SHORT
    * SHORT open & EMA55 flips to BOTTOM -> Close SHORT & immediately open LONG
- Leverage & Wallet position sizing (Fixed USDT or % of Wallet Balance) preserved.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from .strategy import EMAQuadStrategy, Signal
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
    return BinanceFuturesTrader(
        api_key=config["api_key"],
        api_secret=config["api_secret"],
        testnet=config.get("testnet", True),
    )


class SymbolWorker(threading.Thread):
    """One worker per symbol. Runs pure EMA + pure EMA55 reversal loop."""

    def __init__(self, engine, symbol: str, config: dict, leverage_ready: threading.Event = None):
        super().__init__(daemon=True, name=f"worker-{symbol}")
        self.engine = engine
        self.symbol = symbol
        self.config = config
        self.stop_event = threading.Event()
        self.last_signal = Signal.HOLD
        self.candles_processed = 0
        self.trades_today = 0
        self.last_check = None
        self._last_trade_date = datetime.now(timezone.utc).date()

        # Position tracking (pure EMA reversal — no SL/TP/trailing state)
        self.expected_pos_side = None   # "LONG" / "SHORT" / None
        self.position_side = None       # "LONG" / "SHORT" / None
        self.entry_price = None
        self.last_trade_side = None

        self._last_df = None
        self._last_mark_price = None
        self.strategy = EMAQuadStrategy()
        self._leverage_ready = leverage_ready
        self._last_close_timestamp = 0.0
        self._last_open_timestamp = 0.0
        self.state = "starting"

    def update_config(self, cfg: dict):
        """Live-update worker config (timeframe, leverage, sizing, mode)."""
        self.config = cfg

    def _get_effective_leverage(self, symbol: str) -> int:
        """Get active leverage for this symbol from open position or config."""
        cfg_lev = max(1, int(self.config.get("leverage", 20) or 20))
        try:
            trader = self.engine.trader or self.engine.monitor_trader
            if trader:
                pos = trader.get_position(symbol)
                if pos and pos.side != "NONE" and pos.size != 0 and pos.leverage and int(pos.leverage) > 1:
                    return int(pos.leverage)
        except Exception:
            pass
        return cfg_lev

    def run(self):
        poll_seconds = BotEngine._poll_seconds(self.config.get("timeframe", "15m"))
        self.engine._emit("log", {
            "level": "info",
            "msg": f"[{self.symbol}] Worker started (Pure EMA + Reversal). Polling every {poll_seconds}s."
        })
        if self._leverage_ready is not None:
            self.state = "waiting_leverage"
            self._leverage_ready.wait(timeout=30)
            if not self._leverage_ready.is_set():
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"[{self.symbol}] Leverage setup timed out (30s). Proceeding with configured leverage."
                })
        self.state = "running"

        # Pre-fetch chart data immediately for active symbol (NO startup waiting/blocking)
        try:
            df = self.engine.trader.get_klines(self.symbol, interval=self.config["timeframe"], limit=200)
            self._last_df = df
            self.engine.set_connection_state("market_data", "ok")
            if df is not None and len(df) >= 60 and self.engine.active_symbol == self.symbol:
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
        except Exception as e:
            err_msg = str(e)
            logger.error(f"[{self.symbol}] Initial klines fetch failed: {err_msg}")
            if any(x in err_msg.lower() for x in ["timeout", "timed out", "connection", "network", "ssl", "max retries"]):
                self.engine.set_connection_state("market_data", "failed")
            if any(x in err_msg.lower() for x in ["-1121", "invalid symbol", "symbol not supported", "unknown symbol"]):
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"[{self.symbol}] ⚠️ Symbol not supported on current exchange environment. Skipping."
                })

        while not self.stop_event.is_set():
            if not self.engine.is_running:
                break
            try:
                self._tick()
            except Exception as e:
                logger.exception(f"[{self.symbol}] tick error")
                self.state = f"error:{str(e)[:60]}"
                self.engine._emit("log", {
                    "level": "error",
                    "msg": f"[{self.symbol}] tick error: {str(e)[:100]}"
                })
            cur_poll = BotEngine._poll_seconds(self.config.get("timeframe", "15m"))
            for _ in range(cur_poll):
                if self.stop_event.is_set() or not self.engine.is_running:
                    break
                time.sleep(1)

        self.state = "stopped"
        self.engine._emit("log", {
            "level": "info",
            "msg": f"[{self.symbol}] Worker stopped."
        })

    def _tick(self):
        cfg = self.config
        symbol = self.symbol
        timeframe = cfg["timeframe"]

        if self.engine.trader is None:
            return

        # Reset trades_today at midnight UTC
        today = datetime.now(timezone.utc).date()
        if today != self._last_trade_date:
            self.trades_today = 0
            self._last_trade_date = today

        # 1. Fetch klines
        try:
            df = self.engine.trader.get_klines(symbol, interval=timeframe, limit=200)
            self._last_df = df
        except Exception as e:
            err_msg = str(e)
            logger.error(f"[{symbol}] Failed to fetch klines: {err_msg}")
            if any(x in err_msg.lower() for x in ["-1121", "invalid symbol", "symbol not supported", "unknown symbol"]):
                if not hasattr(self, "_warned_invalid_sym"):
                    self._warned_invalid_sym = set()
                if symbol not in self._warned_invalid_sym:
                    self._warned_invalid_sym.add(symbol)
                    self.engine._emit("log", {
                        "level": "warn",
                        "msg": f"[{symbol}] ⚠️ Symbol not supported on current exchange environment. Skipping."
                    })
                return
            if any(x in err_msg.lower() for x in ["418", "429", "-1003", "too many requests", "banned"]):
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"[{symbol}] ⚠️ Exchange rate limit hit. Pausing requests for 60s..."
                })
                for _ in range(60):
                    if self.stop_event.is_set() or not self.engine.is_running:
                        break
                    time.sleep(1)
                return
            if self.candles_processed % 12 == 0:
                self.engine._emit("log", {
                    "level": "error",
                    "msg": f"[{symbol}] Klines fetch fail: {err_msg[:100]}"
                })
            if self._last_df is not None:
                df = self._last_df
            else:
                return

        self.candles_processed += 1
        self.last_check = datetime.now(timezone.utc).isoformat()

        # 2. Compute indicators & mark price
        indicators = self.strategy.latest_indicators(df)
        try:
            mark_price = self.engine.trader.get_mark_price(symbol)
            if mark_price is None or mark_price <= 0:
                mark_price = float(df.iloc[-1]["close"]) if df is not None and len(df) else 0.0
            self._last_mark_price = mark_price
        except Exception as e:
            logger.warning(f"[{symbol}] mark_price fetch failed: {e}, using close price")
            mark_price = self._last_mark_price or (float(df.iloc[-1]["close"]) if df is not None and len(df) else 0.0)

        # 3. Emit indicators & chart data for active symbol
        is_active = (self.engine.active_symbol == symbol or self.engine.active_symbol is None)
        if is_active:
            self.engine._emit("indicators", {
                "symbol": symbol,
                **indicators,
                "mark_price": mark_price,
            })
            candles = self._candles_to_list(df)
            emas = self._emas_to_list(df)
            if candles:
                self.engine._emit("chart_data", {
                    "symbol": symbol,
                    "candles": candles,
                    "emas": emas,
                })

        # 4. Query exchange position
        try:
            pos = self.engine.trader.get_position(symbol)
        except Exception as e:
            logger.warning(f"[{symbol}] get_position failed: {e}")

            class DefaultPos:
                side = "NONE"
                size = 0.0
                entry_price = 0.0
                mark_price = mark_price
                unrealized_pnl = 0.0
                leverage = 1

            pos = DefaultPos()

        actual_side = pos.side if (pos.side in ("LONG", "SHORT") and abs(pos.size) > 0) else "NONE"
        effective_lev = (
            int(pos.leverage)
            if (actual_side != "NONE" and pos.leverage and int(pos.leverage) > 1)
            else self._get_effective_leverage(symbol)
        )

        # 5. Pure EMA analysis
        result = self.strategy.analyze(df)
        if result is None:
            self.engine._emit("position", {
                "symbol": symbol,
                "side": actual_side,
                "size": pos.size,
                "entry_price": pos.entry_price,
                "mark_price": pos.mark_price if pos.mark_price > 0 else mark_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "leverage": effective_lev,
            })
            return

        signal = result.signal
        e8, e13, e21, e55 = result.ema_8, result.ema_13, result.ema_21, result.ema_55
        self.last_signal = signal

        self.engine._emit("signal", {
            "symbol": symbol,
            "signal": signal.value,
            "reason": result.reason,
            "emas": {"ema_8": e8, "ema_13": e13, "ema_21": e21, "ema_55": e55},
        })

        # 6. Sync external opens/closes cleanly (no SL/TP, no cooldown)
        is_settling = (
            (time.time() - getattr(self, "_last_close_timestamp", 0.0) < 12.0)
            or (time.time() - getattr(self, "_last_open_timestamp", 0.0) < 15.0)
        )
        if not is_settling and actual_side != self.expected_pos_side:
            if self.expected_pos_side is not None and actual_side == "NONE":
                mp = mark_price if mark_price > 0 else float(self.entry_price or 0.0)
                open_trade = None
                for t in self.engine.history.trades:
                    if t.get("symbol") == symbol.upper() and t.get("status") == "OPEN":
                        open_trade = t
                        break
                trade_lev = effective_lev
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
                    calc_pnl = (mp - t_entry) * trade_qty if t_side == "LONG" else (t_entry - mp) * trade_qty
                    calc_roe = (calc_pnl / t_margin * 100.0) if t_margin > 0 else 0.0
                    calc_fees = (t_entry + mp) * trade_qty * 0.0006

                ext_reason = "👤 Manual / External Close (Exchange Exit)"
                if self.engine.history.has_open_trade(symbol):
                    try:
                        self.engine.history.record_close(
                            symbol=symbol,
                            exit_price=mp,
                            reason=ext_reason,
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
                    "msg": f"[{symbol}] ⚠️ External position close detected ({ext_reason})."
                })
                self.expected_pos_side = None
                self.position_side = None
                self.entry_price = None
            elif actual_side != "NONE" and self.expected_pos_side != actual_side:
                self.expected_pos_side = actual_side
                self.position_side = actual_side
                self.entry_price = pos.entry_price or mark_price
                if not self.engine.history.has_open_trade(symbol):
                    try:
                        self.engine.history.record_open(
                            symbol=symbol,
                            side=actual_side,
                            entry_price=self.entry_price,
                            qty=abs(pos.size),
                            leverage=effective_lev,
                            initial_sl=None,
                            initial_tp=None,
                        )
                        self.engine._emit("trades_updated", {
                            "trades": self.engine.history.get_trades(limit=50),
                            "stats": self.engine.history.get_stats(),
                        })
                    except Exception as he:
                        logger.error("Failed to register existing position in history: %s", he)

        # If an order was just submitted and exchange position hasn't propagated yet, wait briefly
        if is_settling and self.expected_pos_side is not None and actual_side == "NONE":
            return

        # Keep local side synced with active exchange position
        if actual_side != "NONE":
            self.position_side = actual_side
            self.expected_pos_side = actual_side
            if pos.entry_price and pos.entry_price > 0:
                self.entry_price = pos.entry_price

        self.engine._emit("position", {
            "symbol": symbol,
            "side": actual_side,
            "size": pos.size,
            "entry_price": pos.entry_price,
            "mark_price": pos.mark_price if pos.mark_price > 0 else mark_price,
            "unrealized_pnl": pos.unrealized_pnl,
            "leverage": effective_lev,
        })

        mode = cfg.get("mode", "both")
        just_reversed = False

        # ===================================================================
        # 7. PURE EMA55 REVERSAL CHECK (ONLY EXIT MECHANISM — NO SL/TP/TRAIL)
        # ===================================================================
        if actual_side != "NONE":
            should_reverse = (
                (actual_side == "LONG" and signal == Signal.SELL)
                or (actual_side == "SHORT" and signal == Signal.BUY)
            )
            if not should_reverse:
                # Hold position until EMA55 reverses to the opposite side
                if self.candles_processed % 10 == 0:
                    entry_val = self.entry_price or pos.entry_price or 0.0
                    cur_px = pos.mark_price if pos.mark_price > 0 else mark_price
                    self.engine._emit("log", {
                        "level": "info",
                        "msg": (f"[{symbol}] 📊 Holding {actual_side} | Entry={entry_val:.4f} | "
                                f"Mark={cur_px:.4f} | Signal={signal.value} (Pure EMA55 Reversal Active)")
                    })
                return

            # Opposite EMA55 signal! Close current position and immediately reverse.
            cur_px = pos.mark_price if pos.mark_price > 0 else mark_price
            entry = self.entry_price or pos.entry_price or cur_px
            if actual_side == "LONG":
                pnl_pct = (cur_px - entry) / entry * 100.0 if entry > 0 else 0.0
                next_side_label = "SHORT"
                reason = f"⚡ EMA55-REVERSAL (LONG→SHORT | EMA55 TOP, PnL={pnl_pct:+.2f}%)"
            else:
                pnl_pct = (entry - cur_px) / entry * 100.0 if entry > 0 else 0.0
                next_side_label = "LONG"
                reason = f"⚡ EMA55-REVERSAL (SHORT→LONG | EMA55 BOTTOM, PnL={pnl_pct:+.2f}%)"

            self.engine._emit("log", {
                "level": "warn",
                "msg": f"[{symbol}] 🔄 {reason} -> closing {actual_side} @ {cur_px:.4f} & flipping {next_side_label}"
            })

            close = self.engine.trader.close_position(symbol)
            if not close.get("success"):
                try:
                    latest_p = self.engine.trader.get_position(symbol)
                    if latest_p.side == "NONE" or abs(latest_p.size) <= 0:
                        close = {"success": True, "message": "Position verified closed on exchange"}
                except Exception:
                    pass
            self._log_order(close, f"[{symbol}] CLOSE {actual_side} (EMA55 REVERSAL)")

            if not close.get("success"):
                return  # Will retry on next tick

            self._last_close_timestamp = time.time()
            self.trades_today += 1

            try:
                trade_qty = abs(pos.size) if pos.size else 0.0
                trade_margin = (entry * trade_qty) / effective_lev if (effective_lev > 0 and entry > 0 and trade_qty > 0) else 0.0
                calc_pnl = (cur_px - entry) * trade_qty if actual_side == "LONG" else (entry - cur_px) * trade_qty
                calc_roe = (calc_pnl / trade_margin * 100.0) if trade_margin > 0 else 0.0
                calc_fees = (entry + cur_px) * trade_qty * 0.0006
                self.engine.history.record_close(
                    symbol=symbol,
                    exit_price=cur_px,
                    reason=reason,
                    pnl=calc_pnl,
                    roe_pct=calc_roe,
                    fee_est=calc_fees,
                    leverage=effective_lev,
                    qty=trade_qty,
                )
                self.engine._emit("trades_updated", {
                    "trades": self.engine.history.get_trades(limit=50),
                    "stats": self.engine.history.get_stats(),
                })
            except Exception as he:
                logger.error("Failed to record reversal close in history: %s", he)

            try:
                self.engine.notifier.notify_tp(
                    symbol, actual_side, entry, cur_px, pnl_pct,
                    {"ema_8": e8, "ema_13": e13, "ema_21": e21, "ema_55": e55},
                    tp_type="ema_reversal",
                )
            except Exception as ne:
                logger.error("Reversal notification failed: %s", ne)

            # Clear closed position state
            self.expected_pos_side = None
            self.position_side = None
            self.entry_price = None
            actual_side = "NONE"
            just_reversed = True
            # Brief exchange settle pause before opening opposite side
            time.sleep(0.25)

        # ===================================================================
        # 8. PURE EMA ENTRY (IMMEDIATE — ZERO SPREAD, ZERO WAITING, ZERO SL/TP)
        # ===================================================================
        if signal == Signal.HOLD:
            return
        if signal == Signal.BUY and mode not in ("long", "both"):
            return
        if signal == Signal.SELL and mode not in ("short", "both"):
            return

        with self.engine._trade_entry_lock:
            can_open, lock_reason = self.engine.can_open_new_trade(symbol, is_reversal=just_reversed)
            if not can_open:
                return
            self.engine.register_entry_intent(symbol, signal.value)

        # Confirm leverage BEFORE sizing
        cfg_lev = max(1, int(cfg.get("leverage", 20) or 20))
        eff_lev = cfg_lev
        try:
            cached_sym_lev = getattr(self.engine.trader, "_symbol_leverage", {}).get(symbol)
            if cached_sym_lev and int(cached_sym_lev) == cfg_lev:
                eff_lev = int(cached_sym_lev)
            elif hasattr(self.engine.trader, "set_leverage"):
                lev_res = self.engine.trader.set_leverage(symbol, cfg_lev)
                if isinstance(lev_res, dict) and lev_res.get("leverage"):
                    eff_lev = max(1, int(lev_res["leverage"]))
        except Exception:
            eff_lev = cfg_lev

        # Compute trade size from wallet / investment amount & leverage
        self._last_size_reason = None
        trade_size = self._compute_trade_size(mark_price, eff_lev)
        if trade_size <= 0:
            self.engine.release_entry_intent(symbol)
            if self.candles_processed % 12 == 0:
                reason_msg = getattr(self, "_last_size_reason", None) or (
                    f"[{symbol}] Order size below exchange minimum at {eff_lev}x leverage."
                )
                self.engine._emit("log", {"level": "warn", "msg": reason_msg})
            return

        try:
            filters = self.engine.trader.get_symbol_filters(symbol)
            min_qty = filters.get("min_qty", 0.001)
            max_qty = filters.get("max_qty", 1e9)
            step = filters.get("step_size") or filters.get("qty_step") or 0.001
            if max_qty > 0 and trade_size > max_qty:
                trade_size = self.engine.trader._round_to_step(max_qty, step)
            if trade_size < min_qty:
                self.engine.release_entry_intent(symbol)
                if self.candles_processed % 12 == 0:
                    self.engine._emit("log", {
                        "level": "warn",
                        "msg": (f"[{symbol}] Quantity {trade_size} below min_qty {min_qty} "
                                f"(~${min_qty * mark_price:.2f} min order). Increase amount/leverage.")
                    })
                return
        except Exception:
            pass

        order_type_cfg = cfg.get("order_type", "market").lower()
        target_side = "LONG" if signal == Signal.BUY else "SHORT"
        icon = "🟢" if target_side == "LONG" else "🔴"
        self.engine._emit("log", {
            "level": "info",
            "msg": (f"[{symbol}] {icon} EMA {signal.value} -> opening {target_side} "
                    f"({order_type_cfg.upper()}) qty={trade_size:.6f} @ ~{mark_price:.4f} | "
                    f"EMA8={e8:.4f} EMA13={e13:.4f} EMA21={e21:.4f} EMA55={e55:.4f} | "
                    f"Lev={eff_lev}x | Pure EMA Reversal (No SL/TP)")
        })

        open_fn = self.engine.trader.open_long if target_side == "LONG" else self.engine.trader.open_short
        try:
            order = open_fn(symbol, trade_size, order_type=order_type_cfg, price=mark_price)
        except TypeError:
            order = open_fn(symbol, trade_size)

        actual_qty = order.get("quantity", trade_size)
        self._log_order(order, f"[{symbol}] OPEN {target_side} ({order_type_cfg.upper()}) qty={actual_qty:.6f}")
        self.engine.release_entry_intent(symbol)

        if order.get("success"):
            self._last_open_timestamp = time.time()
            self.expected_pos_side = target_side
            self.position_side = target_side
            self.last_trade_side = target_side
            actual_entry = self._get_actual_entry_price(symbol, mark_price)
            self.entry_price = actual_entry

            try:
                self.engine.history.record_open(
                    symbol=symbol,
                    side=target_side,
                    entry_price=actual_entry,
                    qty=actual_qty,
                    leverage=eff_lev,
                    initial_sl=None,
                    initial_tp=None,
                    order_type=order_type_cfg,
                )
                self.engine._emit("trades_updated", {
                    "trades": self.engine.history.get_trades(limit=50),
                    "stats": self.engine.history.get_stats(),
                })
            except Exception as he:
                logger.error("Failed to record trade open in history: %s", he)

            self.engine._emit("position", {
                "symbol": symbol,
                "side": target_side,
                "size": actual_qty if target_side == "LONG" else -actual_qty,
                "entry_price": actual_entry,
                "mark_price": mark_price,
                "unrealized_pnl": 0.0,
                "leverage": eff_lev,
            })

            try:
                self.engine.notifier.notify_trade_open(
                    symbol, target_side, actual_qty, actual_entry,
                    {"ema_8": e8, "ema_13": e13, "ema_21": e21, "ema_55": e55},
                )
            except Exception as e:
                logger.error("Trade open notification failed: %s", e)

    def _get_actual_entry_price(self, symbol: str, fallback: float) -> float:
        """Get actual entry price from exchange position after order fill."""
        try:
            pos = self.engine.trader.get_position(symbol)
            if pos.entry_price > 0:
                return pos.entry_price
        except Exception as e:
            logger.warning(f"[{symbol}] Could not fetch actual entry price: {e}")
        return fallback

    def _compute_trade_size(self, price: float, leverage: int) -> float:
        """
        Compute base-asset quantity based on amount_mode and leverage:
        - 'fixed'  : use cfg['amount'] as USDT margin, scaled by leverage for notional
        - 'percent': use (balance * amount_pct / 100) as USDT margin, scaled by leverage
        """
        self._last_size_reason = None
        cfg = self.config
        amount_mode = cfg.get("amount_mode", "fixed")
        lev = max(1, int(leverage or cfg.get("leverage", 20)))

        balance: Optional[float] = None
        if hasattr(self.engine.trader, "get_balance"):
            try:
                bal_val = self.engine.trader.get_balance()
                if bal_val is not None:
                    balance = float(bal_val)
            except Exception:
                balance = None

        if amount_mode == "percent":
            bal = float(balance or 0.0)
            pct = float(cfg.get("amount_pct", 10) or 10)
            margin = bal * pct / 100.0
            notional = margin * lev
            if bal <= 0 or margin <= 0:
                self._last_size_reason = (
                    f"[{self.symbol}] Available USDT balance ${bal:.2f} hai — {pct:g}% trade size $0 ho raha hai "
                    f"(Futures wallet balance / API auth check karein)."
                )
                return 0.0
        else:
            margin = float(cfg.get("amount", 100) or 0.0)
            notional = margin * lev
            if margin <= 0:
                self._last_size_reason = f"[{self.symbol}] Order investment amount must be > $0."
                return 0.0

        # Check exchange leverage bracket limit (prevents Binance -2027)
        max_notional = 0.0
        try:
            if hasattr(self.engine.trader, "get_max_notional"):
                max_notional = float(self.engine.trader.get_max_notional(self.symbol) or 0.0)
        except Exception:
            pass

        if max_notional > 0 and notional > (max_notional * 0.95):
            clamped_notional = max_notional * 0.95
            logger.info("[%s] ⚠️ Trade notional $%.2f exceeds %dx bracket limit ($%.2f) -> clamped to $%.2f",
                        self.symbol, notional, lev, max_notional, clamped_notional)
            notional = clamped_notional

        qty_step = 0.001
        min_qty = 0.001
        max_qty = 1e9
        min_notional = 0.0
        try:
            filters = self.engine.trader.get_symbol_filters(self.symbol)
            qty_step = float(filters.get("step_size") or filters.get("qty_step") or 0.001)
            min_qty = float(filters.get("min_qty", 0.001) or 0.001)
            max_qty = float(filters.get("max_qty", 1e9) or 1e9)
            min_notional = float(filters.get("min_notional", 0.0) or 0.0)
        except Exception:
            pass

        def _ceil_step(val: float, step: float):
            if hasattr(self.engine.trader, "_ceil_to_step"):
                return self.engine.trader._ceil_to_step(val, step)
            if step <= 0:
                return val
            dec = max(0, int(math.ceil(-math.log10(step)))) if step < 1 else 0
            r = math.ceil((val / step) - 1e-12) * step
            return int(round(r)) if (step >= 1 and abs(step - round(step)) < 1e-9) else round(r, dec)

        qty = self.engine.trader.compute_quantity(notional, price, lev, qty_step=qty_step)
        if max_qty > 0 and qty > max_qty:
            qty = self.engine.trader._round_to_step(max_qty, qty_step)

        min_qty_for_notional = _ceil_step((min_notional * 1.02) / price, qty_step) if (min_notional > 0 and price > 0) else 0.0
        eff_min_qty = max(min_qty, min_qty_for_notional)
        if eff_min_qty > 0 and qty_step > 0:
            eff_min_qty = _ceil_step(eff_min_qty, qty_step)

        below_min = (
            qty <= 0
            or (eff_min_qty > 0 and qty < eff_min_qty)
            or (min_notional > 0 and price > 0 and (qty * price) < min_notional)
        )
        if below_min and price > 0 and eff_min_qty > 0:
            req_notional = eff_min_qty * price
            req_margin = req_notional / lev
            raw_min_usd = max(min_notional, min_qty * price)
            bal_ok = (balance is None or balance <= 0 or req_margin <= balance * 0.88)
            is_floor_deficit = (raw_min_usd > 0 and notional >= raw_min_usd * 0.80)
            is_small_safe_bump = (req_margin <= max(margin * 1.5, margin + 0.75) and req_notional <= 25.0)
            if (max_qty <= 0 or eff_min_qty <= max_qty) and bal_ok and (is_floor_deficit or is_small_safe_bump):
                qty = eff_min_qty
            else:
                needed_lev = math.ceil(req_notional / margin) if margin > 0 else 0
                ex_name = str(cfg.get("exchange") or "binance").lower()
                ex_max_lev = 1000 if ex_name == "primexbt" else (500 if ex_name == "weex" else 125)
                alt_coins = "/".join([c for c in ("SOL", "XRP", "DOGE", "ADA", "SUI", "BNB") if not self.symbol.startswith(c)][:5])
                if not bal_ok and balance is not None and balance > 0:
                    hint_lev = f" Leverage {needed_lev}x+ karein ya" if (0 < needed_lev <= ex_max_lev and needed_lev > lev) else ""
                    self._last_size_reason = (
                        f"[{self.symbol}] Free balance ${balance:.2f} kam hai — exchange min ${req_notional:.2f} "
                        f"(qty {eff_min_qty}, ${req_margin:.2f} margin @ {lev}x) ke liye enough margin nahi."
                        f"{hint_lev} {alt_coins} trade karein."
                    )
                else:
                    bal_txt = f" | Bal=${balance:.2f}" if (balance is not None and balance > 0) else ""
                    hint_lev = f"Leverage {needed_lev}x+ karein, " if (0 < needed_lev <= ex_max_lev and needed_lev > lev) else ""
                    self._last_size_reason = (
                        f"[{self.symbol}] Exchange min ${req_notional:.2f} (qty {eff_min_qty}, ${req_margin:.2f} margin @ {lev}x) "
                        f"> aapka order ${margin:.2f} (${notional:.2f} notional{bal_txt}). "
                        f"{hint_lev}Fixed ${max(1, math.ceil(req_margin)):d}+ rakhein, ya {alt_coins} trade karein."
                    )
                return 0.0

        # Final available-balance guard
        if balance is not None and balance > 0 and price > 0 and qty > 0:
            est_margin = (qty * price) / lev
            if est_margin > balance * 0.94:
                safe_qty = self.engine.trader.compute_quantity((balance * 0.90) * lev, price, lev, qty_step=qty_step)
                if safe_qty >= eff_min_qty and (min_notional <= 0 or (safe_qty * price) >= min_notional):
                    qty = safe_qty
                else:
                    req_n = max(min_notional, eff_min_qty * price)
                    self._last_size_reason = (
                        f"[{self.symbol}] Free balance ${balance:.2f} kam hai — min order "
                        f"${req_n:.2f} (${req_n / lev:.2f} margin @ {lev}x) ke liye enough margin nahi."
                    )
                    return 0.0

        return qty

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
        enriched = self.strategy.indicators.compute(df)
        tail = enriched.tail(n)
        out = {}
        for col, key in [("ema_8", "ema8"), ("ema_13", "ema13"),
                         ("ema_21", "ema21"), ("ema_55", "ema55")]:
            out[key] = [
                {"time": int(ts.timestamp()), "value": float(v)}
                for ts, v in zip(tail.index, tail[col])
                if not (v != v)
            ]
        return out

    @staticmethod
    def _clean_err_msg(err):
        if not err:
            return "Unknown error"
        err_str = str(err)
        m = re.search(r"(-?\d+),\s*['\"]([^'\"]+)['\"]", err_str)
        if m:
            return f"Binance {m.group(1)}: {m.group(2)}"
        if "CloudFront" in err_str or "x-mbx-" in err_str or "{'Content-Type'" in err_str:
            err_str = err_str.split("{'Content-Type'")[0].strip().rstrip(",").strip("()")
        return err_str[:120]

    def _log_order(self, result, label):
        if result.get("success"):
            order = result.get("order", {})
            oid = order.get("orderId", "?") if isinstance(order, dict) else "?"
            self.engine._emit("log", {
                "level": "success",
                "msg": f"{label} OK | orderId={oid}"
            })
        else:
            clean_err = self._clean_err_msg(result.get("error"))
            self.engine._emit("log", {
                "level": "error",
                "msg": f"{label} FAILED | {clean_err}"
            })


class MonitorThread(threading.Thread):
    """Always-on background thread that streams live balance, chart, indicators, and positions."""

    def __init__(self, engine, config: dict):
        super().__init__(daemon=True, name="monitor")
        self.engine = engine
        self.config = config
        self.stop_event = threading.Event()
        self._last_chart_emit = 0

    def run(self):
        exchange = (self.config.get("exchange") or "binance").upper()
        env_label = "DEMO" if exchange in ("WEEX", "PRIMEXBT") and self.config.get("testnet") else \
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
            for _ in range(10):
                if self.stop_event.is_set():
                    break
                time.sleep(1)

        self.engine._emit("log", {
            "level": "info",
            "msg": "🔌 MONITOR disconnected"
        })

    def _tick(self, first_run=False):
        cfg = self.config
        symbol = self.engine.active_symbol or cfg.get("symbol", "BTCUSDT")
        timeframe = cfg.get("timeframe", "15m")

        if self.engine.monitor_trader is None:
            return

        # 1. Fetch balance
        try:
            balance = self.engine.monitor_trader.get_balance()
            ex_name = (cfg.get("exchange") or "binance").lower()
            if ex_name == "primexbt":
                is_demo = bool(cfg.get("testnet", True))
            else:
                is_demo = bool(cfg.get("testnet", True))
            self.engine.set_connection_state("balance_access", "ok")
            self.engine._emit("balance", {
                "balance": float(balance),
                "exchange": cfg.get("exchange", "binance"),
                "testnet": cfg.get("testnet", True),
                "demo": is_demo,
            })
        except Exception as e:
            self.engine.set_connection_state("balance_access", "failed")
            if first_run:
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"⚠️ Balance fetch failed: {str(e)[:100]}"
                })

        # 2. Fetch klines + indicators + mark price
        try:
            df = self.engine.monitor_trader.get_klines(symbol, interval=timeframe, limit=200)
            self.engine.set_connection_state("market_data", "ok")
        except Exception as e:
            self.engine.set_connection_state("market_data", "failed")
            if first_run:
                self.engine._emit("log", {
                    "level": "warn",
                    "msg": f"⚠️ Chart fetch failed for {symbol}: {str(e)[:100]}"
                })
            return

        if df is None or len(df) == 0:
            return

        try:
            mark_price = self.engine.monitor_trader.get_mark_price(symbol)
            if mark_price is None or mark_price <= 0:
                mark_price = float(df.iloc[-1]["close"])
        except Exception:
            mark_price = float(df.iloc[-1]["close"])

        try:
            indicators = self.engine.strategy.latest_indicators(df)
        except Exception:
            indicators = {"ema_8": 0, "ema_13": 0, "ema_21": 0, "ema_55": 0}

        self.engine._emit("indicators", {
            "symbol": symbol,
            **indicators,
            "mark_price": mark_price,
        })

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

        # 3. Position snapshot (pure position info — no SL/TP)
        try:
            pos = self.engine.monitor_trader.get_position(symbol)
            worker = self.engine.workers.get(symbol)
            effective_lev = pos.leverage if (pos.leverage and int(pos.leverage) > 1) else (
                getattr(worker, "_get_effective_leverage", lambda s: int(self.engine.config.get("leverage", 20)))(symbol)
            )
            self.engine._emit("position", {
                "symbol": symbol,
                "side": pos.side,
                "size": pos.size,
                "entry_price": pos.entry_price,
                "mark_price": pos.mark_price if pos.mark_price > 0 else mark_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "leverage": effective_lev,
            })
        except Exception:
            pass

    def _candles_to_list(self, df, n=200):
        if df is None or len(df) == 0:
            return []
        tail = df.tail(n)
        return [
            {
                "time": int(ts.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
            for ts, row in tail.iterrows()
        ]

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
                if not (v != v)
            ]
        return out


class BotEngine:
    """Background trading engine supporting multi-symbol pure EMA + reversal trading."""

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
        self._entry_intents: dict[str, dict] = {}
        self.is_running = False
        self.active_symbol = None
        self.monitor_thread: Optional[MonitorThread] = None
        self.monitor_trader = None
        self.connection: dict = {
            "market_data": "unknown",
            "api_auth": "unknown",
            "balance_access": "unknown",
            "trading_permission": "unknown",
            "env": "UNKNOWN",
            "auth_check": None,
            "checked_at": None,
        }
        self.auth_check: Optional[dict] = None

    def set_connection_state(self, key: str, value: str):
        if key in ("market_data", "api_auth", "balance_access", "trading_permission"):
            self.connection[key] = value
            self.connection["checked_at"] = datetime.now(timezone.utc).isoformat()
            self._emit("connection", dict(self.connection))

    def validate_credentials(self, trader=None) -> dict:
        t = trader or self.trader or self.monitor_trader
        if t is None:
            return {"ok": False, "message": "No trader instance - cannot validate credentials"}
        if not hasattr(t, "validate_credentials"):
            return {"ok": False, "message": "Adapter does not implement validate_credentials"}
        self.set_connection_state("api_auth", "checking")
        try:
            res = t.validate_credentials()
        except Exception as e:
            res = {"ok": False, "message": f"validate_credentials crashed: {e}"}
        self.auth_check = res
        self.connection["auth_check"] = res
        self.connection["env"] = getattr(t, "env_label", lambda: "UNKNOWN")()
        self.connection["checked_at"] = datetime.now(timezone.utc).isoformat()
        self.set_connection_state("api_auth", "ok" if res.get("ok") else "failed")
        if res.get("ok"):
            if res.get("balance") is not None:
                self.set_connection_state("balance_access", "ok")
            ct = res.get("can_trade")
            if ct is True:
                self.set_connection_state("trading_permission", "ok")
            elif ct is False:
                self.set_connection_state("trading_permission", "failed")
        else:
            self.set_connection_state("balance_access", "unknown")
            self.set_connection_state("trading_permission", "unknown")
        return res

    def get_active_positions(self) -> list[str]:
        active = []
        for sym, worker in self.workers.items():
            is_active = (
                getattr(worker, "position_side", None) in ("LONG", "SHORT")
                or getattr(worker, "expected_pos_side", None) in ("LONG", "SHORT")
                or (getattr(worker, "entry_price", None) is not None and getattr(worker, "entry_price", 0) > 0)
            )
            if is_active:
                active.append(sym)
        return list(dict.fromkeys(active))

    def has_any_active_position(self) -> tuple[bool, Optional[str]]:
        active = self.get_active_positions()
        return (len(active) > 0, active[0] if active else None)

    def register_entry_intent(self, symbol: str, side: str):
        self._entry_intents[str(symbol).upper()] = {"side": side, "ts": time.time()}

    def release_entry_intent(self, symbol: str):
        self._entry_intents.pop(str(symbol).upper(), None)

    def can_open_new_trade(self, symbol: str, is_reversal: bool = False) -> tuple[bool, str]:
        """Check concurrent slot limit (1, 2, or 3 coins). No cooldown, no waiting."""
        active_symbols = self.get_active_positions()
        if not is_reversal and symbol in active_symbols:
            return False, f"[{symbol}] already has an active position"

        now = time.time()
        try:
            max_trades = int(self.config.get("max_concurrent_trades", 3))
        except (ValueError, TypeError):
            max_trades = 3
        max_trades = max(1, min(3, max_trades))

        intent_syms = {
            s for s, v in self._entry_intents.items()
            if now - float(v.get("ts", 0.0)) < 60.0 and s not in active_symbols
        }
        effective_active = [s for s in active_symbols if s != symbol] if is_reversal else active_symbols
        if len(effective_active) + len(intent_syms) >= max_trades:
            return False, (f"limit of {max_trades} simultaneous coin trades reached "
                           f"({', '.join(sorted(set(effective_active) | intent_syms))})")
        return True, ""

    # ---------- Monitor Lifecycle ----------

    def start_monitor(self, config: dict) -> dict:
        self.stop_monitor()
        api_key = config.get("api_key", "").strip()
        api_secret = config.get("api_secret", "").strip()
        if not api_key or not api_secret:
            return {"success": False, "error": "API keys not set — monitor not started"}
        if config.get("exchange") == "weex" and not config.get("api_passphrase", "").strip():
            return {"success": False, "error": "WEEX Passphrase not set — monitor not started"}
        try:
            self.monitor_trader = get_trader(config)
        except Exception as e:
            logger.error(f"Monitor trader creation failed: {e}")
            self.monitor_trader = None
            return {"success": False, "error": f"Exchange connection failed: {e}"}

        self.monitor_thread = MonitorThread(self, config)
        self.monitor_thread.start()
        return {"success": True, "message": "Monitor started"}

    def stop_monitor(self):
        if self.monitor_thread is not None:
            self.monitor_thread.stop_event.set()
            try:
                self.monitor_thread.join(timeout=8)
            except Exception:
                pass
            self.monitor_thread = None
        self.monitor_trader = None

    def apply_leverage(self, leverage: int, symbol: Optional[str] = None) -> dict:
        """Apply leverage to symbol(s) on exchange (Binance / WEEX / PrimeXBT)."""
        symbols = [symbol.strip().upper()] if symbol else self._symbols_list()
        if not symbols:
            symbols = [str(self.config.get("symbol", "BTCUSDT")).strip().upper()]

        self.config["leverage"] = leverage
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
                            "msg": f"[{sym}] ⚠️ Exchange max leverage {actual}x applied (requested {leverage}x)."
                        })
                    elif r.get("success"):
                        _note = r.get("note")
                        self._emit("log", {
                            "level": "success",
                            "msg": (f"[{sym}] ⚡ Leverage set to {actual}x on {self.config.get('exchange', 'binance').upper()}"
                                    + (f" ({_note})" if _note else ""))
                        })
                    else:
                        _err = str(r.get("error", "unknown"))
                        if "-2014" in _err or "API-key format invalid" in _err:
                            _msg = ("API-key FORMAT invalid (-2014): API Key aur SECRET alag-alag fields mein saaf paste karo.")
                        elif "-2015" in _err or "Invalid API-key" in _err:
                            _msg = ("API Key REJECTED (-2015): Testnet vs Mainnet keys aur Futures permission check karo.")
                        else:
                            _msg = _err[:200]
                        self._emit("log", {"level": "warn", "msg": f"[{sym}] ⚠️ Leverage notice: {_msg}"})
                except Exception as e:
                    logger.error("Failed to set leverage for %s: %s", sym, e)
                    results[sym] = {"success": False, "error": str(e)}

        cur_sym = self.active_symbol or (symbols[0] if symbols else "BTCUSDT")
        try:
            if active_trader:
                pos = active_trader.get_position(cur_sym)
                self._emit("position", {
                    "symbol": cur_sym,
                    "side": pos.side,
                    "size": pos.size,
                    "entry_price": pos.entry_price,
                    "mark_price": pos.mark_price,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "leverage": pos.leverage,
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
            "results": results,
        }

    def start(self, config: dict):
        """Start the pure EMA + Reversal bot across all configured coins."""
        if self.is_running:
            alive_workers = [w for w in self.workers.values() if w.is_alive()]
            if not alive_workers:
                logger.warning("Zombie state detected: auto-resetting.")
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
        self.stop_monitor()
        try:
            self.trader = get_trader(config)
        except Exception as e:
            logger.error("Failed to connect to exchange: %s", e)
            self.set_connection_state("api_auth", "failed")
            return {"success": False, "error": f"Exchange connection failed: {e}"}

        # Protect real funds: live execution requires explicit confirmation checkbox
        if not bool(config.get("testnet", True)) and not bool(config.get("live_confirmed")):
            self.set_connection_state("api_auth", "unknown")
            self._emit("log", {
                "level": "error",
                "msg": ("⛔ LIVE TRADING LOCKED: Env=MAINNET hai lekin live confirmation box "
                        "tick nahi hai. Settings mein 'I understand this will trade REAL funds' tick karke save karo.")
            })
            return {
                "success": False,
                "auth_blocked": True,
                "error": "Live trading is locked (live_confirmed not set). Confirm LIVE in settings first.",
            }

        # Pre-flight auth check (read-only)
        auth = self.validate_credentials(self.trader)
        if not auth.get("ok"):
            self._emit("log", {
                "level": "error",
                "msg": f"⛔ START BLOCKED - {auth.get('message', 'authentication failed')}"
            })
            return {
                "success": False,
                "auth_blocked": True,
                "error_code": auth.get("error_code"),
                "error": auth.get("message", "Authentication failed"),
                "auth_check": auth,
            }
        self._emit("log", {
            "level": "success",
            "msg": f"✅ Pre-flight auth OK - {auth.get('message', '')}"
        })
        if auth.get("can_trade") is False:
            self._emit("log", {
                "level": "error",
                "msg": "⛔ START BLOCKED - account canTrade=False: exchange par Futures trading permission OFF hai."
            })
            return {
                "success": False,
                "auth_blocked": True,
                "error": "Account cannot trade (canTrade=False). Enable Futures permission for this API key.",
                "auth_check": auth,
            }

        if (config.get("exchange") or "").lower() == "primexbt":
            if not getattr(self.trader, "has_valid_auth", False):
                self._emit("log", {
                    "level": "warn",
                    "msg": "⚠️ PrimeXBT: Secret Key NOT loaded — orders will not execute on live account."
                })
            else:
                env_lbl = "DEMO" if config.get("testnet", True) else "LIVE"
                bal = None
                if hasattr(self.trader, "get_balance_or_none"):
                    try:
                        bal = self.trader.get_balance_or_none()
                    except Exception:
                        bal = None
                bal_txt = f" | Balance ${bal:,.2f}" if bal is not None else ""
                self._emit("log", {
                    "level": "success",
                    "msg": f"✅ PrimeXBT ({env_lbl}) connected{bal_txt}"
                })

        symbols = self._symbols_list()
        lev = config.get("leverage", 20)
        if not symbols:
            return {"success": False, "error": "No symbols added. Please add coins."}

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
                        try:
                            pos = self.trader.get_position(sym)
                            self._emit("position", {
                                "symbol": sym,
                                "side": pos.side,
                                "size": pos.size,
                                "entry_price": pos.entry_price,
                                "mark_price": pos.mark_price,
                                "unrealized_pnl": pos.unrealized_pnl,
                                "leverage": pos.leverage,
                            })
                        except Exception:
                            pass
                    else:
                        err = str(r.get("error", ""))
                        is_binance = self.config.get("exchange", "binance").lower() == "binance"
                        if is_binance and ("-2014" in err or "API-key format invalid" in err):
                            self._emit("log", {"level": "error", "msg": f"[{sym}] ❌ API KEY FORMAT INVALID (-2014)."})
                            self.is_running = False
                            for w in self.workers.values():
                                w.stop_event.set()
                            return
                        elif is_binance and ("-2015" in err or "Invalid API-key" in err or "401" in err):
                            self._emit("log", {"level": "error", "msg": f"[{sym}] ❌ API AUTH FAILED (-2015)."})
                            self.is_running = False
                            for w in self.workers.values():
                                w.stop_event.set()
                            return
                        elif "-1121" in err or "Invalid symbol" in err:
                            logger.info(f"[{sym}] Leverage setup skipped: symbol not supported.")
                        else:
                            self._emit("log", {
                                "level": "warn",
                                "msg": f"[{sym}] ⚠️ Leverage notice: {err[:100]}. Continuing."
                            })
            finally:
                leverage_ready.set()

        threading.Thread(target=_set_leverage_bg, daemon=True).start()

        self.is_running = True
        if symbols:
            self.active_symbol = symbols[0]

        with self.lock:
            self.workers.clear()
            for i, sym in enumerate(symbols):
                w = SymbolWorker(self, sym, config, leverage_ready=leverage_ready)
                self.workers[sym] = w
                stagger_delay = min(i * 0.5, 10)
                if stagger_delay > 0:
                    threading.Timer(stagger_delay, w.start).start()
                else:
                    w.start()

        self._emit("status", {"running": True, "message": "Bot started"})
        exchange = (config.get("exchange") or "binance").upper()
        env_label = "DEMO" if exchange in ("WEEX", "PRIMEXBT") and config.get("testnet") else \
                    ("TESTNET" if config.get("testnet") else "MAINNET")
        self._emit("log", {
            "level": "info",
            "msg": (f"Bot STARTED | Exchange={exchange} | Symbols={','.join(symbols)} | "
                    f"TF={config['timeframe']} | Lev={config['leverage']}x | "
                    f"Mode={config.get('mode', 'both')} | Amount={self._amount_desc()} | "
                    f"Strategy=Pure EMA 8/13/21/55 + Reversal (No SL/TP) | Env={env_label}")
        })
        try:
            self.notifier.notify_bot_start(config)
        except Exception as e:
            logger.error("Bot start notification failed: %s", e)
        return {"success": True, "message": "Bot started"}

    def sync_config(self, new_config: dict):
        """Dynamically update running workers when user saves settings."""
        self.config = new_config
        self.notifier.update_config(new_config)
        if not self.is_running:
            return

        new_symbols = set(self._symbols_list())
        with self.lock:
            current_symbols = set(self.workers.keys())
            for sym in (current_symbols - new_symbols):
                w = self.workers.pop(sym, None)
                if w:
                    w.stop_event.set()
                    self._emit("log", {"level": "info", "msg": f"[{sym}] ⏹️ Removed from watchlist. Worker stopped."})

            for sym in (new_symbols - current_symbols):
                w = SymbolWorker(self, sym, new_config)
                self.workers[sym] = w
                w.start()
                self._emit("log", {"level": "info", "msg": f"[{sym}] ▶️ Added to watchlist. Worker started."})

            for sym in (current_symbols & new_symbols):
                w = self.workers.get(sym)
                if w:
                    w.update_config(new_config)

            self._emit("log", {
                "level": "success",
                "msg": f"⚙️ Settings live-updated: TF={new_config.get('timeframe')} | Lev={new_config.get('leverage')}x | Pure EMA + Reversal"
            })

        if new_symbols and self.active_symbol not in new_symbols:
            self.set_active_symbol(list(new_symbols)[0])

    def stop(self):
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
        try:
            self.notifier.notify_bot_stop()
        except Exception as e:
            logger.error("Bot stop notification failed: %s", e)
        return {"success": True, "message": "Bot stopped"}

    def force_stop(self):
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
            "msg": "⚠️ FORCE STOP done. Trading state reset."
        })
        return {"success": True, "message": "Force stop done - trading state reset"}

    def set_active_symbol(self, symbol: str):
        self.active_symbol = symbol
        logger.info(f"Active symbol set to: {symbol}")
        if self.is_running and symbol in self.workers:
            try:
                worker = self.workers[symbol]
                if hasattr(worker, "_last_df") and worker._last_df is not None:
                    df = worker._last_df
                    candles = worker._candles_to_list(df)
                    emas = worker._emas_to_list(df)
                    indicators = self.strategy.latest_indicators(df)
                    try:
                        mark_price = self.trader.get_mark_price(symbol)
                    except Exception:
                        mark_price = float(df.iloc[-1]["close"]) if df is not None and len(df) else 0.0
                    self._emit("chart_data", {"symbol": symbol, "candles": candles, "emas": emas})
                    self._emit("indicators", {"symbol": symbol, **indicators, "mark_price": mark_price})
            except Exception as e:
                logger.warning(f"Could not send immediate chart data for {symbol}: {e}")
        return {"success": True}

    # ---------- Helpers ----------

    def _clean_sym(self, s: str) -> str:
        sym = str(s or "").strip().upper()
        typo_map = {
            "1000CHEEMUSDT": "1000CHEEMSUSDT",
            "1000RATUSDT": "1000RATSUSDT",
            "1000SATUSDT": "1000SATSUSDT",
            "100000NKUSDT": "1000BONKUSDT",
            "CHEEMUSDT": "1000CHEEMSUSDT",
            "CHEEMSUSDT": "1000CHEEMSUSDT",
            "RATUSDT": "1000RATSUSDT",
            "SATUSDT": "1000SATSUSDT",
            "PEPEUSDT": "1000PEPEUSDT",
            "BONKUSDT": "1000BONKUSDT",
            "FLOKIUSDT": "1000FLOKIUSDT",
            "SHIBUSDT": "1000SHIBUSDT",
            "LUNCUSDT": "1000LUNCUSDT",
            "BABYDOGEUSDT": "1MBABYDOGEUSDT",
            "MOGUSDT": "1000000MOGUSDT",
            "CATUSDT": "1000000CATUSDT",
        }
        return typo_map.get(sym, sym)

    def _symbols_list(self) -> list:
        sl = self.config.get("symbols_list")
        if isinstance(sl, list):
            parts = [self._clean_sym(x) for x in sl if x and str(x).strip()]
            if parts:
                return parts
        elif isinstance(sl, str) and sl.strip():
            parts = [self._clean_sym(x) for x in sl.split(",") if x.strip()]
            if parts:
                return parts
        s = self.config.get("symbol", "BTCUSDT")
        if isinstance(s, list):
            return [self._clean_sym(x) for x in s if x and x.strip()]
        if isinstance(s, str):
            parts = [self._clean_sym(x) for x in s.split(",") if x and x.strip()]
            return parts if parts else ["BTCUSDT"]
        return ["BTCUSDT"]

    def _amount_desc(self) -> str:
        m = self.config.get("amount_mode", "fixed")
        if m == "percent":
            return f"{self.config.get('amount_pct', 10)}% of wallet"
        return f"${self.config.get('amount', 100)}"

    def _emit(self, event: str, data: dict):
        try:
            if event == "log":
                level = (data.get("level") or "info").upper()
                msg = data.get("msg", "")
                if level == "ERROR":
                    logger.error(msg)
                elif level in ("WARN", "WARNING"):
                    logger.warning(msg)
                elif level == "SUCCESS":
                    logger.info(f"[SUCCESS] {msg}")
                else:
                    logger.info(msg)
            if self.socketio:
                self.socketio.emit(event, data, namespace="/")
        except Exception as e:
            logger.error("Socket emit failed: %s", e)

    @staticmethod
    def _poll_seconds(timeframe: str) -> int:
        mapping = {
            "1m": 3, "3m": 3, "5m": 4, "15m": 6,
            "30m": 10, "1h": 15, "2h": 20, "4h": 30,
            "1d": 60, "1w": 120,
        }
        return mapping.get(timeframe, 4)

    def status(self) -> dict:
        symbols = self._symbols_list() if self.is_running else []
        alive_count = sum(1 for w in self.workers.values() if w.is_alive())
        if self.is_running and alive_count == 0 and self.workers:
            self.is_running = False
            self.workers.clear()
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        trades_today_count = 0
        history = getattr(self, "history", None)
        if history is not None:
            try:
                with history.lock:
                    trades_today_count = sum(
                        1 for t in history.trades
                        if t.get("status") == "CLOSED" and str(t.get("closed_at", "")).startswith(today_utc)
                    )
            except Exception:
                trades_today_count = 0
        if trades_today_count == 0 and self.workers:
            trades_today_count = sum(w.trades_today for w in self.workers.values())

        return {
            "running": self.is_running,
            "trades_today": trades_today_count,
            "exchange": self.config.get("exchange", "binance"),
            "symbols": symbols,
            "timeframe": self.config.get("timeframe"),
            "leverage": self.config.get("leverage"),
            "amount_mode": self.config.get("amount_mode", "fixed"),
            "amount": self.config.get("amount"),
            "amount_pct": self.config.get("amount_pct", 10),
            "mode": self.config.get("mode", "both"),
            "testnet": self.config.get("testnet", True),
            "live_confirmed": bool(self.config.get("live_confirmed", False)),
            "connection": dict(self.connection),
            "workers": {
                sym: {
                    "candles_processed": w.candles_processed,
                    "trades_today": w.trades_today,
                    "last_signal": w.last_signal.value,
                    "last_trade_side": getattr(w, "last_trade_side", None),
                    "last_check": w.last_check,
                    "alive": w.is_alive(),
                    "state": getattr(w, "state", "unknown"),
                }
                for sym, w in self.workers.items()
            },
        }

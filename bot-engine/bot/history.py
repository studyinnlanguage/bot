"""
Trade History Manager
Persists and manages all bot-executed trades and manual closures.
Tracks trades from entry to exit (SL, Trailing TP, Manual Bot Close, Manual Exchange Close).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TradeHistoryManager:
    """Thread-safe persistent storage and statistics for bot trade history."""

    def __init__(self, filepath: Optional[Path | str] = None):
        if filepath is None:
            base_dir = Path(__file__).resolve().parent.parent
            data_dir = base_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            self.filepath = data_dir / "trade_history.json"
        else:
            self.filepath = Path(filepath)
            self.filepath.parent.mkdir(parents=True, exist_ok=True)

        self.lock = threading.Lock()
        self.trades: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        with self.lock:
            if self.filepath.exists():
                try:
                    with open(self.filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            self.trades = data
                        elif isinstance(data, dict) and "trades" in data:
                            self.trades = data["trades"]
                        else:
                            self.trades = []

                    # Purge any corrupt phantom trades (side=='POSITION', qty==0, pnl==0)
                    cleaned = []
                    for t in self.trades:
                        is_phantom = (t.get("side") == "POSITION" and
                                      (t.get("qty") == 0 or not t.get("qty")) and
                                      (t.get("pnl") == 0 or not t.get("pnl")))
                        if not is_phantom:
                            cleaned.append(t)
                    if len(cleaned) != len(self.trades):
                        self.trades = cleaned
                        self._save()

                    logger.info("Loaded %d trade history records from %s", len(self.trades), self.filepath)
                except Exception as e:
                    logger.error("Failed to load trade history from %s: %s", self.filepath, e)
                    self.trades = []
            else:
                self.trades = []

    def _save(self):
        try:
            temp_file = self.filepath.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.trades, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.filepath)
        except Exception as e:
            logger.error("Failed to save trade history to %s: %s", self.filepath, e)

    def has_open_trade(self, symbol: str) -> bool:
        """Check if an OPEN trade currently exists for the symbol."""
        with self.lock:
            return any(t.get("symbol") == symbol.upper() and t.get("status") == "OPEN" for t in self.trades)

    def record_open(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        qty: float,
        leverage: int = 50,
        initial_sl: Optional[float] = None,
        initial_tp: Optional[float] = None,
        order_type: str = "maker",
        margin: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Record a newly opened trade."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        now_ts = int(now.timestamp())

        lev_safe = max(int(leverage or 50), 1)
        if margin is None or margin <= 0:
            margin = (entry_price * qty) / lev_safe if entry_price > 0 else 0.0

        trade_id = f"tr_{now_ts}_{symbol}_{side.lower()}"

        # Estimate entry fee (~0.02% maker or ~0.06% taker)
        fee_rate = 0.0002 if order_type.lower() == "maker" else 0.0006
        est_entry_fee = (entry_price * qty) * fee_rate

        trade: Dict[str, Any] = {
            "id": trade_id,
            "symbol": symbol.upper(),
            "side": side.upper(),
            "order_type": order_type.lower(),
            "entry_price": round(float(entry_price), 6),
            "exit_price": None,
            "qty": round(float(qty), 6),
            "leverage": lev_safe,
            "margin": round(float(margin), 4),
            "initial_sl": round(float(initial_sl), 6) if initial_sl else None,
            "initial_tp": round(float(initial_tp), 6) if initial_tp else None,
            "opened_at": now_iso,
            "opened_ts": now_ts,
            "closed_at": None,
            "closed_ts": None,
            "status": "OPEN",
            "close_reason": None,
            "pnl": 0.0,
            "roe_pct": 0.0,
            "fee_est": round(est_entry_fee * 2.0, 4),  # estimated round-trip
            "trailing_stage": 1,
            "highest_roe": 0.0,
        }

        with self.lock:
            # If an existing OPEN trade exists for this symbol, mark it as closed (or replace)
            for existing in self.trades:
                if existing.get("symbol") == symbol.upper() and existing.get("status") == "OPEN":
                    existing["status"] = "CLOSED"
                    existing["closed_at"] = now_iso
                    existing["close_reason"] = "Overwritten by new trade"

            self.trades.insert(0, trade)
            self._save()

        logger.info("[%s] Recorded trade open: %s %s @ %s (lev=%dx)", symbol, side, qty, entry_price, lev_safe)
        return trade

    def update_stage(self, symbol: str, reached_stage: int, reached_roe: float) -> Optional[Dict[str, Any]]:
        """Update trailing stage progress for an active trade."""
        with self.lock:
            for t in self.trades:
                if t.get("symbol") == symbol.upper() and t.get("status") == "OPEN":
                    t["trailing_stage"] = max(t.get("trailing_stage", 1), reached_stage)
                    t["highest_roe"] = max(t.get("highest_roe", 0.0), reached_roe)
                    self._save()
                    return t
        return None

    def record_close(
        self,
        symbol: str,
        exit_price: float,
        reason: str,
        pnl: Optional[float] = None,
        roe_pct: Optional[float] = None,
        fee_est: Optional[float] = None,
        side: Optional[str] = None,
        qty: Optional[float] = None,
        entry_price: Optional[float] = None,
        leverage: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record trade closure (SL, Trailing TP, Manual Bot Close, or Manual Exchange Close)."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        now_ts = int(now.timestamp())

        with self.lock:
            target_trade = None
            for t in self.trades:
                if t.get("symbol") == symbol.upper() and t.get("status") == "OPEN":
                    target_trade = t
                    break

            if target_trade is None:
                # If there is no open trade tracked and this is just a zero PnL sync event, DO NOT record!
                if (pnl is None or pnl == 0.0) and (qty is None or qty == 0.0):
                    logger.debug("[%s] Skipping phantom close event with no open trade and 0 PnL.", symbol)
                    return None

                # Otherwise, if an actual trade was closed that missed record_open, capture it with REAL fields
                actual_side = (side or "LONG").upper()
                actual_lev = max(int(leverage or 50), 1)
                actual_qty = float(qty or 0.0)
                actual_entry = float(entry_price or exit_price)

                calc_pnl = float(pnl or 0.0)
                margin = (actual_entry * actual_qty) / actual_lev if (actual_entry > 0 and actual_qty > 0) else 0.0
                calc_roe = (calc_pnl / margin * 100.0) if (roe_pct is None and margin > 0) else float(roe_pct or 0.0)
                calc_fee = float(fee_est or ((actual_entry + exit_price) * actual_qty * 0.0006))

                trade_id = f"tr_{now_ts}_{symbol}_close"
                target_trade = {
                    "id": trade_id,
                    "symbol": symbol.upper(),
                    "side": actual_side,
                    "order_type": "market",
                    "entry_price": round(actual_entry, 6),
                    "exit_price": round(float(exit_price), 6),
                    "qty": round(actual_qty, 6),
                    "leverage": actual_lev,
                    "margin": round(margin, 4),
                    "initial_sl": None,
                    "initial_tp": None,
                    "opened_at": now_iso,
                    "opened_ts": now_ts,
                    "closed_at": now_iso,
                    "closed_ts": now_ts,
                    "status": "CLOSED",
                    "close_reason": reason,
                    "pnl": round(calc_pnl, 4),
                    "roe_pct": round(calc_roe, 2),
                    "fee_est": round(calc_fee, 4),
                    "trailing_stage": 1,
                    "highest_roe": 0.0,
                }
                self.trades.insert(0, target_trade)
            else:
                entry = float(target_trade.get("entry_price") or exit_price)
                t_qty = float(target_trade.get("qty") or (qty or 0.0))
                t_side = target_trade.get("side", (side or "LONG")).upper()
                t_lev = max(int(target_trade.get("leverage") or (leverage or 50)), 1)
                margin = float(target_trade.get("margin") or 0.0)
                if margin <= 0 and entry > 0 and t_qty > 0:
                    margin = (entry * t_qty) / t_lev

                if pnl is None:
                    if t_side == "LONG":
                        calc_pnl = (exit_price - entry) * t_qty
                    else:
                        calc_pnl = (entry - exit_price) * t_qty
                else:
                    calc_pnl = pnl

                if roe_pct is None:
                    calc_roe = (calc_pnl / margin * 100.0) if margin > 0 else 0.0
                else:
                    calc_roe = roe_pct

                if fee_est is None:
                    calc_fee = (entry + exit_price) * t_qty * 0.0006
                else:
                    calc_fee = fee_est

                target_trade["exit_price"] = round(float(exit_price), 6)
                target_trade["closed_at"] = now_iso
                target_trade["closed_ts"] = now_ts
                target_trade["status"] = "CLOSED"
                target_trade["close_reason"] = reason
                target_trade["pnl"] = round(float(calc_pnl), 4)
                target_trade["roe_pct"] = round(float(calc_roe), 2)
                target_trade["fee_est"] = round(float(calc_fee), 4)
                if t_qty > 0:
                    target_trade["qty"] = round(t_qty, 6)
                target_trade["leverage"] = t_lev

            self._save()

        logger.info(
            "[%s] Recorded trade close: exit=%s, pnl=%s, reason=%s",
            symbol,
            exit_price,
            target_trade.get("pnl"),
            reason,
        )
        return target_trade

    def get_trades(
        self,
        limit: int = 100,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get trades filtered and sorted newest first."""
        with self.lock:
            result = list(self.trades)

        if symbol:
            sym_u = symbol.upper()
            result = [t for t in result if t.get("symbol") == sym_u]

        if status:
            stat_u = status.upper()
            result = [t for t in result if t.get("status") == stat_u]

        return result[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Compute performance statistics across all closed trades."""
        with self.lock:
            closed = [t for t in self.trades if t.get("status") == "CLOSED"]

        total_trades = len(closed)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate_pct": 0.0,
                "total_pnl": 0.0,
                "total_fees": 0.0,
                "net_pnl": 0.0,
                "best_pnl": 0.0,
                "worst_pnl": 0.0,
                "avg_trade_pnl": 0.0,
            }

        wins = sum(1 for t in closed if float(t.get("pnl", 0)) > 0)
        losses = sum(1 for t in closed if float(t.get("pnl", 0)) < 0)
        pnls = [float(t.get("pnl", 0)) for t in closed]
        fees = [float(t.get("fee_est", 0)) for t in closed]

        total_pnl = sum(pnls)
        total_fees = sum(fees)
        net_pnl = total_pnl - total_fees
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0

        return {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "total_fees": round(total_fees, 2),
            "net_pnl": round(net_pnl, 2),
            "best_pnl": round(max(pnls), 2) if pnls else 0.0,
            "worst_pnl": round(min(pnls), 2) if pnls else 0.0,
            "avg_trade_pnl": round(total_pnl / total_trades, 2) if total_trades > 0 else 0.0,
        }

    def clear_history(self) -> bool:
        """Clear all closed trades, leaving open positions intact."""
        with self.lock:
            self.trades = [t for t in self.trades if t.get("status") == "OPEN"]
            self._save()
        logger.info("Cleared closed trade history.")
        return True

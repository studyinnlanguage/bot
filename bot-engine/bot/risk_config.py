"""
Shared Risk, TP/SL, Timeframe, and Strategy Validation Helpers.
Used uniformly across SaaS (app.py, mobile_api.py), Bot-Engine API (bot-engine/app.py),
and Strategy Workers (bot-engine/bot/engine.py) so all endpoints share one source of truth.
"""
from __future__ import annotations

SL_MIN = 0.05
SL_MAX = 50.0
SL_DEFAULT = 0.5

TP_MIN = 0.30   # Safely above ~0.12-0.15% roundtrip taker fees + slippage
TP_MAX = 50.0
TP_DEFAULT = 1.5

MAX_SAFE_SL_ROE = 80.0       # Max SL loss % of margin before liquidation clamp
LIQ_GUARD_TRIGGER_ROE = 85.0  # Trigger clamp when sl_pct * leverage >= 85%

VALID_TP_MODES = ("fixed", "trailing")
VALID_TIMEFRAMES = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w")

RECOMMENDED_PRESET = {
    "timeframe": "15m",
    "leverage": 20,
    "stop_loss_pct": 0.5,
    "take_profit_pct": 1.5,
    "tp_mode": "trailing",
    "breakeven_lock": False,
    "min_ema_spread": 0.0,
    "max_concurrent_trades": 2,
    "reentry_cooldown_sec": 180,
}


def price_for_roe(entry_price: float, side: str, leverage: int, roe_pct: float) -> float:
    """Convert a target ROE % on margin into an exact asset trigger price."""
    if entry_price <= 0:
        return 0.0
    lev = max(1, int(leverage or 1))
    move_frac = (float(roe_pct) / lev) / 100.0
    if str(side or "").upper() == "LONG":
        return entry_price * (1.0 + move_frac)
    return entry_price * (1.0 - move_frac)


def clamp_stop_loss(raw_sl, leverage: int = 10, default: float = SL_DEFAULT) -> tuple[float, bool, float]:
    """Clamp SL % within [SL_MIN, SL_MAX] and prevent >= 85% ROE liquidation risk on high leverage.

    Returns (safe_sl_pct, was_liq_clamped, max_safe_sl_pct).
    """
    try:
        sl = float(raw_sl) if raw_sl is not None and raw_sl != "" else float(default)
        if sl <= 0:
            sl = float(default)
    except (TypeError, ValueError):
        sl = float(default)

    sl = max(SL_MIN, min(SL_MAX, sl))
    lev = max(1, int(leverage or 10))
    max_safe_sl = max(SL_MIN, round(MAX_SAFE_SL_ROE / lev, 2))
    was_clamped = False
    if lev >= 10 and (sl * lev) >= LIQ_GUARD_TRIGGER_ROE and sl > max_safe_sl:
        sl = max_safe_sl
        was_clamped = True
    return round(sl, 4), was_clamped, max_safe_sl


def clamp_take_profit(raw_tp, default: float = TP_DEFAULT) -> float:
    """Clamp user-configurable TP % within fee-safe [TP_MIN, TP_MAX]."""
    try:
        tp = float(raw_tp) if raw_tp is not None and raw_tp != "" else float(default)
        if tp <= 0:
            tp = float(default)
    except (TypeError, ValueError):
        tp = float(default)
    tp = max(TP_MIN, min(TP_MAX, tp))
    return round(tp, 4)


def normalize_tp_mode(raw_mode, default: str = "trailing") -> str:
    """Normalize exit TP mode: 'trailing' (Stepped ROE Trailing) or 'fixed'."""
    val = str(raw_mode or default).strip().lower()
    return val if val in VALID_TP_MODES else default


def normalize_breakeven_lock(raw_val, default: bool = True) -> bool:
    """Normalize breakeven SL profit-lock toggle (default ON)."""
    if raw_val is None:
        return bool(default)
    if isinstance(raw_val, str):
        return raw_val.strip().lower() not in ("false", "0", "no", "off", "")
    return bool(raw_val)


def normalize_timeframe(raw_tf, default: str = "15m") -> str:
    """Validate candle timeframe string while preserving existing saved user choices."""
    val = str(raw_tf or default).strip()
    return val if val in VALID_TIMEFRAMES else default

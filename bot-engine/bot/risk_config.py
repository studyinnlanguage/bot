"""
Shared Timeframe Validation Helper.
Used uniformly across SaaS (app.py, mobile_api.py), Bot-Engine API (bot-engine/app.py),
and Strategy Workers (bot-engine/bot/engine.py).
Pure EMA (8/13/21/55) + Pure EMA55 Reversal mode — no SL, no TP, no trailing, no spread/wait filters.
"""
from __future__ import annotations

VALID_TIMEFRAMES = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w")


def normalize_timeframe(raw_tf, default: str = "15m") -> str:
    """Validate candle timeframe string while preserving existing saved user choices."""
    val = str(raw_tf or default).strip()
    return val if val in VALID_TIMEFRAMES else default

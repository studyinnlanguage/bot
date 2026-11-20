"""
Trading Strategy Module — Pure EMA (8, 13, 21, 55) + Pure EMA55 Reversal.

Rules (ZERO spread filter, ZERO candle waiting, ZERO SL/TP/trailing):
- BUY  (LONG)  : EMA 55 strictly below ALL fast EMAs (EMA 55 < EMA 8, EMA 13, EMA 21)
- SELL (SHORT) : EMA 55 strictly above ALL fast EMAs (EMA 55 > EMA 8, EMA 13, EMA 21)
- HOLD         : EMA 55 is inside / between the 8, 13, 21 lines

Evaluated directly on the latest live candle so entries and EMA55 reversals trigger
immediately without any spread wait, candle-count window, or startup waiting lock.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd

from .indicators import IndicatorSet

logger = logging.getLogger(__name__)


class Signal(str, Enum):
    BUY = "BUY"      # Go LONG
    SELL = "SELL"    # Go SHORT
    HOLD = "HOLD"    # No action


@dataclass
class StrategyResult:
    signal: Signal
    ema_8: float
    ema_13: float
    ema_21: float
    ema_55: float
    last_close: float
    reason: str


class EMAQuadStrategy:
    """Pure 4-EMA (8/13/21/55) strategy — zero spread filter, zero waiting."""

    def __init__(self, ema_short=8, ema_mid1=13, ema_mid2=21, ema_long=55):
        self.indicators = IndicatorSet(ema_short, ema_mid1, ema_mid2, ema_long)
        self.ema_short = ema_short
        self.ema_mid1 = ema_mid1
        self.ema_mid2 = ema_mid2
        self.ema_long = ema_long

    @staticmethod
    def _classify(e8: float, e13: float, e21: float, e55: float) -> tuple[Signal, str]:
        if e55 < e8 and e55 < e13 and e55 < e21:
            return Signal.BUY, "EMA55 at BOTTOM (< 8, 13, 21) -> BUY (LONG)"
        if e55 > e8 and e55 > e13 and e55 > e21:
            return Signal.SELL, "EMA55 at TOP (> 8, 13, 21) -> SELL (SHORT)"
        return Signal.HOLD, "EMA55 inside lines (8, 13, 21) -> HOLD"

    def analyze(self, df: pd.DataFrame) -> Optional[StrategyResult]:
        """Analyze candles and return the immediate pure-EMA signal."""
        if df is None or len(df) < self.ema_long + 5:
            return None

        enriched = self.indicators.compute(df)
        last = enriched.iloc[-1]

        e8 = last["ema_8"]
        e13 = last["ema_13"]
        e21 = last["ema_21"]
        e55 = last["ema_55"]
        if pd.isna(e8) or pd.isna(e13) or pd.isna(e21) or pd.isna(e55):
            return None

        e8_f, e13_f, e21_f, e55_f = float(e8), float(e13), float(e21), float(e55)
        last_close = float(last["close"])
        signal, reason = self._classify(e8_f, e13_f, e21_f, e55_f)

        return StrategyResult(
            signal=signal,
            ema_8=e8_f,
            ema_13=e13_f,
            ema_21=e21_f,
            ema_55=e55_f,
            last_close=last_close,
            reason=reason,
        )

    def latest_indicators(self, df: pd.DataFrame) -> dict:
        """Return latest EMA indicator values & pure-EMA signal for UI display."""
        if df is None or len(df) < self.ema_long + 5:
            return {}
        enriched = self.indicators.compute(df)
        last = enriched.iloc[-1]
        e8 = float(last["ema_8"]) if not pd.isna(last["ema_8"]) else None
        e13 = float(last["ema_13"]) if not pd.isna(last["ema_13"]) else None
        e21 = float(last["ema_21"]) if not pd.isna(last["ema_21"]) else None
        e55 = float(last["ema_55"]) if not pd.isna(last["ema_55"]) else None

        sig = "HOLD"
        if e8 is not None and e13 is not None and e21 is not None and e55 is not None:
            sig = self._classify(e8, e13, e21, e55)[0].value

        return {
            "ema_8": e8,
            "ema_13": e13,
            "ema_21": e21,
            "ema_55": e55,
            "signal": sig,
            "close": float(last["close"]),
            "timestamp": str(last.name) if last.name is not None else None,
        }

"""
Trading Strategy Module
EMA Crossover Strategy based on 4 EMAs (8, 13, 21, 55).

Rules (STRICT TREND & ANTI-CHOP MODE):
- BUY  (LONG)  : Full Bullish Fan -> EMA 8 >= EMA 13 >= EMA 21 > EMA 55 with spread >= min_spread_pct
- SELL (SHORT) : Full Bearish Fan -> EMA 8 <= EMA 13 <= EMA 21 < EMA 55 with spread >= min_spread_pct
- HOLD         : Tangled EMAs or sideways flat market (spread < min_spread_pct)

Cross Detection:
- `just_crossed` is True ONLY on the candle where the signal FIRST appears from a non-trend state.
- Chop micro-fluctuations (wobbling between HOLD and trend) will NEVER re-trigger false entries.
- Unused legacy indicators (ATR, ADX, Slope) completely removed for maximum speed and zero bloat.
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
    just_crossed: bool = False   # True only on the FRESH candle where cross first happens
    min_sep_pct: float = 0.0


class EMAQuadStrategy:
    """Quad-EMA crossover strategy with sequential alignment & anti-chop spread guard."""

    def __init__(self, ema_short=8, ema_mid1=13, ema_mid2=21, ema_long=55, min_spread_pct=0.15):
        self.indicators = IndicatorSet(ema_short, ema_mid1, ema_mid2, ema_long)
        self.ema_short = ema_short
        self.ema_mid1 = ema_mid1
        self.ema_mid2 = ema_mid2
        self.ema_long = ema_long
        self.min_spread_pct = float(min_spread_pct)
        self._prev_signal: Signal = Signal.HOLD
        self._last_trend_side: Optional[Signal] = None
        self._trade_entered_for_signal: bool = False

    def _calc_signal(self, row) -> Signal:
        e8 = float(row["ema_8"]) if not pd.isna(row["ema_8"]) else None
        e13 = float(row["ema_13"]) if not pd.isna(row["ema_13"]) else None
        e21 = float(row["ema_21"]) if not pd.isna(row["ema_21"]) else None
        e55 = float(row["ema_55"]) if not pd.isna(row["ema_55"]) else None
        if e8 is None or e13 is None or e21 is None or e55 is None:
            return Signal.HOLD

        sep_pct = (abs(e8 - e55) / e55) * 100.0 if e55 else 0.0
        if sep_pct < self.min_spread_pct:
            return Signal.HOLD

        # Full Bullish Fan -> 8 >= 13 >= 21 > 55
        if e8 >= e13 and e13 >= e21 and e21 > e55:
            return Signal.BUY
        # Full Bearish Fan -> 8 <= 13 <= 21 < 55
        elif e8 <= e13 and e13 <= e21 and e21 < e55:
            return Signal.SELL
        return Signal.HOLD

    def _is_bullish_aligned(self, row) -> bool:
        """Check if row has clean bullish EMA fan: 8 >= 13 >= 21 > 55."""
        e8 = row.get("ema_8")
        e13 = row.get("ema_13")
        e21 = row.get("ema_21")
        e55 = row.get("ema_55")
        if pd.isna(e8) or pd.isna(e13) or pd.isna(e21) or pd.isna(e55):
            return False
        return float(e8) >= float(e13) and float(e13) >= float(e21) and float(e21) > float(e55)

    def _is_bearish_aligned(self, row) -> bool:
        """Check if row has clean bearish EMA fan: 8 <= 13 <= 21 < 55."""
        e8 = row.get("ema_8")
        e13 = row.get("ema_13")
        e21 = row.get("ema_21")
        e55 = row.get("ema_55")
        if pd.isna(e8) or pd.isna(e13) or pd.isna(e21) or pd.isna(e55):
            return False
        return float(e8) <= float(e13) and float(e13) <= float(e21) and float(e21) < float(e55)

    def seed_startup_state(self, signal: Signal):
        """Seed startup state so bot NEVER enters on startup without a fresh crossover."""
        self._prev_signal = signal
        if signal in (Signal.BUY, Signal.SELL):
            self._last_trend_side = signal
        self._trade_entered_for_signal = True
        logger.info("Strategy seeded on startup with signal=%s (waiting for fresh cross)", signal.value)

    def analyze(self, df: pd.DataFrame) -> Optional[StrategyResult]:
        """Analyze candles and return signal."""
        if df is None or len(df) < self.ema_long + 5:
            return None

        enriched = self.indicators.compute(df)
        # Evaluate trade signals on the last confirmed CLOSED candle (iloc[-2]).
        # iloc[-1] is the unclosed/forming candle whose close price ticks every second.
        closed_candle = enriched.iloc[-2] if len(enriched) >= 2 else enriched.iloc[-1]
        last = enriched.iloc[-1]

        e8, e13, e21, e55 = closed_candle["ema_8"], closed_candle["ema_13"], closed_candle["ema_21"], closed_candle["ema_55"]
        last_close = float(last["close"])

        if pd.isna(e55) or pd.isna(e8) or pd.isna(e13) or pd.isna(e21):
            return None

        sep_pct = (abs(float(e8) - float(e55)) / float(e55)) * 100.0 if float(e55) else 0.0

        # 1. Sequential EMA Alignment Detection
        is_buy_candidate = (float(e8) >= float(e13) and float(e13) >= float(e21) and float(e21) > float(e55))
        is_sell_candidate = (float(e8) <= float(e13) and float(e13) <= float(e21) and float(e21) < float(e55))

        # 2. Minimum Spread Chop Filter
        is_flat_chop = sep_pct < self.min_spread_pct

        if is_flat_chop and (is_buy_candidate or is_sell_candidate):
            signal = Signal.HOLD
            reason = f"Flat market chop (EMA spread {sep_pct:.3f}% < {self.min_spread_pct:.3f}% required) -> HOLD"
        elif is_buy_candidate:
            signal = Signal.BUY
            reason = f"EMA55 at BOTTOM & Bullish EMA stack 8>=13>=21>55 (spread={sep_pct:.2f}%) -> BUY (LONG)"
        elif is_sell_candidate:
            signal = Signal.SELL
            reason = f"EMA55 at TOP & Bearish EMA stack 8<=13<=21<55 (spread={sep_pct:.2f}%) -> SELL (SHORT)"
        else:
            signal = Signal.HOLD
            reason = "EMAs tangled / no clear trend -> HOLD"

        # 3. Genuine Fresh Crossover Check:
        # A fresh BUY cross requires that prior to this candle, EMAs were NOT already in full bullish alignment.
        # A fresh SELL cross requires that prior to this candle, EMAs were NOT already in full bearish alignment.
        is_fresh_cross = False
        if signal == Signal.BUY and len(enriched) >= 4:
            was_not_bullish_prev1 = not self._is_bullish_aligned(enriched.iloc[-3])
            was_not_bullish_prev2 = not self._is_bullish_aligned(enriched.iloc[-4])
            if was_not_bullish_prev1 or was_not_bullish_prev2:
                is_fresh_cross = True
        elif signal == Signal.SELL and len(enriched) >= 4:
            was_not_bearish_prev1 = not self._is_bearish_aligned(enriched.iloc[-3])
            was_not_bearish_prev2 = not self._is_bearish_aligned(enriched.iloc[-4])
            if was_not_bearish_prev1 or was_not_bearish_prev2:
                is_fresh_cross = True

        # 4. Anti-Whipsaw Flicker State Transition:
        # If signal dips into HOLD due to chop spread, DO NOT reset _trade_entered_for_signal.
        # Only reset it when the signal explicitly crosses to the OPPOSITE side.
        if signal in (Signal.BUY, Signal.SELL):
            if signal != self._last_trend_side:
                # Genuine trend flip to opposite direction
                self._trade_entered_for_signal = False
                self._last_trend_side = signal
            self._prev_signal = signal
        else:
            self._prev_signal = Signal.HOLD

        # STRICT RULE: Only enter on a genuine FRESH crossover!
        just_crossed = False
        if signal in (Signal.BUY, Signal.SELL) and not self._trade_entered_for_signal and is_fresh_cross:
            just_crossed = True

        return StrategyResult(
            signal=signal,
            ema_8=float(e8),
            ema_13=float(e13),
            ema_21=float(e21),
            ema_55=float(e55),
            last_close=last_close,
            reason=reason,
            just_crossed=just_crossed,
            min_sep_pct=float(sep_pct),
        )

    def mark_trade_entered(self):
        """Called when a trade is entered so we don't fire multiple entries for same cross."""
        self._trade_entered_for_signal = True

    def latest_indicators(self, df: pd.DataFrame) -> dict:
        """Return latest indicator values as a dict (for UI display)."""
        if df is None or len(df) < self.ema_long + 5:
            return {}
        enriched = self.indicators.compute(df)
        last = enriched.iloc[-1]
        e8 = float(last["ema_8"]) if not pd.isna(last["ema_8"]) else None
        e13 = float(last["ema_13"]) if not pd.isna(last["ema_13"]) else None
        e21 = float(last["ema_21"]) if not pd.isna(last["ema_21"]) else None
        e55 = float(last["ema_55"]) if not pd.isna(last["ema_55"]) else None
        sep_pct = round(abs(e8 - e55) / e55 * 100.0, 3) if (e8 and e55) else 0.0

        sig = "HOLD"
        if e8 and e13 and e21 and e55 and sep_pct >= self.min_spread_pct:
            if e8 >= e13 and e13 >= e21 and e21 > e55:
                sig = "BUY"
            elif e8 <= e13 and e13 <= e21 and e21 < e55:
                sig = "SELL"

        return {
            "ema_8": e8,
            "ema_13": e13,
            "ema_21": e21,
            "ema_55": e55,
            "signal": sig,
            "ema_sep_pct": sep_pct,
            "close": float(last["close"]),
            "timestamp": str(last.name) if last.name is not None else None,
        }

    def reset_cross_state(self):
        """Reset the cross state to wait for a brand new crossover."""
        self._prev_signal = Signal.HOLD
        self._last_trend_side = None
        self._trade_entered_for_signal = False
        logger.info("Strategy cross state reset - waiting for fresh cross")

    def reset_for_reversal(self):
        """Reset for reversal exit."""
        self._prev_signal = Signal.HOLD
        self._last_trend_side = None
        self._trade_entered_for_signal = False
        logger.info("Strategy reset for REVERSAL exit")

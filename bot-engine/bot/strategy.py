"""
Trading Strategy Module
EMA Crossover Strategy based on 4 EMAs (8, 13, 21, 55).

Rules (STRICT MODE):
- BUY  (LONG)  : EMA 55 crosses BELOW all other EMAs (8, 13, 21) -> 55 is the LOWEST line.
- SELL (SHORT) : EMA 55 crosses ABOVE all other EMAs (8, 13, 21) -> 55 is the HIGHEST line.
- HOLD         : otherwise

Cross Detection:
- `just_crossed` is True ONLY on the candle where the signal FIRST appears.
- If bot starts and line is ALREADY crossed, just_crossed = False (no trade).
- Bot must wait for a FRESH cross to enter a trade.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
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
    adx_14: float = 0.0
    ema_21_slope: float = 0.0
    min_sep_pct: float = 0.0
    chop_passed: bool = True
    chop_reason: str = ""


class EMAQuadStrategy:
    """Quad-EMA crossover strategy with 3-candle confirmation window, anti-exhaustion, and chop filters."""

    ADX_MIN: float = 14.0
    EMA_SLOPE_MIN_PCT: float = 0.02
    MIN_SEP_PCT: float = 0.10
    COOLDOWN_MOVE_THRESHOLD_PCT: float = 2.5
    COOLDOWN_CANDLES: int = 3
    MAX_EMA21_EXTENSION_PCT: float = 1.5

    def __init__(self, ema_short=8, ema_mid1=13, ema_mid2=21, ema_long=55):
        self.indicators = IndicatorSet(ema_short, ema_mid1, ema_mid2, ema_long)
        self.ema_short = ema_short
        self.ema_mid1 = ema_mid1
        self.ema_mid2 = ema_mid2
        self.ema_long = ema_long
        # Track previous candle's signal to detect fresh crosses
        self._prev_signal: Signal = Signal.HOLD
        self._require_hold_before_cross: bool = False
        self._cross_candle_count: int = 0
        self._trade_entered_for_signal: bool = False

    def analyze(self, df: pd.DataFrame) -> Optional[StrategyResult]:
        """Analyze candles and return a signal with clean stack, anti-exhaustion, and chop filters applied."""
        if df is None or len(df) < self.ema_long + 5:
            logger.warning("Insufficient data for strategy (need >= %d rows, got %d)",
                           self.ema_long + 5, len(df) if df is not None else 0)
            return None

        # Exclude currently forming unclosed candle to prevent intra-candle wick false signals
        if len(df) > self.ema_long + 10:
            df_eval = df.iloc[:-1]
        else:
            df_eval = df

        enriched = self.indicators.compute(df_eval)
        last = enriched.iloc[-1]

        e8, e13, e21, e55 = last["ema_8"], last["ema_13"], last["ema_21"], last["ema_55"]
        last_close = float(last["close"])

        if pd.isna(e55) or pd.isna(e8) or pd.isna(e13) or pd.isna(e21):
            logger.warning("EMA values contain NaN - need more historical data")
            return None

        # Core EMA Strategy:
        # BUY (LONG): EMA55 is at the BOTTOM (e55 < e8, e13, e21)
        # SELL (SHORT): EMA55 is at the TOP (e55 > e8, e13, e21)
        if float(e55) < float(e8) and float(e55) < float(e13) and float(e55) < float(e21):
            signal = Signal.BUY
            reason = "EMA55 is at BOTTOM (below EMA8, 13, 21) -> LONG signal"
        elif float(e55) > float(e8) and float(e55) > float(e13) and float(e55) > float(e21):
            signal = Signal.SELL
            reason = "EMA55 is at TOP (above EMA8, 13, 21) -> SHORT signal"
        else:
            signal = Signal.HOLD
            reason = "EMA55 in middle / tangled -> HOLD"

        # ===== CHOP & EXHAUSTION FILTERS =====
        # 1. ADX(14) < 14 -> Chop (market flat)
        adx_val = float(last.get("adx_14", 0.0)) if "adx_14" in last and not pd.isna(last["adx_14"]) else 0.0

        # 2. EMA slope check: EMA21 abhi vs 6 candles pehle — agar flat (|slope| < 0.02%) -> no trade
        slope_val = float(last.get("ema_21_slope", 0.0)) if "ema_21_slope" in last and not pd.isna(last["ema_21_slope"]) else 0.0

        # 3. Price cloud check:
        # For BUY: price should be above EMA55
        # For SELL: price should be below EMA55
        price_valid_for_trend = True
        if signal == Signal.BUY and last_close <= float(e55):
            price_valid_for_trend = False
        elif signal == Signal.SELL and last_close >= float(e55):
            price_valid_for_trend = False

        # 4. Cooldown: 1 candle mein >= 2.5% ka massive move (dump/pump) -> agle 3 candles cooldown
        has_big_move_in_recent_candles = False
        recent_tail = df_eval.tail(4)
        if len(recent_tail) >= 2:
            check_slice = recent_tail.iloc[-4:-1] if len(recent_tail) >= 4 else recent_tail.iloc[:-1]
            if "candle_move_pct" in check_slice.columns:
                max_body = check_slice["candle_move_pct"].max()
                if not pd.isna(max_body) and max_body >= self.COOLDOWN_MOVE_THRESHOLD_PCT:
                    has_big_move_in_recent_candles = True
            if not has_big_move_in_recent_candles and "candle_hl_pct" in check_slice.columns:
                max_hl = check_slice["candle_hl_pct"].max()
                if not pd.isna(max_hl) and max_hl >= self.COOLDOWN_MOVE_THRESHOLD_PCT:
                    has_big_move_in_recent_candles = True

        # 5. min_sep_pct (separation between EMA8 and EMA55 >= 0.10%)
        sep_pct = (abs(float(e8) - float(e55)) / float(e55)) * 100.0

        # 6. Anti-Exhaustion / Late Entry Trap Filter:
        # Prevents buying at top after 3-4 consecutive pump candles, or shorting at bottom after 3-4 dump candles
        is_exhausted_move = False
        exhaustion_reason = ""
        if len(df_eval) >= 4 and signal in (Signal.BUY, Signal.SELL):
            recent_candles = df_eval.tail(4)
            if signal == Signal.BUY:
                consecutive_green = sum(1 for i in (1, 2, 3) if recent_candles["close"].iloc[-i] > recent_candles["open"].iloc[-i])
                three_candle_move = ((recent_candles["close"].iloc[-1] - recent_candles["open"].iloc[-3]) / recent_candles["open"].iloc[-3]) * 100.0
                dist_above_ema21 = (last_close - float(e21)) / float(e21) * 100.0
                if consecutive_green >= 3 and (three_candle_move >= 2.0 or dist_above_ema21 >= self.MAX_EMA21_EXTENSION_PCT):
                    is_exhausted_move = True
                    exhaustion_reason = f"Exhaustion Trap: 3 consecutive pump candles (+{three_candle_move:.2f}%) / overextended. Skip buying top."
            elif signal == Signal.SELL:
                consecutive_red = sum(1 for i in (1, 2, 3) if recent_candles["close"].iloc[-i] < recent_candles["open"].iloc[-i])
                three_candle_drop = ((recent_candles["open"].iloc[-3] - recent_candles["close"].iloc[-1]) / recent_candles["open"].iloc[-3]) * 100.0
                dist_below_ema21 = (float(e21) - last_close) / float(e21) * 100.0
                if consecutive_red >= 3 and (three_candle_drop >= 2.0 or dist_below_ema21 >= self.MAX_EMA21_EXTENSION_PCT):
                    is_exhausted_move = True
                    exhaustion_reason = f"Exhaustion Trap: 3 consecutive dump candles (-{three_candle_drop:.2f}%) / overextended. Skip shorting bottom."

        chop_passed = True
        chop_reason = ""
        if signal in (Signal.BUY, Signal.SELL):
            if is_exhausted_move:
                chop_passed = False
                chop_reason = exhaustion_reason
            elif adx_val > 0 and adx_val < self.ADX_MIN:
                chop_passed = False
                chop_reason = f"ADX(14)={adx_val:.1f} < {self.ADX_MIN} (Chop / sideways market)"
            elif abs(slope_val) < self.EMA_SLOPE_MIN_PCT:
                chop_passed = False
                chop_reason = f"EMA21 slope={slope_val:+.3f}% (|slope| < {self.EMA_SLOPE_MIN_PCT}%, flat)"
            elif not price_valid_for_trend:
                chop_passed = False
                chop_reason = f"Price (${last_close:.4f}) lagging behind EMA55 (${float(e55):.4f})"
            elif has_big_move_in_recent_candles:
                chop_passed = False
                chop_reason = f"Dump/Pump Cooldown active (>= {self.COOLDOWN_MOVE_THRESHOLD_PCT}% spike in last 3 candles)"
            elif sep_pct < self.MIN_SEP_PCT:
                chop_passed = False
                chop_reason = f"EMA separation {sep_pct:.3f}% < {self.MIN_SEP_PCT}% (EMAs squeezed)"

        # ===== FRESH CROSS TRACKING & CONFIRMATION WINDOW =====
        just_crossed = False

        if signal != self._prev_signal:
            # Signal changed (e.g. HOLD -> BUY, or SELL -> BUY)
            self._cross_candle_count = 0
            self._trade_entered_for_signal = False
            self._prev_signal = signal
        else:
            self._cross_candle_count += 1

        if self._require_hold_before_cross:
            if signal == Signal.HOLD:
                self._require_hold_before_cross = False
        else:
            # Allow entry on the first 3 candles of the fresh cross
            if signal in (Signal.BUY, Signal.SELL) and not self._trade_entered_for_signal:
                if self._cross_candle_count <= 3:
                    if chop_passed:
                        just_crossed = True
                        self._trade_entered_for_signal = True
                        logger.info("✅ Valid %s entry triggered on candle %d of cross!",
                                    signal.value, self._cross_candle_count)
                    else:
                        logger.info("⏳ Candle %d of %s cross held by filter: %s",
                                    self._cross_candle_count, signal.value, chop_reason)

        return StrategyResult(
            signal=signal,
            ema_8=float(e8),
            ema_13=float(e13),
            ema_21=float(e21),
            ema_55=float(e55),
            last_close=last_close,
            reason=reason,
            just_crossed=just_crossed,
            adx_14=float(adx_val),
            ema_21_slope=float(slope_val),
            min_sep_pct=float(sep_pct),
            chop_passed=chop_passed,
            chop_reason=chop_reason,
        )

    def latest_indicators(self, df: pd.DataFrame) -> dict:
        """Return latest indicator values as a dict (for UI display)."""
        if df is None or len(df) < self.ema_long + 5:
            return {}
        enriched = self.indicators.compute(df)
        last = enriched.iloc[-1]
        e8 = float(last["ema_8"]) if not pd.isna(last["ema_8"]) else None
        e55 = float(last["ema_55"]) if not pd.isna(last["ema_55"]) else None
        sep_pct = round(abs(e8 - e55) / e55 * 100.0, 3) if (e8 and e55) else 0.0

        return {
            "ema_8": e8,
            "ema_13": float(last["ema_13"]) if not pd.isna(last["ema_13"]) else None,
            "ema_21": float(last["ema_21"]) if not pd.isna(last["ema_21"]) else None,
            "ema_55": e55,
            "adx_14": round(float(last.get("adx_14", 0)), 1) if "adx_14" in last and not pd.isna(last["adx_14"]) else 0.0,
            "ema_21_slope": round(float(last.get("ema_21_slope", 0)), 3) if "ema_21_slope" in last and not pd.isna(last["ema_21_slope"]) else 0.0,
            "ema_sep_pct": sep_pct,
            "close": float(last["close"]),
            "timestamp": str(last.name) if last.name is not None else None,
        }

    def reset_cross_state(self):
        """Reset the previous-signal tracker. Called when bot starts or
        after a trade closes, so the next cross must be FRESH.
        """
        self._prev_signal = Signal.HOLD
        self._require_hold_before_cross = True
        self._cross_candle_count = 0
        self._trade_entered_for_signal = False
        logger.info("Strategy cross state reset - waiting for fresh cross")

    def reset_for_reversal(self):
        """Reset prev_signal to HOLD WITHOUT requiring HOLD-before-cross."""
        self._prev_signal = Signal.HOLD
        self._require_hold_before_cross = False
        self._cross_candle_count = 0
        self._trade_entered_for_signal = False
        logger.info("Strategy reset for REVERSAL - opposite signal will trigger fresh entry")

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
    """Quad-EMA crossover strategy: EMA55 at bottom = BUY, EMA55 at top = SELL."""

    def __init__(self, ema_short=8, ema_mid1=13, ema_mid2=21, ema_long=55):
        self.indicators = IndicatorSet(ema_short, ema_mid1, ema_mid2, ema_long)
        self.ema_short = ema_short
        self.ema_mid1 = ema_mid1
        self.ema_mid2 = ema_mid2
        self.ema_long = ema_long
        self._prev_signal: Signal = Signal.HOLD
        self._trade_entered_for_signal: bool = False

    def _calc_signal(self, row) -> Signal:
        e8 = float(row["ema_8"]) if not pd.isna(row["ema_8"]) else None
        e13 = float(row["ema_13"]) if not pd.isna(row["ema_13"]) else None
        e21 = float(row["ema_21"]) if not pd.isna(row["ema_21"]) else None
        e55 = float(row["ema_55"]) if not pd.isna(row["ema_55"]) else None
        if e8 is None or e13 is None or e21 is None or e55 is None:
            return Signal.HOLD
        # BUY: EMA55 at bottom and EMA8 >= EMA13
        if e55 < e8 and e55 < e13 and e55 < e21 and e8 >= e13:
            return Signal.BUY
        # SELL: EMA55 at top and EMA8 <= EMA13
        elif e55 > e8 and e55 > e13 and e55 > e21 and e8 <= e13:
            return Signal.SELL
        return Signal.HOLD

    def _is_ema55_at_bottom(self, row) -> bool:
        """Check if EMA55 is strictly at the bottom (below 8, 13, and 21)."""
        e8 = row.get("ema_8")
        e13 = row.get("ema_13")
        e21 = row.get("ema_21")
        e55 = row.get("ema_55")
        if pd.isna(e8) or pd.isna(e13) or pd.isna(e21) or pd.isna(e55):
            return False
        return float(e55) < float(e8) and float(e55) < float(e13) and float(e55) < float(e21)

    def _is_ema55_at_top(self, row) -> bool:
        """Check if EMA55 is strictly at the top (above 8, 13, and 21)."""
        e8 = row.get("ema_8")
        e13 = row.get("ema_13")
        e21 = row.get("ema_21")
        e55 = row.get("ema_55")
        if pd.isna(e8) or pd.isna(e13) or pd.isna(e21) or pd.isna(e55):
            return False
        return float(e55) > float(e8) and float(e55) > float(e13) and float(e55) > float(e21)

    def seed_startup_state(self, signal: Signal):
        """Seed startup state so bot NEVER enters on startup."""
        self._prev_signal = signal
        self._trade_entered_for_signal = True
        logger.info("Strategy seeded on startup with signal=%s (waiting for fresh cross)", signal.value)

    def analyze(self, df: pd.DataFrame) -> Optional[StrategyResult]:
        """Analyze candles and return signal."""
        if df is None or len(df) < self.ema_long + 5:
            return None

        enriched = self.indicators.compute(df)
        # CRITICAL FIX: Evaluate trade signals on the last confirmed CLOSED candle (iloc[-2]).
        # iloc[-1] is the unclosed/forming candle whose close price ticks every second.
        # Evaluating on confirmed closed candle prevents rapid intra-candle flip traps and whipsaws!
        closed_candle = enriched.iloc[-2] if len(enriched) >= 2 else enriched.iloc[-1]
        last = enriched.iloc[-1]

        e8, e13, e21, e55 = closed_candle["ema_8"], closed_candle["ema_13"], closed_candle["ema_21"], closed_candle["ema_55"]
        last_close = float(last["close"])

        if pd.isna(e55) or pd.isna(e8) or pd.isna(e13) or pd.isna(e21):
            return None

        # CRITICAL FIX: Read ADX & slope from confirmed CLOSED candle (iloc[-2]), NOT forming candle!
        adx_val = float(closed_candle.get("adx_14", 0.0)) if "adx_14" in closed_candle and not pd.isna(closed_candle["adx_14"]) else 0.0
        slope_val = float(closed_candle.get("ema_21_slope", 0.0)) if "ema_21_slope" in closed_candle and not pd.isna(closed_candle["ema_21_slope"]) else 0.0
        sep_pct = (abs(float(e8) - float(e55)) / float(e55)) * 100.0 if float(e55) else 0.0
        closed_close = float(closed_candle["close"])
        cloud_low = min(float(e8), float(e55))
        cloud_high = max(float(e8), float(e55))

        # Check for recent extreme spike candles (>= 1.0% move in single closed candle)
        has_spike_trap = False
        if len(enriched) >= 4:
            recent_candles = enriched.iloc[-4:-1]
            for _, r_bar in recent_candles.iterrows():
                o_val = float(r_bar["open"]) if not pd.isna(r_bar["open"]) else 0.0
                c_val = float(r_bar["close"]) if not pd.isna(r_bar["close"]) else 0.0
                if o_val > 0:
                    c_move = abs(c_val - o_val) / o_val * 100.0
                    if c_move >= 1.0:
                        has_spike_trap = True
                        break

        # 1. Base EMA Candidate Detection
        is_buy_candidate = (float(e55) < float(e8) and float(e55) < float(e13) and float(e55) < float(e21) and float(e8) >= float(e13))
        is_sell_candidate = (float(e55) > float(e8) and float(e55) > float(e13) and float(e55) > float(e21) and float(e8) <= float(e13))

        # 2. Strict Price-Action Chop Filters (No lagging ADX)
        MIN_SEP_PCT = 0.20

        if is_buy_candidate:
            if closed_close <= cloud_high:
                signal = Signal.HOLD
                reason = f"Price (${closed_close:.4f}) inside EMA cloud [{cloud_low:.4f} - {cloud_high:.4f}] -> Chop HOLD"
            elif sep_pct < MIN_SEP_PCT:
                signal = Signal.HOLD
                reason = f"EMAs squeezed (sep {sep_pct:.3f}% < {MIN_SEP_PCT}%) -> Flat Chop HOLD"
            elif has_spike_trap:
                signal = Signal.HOLD
                reason = "Spike Wick Trap Cooldown active (recent >=1.0% candle move) -> HOLD"
            else:
                signal = Signal.BUY
                reason = "EMA55 at BOTTOM & Breakout above Cloud -> LONG signal"

        elif is_sell_candidate:
            if closed_close >= cloud_low:
                signal = Signal.HOLD
                reason = f"Price (${closed_close:.4f}) inside EMA cloud [{cloud_low:.4f} - {cloud_high:.4f}] -> Chop HOLD"
            elif sep_pct < MIN_SEP_PCT:
                signal = Signal.HOLD
                reason = f"EMAs squeezed (sep {sep_pct:.3f}% < {MIN_SEP_PCT}%) -> Flat Chop HOLD"
            elif has_spike_trap:
                signal = Signal.HOLD
                reason = "Spike Wick Trap Cooldown active (recent >=1.0% candle move) -> HOLD"
            else:
                signal = Signal.SELL
                reason = "EMA55 at TOP & Breakdown below Cloud -> SHORT signal"
        else:
            signal = Signal.HOLD
            reason = "EMA55 in middle / tangled -> HOLD"

        # CRITICAL FIX: Pure Genuine EMA55 Crossover Check
        # A fresh BUY cross requires that prior to this candle, EMA55 was NOT already sitting at the bottom.
        # A fresh SELL cross requires that prior to this candle, EMA55 was NOT already sitting at the top.
        # This completely prevents ADX fluctuations or HOLD flickers from triggering fake "fresh" entries in mid-trend!
        is_fresh_cross = False
        if signal == Signal.BUY and len(enriched) >= 4:
            was_not_bottom_prev1 = not self._is_ema55_at_bottom(enriched.iloc[-3])
            was_not_bottom_prev2 = not self._is_ema55_at_bottom(enriched.iloc[-4])
            if was_not_bottom_prev1 or was_not_bottom_prev2:
                is_fresh_cross = True
        elif signal == Signal.SELL and len(enriched) >= 4:
            was_not_top_prev1 = not self._is_ema55_at_top(enriched.iloc[-3])
            was_not_top_prev2 = not self._is_ema55_at_top(enriched.iloc[-4])
            if was_not_top_prev1 or was_not_top_prev2:
                is_fresh_cross = True

        # Signal state transition
        if signal != self._prev_signal:
            self._trade_entered_for_signal = False
            self._prev_signal = signal

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
            adx_14=float(adx_val),
            ema_21_slope=float(slope_val),
            min_sep_pct=float(sep_pct),
            chop_passed=True,
            chop_reason="",
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
        """Reset the previous-signal tracker."""
        self._prev_signal = Signal.HOLD
        self._trade_entered_for_signal = False
        logger.info("Strategy cross state reset - waiting for fresh cross")

    def reset_for_reversal(self):
        """Reset for reversal."""
        self._prev_signal = Signal.HOLD
        self._trade_entered_for_signal = False
        logger.info("Strategy reset for REVERSAL")

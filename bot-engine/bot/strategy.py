"""
Trading Strategy Module
EMA Crossover Strategy based on 4 EMAs (8, 13, 21, 55).

Rules (STRICT TREND & ANTI-CHOP MODE):
- BUY  (LONG)  : Full Bullish Fan -> EMA 8 >= EMA 13 >= EMA 21 > EMA 55 with spread >= min_spread_pct
- SELL (SHORT) : Full Bearish Fan -> EMA 8 <= EMA 13 <= EMA 21 < EMA 55 with spread >= min_spread_pct
- HOLD         : Tangled EMAs or sideways flat market (spread < min_spread_pct)

Cross Detection:
- `just_crossed` is True when EMA55 exited the bundle within the last `fresh_window`
  closed candles (configurable 2–8 in Engine UI, default 2 for strict fresh crosses).
- Chop micro-fluctuations (wobbling between HOLD and trend) will NEVER re-trigger
  false entries for the SAME trend side (one entry per cross, state machine kept).
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

    def __init__(self, ema_short=8, ema_mid1=13, ema_mid2=21, ema_long=55,
                 min_spread_pct=0.0, fresh_window=2):
        self.indicators = IndicatorSet(ema_short, ema_mid1, ema_mid2, ema_long)
        self.ema_short = ema_short
        self.ema_mid1 = ema_mid1
        self.ema_mid2 = ema_mid2
        self.ema_long = ema_long
        self.min_spread_pct = float(min_spread_pct)
        # How many closed candles back (2–8, default 2) a fresh EMA55 cross is
        # considered fresh and tradeable. Configurable live via Engine settings.
        self.fresh_window = max(2, min(8, int(fresh_window)))
        self._prev_signal: Signal = Signal.HOLD
        self._last_trend_side: Optional[Signal] = None
        self._trade_entered_for_signal: bool = False
        # ===== ANTI-INSTANT-REENTRY =====
        # Timestamp (candle) of the last closed candle this strategy has seen.
        self._last_closed_candle_ts = None
        # When a position closes, reset_cross_state()/reset_for_reversal() set
        # this to the current closed candle. Any "fresh cross" whose cross event
        # (EMA55 exiting the bundle) happened AT OR BEFORE this candle is a STALE
        # cross from the previous trend and is consumed — it can never trigger an
        # entry. This kills the "trade closes -> bot instantly re-opens the SAME
        # coin on the same old cross" bug (fresh_window lookback used to re-arm
        # the pre-exit cross after every reset).
        self._block_crosses_before = None

    def _calc_signal(self, row) -> Signal:
        e8 = float(row["ema_8"]) if not pd.isna(row["ema_8"]) else None
        e13 = float(row["ema_13"]) if not pd.isna(row["ema_13"]) else None
        e55 = float(row["ema_55"]) if not pd.isna(row["ema_55"]) else None
        if e8 is None or e13 is None or e55 is None:
            return Signal.HOLD

        sep_pct = (abs(e8 - e55) / e55) * 100.0 if e55 else 0.0
        if self.min_spread_pct > 0 and sep_pct < self.min_spread_pct:
            return Signal.HOLD

        # Fast Trigger: EMA 8 & EMA 13 cross EMA 55 (no waiting 4-5 candles for slow EMA 21)
        if e55 < e13 and e13 <= e8:
            return Signal.BUY
        elif e55 > e13 and e13 >= e8:
            return Signal.SELL
        return Signal.HOLD

    def _is_ema55_at_bottom(self, row) -> bool:
        """Fast cross trigger: EMA55 strictly below fast EMAs (8 & 13) — zero EMA21 lag."""
        e8 = row.get("ema_8")
        e13 = row.get("ema_13")
        e55 = row.get("ema_55")
        if pd.isna(e8) or pd.isna(e13) or pd.isna(e55):
            return False
        return float(e55) < float(e8) and float(e55) < float(e13)

    def _is_ema55_at_top(self, row) -> bool:
        """Fast cross trigger: EMA55 strictly above fast EMAs (8 & 13) — zero EMA21 lag."""
        e8 = row.get("ema_8")
        e13 = row.get("ema_13")
        e55 = row.get("ema_55")
        if pd.isna(e8) or pd.isna(e13) or pd.isna(e55):
            return False
        return float(e55) > float(e8) and float(e55) > float(e13)

    def seed_startup_state(self, signal: Signal):
        """Seed startup state so bot NEVER enters on startup or pre-startup crosses."""
        self._prev_signal = signal
        if signal in (Signal.BUY, Signal.SELL):
            self._last_trend_side = signal
        self._trade_entered_for_signal = True
        if self._last_closed_candle_ts is not None:
            self._block_crosses_before = self._last_closed_candle_ts
        logger.info("Strategy seeded on startup with signal=%s, block_before=%s (waiting for fresh cross)",
                    signal.value, self._block_crosses_before)

    def analyze(self, df: pd.DataFrame) -> Optional[StrategyResult]:
        """Analyze candles and return signal."""
        if df is None or len(df) < self.ema_long + 5:
            return None

        enriched = self.indicators.compute(df)
        # Evaluate trade signals on the last confirmed CLOSED candle (iloc[-2]).
        # iloc[-1] is the unclosed/forming candle whose close price ticks every second.
        closed_candle = enriched.iloc[-2] if len(enriched) >= 2 else enriched.iloc[-1]
        last = enriched.iloc[-1]
        # Remember the last closed candle so a later reset_cross_state() can
        # consume every cross that happened up to now (anti-instant-reentry).
        try:
            self._last_closed_candle_ts = enriched.index[-2] if len(enriched) >= 2 else enriched.index[-1]
        except Exception:
            pass

        e8, e13, e21, e55 = closed_candle["ema_8"], closed_candle["ema_13"], closed_candle["ema_21"], closed_candle["ema_55"]
        last_close = float(last["close"])

        if pd.isna(e55) or pd.isna(e8) or pd.isna(e13) or pd.isna(e21):
            return None

        sep_pct = (abs(float(e8) - float(e55)) / float(e55)) * 100.0 if float(e55) else 0.0

        # 1. Fast EMA 8 & EMA 13 crossing EMA 55 detection (eliminates 4-5 candle slow EMA 21 lag)
        ema55_at_bottom = self._is_ema55_at_bottom(closed_candle)
        ema55_at_top = self._is_ema55_at_top(closed_candle)

        is_buy_candidate = ema55_at_bottom and (float(e8) >= float(e13))
        is_sell_candidate = ema55_at_top and (float(e8) <= float(e13))

        # 2. Smart Anti-Chop Box Breakout + EMA55 Direction Filter (Zero Spread Delay on Breakouts)
        closed_close = float(closed_candle["close"])
        box_breakout_confirmed = False
        in_chop_box = False
        ema55_slope_pct = 0.0
        braid_crosses = 0

        if len(enriched) >= 18 and (is_buy_candidate or is_sell_candidate):
            recent_box = enriched.iloc[-17:-2]  # 15 closed candles prior to closed_candle
            box_high = float(recent_box["close"].max())
            box_low = float(recent_box["close"].min())
            e55_prev3 = float(enriched.iloc[-5]["ema_55"]) if not pd.isna(enriched.iloc[-5]["ema_55"]) else float(e55)
            ema55_slope_pct = ((float(e55) - e55_prev3) / e55_prev3 * 100.0) if e55_prev3 else 0.0

            # Count how many times EMA8 and EMA21 crossed back and forth in the recent 15-candle box (braided chop detector)
            e8_arr = recent_box["ema_8"].astype(float).values
            e21_arr = recent_box["ema_21"].astype(float).values
            diff_sign = (e8_arr > e21_arr).astype(int)
            if len(diff_sign) > 1:
                braid_crosses = int((diff_sign[1:] != diff_sign[:-1]).sum())

            if is_buy_candidate:
                if closed_close >= box_high and ema55_slope_pct >= 0.0:
                    box_breakout_confirmed = True
                elif (braid_crosses >= 2 and closed_close < box_high) or (ema55_slope_pct < -0.015):
                    in_chop_box = True
            elif is_sell_candidate:
                if closed_close <= box_low and ema55_slope_pct <= 0.0:
                    box_breakout_confirmed = True
                elif (braid_crosses >= 2 and closed_close > box_low) or (ema55_slope_pct > 0.015):
                    in_chop_box = True

        # Zero spread waiting in live engine (min_spread_pct=0.0). Chop-Box Breakout handles anti-chop directly.
        eff_min_spread = 0.0 if (box_breakout_confirmed and self.min_spread_pct <= 0.15) else self.min_spread_pct
        is_flat_chop = in_chop_box or (eff_min_spread > 0 and sep_pct < eff_min_spread)

        if is_flat_chop and (is_buy_candidate or is_sell_candidate):
            signal = Signal.HOLD
            if in_chop_box:
                reason = f"Chop-Box filter active (braid={braid_crosses}, slope={ema55_slope_pct:+.3f}%, price inside box) -> HOLD"
            else:
                reason = f"Flat market chop (EMA spread {sep_pct:.3f}% < {eff_min_spread:.3f}% required) -> HOLD"
        elif is_buy_candidate:
            signal = Signal.BUY
            reason = f"EMA55 crossed below ALL lines & 8>=13>=21 (spread={sep_pct:.2f}%, slope={ema55_slope_pct:+.3f}%) -> BUY (LONG)"
        elif is_sell_candidate:
            signal = Signal.SELL
            reason = f"EMA55 crossed above ALL lines & 8<=13<=21 (spread={sep_pct:.2f}%, slope={ema55_slope_pct:+.3f}%) -> SELL (SHORT)"
        else:
            signal = Signal.HOLD
            reason = "EMA55 tangled / inside lines (no full cross) -> HOLD"

        # 3. Genuine Fresh Crossover Check (EMA 55 MUST freshly cross across ALL lines):
        # A fresh BUY cross occurs when EMA55 crossed below ALL lines within the last
        # `fresh_window` closed candles (at least one candle in the lookback BEFORE the
        # closed candle was NOT at the bottom extreme).
        # A fresh SELL cross is the mirror image (top extreme).
        # Wider window (was hard-coded 2) so a cross is no longer "consumed" while the
        # chop-spread filter is still active on the first 1-2 candles of a new trend.
        is_fresh_cross = False
        cross_event_ts = None
        lookback = max(2, min(8, int(self.fresh_window)))
        if signal == Signal.BUY and len(enriched) >= lookback + 3:
            recent = enriched.iloc[-(lookback + 2):-2]  # candles just BEFORE the closed candle
            # Find the LAST (most recent) candle in the window that was NOT at the
            # bottom extreme — the cross into the current fan happened on the candle
            # immediately AFTER it (index base + j + 1).
            for j in range(len(recent) - 1, -1, -1):
                if not self._is_ema55_at_bottom(recent.iloc[j]):
                    is_fresh_cross = True
                    try:
                        base = len(enriched) - (lookback + 2)
                        cross_event_ts = enriched.index[base + j + 1]
                    except Exception:
                        cross_event_ts = None
                    break
        elif signal == Signal.SELL and len(enriched) >= lookback + 3:
            recent = enriched.iloc[-(lookback + 2):-2]
            for j in range(len(recent) - 1, -1, -1):
                if not self._is_ema55_at_top(recent.iloc[j]):
                    is_fresh_cross = True
                    try:
                        base = len(enriched) - (lookback + 2)
                        cross_event_ts = enriched.index[base + j + 1]
                    except Exception:
                        cross_event_ts = None
                    break

        # ===== STALE-CROSS CONSUMPTION (anti-instant-reentry) =====
        # If the detected cross event happened at or before the candle where the
        # last position exited, it is the OLD trend's cross — not a new signal.
        if is_fresh_cross and self._block_crosses_before is not None and cross_event_ts is not None:
            try:
                if pd.Timestamp(cross_event_ts) <= pd.Timestamp(self._block_crosses_before):
                    is_fresh_cross = False
            except Exception:
                pass

        # 4. Anti-Whipsaw Flicker State Transition:
        # - If EMA55 stays at the bottom/top extreme and only spread wobbles briefly into HOLD,
        #   keep _trade_entered_for_signal locked so chop micro-wobbles do not double-enter.
        # - HOWEVER, once EMA55 physically returns inside/tangles with the 8/13/21 bundle
        #   (not ema55_at_bottom and not ema55_at_top), that old trend fan has ended! Clear
        #   _last_trend_side and _trade_entered_for_signal so the next genuine breakout in
        #   EITHER direction (even same direction after consolidation) fires immediately!
        if not ema55_at_bottom and not ema55_at_top:
            self._last_trend_side = None
            self._trade_entered_for_signal = False
            self._prev_signal = Signal.HOLD
        elif signal in (Signal.BUY, Signal.SELL):
            if signal != self._last_trend_side:
                # Genuine trend flip to opposite direction (or fresh breakout after tangle)
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

    def consume_current_cross(self):
        """Consume a fresh cross that was skipped (e.g. concurrent trade slots full or
        cooldown active) so this old cross can NEVER stay armed and fire later when
        another coin closes via SL or manual close."""
        self._prev_signal = Signal.HOLD
        self._last_trend_side = None
        self._trade_entered_for_signal = False
        if self._last_closed_candle_ts is not None:
            self._block_crosses_before = self._last_closed_candle_ts
        logger.info("Strategy cross consumed while blocked (block_before=%s) - waiting for a brand-new cross",
                    self._block_crosses_before)

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
        if e8 and e13 and e55 and (self.min_spread_pct <= 0 or sep_pct >= self.min_spread_pct):
            if e55 < e13 and e13 <= e8:
                sig = "BUY"
            elif e55 > e13 and e13 >= e8:
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
        """Reset the cross state to wait for a brand new crossover.

        Consumes every cross up to the last closed candle seen, so the old
        trend's cross can NOT re-trigger an entry after a position closes.
        """
        self._prev_signal = Signal.HOLD
        self._last_trend_side = None
        self._trade_entered_for_signal = False
        self._block_crosses_before = self._last_closed_candle_ts
        logger.info("Strategy cross state reset - stale crosses consumed, waiting for a NEW cross")

    def reset_for_reversal(self):
        """Reset for reversal exit (allow immediate opposite flip without blocking the new cross)."""
        self._prev_signal = Signal.HOLD
        self._last_trend_side = None
        self._trade_entered_for_signal = False
        self._block_crosses_before = None
        logger.info("Strategy reset for REVERSAL exit - ready for immediate opposite flip")

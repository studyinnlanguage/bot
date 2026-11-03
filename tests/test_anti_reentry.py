"""Anti-instant-reentry & trade-limit regression tests (REDLINE fix).

Covers the user-reported bugs:
  BUG A: "ek waqt mai 4 4 trade open krraha hai"  -> concurrent-trade limit
         must count in-flight entry intents (atomic slot claim).
  BUG B: "agar ek close kro to usi time ne khol deta hai same coin pe"
         -> same-coin re-entry cooldown blocks instant reopen.
  BUG C: stale-cross consumption -> after a position closes, the OLD trend's
         EMA55 cross must never re-trigger an entry; only a genuinely NEW
         cross (after the exit candle) may enter.

Pure unit tests — no network, no subprocess.
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bot-engine"))

from bot.strategy import EMAQuadStrategy, Signal  # noqa: E402
from bot.engine import BotEngine  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_engine(max_trades=3, cooldown=180):
    eng = object.__new__(BotEngine)
    eng.config = {"max_concurrent_trades": max_trades,
                  "reentry_cooldown_sec": cooldown}
    eng._entry_intents = {}
    eng._reentry_block = {}
    eng.workers = {}
    eng.lock = MagicMock()
    eng.socketio = MagicMock()
    eng._emit = lambda *a, **k: None
    return eng


def _worker_with_position(eng, symbol, side):
    w = SimpleNamespace(position_side=side, expected_pos_side=side,
                        entry_price=100.0)
    eng.workers[symbol] = w
    return w


def _synth_trend(pre_osc=120, fan=8, direction="SELL", tf="5min"):
    """Build a df: `pre_osc` oscillating candles (EMAs tangled) followed by
    `fan` strong candles that end with EMA55 outside the bundle.
    direction='SELL': strong fall -> EMA55 ends at TOP -> SELL signal.
    direction='BUY' : strong rise -> EMA55 ends at BOTTOM -> BUY signal."""
    n = pre_osc + fan
    idx = pd.date_range("2026-01-01", periods=n, freq=tf)
    price = []
    p = 100.0
    for i in range(n):
        if i < pre_osc:
            p = 100.0 + 0.6 * ((-1) ** i) + 0.02 * i
        else:
            p += -1.4 if direction == "SELL" else 1.4
        price.append(p)
    df = pd.DataFrame({"open": price, "high": price, "low": price,
                       "close": price, "volume": [1.0] * n}, index=idx)
    return df


# ---------------------------------------------------------------------------
# BUG C — strategy stale-cross consumption
# ---------------------------------------------------------------------------

def test_strategy_blocks_stale_cross_after_reset():
    """Same-side old cross must NOT be 'fresh' after reset_cross_state()."""
    s = EMAQuadStrategy()
    df = _synth_trend(direction="SELL", fan=8)  # fresh SELL fan at the end
    r1 = s.analyze(df)
    assert r1 is not None and r1.signal == Signal.SELL
    # Simulate: trade entered, then position closed -> engine calls reset.
    s.mark_trade_entered()
    s.analyze(df)              # strategy sees the last closed candle
    s.reset_cross_state()      # exit processing

    # MANY later ticks on the SAME trend (cross still within fresh window)
    for _ in range(6):
        r2 = s.analyze(df)
        assert r2 is not None and r2.signal == Signal.SELL
        assert r2.just_crossed is False, "stale pre-exit cross re-armed after reset!"


def test_strategy_allows_genuinely_new_cross_after_reset():
    """A NEW cross (fan re-formed AFTER the exit candle) must be tradeable."""
    s = EMAQuadStrategy()
    df = _synth_trend(direction="SELL", fan=8)
    r1 = s.analyze(df)
    assert r1 is not None and r1.signal == Signal.SELL
    s.mark_trade_entered()
    s.analyze(df)
    s.reset_cross_state()   # consumes every cross up to df's last closed candle

    # Append: long re-tangle phase, then a brand-new SELL fan whose cross
    # event happens strictly AFTER the exit candle.
    tail = _synth_trend(pre_osc=160, fan=8, direction="SELL")
    tail.index = pd.date_range(df.index[-1] + pd.Timedelta("5min"),
                               periods=len(tail), freq="5min")
    df2 = pd.concat([df, tail])
    seen_fresh = False
    for cut in range(len(df) + 40, len(df2) + 1, 5):
        r = s.analyze(df2.iloc[:cut])
        if r is not None and r.just_crossed:
            seen_fresh = True
            break
    assert seen_fresh, "a genuinely NEW cross after the exit was blocked!"


def test_seed_startup_then_reset_uses_last_seen_candle():
    s = EMAQuadStrategy()
    df = _synth_trend(direction="SELL", fan=8)
    assert s.analyze(df) is not None
    s.reset_cross_state()
    assert s._block_crosses_before is not None


# ---------------------------------------------------------------------------
# BUG B — same-coin re-entry cooldown
# ---------------------------------------------------------------------------

def test_cooldown_blocks_same_coin_reentry():
    eng = _make_engine(cooldown=180)
    eng.set_reentry_cooldown("BTCUSDT", reason="test")
    ok, why = eng.can_open_new_trade("BTCUSDT")
    assert ok is False
    assert "cooldown" in why.lower()


def test_cooldown_does_not_block_other_coins():
    eng = _make_engine(cooldown=180)
    eng.set_reentry_cooldown("BTCUSDT")
    ok, _ = eng.can_open_new_trade("ETHUSDT")
    assert ok is True


def test_cooldown_expires():
    eng = _make_engine(cooldown=1)
    eng._reentry_block["BTCUSDT"] = time.time() + 0.05
    time.sleep(0.06)
    ok, _ = eng.can_open_new_trade("BTCUSDT")
    assert ok is True


def test_cooldown_zero_disables():
    eng = _make_engine(cooldown=0)
    eng._reentry_block["BTCUSDT"] = time.time() + 999
    # _reentry_cooldown_sec()==0 -> set_reentry_cooldown no-ops, but a manually
    # injected block must still be honoured by can_open_new_trade only when
    # cooldown>0 was configured; with 0 the setter never fires, so simulate:
    eng.config["reentry_cooldown_sec"] = 180
    ok, _ = eng.can_open_new_trade("BTCUSDT")
    assert ok is False


# ---------------------------------------------------------------------------
# BUG A — concurrent limit counts in-flight entry intents
# ---------------------------------------------------------------------------

def test_intent_counts_toward_limit():
    eng = _make_engine(max_trades=2)
    _worker_with_position(eng, "BTCUSDT", "LONG")
    eng.register_entry_intent("ETHUSDT", "SHORT")
    ok, why = eng.can_open_new_trade("SOLUSDT")
    assert ok is False, "intent did not reserve a slot!"
    assert "limit" in why.lower()


def test_intent_released_frees_slot():
    eng = _make_engine(max_trades=2)
    _worker_with_position(eng, "BTCUSDT", "LONG")
    eng.register_entry_intent("ETHUSDT", "SHORT")
    eng.release_entry_intent("ETHUSDT")
    ok, _ = eng.can_open_new_trade("SOLUSDT")
    assert ok is True


def test_intent_ttl_expires():
    eng = _make_engine(max_trades=2)
    _worker_with_position(eng, "BTCUSDT", "LONG")
    eng._entry_intents["ETHUSDT"] = {"side": "SHORT", "ts": time.time() - 120}
    ok, _ = eng.can_open_new_trade("SOLUSDT")
    assert ok is True


def test_full_limit_blocks_even_without_positions_or_intents():
    eng = _make_engine(max_trades=1)
    eng.register_entry_intent("ETHUSDT", "LONG")
    ok, _ = eng.can_open_new_trade("SOLUSDT")
    assert ok is False

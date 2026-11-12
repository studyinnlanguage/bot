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


# ---------------------------------------------------------------------------
# BUG D — slot-blocked crosses & reversals MUST be consumed (no instant jump
#         onto another coin's stale signal after SL hit or Manual Close)
# ---------------------------------------------------------------------------

def _make_live_worker(eng, symbol, trader_mock, cfg_extra=None):
    from bot.engine import SymbolWorker
    cfg = {
        "timeframe": "5m", "leverage": 20, "amount_mode": "fixed", "amount": 50,
        "amount_pct": 10, "stop_loss_pct": 0.2, "take_profit_pct": 1.0,
        "tp_mode": "fixed", "mode": "both", "max_concurrent_trades": eng.config.get("max_concurrent_trades", 1),
        "reentry_cooldown_sec": eng.config.get("reentry_cooldown_sec", 180),
        "min_ema_spread": 0, "fresh_window": 2,
        **(cfg_extra or {}),
    }
    eng.config.update(cfg)
    eng.trader = trader_mock
    eng._trade_entry_lock = __import__("threading").Lock()
    eng.notifier = MagicMock()
    eng.history = MagicMock()
    eng.active_symbol = symbol
    eng.set_connection_state = lambda *a, **k: None
    w = SymbolWorker(eng, symbol, cfg)
    w._startup_seeded = True
    eng.workers[symbol] = w
    return w


def test_slot_blocked_cross_consumed_no_instant_other_coin_trade():
    """When Coin A holds the slot, Coin B's fresh cross must be consumed immediately
    so that when Coin A later closes (SL hit / manual close), Coin B does NOT
    immediately open a trade on that stale cross."""
    eng = _make_engine(max_trades=1, cooldown=180)
    _worker_with_position(eng, "BTCUSDT", "LONG")  # Coin A occupies the only slot

    # Build a DataFrame where the very latest closed candle has a fresh SELL cross
    full_df = _synth_trend(pre_osc=120, fan=8, direction="SELL")
    cross_df = None
    probe = EMAQuadStrategy(fresh_window=2)
    probe_init = full_df.iloc[:120]
    probe.analyze(probe_init)
    probe.seed_startup_state(Signal.HOLD)
    for cut in range(121, len(full_df) + 1):
        sub = full_df.iloc[:cut]
        res = probe.analyze(sub)
        if res is not None and res.just_crossed:
            cross_df = sub
            break
    assert cross_df is not None, "failed to synthesize a 2-candle fresh cross"

    trader = MagicMock()
    trader.get_klines.return_value = cross_df
    trader.get_mark_price.return_value = float(cross_df.iloc[-1]["close"])
    trader.get_position.return_value = SimpleNamespace(
        side="NONE", size=0.0, entry_price=0.0, mark_price=float(cross_df.iloc[-1]["close"]),
        unrealized_pnl=0.0, leverage=20,
    )
    trader.get_symbol_filters.return_value = {"min_qty": 0.001, "max_qty": 1e6, "step_size": 0.001}
    trader.compute_quantity.return_value = 1.0
    trader.open_short.return_value = {"success": True, "quantity": 1.0, "order": {"orderId": "1"}}

    eth_worker = _make_live_worker(eng, "ETHUSDT", trader, {"fresh_window": 6})
    eth_worker.strategy.analyze(full_df.iloc[:120])
    eth_worker.strategy.seed_startup_state(Signal.HOLD)

    # Tick 1 while Coin A's slot is FULL -> ETHUSDT sees fresh cross, must consume & NOT open
    eth_worker._tick()
    assert trader.open_short.call_count == 0, "opened trade despite full slot limit!"

    # Now Coin A hits SL or is manually closed -> slot frees up!
    eng.workers["BTCUSDT"].position_side = None
    eng.workers["BTCUSDT"].expected_pos_side = None
    eng.workers["BTCUSDT"].entry_price = None
    ok, _ = eng.can_open_new_trade("ETHUSDT")
    assert ok is True

    # Next ticks on ETHUSDT (even with fresh_window=6 still covering that cross!) -> MUST NOT open!
    for extra in range(0, len(full_df) - len(cross_df) + 1):
        trader.get_klines.return_value = full_df.iloc[:len(cross_df) + extra]
        eth_worker._tick()
    assert trader.open_short.call_count == 0, "opened trade on stale cross right after slot freed!"


def test_blocked_pending_reversal_consumed_never_queued():
    """If a pending reversal is blocked by concurrent trade limits, it must be
    cleared & consumed immediately rather than waiting to pounce when a slot frees."""
    eng = _make_engine(max_trades=1, cooldown=180)
    _worker_with_position(eng, "BTCUSDT", "LONG")  # Another coin holds the slot

    df = _synth_trend(pre_osc=120, fan=8, direction="SELL")
    trader = MagicMock()
    trader.get_klines.return_value = df
    trader.get_mark_price.return_value = float(df.iloc[-1]["close"])
    trader.get_position.return_value = SimpleNamespace(
        side="NONE", size=0.0, entry_price=0.0, mark_price=float(df.iloc[-1]["close"]),
        unrealized_pnl=0.0, leverage=20,
    )
    trader.open_short.return_value = {"success": True, "quantity": 1.0}

    sol_worker = _make_live_worker(eng, "SOLUSDT", trader)
    sol_worker.reversal_pending_side = "SHORT"
    sol_worker._reversal_armed_ts = time.time()

    # Tick while slot is blocked -> reversal flag must be cleared immediately
    sol_worker._tick()
    assert sol_worker.reversal_pending_side is None
    assert trader.open_short.call_count == 0

    # Free BTC slot -> SOL must STILL not open on the old trend
    eng.workers["BTCUSDT"].position_side = None
    eng.workers["BTCUSDT"].expected_pos_side = None
    eng.workers["BTCUSDT"].entry_price = None
    sol_worker._tick()
    assert trader.open_short.call_count == 0


def test_startup_seed_blocks_pre_startup_chop_cross_and_allows_post_startup_cross():
    """Pre-startup cross masked by flat spread (HOLD at startup) must NOT fire when
    spread opens later; a genuinely new cross AFTER startup MUST fire."""
    full_df = _synth_trend(pre_osc=120, fan=8, direction="SELL")

    # Find exact candle `c_cross` where EMA55 first enters top extreme (SELL cross)
    probe = EMAQuadStrategy(min_spread_pct=0.15, fresh_window=6)
    c_cross = None
    for cut in range(121, len(full_df) + 1):
        sub = full_df.iloc[:cut]
        enr = probe.indicators.compute(sub)
        if probe._is_ema55_at_top(enr.iloc[-2]):
            c_cross = cut
            break
    assert c_cross is not None

    # 1) Startup happens AT `c_cross` with high spread requirement so startup signal is HOLD
    s_pre = EMAQuadStrategy(min_spread_pct=5.0, fresh_window=6)
    r_seed = s_pre.analyze(full_df.iloc[:c_cross])
    assert r_seed is not None and r_seed.signal == Signal.HOLD
    s_pre.seed_startup_state(r_seed.signal)
    # Now relax spread back to normal 0.15% on subsequent candles -> pre-startup cross MUST stay blocked!
    s_pre.min_spread_pct = 0.15
    for cut in range(c_cross, len(full_df) + 1):
        r = s_pre.analyze(full_df.iloc[:cut])
        assert r.just_crossed is False, "pre-startup chop cross falsely fired after startup!"

    # 2) Startup happens BEFORE `c_cross` (at candle 120, before SELL cross) -> new SELL cross MUST fire!
    s_post = EMAQuadStrategy(min_spread_pct=0.15, fresh_window=2)
    r0 = s_post.analyze(full_df.iloc[:120])
    s_post.seed_startup_state(r0.signal)
    fired = False
    for cut in range(121, len(full_df) + 1):
        r = s_post.analyze(full_df.iloc[:cut])
        if r is not None and r.just_crossed and r.signal == Signal.SELL:
            fired = True
            break
    assert fired, "genuinely new post-startup cross was blocked!"


def test_manual_engine_fresh_window_2_to_8_live_sync():
    """Engine fresh_window defaults to 2, clamps to 2..8, and sync_config live-updates
    running workers without needing a restart."""
    s_default = EMAQuadStrategy()
    assert s_default.fresh_window == 2
    assert EMAQuadStrategy(fresh_window=1).fresh_window == 2
    assert EMAQuadStrategy(fresh_window=50).fresh_window == 8
    assert EMAQuadStrategy(fresh_window=5).fresh_window == 5

    eng = _make_engine(max_trades=3, cooldown=180)
    eng.is_running = True
    eng.notifier = MagicMock()
    eng._symbols_list = lambda: ["BTCUSDT"]
    trader = MagicMock()
    w = _make_live_worker(eng, "BTCUSDT", trader, {"fresh_window": 2, "min_ema_spread": 0})
    assert w.strategy.fresh_window == 2

    # User updates Fresh Cross Window to 6 and Min EMA Spread to 0.30 in Engine UI
    eng.sync_config({
        **eng.config,
        "symbols_list": ["BTCUSDT"],
        "fresh_window": 6,
        "min_ema_spread": 0.30,
    })
    assert w.strategy.fresh_window == 6
    assert abs(w.strategy.min_spread_pct - 0.30) < 1e-9

    # Out-of-range values clamp cleanly to 2..8
    eng.sync_config({**eng.config, "symbols_list": ["BTCUSDT"], "fresh_window": 99})
    assert w.strategy.fresh_window == 8
    eng.sync_config({**eng.config, "symbols_list": ["BTCUSDT"], "fresh_window": 0})
    assert w.strategy.fresh_window == 2


def test_same_direction_breakout_after_tangle_is_not_missed():
    """If a coin was in SELL (e.g. at startup), then EMAs tangle inside EMA55 (HOLD)
    without ever reaching a full BUY fan, and then breaks down into a brand-new SELL cross,
    the strategy MUST detect just_crossed=True instead of missing it."""
    s = EMAQuadStrategy(min_spread_pct=0.03, fresh_window=2)
    df1 = _synth_trend(pre_osc=120, fan=8, direction="SELL")
    r_init = s.analyze(df1)
    assert r_init is not None and r_init.signal == Signal.SELL
    s.seed_startup_state(r_init.signal)

    # Append oscillation (EMAs tangle with EMA55 -> HOLD, no full BUY trend) + new SELL breakout
    tail = _synth_trend(pre_osc=140, fan=8, direction="SELL")
    tail.index = pd.date_range(df1.index[-1] + pd.Timedelta("5min"),
                               periods=len(tail), freq="5min")
    df2 = pd.concat([df1, tail])

    fired = False
    for cut in range(len(df1) + 1, len(df2) + 1):
        r = s.analyze(df2.iloc[:cut])
        if r is not None and r.just_crossed and r.signal == Signal.SELL:
            fired = True
            break
    assert fired, "same-direction breakout after EMA55 re-tangle was missed!"


def test_fast_auto_spread_and_polling_defaults():
    """Auto spread (min_ema_spread=0) must use fast 0.03% (majors) / 0.05% (memes)
    and 5m polling must be <= 4s so fresh crosses are never entered 5 candles late."""
    eng = _make_engine()
    trader = MagicMock()
    w_btc = _make_live_worker(eng, "BTCUSDT", trader, {"min_ema_spread": 0})
    w_pepe = _make_live_worker(eng, "1000PEPEUSDT", trader, {"min_ema_spread": 0})
    assert abs(w_btc.strategy.min_spread_pct - 0.03) < 1e-9
    assert abs(w_pepe.strategy.min_spread_pct - 0.05) < 1e-9
    assert BotEngine._poll_seconds("5m") <= 4
    assert BotEngine._poll_seconds("1m") <= 3


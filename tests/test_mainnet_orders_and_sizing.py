"""Regression tests for Binance Mainnet Algo SL/TP (-4120), Hedge Mode (-4061),
and small-balance ($14 / 10% / $1 Fixed) minimum-notional & quantity sizing.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent / "bot-engine"
if str(ENGINE_DIR) not in sys.path:
    # Append (never prepend at 0) so `import app` resolves repo SaaS `app.py`, not `bot-engine/app.py`.
    sys.path.append(str(ENGINE_DIR))

from bot.trader import BinanceFuturesTrader
from bot.weex_trader import WEEXFuturesTrader
from bot.primexbt_trader import PrimeXBTTrader
from bot.engine import BotEngine, SymbolWorker


def _make_binance_trader(monkeypatch, *, hedge=False, testnet=False):
    monkeypatch.setattr(BinanceFuturesTrader, "_connect", lambda self: None)
    trader = BinanceFuturesTrader("A" * 64, "B" * 64, testnet=testnet)
    mock_client = MagicMock()
    mock_client.get_position_mode.return_value = {"dualSidePosition": hedge}
    trader.client = mock_client
    trader._exchange_info_cache = {
        "BTCUSDT": {"step_size": 0.001, "min_qty": 0.001, "max_qty": 100.0, "tick_size": 0.1, "min_notional": 50.0},
        "ETHUSDT": {"step_size": 0.001, "min_qty": 0.001, "max_qty": 1000.0, "tick_size": 0.01, "min_notional": 20.0},
        "BNBUSDT": {"step_size": 0.01, "min_qty": 0.01, "max_qty": 1000.0, "tick_size": 0.01, "min_notional": 5.0},
        "SOLUSDT": {"step_size": 0.01, "min_qty": 0.01, "max_qty": 10000.0, "tick_size": 0.01, "min_notional": 5.0},
        "ADAUSDT": {"step_size": 1.0, "min_qty": 1.0, "max_qty": 1000000.0, "tick_size": 0.0001, "min_notional": 5.0},
    }
    return trader, mock_client


class TestBinanceMainnetExecution:
    def test_exchange_info_parses_min_notional(self, monkeypatch):
        trader, mock_client = _make_binance_trader(monkeypatch, testnet=False)
        trader._exchange_info_cache.clear()
        mock_client.exchange_info.return_value = {
            "symbols": [
                {
                    "symbol": "ETHUSDT",
                    "filters": [
                        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "10000"},
                        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                        {"filterType": "MIN_NOTIONAL", "notional": "20"},
                    ],
                }
            ]
        }
        f = trader.get_symbol_filters("ETHUSDT")
        assert f["min_notional"] == 20.0
        assert f["min_qty"] == 0.001
        assert f["step_size"] == 0.001

    def test_pure_market_open_no_sl_tp_and_cancel_open_orders(self, monkeypatch):
        trader, mock_client = _make_binance_trader(monkeypatch, hedge=False, testnet=False)
        mock_client.new_order.return_value = {"orderId": 1001, "symbol": "SOLUSDT"}

        res = trader.open_long("SOLUSDT", 0.25)
        assert res["success"] is True
        assert "sl_price" not in res
        assert "tp_price" not in res
        assert not hasattr(trader, "place_stop_loss")
        assert not hasattr(trader, "place_take_profit")
        mock_client.new_order.assert_called_once()
        sent = mock_client.new_order.call_args.kwargs
        assert sent["symbol"] == "SOLUSDT"
        assert sent["side"] == "BUY"
        assert sent["type"] == "MARKET"
        assert sent["quantity"] == 0.25

        cancel = trader.cancel_open_orders("SOLUSDT")
        assert cancel["success"] is True
        mock_client.cancel_open_orders.assert_called_once_with(symbol="SOLUSDT")

    def test_hedge_mode_and_4061_auto_recovery(self, monkeypatch):
        trader, mock_client = _make_binance_trader(monkeypatch, hedge=True, testnet=False)
        trader._is_hedge_mode = False
        sent_market = []

        def fake_new_order(**kwargs):
            sent_market.append(dict(kwargs))
            if kwargs.get("positionSide") != "SHORT":
                raise RuntimeError("(-4061, \"Order's position side does not match user's setting.\")")
            return {"orderId": 2002, "positionSide": "SHORT"}

        mock_client.new_order.side_effect = fake_new_order

        res = trader.open_short("SOLUSDT", 0.2)
        assert res["success"] is True
        assert len(sent_market) == 2
        assert sent_market[1]["positionSide"] == "SHORT"
        assert "reduceOnly" not in sent_market[1]

    def test_2027_downscaled_qty_succeeds_cleanly(self, monkeypatch):
        trader, mock_client = _make_binance_trader(monkeypatch, hedge=False, testnet=False)

        def fake_new_order(**kwargs):
            if float(kwargs["quantity"]) > 0.6:
                raise RuntimeError("(-2027, 'Exceeded the maximum allowable position at current leverage.')")
            return {"orderId": 3003}

        mock_client.new_order.side_effect = fake_new_order

        res = trader.open_long("SOLUSDT", 1.0)
        assert res["success"] is True
        assert res["quantity"] == 0.5

    def test_close_small_position_under_min_notional_keeps_reduce_only(self, monkeypatch):
        from bot.trader import Position
        trader, mock_client = _make_binance_trader(monkeypatch, hedge=False, testnet=True)
        trader._use_algo_orders = True

        # ETHUSDT 0.008 ETH (~$14.52 < $20 MIN_NOTIONAL): Binance rejects non-reduceOnly with -4164.
        monkeypatch.setattr(
            trader,
            "get_position",
            lambda sym: Position("ETHUSDT", "LONG", 0.008, 1819.99, 1815.56, -0.04, 50),
        )
        cancel_count = {"n": 0}
        monkeypatch.setattr(trader, "cancel_open_orders", lambda sym: (cancel_count.__setitem__("n", cancel_count["n"] + 1) or {"success": True}))

        seen_orders = []

        def fake_new_order(**kwargs):
            seen_orders.append(dict(kwargs))
            # First close hits -2022 before second cancel settles; retry MUST still pass reduceOnly='true'
            if kwargs.get("reduceOnly") != "true":
                raise RuntimeError("(-4164, \"Order's notional must be no smaller than 20 (unless you choose reduce only)\")")
            if len(seen_orders) == 1:
                raise RuntimeError("(-2022, 'ReduceOnly Order is rejected.')")
            return {"orderId": 4004}

        mock_client.new_order.side_effect = fake_new_order
        res = trader.close_position("ETHUSDT")
        assert res["success"] is True
        assert cancel_count["n"] == 2
        assert len(seen_orders) == 2
        assert seen_orders[1].get("reduceOnly") == "true"


class TestSmallBalanceAndExchangeFilters:
    def _make_worker(self, symbol, cfg, *, balance=14.0, filters=None, max_notional=0.0):
        engine = BotEngine.__new__(BotEngine)
        engine.trader = MagicMock()
        engine.trader.get_balance.return_value = balance
        engine.trader.get_max_notional.return_value = max_notional
        engine.trader.get_symbol_filters.return_value = filters or {
            "step_size": 0.01, "min_qty": 0.01, "max_qty": 10000.0, "tick_size": 0.01, "min_notional": 5.0
        }
        engine.trader._round_to_step = BinanceFuturesTrader._round_to_step
        engine.trader._ceil_to_step = BinanceFuturesTrader._ceil_to_step
        engine.trader.compute_quantity = lambda notional, price, lev, qty_step=0.001: BinanceFuturesTrader.compute_quantity(
            engine.trader, notional, price, lev, qty_step=qty_step
        )
        worker = SymbolWorker.__new__(SymbolWorker)
        worker.engine = engine
        worker.symbol = symbol
        worker.config = cfg
        worker._last_size_reason = None
        return worker

    def test_14_dollar_10pct_and_1_dollar_fixed_trade_safely(self):
        # 1. $14 wallet + 10% ($1.40) @ 10x on SOL ($71.06) -> $14 notional -> 0.19 SOL executes cleanly
        w_sol = self._make_worker(
            "SOLUSDT",
            {"amount_mode": "percent", "amount_pct": 10, "leverage": 10},
            balance=14.0,
            filters={"step_size": 0.01, "min_qty": 0.01, "max_qty": 1000.0, "min_notional": 5.0},
        )
        assert w_sol._compute_trade_size(71.06, 10) == 0.19

        # 2. $14 wallet + Fixed $1 @ 5x ($5.00 notional) where floor 5.0/71.06=0.07 ($4.97 < $5)
        #    Must bump 1 step to 0.08 ($5.68, $1.14 margin) instead of failing Binance -4164!
        w_sol_fix = self._make_worker(
            "SOLUSDT",
            {"amount_mode": "fixed", "amount": 1, "leverage": 5},
            balance=14.0,
            filters={"step_size": 0.01, "min_qty": 0.01, "max_qty": 1000.0, "min_notional": 5.0},
        )
        assert w_sol_fix._compute_trade_size(71.06, 5) == 0.08

        # 3. $14 wallet + Fixed $1 @ 5x on BNB ($589.49, min_qty=0.01 = $5.89 = $1.18 margin <= $1.75 safe cap)
        w_bnb = self._make_worker(
            "BNBUSDT",
            {"amount_mode": "fixed", "amount": 1, "leverage": 5},
            balance=14.0,
            filters={"step_size": 0.01, "min_qty": 0.01, "max_qty": 1000.0, "min_notional": 5.0},
        )
        assert w_bnb._compute_trade_size(589.49, 5) == 0.01

        # 4. $14 wallet + Fixed $1 @ 10x ($10 notional) on BTC ($64,351, min $64.35 = $6.44 margin = 46% of wallet)
        #    Must NOT silently risk $6.44 on a $1 fixed setting; must return 0.0 with explicit reason!
        w_btc = self._make_worker(
            "BTCUSDT",
            {"amount_mode": "fixed", "amount": 1, "leverage": 10},
            balance=14.0,
            filters={"step_size": 0.001, "min_qty": 0.001, "max_qty": 100.0, "min_notional": 50.0},
        )
        assert w_btc._compute_trade_size(64351.50, 10) == 0.0
        assert w_btc._last_size_reason is not None
        assert "BTCUSDT" in w_btc._last_size_reason
        assert "margin" in w_btc._last_size_reason.lower()

        # 5. $14 wallet + 10% ($1.40) @ 50x ($70 notional) on BTC ($64,351) -> 0.001 BTC executes!
        w_btc_50x = self._make_worker(
            "BTCUSDT",
            {"amount_mode": "percent", "amount_pct": 10, "leverage": 50},
            balance=14.0,
            filters={"step_size": 0.001, "min_qty": 0.001, "max_qty": 100.0, "min_notional": 50.0},
        )
        assert w_btc_50x._compute_trade_size(64351.50, 50) == 0.001

        # 6. $1 free balance remaining -> Fixed $1 on BNB @ 5x ($1.18 needed) refuses cleanly before -2019
        w_low_free = self._make_worker(
            "BNBUSDT",
            {"amount_mode": "fixed", "amount": 1, "leverage": 5},
            balance=1.0,
            filters={"step_size": 0.01, "min_qty": 0.01, "max_qty": 1000.0, "min_notional": 5.0},
        )
        assert w_low_free._compute_trade_size(589.49, 5) == 0.0
        assert "balance" in (w_low_free._last_size_reason or "").lower()

    def test_weex_and_primexbt_integer_steps_and_filters(self):
        # WEEX DOGEUSDT uses step=100 -> must format cleanly as int 100 ("100", not "100.0")
        rounded = WEEXFuturesTrader._round_to_step(150.0, 100.0)
        assert rounded == 100 and isinstance(rounded, int)
        assert str(rounded) == "100"
        ceiled = WEEXFuturesTrader._ceil_to_step(101.0, 100.0)
        assert ceiled == 200 and isinstance(ceiled, int)

        px = PrimeXBTTrader({"exchange": "primexbt", "testnet": True})
        f = px.get_symbol_filters("XAU/USD")
        assert f["step_size"] == 0.01
        assert f["qty_step"] == 0.01
        assert "min_notional" in f

    def test_high_leverage_caps_200x_500x_1000x_across_exchanges(self, monkeypatch):
        # 1. Binance: requesting 500x clamps to 125x with adjusted=True, and -4028 drops to 100x cleanly
        trader, mock_client = _make_binance_trader(monkeypatch, testnet=False)

        def fake_lev(symbol, leverage):
            if leverage > 100:
                raise RuntimeError("(-4028, 'Leverage 125 is not valid')")
            return {"leverage": leverage, "maxNotionalValue": "500000"}

        mock_client.change_initial_leverage.side_effect = fake_lev
        r_bin = trader.set_leverage("SOLUSDT", 500)
        assert r_bin["success"] is True
        assert r_bin["leverage"] == 100
        assert r_bin["adjusted"] is True
        assert r_bin["original"] == 500
        assert trader._symbol_leverage["SOLUSDT"] == 100

        # 2. WEEX: requesting 500x on DOGEUSDT (maxLeverage=200) clamps to 200x BEFORE hitting API,
        #    and tier-rejection on SOLUSDT (max=300) auto-steps down cleanly
        wx = WEEXFuturesTrader("k", "s", "p", testnet=False)
        wx._contract_cache = {
            "DOGEUSDT": {"step_size": 100, "min_qty": 100, "max_qty": 1e9, "tick_size": 0.00001, "min_notional": 5.0, "max_leverage": 200},
            "SOLUSDT": {"step_size": 0.1, "min_qty": 0.1, "max_qty": 1e6, "tick_size": 0.01, "min_notional": 5.0, "max_leverage": 300},
        }
        wx_sent = []

        def fake_wx_req(method, path, params=None, body=None, signed=False):
            lev_val = int(body.get("leverage") or body.get("crossLeverage") or 0)
            sym = body.get("symbol")
            wx_sent.append((sym, lev_val))
            if sym == "SOLUSDT" and lev_val > 200:
                raise RuntimeError("WEEX API error: max leverage limit 200 exceeded")
            return {"code": "0", "msg": "success"}

        monkeypatch.setattr(wx, "_request", fake_wx_req)
        r_doge = wx.set_leverage("DOGEUSDT", 500)
        assert r_doge["success"] is True
        assert r_doge["leverage"] == 200
        assert r_doge["adjusted"] is True
        assert r_doge["original"] == 500
        assert wx_sent[0] == ("DOGEUSDT", 200)

        r_sol = wx.set_leverage("SOLUSDT", 500)
        assert r_sol["success"] is True
        assert r_sol["leverage"] == 200
        assert r_sol["adjusted"] is True
        assert wx._symbol_leverage["SOLUSDT"] == 200

        # 3. PrimeXBT: 1000x on Gold allowed; 500x on crypto rejected by tier drops to 200x
        px = PrimeXBTTrader({"exchange": "primexbt", "api_key": "pxk_123", "api_secret": "hmac_sec", "testnet": False})
        px.private_key = "hmac_sec"
        monkeypatch.setattr(
            px,
            "get_symbol_filters",
            lambda sym: {"min_qty": 0.01, "max_qty": 1000.0, "qty_step": 0.01, "step_size": 0.01,
                         "max_leverage": 1000 if "XAU" in sym else 500},
        )
        px_sent = []

        def fake_px_req(method, path, params=None, body=None):
            px_sent.append((body.get("symbol"), body.get("leverage")))
            if body.get("symbol") == "SOL/USD" and int(body.get("leverage", 0)) > 200:
                return {"error": "Maximum leverage limit exceeded"}
            return {"ok": True}

        monkeypatch.setattr(px, "_request", fake_px_req)
        r_gold = px.set_leverage("XAU/USD", 1000)
        assert r_gold["success"] is True and r_gold["leverage"] == 1000

        r_px_sol = px.set_leverage("SOL/USD", 500)
        assert r_px_sol["success"] is True
        assert r_px_sol["leverage"] == 200
        assert r_px_sol["adjusted"] is True
        assert px._symbol_leverage["SOL/USD"] == 200


class TestPureEMAAndReversalAcrossAllExchanges:
    @staticmethod
    def _make_trend_df(direction: str):
        import pandas as pd
        idx = pd.date_range("2026-11-01", periods=80, freq="15min")
        if direction == "up":
            closes = [100.0 + i * 0.5 for i in range(80)]
        elif direction == "down":
            closes = [200.0 - i * 0.5 for i in range(80)]
        else:
            closes = [100.0] * 80
        return pd.DataFrame({
            "open": closes, "high": closes, "low": closes,
            "close": closes, "volume": [1000.0] * 80,
        }, index=idx)

    def test_pure_ema_strategy_no_spread_no_waiting(self):
        from bot.strategy import EMAQuadStrategy, Signal
        strat = EMAQuadStrategy()
        assert not hasattr(strat, "min_spread_pct")
        assert not hasattr(strat, "fresh_window")

        # Immediate BUY on uptrend (zero spread wait, zero 2-candle window)
        res_up = strat.analyze(self._make_trend_df("up"))
        assert res_up is not None and res_up.signal == Signal.BUY

        # Immediate SELL on downtrend
        res_dn = strat.analyze(self._make_trend_df("down"))
        assert res_dn is not None and res_dn.signal == Signal.SELL

        # Flat -> HOLD
        res_flat = strat.analyze(self._make_trend_df("flat"))
        assert res_flat is not None and res_flat.signal == Signal.HOLD

    @pytest.mark.parametrize("exchange,testnet,symbol", [
        ("binance", False, "SOLUSDT"),
        ("binance", True, "SOLUSDT"),
        ("weex", False, "SOLUSDT"),
        ("weex", True, "SOLSUSDT"),
        ("primexbt", False, "SOL/USD"),
        ("primexbt", True, "SOL/USD"),
    ])
    def test_worker_enters_immediately_and_reverses_on_all_exchanges(self, exchange, testnet, symbol):
        from types import SimpleNamespace
        from bot.engine import BotEngine, SymbolWorker

        cfg = {
            "exchange": exchange, "testnet": testnet, "live_confirmed": True,
            "symbols_list": [symbol], "timeframe": "15m", "leverage": 20,
            "amount_mode": "percent", "amount_pct": 10, "mode": "both",
            "max_concurrent_trades": 3,
        }
        eng = BotEngine(MagicMock(), cfg)
        eng.history = MagicMock()
        eng.history.trades = []
        eng.history.has_open_trade.return_value = False
        eng.history.get_trades.return_value = []
        eng.history.get_stats.return_value = {}

        state = {"side": "NONE", "size": 0.0, "entry": 0.0}
        actions = []

        trader = MagicMock()
        trader._symbol_leverage = {symbol: 20}
        trader.get_balance.return_value = 100.0
        trader.get_mark_price.return_value = 140.0
        trader.get_max_notional.return_value = 0.0
        trader.get_symbol_filters.return_value = {
            "step_size": 0.01, "min_qty": 0.01, "max_qty": 10000.0, "min_notional": 5.0
        }
        trader._round_to_step = BinanceFuturesTrader._round_to_step
        trader._ceil_to_step = BinanceFuturesTrader._ceil_to_step
        trader.compute_quantity = lambda n, p, l, qty_step=0.01: BinanceFuturesTrader._round_to_step(n / p, qty_step)
        trader.get_position.side_effect = lambda s: SimpleNamespace(
            symbol=s, side=state["side"], size=state["size"],
            entry_price=state["entry"], mark_price=140.0, unrealized_pnl=0.0, leverage=20,
        )

        def _open_long(sym, qty, **kw):
            assert "sl_price" not in kw and "tp_price" not in kw
            actions.append(("OPEN_LONG", sym, qty))
            state.update(side="LONG", size=qty, entry=140.0)
            return {"success": True, "quantity": qty, "order": {"orderId": "L1"}}

        def _open_short(sym, qty, **kw):
            assert "sl_price" not in kw and "tp_price" not in kw
            actions.append(("OPEN_SHORT", sym, qty))
            state.update(side="SHORT", size=-qty, entry=140.0)
            return {"success": True, "quantity": qty, "order": {"orderId": "S1"}}

        def _close(sym):
            actions.append(("CLOSE_" + state["side"], sym))
            state.update(side="NONE", size=0.0, entry=0.0)
            return {"success": True, "order": {"orderId": "C1"}}

        trader.open_long.side_effect = _open_long
        trader.open_short.side_effect = _open_short
        trader.close_position.side_effect = _close
        eng.trader = trader

        w = SymbolWorker(eng, symbol, cfg)
        eng.workers[symbol] = w

        # Tick 1: EMA55 at BOTTOM -> opens LONG immediately (no waiting, no spread, no SL/TP)
        trader.get_klines.return_value = self._make_trend_df("up")
        w._tick()
        assert state["side"] == "LONG"
        assert actions == [("OPEN_LONG", symbol, actions[0][2])]

        # Tick 2: Still BUY -> holds LONG (no extra order, no SL/TP exit)
        w._tick()
        assert len(actions) == 1 and state["side"] == "LONG"

        # Tick 3: EMA55 flips to TOP -> closes LONG & immediately opens SHORT
        trader.get_klines.return_value = self._make_trend_df("down")
        w._tick()
        assert state["side"] == "SHORT"
        assert [a[0] for a in actions] == ["OPEN_LONG", "CLOSE_LONG", "OPEN_SHORT"]

        # Tick 4: EMA55 flips back to BOTTOM -> closes SHORT & immediately opens LONG
        trader.get_klines.return_value = self._make_trend_df("up")
        w._tick()
        assert state["side"] == "LONG"
        assert [a[0] for a in actions] == ["OPEN_LONG", "CLOSE_LONG", "OPEN_SHORT", "CLOSE_SHORT", "OPEN_LONG"]

    def test_weex_and_primexbt_orders_never_send_sl_tp_fields(self, monkeypatch):
        # WEEX (Demo & Mainnet)
        for is_demo in (True, False):
            wx = WEEXFuturesTrader("k", "s", "p", testnet=is_demo)
            wx._contract_cache["BTCUSDT"] = {"step_size": 0.001, "min_qty": 0.001, "max_qty": 100.0, "tick_size": 0.1}
            sent_wx = []
            monkeypatch.setattr(wx, "_request", lambda m, p, params=None, body=None, signed=False: (sent_wx.append(dict(body or {})) or {"orderId": "W1"}))
            r = wx.open_long("BTCUSDT", 0.01)
            assert r["success"] is True
            assert "slTriggerPrice" not in sent_wx[0]
            assert "tpTriggerPrice" not in sent_wx[0]
            assert not hasattr(wx, "place_stop_loss")

        # PrimeXBT (Live with HMAC key)
        px = PrimeXBTTrader({"exchange": "primexbt", "api_key": "pxk_123", "api_secret": "hmac_secret_12345", "testnet": False})
        sent_px = []
        monkeypatch.setattr(px, "_request", lambda m, p, body=None, query=None: (sent_px.append(dict(body or {})) or {"orderId": "P1"}))
        r_px = px.open_short("BTC/USD", 0.05)
        assert r_px["success"] is True
        assert "stopLoss" not in sent_px[0]
        assert "takeProfit" not in sent_px[0]

    def test_existing_user_config_preserved_and_obsolete_sl_tp_stripped(self, tmp_path):
        import json as _json
        import subprocess as _sp
        import sys as _sys
        from pathlib import Path as _Path

        bot_dir = _Path(r"d:\bot\bot-engine")
        cfg_path = tmp_path / "config.json"
        existing = {
            "exchange": "weex",
            "testnet": False,
            "live_confirmed": True,
            "api_key": "SAVED_KEY_123",
            "api_secret": "SAVED_SEC_456",
            "api_passphrase": "PASS",
            "api_keys": {"weex": {"api_key": "SAVED_KEY_123", "api_secret": "SAVED_SEC_456", "api_passphrase": "PASS"}},
            "symbols_list": ["BTCUSDT", "XRPUSDT"],
            "timeframe": "5m",
            "leverage": 35,
            "amount_mode": "percent",
            "amount_pct": 10,
            "stop_loss_pct": 0.25,
            "take_profit_pct": 1.0,
            "min_ema_spread": 0.15,
            "fresh_window": 2,
            "reentry_cooldown_sec": 180,
        }
        cfg_path.write_text(_json.dumps(existing), encoding="utf-8")
        script = (
            f"import sys, json; from pathlib import Path; "
            f"sys.path.insert(0, {str(bot_dir)!r}); "
            f"import app; app.CONFIG_FILE = Path({str(cfg_path)!r}); "
            f"loaded = app.load_config(); print(json.dumps(loaded))"
        )
        res = _sp.run([_sys.executable, "-c", script], cwd=str(bot_dir), capture_output=True, text=True, timeout=15)
        assert res.returncode == 0, res.stderr
        loaded = _json.loads(res.stdout.strip().splitlines()[-1])
        assert loaded["exchange"] == "weex"
        assert loaded["api_key"] == "SAVED_KEY_123"
        assert loaded["symbols_list"] == ["BTCUSDT", "XRPUSDT"]
        assert loaded["timeframe"] == "5m"
        assert loaded["leverage"] == 35
        assert loaded["amount_mode"] == "percent"
        assert loaded["amount_pct"] == 10
        for obsolete in ("stop_loss_pct", "take_profit_pct", "tp_mode", "breakeven_lock",
                         "min_ema_spread", "fresh_window", "reentry_cooldown_sec"):
            assert obsolete not in loaded



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

    def test_algo_order_fallback_on_4120_and_cancel_algo_orders(self, monkeypatch):
        trader, mock_client = _make_binance_trader(monkeypatch, hedge=False, testnet=False)

        # Standard endpoint raises -4120 on STOP_MARKET / TAKE_PROFIT_MARKET (Binance mainnet migration)
        def fake_new_order(**kwargs):
            if kwargs.get("type") in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
                raise RuntimeError("(-4120, 'Order type not supported for this endpoint. Please use the Algo Order API endpoints instead.')")
            return {"orderId": 1001, "symbol": kwargs["symbol"]}

        mock_client.new_order.side_effect = fake_new_order

        algo_calls = []

        def fake_fapi_signed(method, path, params=None, timeout=15):
            algo_calls.append((method, path, dict(params or {})))
            if method == "POST":
                return {"algoId": 9001, "clientAlgoId": "alg_9001"}
            return {"code": 200, "msg": "success"}

        monkeypatch.setattr(trader, "_fapi_signed_request", fake_fapi_signed)

        res = trader.open_long("SOLUSDT", 0.25, sl_price=70.50, tp_price=71.80)
        assert res["success"] is True
        assert res["sl_price"] == 70.5
        assert res["tp_price"] == 71.8
        assert trader._use_algo_orders is True

        post_calls = [c for c in algo_calls if c[0] == "POST"]
        assert len(post_calls) == 2
        assert post_calls[0][1] == "/fapi/v1/algoOrder"
        assert post_calls[0][2]["type"] == "STOP_MARKET"
        assert post_calls[0][2]["algoType"] == "CONDITIONAL"
        assert post_calls[0][2]["reduceOnly"] == "true"
        assert "positionSide" not in post_calls[0][2]
        assert post_calls[1][2]["type"] == "TAKE_PROFIT_MARKET"

        # Subsequent SL order goes straight to /fapi/v1/algoOrder without hitting -4120 again
        pre_new_order_count = mock_client.new_order.call_count
        sl2 = trader.place_stop_loss("SOLUSDT", "SELL", 70.60, 0.25)
        assert sl2["success"] is True
        assert sl2["algo"] is True
        assert mock_client.new_order.call_count == pre_new_order_count

        # Cancel open orders clears BOTH standard orders and /fapi/v1/algoOpenOrders
        cancel = trader.cancel_open_orders("SOLUSDT")
        assert cancel["success"] is True
        mock_client.cancel_open_orders.assert_called_once_with(symbol="SOLUSDT")
        assert any(c[0] == "DELETE" and c[1] == "/fapi/v1/algoOpenOrders" for c in algo_calls)

    def test_hedge_mode_and_4061_auto_recovery(self, monkeypatch):
        trader, mock_client = _make_binance_trader(monkeypatch, hedge=True, testnet=False)
        trader._use_algo_orders = True

        # Start with wrong cached flag to verify -4061 auto-recovery
        trader._is_hedge_mode = False
        sent_market = []

        def fake_new_order(**kwargs):
            sent_market.append(dict(kwargs))
            if kwargs.get("positionSide") != "SHORT":
                raise RuntimeError("(-4061, \"Order's position side does not match user's setting.\")")
            return {"orderId": 2002, "positionSide": "SHORT"}

        mock_client.new_order.side_effect = fake_new_order

        algo_calls = []
        monkeypatch.setattr(
            trader,
            "_fapi_signed_request",
            lambda method, path, params=None, timeout=15: (algo_calls.append(dict(params or {})) or {"algoId": 777}),
        )

        res = trader.open_short("SOLUSDT", 0.2, sl_price=72.0, tp_price=70.0)
        assert res["success"] is True
        assert len(sent_market) == 2
        assert sent_market[1]["positionSide"] == "SHORT"
        assert "reduceOnly" not in sent_market[1]
        assert res["sl_price"] == 72.0
        assert res["tp_price"] == 70.0
        assert algo_calls[0]["positionSide"] == "SHORT"
        assert "reduceOnly" not in algo_calls[0]

    def test_2027_downscaled_qty_propagates_to_sl_tp(self, monkeypatch):
        trader, mock_client = _make_binance_trader(monkeypatch, hedge=False, testnet=False)
        trader._use_algo_orders = True

        def fake_new_order(**kwargs):
            if float(kwargs["quantity"]) > 0.6:
                raise RuntimeError("(-2027, 'Exceeded the maximum allowable position at current leverage.')")
            return {"orderId": 3003}

        mock_client.new_order.side_effect = fake_new_order
        sltp_qtys = []
        monkeypatch.setattr(
            trader,
            "_fapi_signed_request",
            lambda m, p, params=None, timeout=15: (sltp_qtys.append(float(params["quantity"])) or {"algoId": 888}),
        )

        res = trader.open_long("SOLUSDT", 1.0, sl_price=70.0, tp_price=72.0)
        assert res["success"] is True
        assert res["quantity"] == 0.5
        assert sltp_qtys == [0.5, 0.5]

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


class TestConfigurableTPRiskAndTrailingProtection:
    def test_breakeven_lock_moves_sl_above_entry_and_preserves_fixed_tp(self):
        from bot.engine import SymbolWorker, BotEngine
        from bot.strategy import Signal
        from types import SimpleNamespace

        cfg = {
            "exchange": "binance", "testnet": False, "live_confirmed": True,
            "symbols_list": ["XRPUSDT"], "timeframe": "15m", "leverage": 20,
            "stop_loss_pct": 0.5, "take_profit_pct": 1.5,
            "tp_mode": "fixed", "breakeven_lock": True,
        }
        eng = BotEngine(MagicMock(), cfg)
        trader = MagicMock()
        eng.trader = trader
        w = SymbolWorker(eng, "XRPUSDT", cfg)
        w._set_software_sl_tp(
            "XRPUSDT", "LONG", entry_price=1.0000,
            sl_pct=0.5, tp_pct=1.5, tp_mode="fixed",
            entry_signal=Signal.BUY, actual_leverage=20,
        )
        assert abs(w.sl_price - 0.9950) < 1e-6
        assert abs(w.tp_price - 1.0150) < 1e-6

        # Price moves up +0.90% (>= 55% of 1.5% TP -> 0.825%) -> Breakeven lock triggers!
        pos_up = SimpleNamespace(side="LONG", size=100.0, entry_price=1.0, mark_price=1.0090, leverage=20)
        sl_hit, tp_hit, _ = w._check_software_sl_tp(pos_up, None)
        assert not sl_hit and not tp_hit
        assert w.be_sl_set is True
        assert abs(w.sl_price - 1.0015) < 1e-6
        # _update_exchange_sl must re-attach BOTH new SL and fixed TP after cancel_open_orders!
        trader.cancel_open_orders.assert_called_once_with("XRPUSDT")
        trader.place_stop_loss.assert_called_once()
        trader.place_take_profit.assert_called_once()

        # Price pulls back to breakeven SL -> exits cleanly as profit/breakeven win, NOT SL loss
        pos_be = SimpleNamespace(side="LONG", size=100.0, entry_price=1.0, mark_price=1.0014, leverage=20)
        sl_hit2, tp_hit2, reason2 = w._check_software_sl_tp(pos_be, None)
        assert sl_hit2 is False
        assert tp_hit2 is True
        assert "BREAKEVEN LOCK HIT" in reason2

    def test_stepped_roe_trailing_50_15_100_50_150_ladder(self):
        from bot.engine import SymbolWorker, BotEngine
        from bot.strategy import Signal
        from types import SimpleNamespace

        cfg = {
            "exchange": "binance", "testnet": False, "live_confirmed": True,
            "symbols_list": ["SOLUSDT"], "timeframe": "15m", "leverage": 20,
            "stop_loss_pct": 0.5, "take_profit_pct": 1.5,
            "tp_mode": "trailing", "breakeven_lock": True,
        }
        eng = BotEngine(MagicMock(), cfg)
        trader = MagicMock()
        eng.trader = trader
        w = SymbolWorker(eng, "SOLUSDT", cfg)
        w._set_software_sl_tp(
            "SOLUSDT", "LONG", entry_price=100.0,
            sl_pct=0.5, tp_pct=1.5, tp_mode="trailing",
            entry_signal=Signal.BUY, actual_leverage=20,
        )
        assert w.tp_stage == 0
        assert abs(w.sl_price - 99.50) < 1e-6

        # Step 1: +50% ROE ($102.50 at 20x -> +2.5% * 20 = +50% ROE) -> SL jumps to +15% ROE ($100.75)
        pos_s1 = SimpleNamespace(side="LONG", size=1.0, entry_price=100.0, mark_price=102.50, leverage=20)
        sl_hit, tp_hit, _ = w._check_software_sl_tp(pos_s1, None)
        assert not sl_hit and not tp_hit
        assert w.tp_stage == 1
        assert abs(w.sl_price - 100.75) < 1e-6
        assert trader.place_stop_loss.call_count == 1
        assert trader.place_take_profit.call_count == 0  # don't cap at 100% yet

        # If price pulls back below +15% ROE lock ($100.74) -> closes cleanly as fees-saved WIN
        pos_pull1 = SimpleNamespace(side="LONG", size=1.0, entry_price=100.0, mark_price=100.74, leverage=20)
        sl_h_p1, tp_h_p1, r_p1 = w._check_software_sl_tp(pos_pull1, None)
        assert sl_h_p1 is False and tp_h_p1 is True
        assert "TRAILING STEP 1 SL HIT" in r_p1

        # Step 2: Re-test forward to +100% ROE ($105.00 at 20x) -> SL moves to +50% ROE ($102.50) & TP set to +150% ROE ($107.50)
        pos_s2 = SimpleNamespace(side="LONG", size=1.0, entry_price=100.0, mark_price=105.00, leverage=20)
        sl_hit2, tp_hit2, _ = w._check_software_sl_tp(pos_s2, None)
        assert not sl_hit2 and not tp_hit2
        assert w.tp_stage == 2
        assert abs(w.sl_price - 102.50) < 1e-6
        assert abs(w.tp_price - 107.50) < 1e-6
        assert trader.place_stop_loss.call_count == 2
        assert trader.place_take_profit.call_count == 1  # exchange TP now attached at +150% ROE!

        # Pullback to locked +50% SL ($102.49) -> closes as +50% ROE profit win
        pos_pull2 = SimpleNamespace(side="LONG", size=1.0, entry_price=100.0, mark_price=102.49, leverage=20)
        sl_h_p2, tp_h_p2, r_p2 = w._check_software_sl_tp(pos_pull2, None)
        assert sl_h_p2 is False and tp_h_p2 is True
        assert "TRAILING STEP 2 SL HIT" in r_p2

        # Reaching +150% ROE ($107.50) hits full TP target!
        pos_tp150 = SimpleNamespace(side="LONG", size=1.0, entry_price=100.0, mark_price=107.50, leverage=20)
        sl_h3, tp_h3, r3 = w._check_software_sl_tp(pos_tp150, None)
        assert sl_h3 is False and tp_h3 is True
        assert "TRAILING TP HIT (+150% ROE" in r3

    def test_existing_user_config_preserved_without_data_loss(self, tmp_path):
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
        }
        cfg_path.write_text(_json.dumps(existing), encoding="utf-8")
        # Run in an isolated subprocess so bot-engine/app.py's sys.path[0] never shadows SaaS app.py in pytest
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
        assert abs(loaded["stop_loss_pct"] - 0.25) < 1e-9
        assert abs(loaded["take_profit_pct"] - 1.0) < 1e-9



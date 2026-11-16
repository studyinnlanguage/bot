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

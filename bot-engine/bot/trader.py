"""
Binance Futures Trader Module
Handles all interactions with Binance USDT-M Futures API.

Uses the official `binance-futures-connector` package (v1.5.0+) for API calls.
Falls back to `python-binance` if the connector is not available.

Functions:
- Set leverage
- Place market orders (long / short)
- Query account balance & open positions
- Close positions
- Fetch historical klines for strategy
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Try to import a Binance futures client.
# Preferred: `binance-futures-connector` (official, v1.5.0+ or v4.x UMFutures).
# Fallback: `python-binance`.
try:
    from binance.um_futures import UMFutures as FuturesClient  # binance-futures-connector v4+
    _CONNECTOR = "binance-futures-connector"
except Exception:  # pragma: no cover
    try:
        from binance.futures import Futures as FuturesClient  # binance-futures-connector v1+
        _CONNECTOR = "binance-futures-connector"
    except Exception:
        try:
            from binance.client import Client as _BClient  # python-binance
            FuturesClient = None
            _CONNECTOR = "python-binance"
        except Exception:
            FuturesClient = None
            _CONNECTOR = "none"


@dataclass
class Position:
    symbol: str
    side: str            # "LONG" / "SHORT" / "NONE"
    size: float          # base asset qty (signed: + long, - short)
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: int


class BinanceFuturesTrader:
    """Wraps Binance USDT-M Futures API for the bot. Supports testnet and mainnet."""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = str(api_key or "").strip().strip('"').strip("'")
        self.api_secret = str(api_secret or "").strip().strip('"').strip("'")
        self.testnet = bool(testnet)
        self.client = None
        self._exchange_info_cache: dict = {}  # symbol -> {step_size, min_qty, tick_size}
        self._symbol_leverage: dict[str, int] = {}  # symbol -> last set/confirmed leverage
        self._symbol_max_notional: dict[str, float] = {}  # symbol -> max allowed notional at current leverage
        self._connect()

    def _connect(self):
        if _CONNECTOR == "binance-futures-connector":
            # v1.5.0 API: Futures(key=..., secret=..., base_url=...)
            # IMPORTANT: do NOT add /fapi suffix - the library already prepends /fapi/v1/... to paths
            base_url = (
                "https://testnet.binancefuture.com"
                if self.testnet else "https://fapi.binance.com"
            )
            self.client = FuturesClient(
                key=self.api_key,
                secret=self.api_secret,
                base_url=base_url,
            )
            logger.info("Connected to Binance Futures (%s) via binance-futures-connector",
                        "TESTNET" if self.testnet else "MAINNET")
        elif _CONNECTOR == "python-binance":
            self.client = _BClient(self.api_key, self.api_secret, testnet=self.testnet)
            try:
                self.client.FUTURES_URL = (
                    "https://testnet.binancefuture.com/fapi"
                    if self.testnet else "https://fapi.binance.com/fapi"
                )
            except Exception:
                pass
            logger.info("Connected to Binance Futures (%s) via python-binance",
                        "TESTNET" if self.testnet else "MAINNET")
        else:
            raise RuntimeError(
                "No Binance library installed. Run: pip install -r requirements.txt"
            )

    # ---------- Market data ----------

    def _retry_api_call(self, func, *args, max_retries=3, **kwargs):
        """Retry an API call on network errors with exponential backoff.
        Prevents bot crashes from temporary internet drops."""
        import time
        last_error = None
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                # Only retry on network/connection errors, not on auth errors
                is_network_error = any(x in err_str for x in [
                    "connection aborted", "remotedisconnected", "connectionerror",
                    "timeout", "timed out", "connection reset", "max retries",
                    "ssl", "eof", "broken pipe", "remote end closed"
                ])
                if not is_network_error:
                    # Don't retry on auth errors, invalid symbol, etc.
                    raise
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(f"API call failed (attempt {attempt+1}/{max_retries}), "
                                   f"retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"API call failed after {max_retries} attempts: {e}")
        raise last_error

    def get_klines(self, symbol: str, interval: str = "1d", limit: int = 200) -> pd.DataFrame:
        """
        Fetch historical klines (candlesticks). Auto-retries on network errors.

        Args:
            symbol: e.g. "BTCUSDT"
            interval: "1m","5m","15m","1h","4h","1d","1w"
            limit: number of candles (max 1500)

        Returns:
            DataFrame indexed by open time with columns: open, high, low, close, volume.
        """
        if _CONNECTOR == "binance-futures-connector":
            raw = self._retry_api_call(self.client.klines, symbol=symbol, interval=interval, limit=limit)
        else:
            raw = self._retry_api_call(self.client.futures_klines, symbol=symbol, interval=interval, limit=limit)

        cols = ["open_time", "open", "high", "low", "close", "volume",
                "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"]
        df = pd.DataFrame(raw, columns=cols)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)
        return df[["open", "high", "low", "close", "volume"]]

    def get_mark_price(self, symbol: str) -> float:
        """Get current mark price for a symbol. Auto-retries on network errors."""
        if _CONNECTOR == "binance-futures-connector":
            data = self._retry_api_call(self.client.mark_price, symbol=symbol)
            if isinstance(data, list):
                data = data[0]
            return float(data["markPrice"])
        else:
            data = self._retry_api_call(self.client.futures_mark_price, symbol=symbol)
            return float(data["markPrice"])

    # ---------- Account ----------

    def get_balance(self) -> float:
        """Get USDT balance available for trading. Auto-retries on network errors."""
        try:
            if _CONNECTOR == "binance-futures-connector":
                acct = self._retry_api_call(self.client.balance)
                if isinstance(acct, dict) and "code" in acct and acct.get("code") != 200:
                    logger.error("Binance balance API error: %s", acct)
                    return 0.0
                if isinstance(acct, list):
                    for item in acct:
                        if isinstance(item, dict) and str(item.get("asset", "")).upper() == "USDT":
                            for key in ("availableBalance", "balance", "crossWalletBalance", "maxWithdrawAmount", "walletBalance"):
                                val = item.get(key)
                                if val not in (None, "", 0, "0"):
                                    try:
                                        v = float(val)
                                        if v > 0:
                                            return v
                                    except (ValueError, TypeError):
                                        continue
                            try:
                                return float(item.get("availableBalance", item.get("balance", 0.0)))
                            except (ValueError, TypeError):
                                return 0.0
                return 0.0
            else:
                try:
                    acct = self._retry_api_call(self.client.futures_account_balance)
                    if isinstance(acct, list):
                        for item in acct:
                            if isinstance(item, dict) and str(item.get("asset", "")).upper() == "USDT":
                                for key in ("availableBalance", "balance", "crossWalletBalance", "maxWithdrawAmount", "walletBalance"):
                                    val = item.get(key)
                                    if val not in (None, "", 0, "0"):
                                        try:
                                            v = float(val)
                                            if v > 0:
                                                return v
                                        except (ValueError, TypeError):
                                            continue
                                return float(item.get("availableBalance", item.get("balance", 0.0)))
                except Exception:
                    pass

                acct = self._retry_api_call(self.client.futures_account)
                if isinstance(acct, dict):
                    for item in acct.get("assets", []):
                        if isinstance(item, dict) and str(item.get("asset", "")).upper() == "USDT":
                            for key in ("availableBalance", "walletBalance", "marginBalance", "crossWalletBalance", "maxWithdrawAmount"):
                                val = item.get(key)
                                if val not in (None, "", 0, "0"):
                                    try:
                                        v = float(val)
                                        if v > 0:
                                            return v
                                    except (ValueError, TypeError):
                                        continue
                            return float(item.get("availableBalance", item.get("walletBalance", 0.0)))
                return 0.0
        except Exception as e:
            logger.error("Binance get_balance failed: %s", e)
            return 0.0

    def _call_change_leverage(self, symbol: str, leverage: int) -> dict:
        """Call Binance API to change initial leverage, trying all client library method variants."""
        symbol = str(symbol).strip().upper()
        leverage = int(leverage)
        # binance-futures-connector / binance-connector-python uses change_initial_leverage
        # python-binance uses futures_change_leverage
        # some wrappers use change_leverage
        for method_name in ("change_initial_leverage", "futures_change_leverage", "change_leverage"):
            fn = getattr(self.client, method_name, None)
            if callable(fn):
                return fn(symbol=symbol, leverage=leverage)
        raise AttributeError(
            f"Binance client ({type(self.client).__name__}) has no supported leverage method "
            "(tried change_initial_leverage, futures_change_leverage, change_leverage)"
        )

    def get_position(self, symbol: str) -> Position:
        """Get current position for a symbol using positionRisk / futures_position_information. Auto-retries."""
        symbol = str(symbol).strip().upper()
        cached_lev = self._symbol_leverage.get(symbol, 1)

        positions = None
        for method_name in ("get_position_risk", "futures_position_information", "position_risk"):
            fn = getattr(self.client, method_name, None)
            if callable(fn):
                try:
                    positions = self._retry_api_call(fn, symbol=symbol)
                    break
                except Exception as e:
                    logger.warning("%s failed for %s: %s", method_name, symbol, e)

        if not positions:
            return Position(symbol, "NONE", 0.0, 0.0, 0.0, 0.0, cached_lev)

        if isinstance(positions, dict):
            if "code" in positions and positions.get("code") != 200:
                logger.warning("Binance position API error for %s: %s", symbol, positions)
                return Position(symbol, "NONE", 0.0, 0.0, 0.0, 0.0, cached_lev)
            positions = [positions]
        elif not isinstance(positions, list):
            return Position(symbol, "NONE", 0.0, 0.0, 0.0, 0.0, cached_lev)

        # Match exact symbol
        matching = [p for p in positions if isinstance(p, dict) and str(p.get("symbol", "")).upper() == symbol]
        if not matching:
            matching = [p for p in positions if isinstance(p, dict)]

        if not matching:
            return Position(symbol, "NONE", 0.0, 0.0, 0.0, 0.0, cached_lev)

        # In Hedge mode or multiple positions, find active one if any
        p = matching[0]
        for item in matching:
            try:
                if abs(float(item.get("positionAmt", 0))) > 0:
                    p = item
                    break
            except (ValueError, TypeError):
                continue

        amt = float(p.get("positionAmt", 0))
        side = "LONG" if amt > 0 else ("SHORT" if amt < 0 else "NONE")

        # Parse leverage from API response
        lev = cached_lev
        for k in ("leverage", "lever", "marginLevel"):
            v = p.get(k)
            if v not in (None, "", 0, "0"):
                try:
                    lev_val = int(float(v))
                    if lev_val > 1:
                        lev = lev_val
                        self._symbol_leverage[symbol] = lev
                    elif lev_val == 1 and cached_lev > 1:
                        lev = cached_lev
                    elif lev_val > 0 and lev <= 1:
                        lev = lev_val
                    break
                except (ValueError, TypeError):
                    continue
        if lev <= 1 and cached_lev > 1:
            lev = cached_lev

        return Position(
            symbol=symbol,
            side=side,
            size=amt,
            entry_price=float(p.get("entryPrice", 0)),
            mark_price=float(p.get("markPrice", 0)),
            unrealized_pnl=float(p.get("unRealizedProfit", 0)),
            leverage=lev,
        )

    # ---------- Orders ----------

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        """Set leverage for a symbol (1-125). Auto-adjusts if leverage
        exceeds the symbol's max allowed leverage (error -4028)."""
        symbol = str(symbol).strip().upper()
        leverage = max(1, min(125, int(leverage)))
        try:
            resp = self._call_change_leverage(symbol, leverage)
            actual_lev = leverage
            max_notional = 0.0
            if isinstance(resp, dict):
                if "leverage" in resp:
                    try:
                        actual_lev = int(resp["leverage"])
                    except (ValueError, TypeError):
                        actual_lev = leverage
                if "maxNotionalValue" in resp:
                    try:
                        max_notional = float(resp["maxNotionalValue"])
                    except Exception:
                        pass
            self._symbol_leverage[symbol] = actual_lev
            if max_notional > 0:
                self._symbol_max_notional[symbol] = max_notional
            logger.info("Leverage set to %dx for %s (maxNotional: %s, resp: %s)", actual_lev, symbol, max_notional, resp)
            return {"success": True, "leverage": actual_lev, "maxNotionalValue": max_notional, "raw": resp}
        except Exception as e:
            msg = str(e)
            # Auto-fix: Leverage too high for this coin → reduce and retry
            if "-4028" in msg or "not valid" in msg.lower():
                # Try progressively lower leverage
                for try_lev in [75, 50, 25, 20, 10, 5, 3, 1]:
                    if try_lev >= leverage:
                        continue
                    try:
                        resp = self._call_change_leverage(symbol, try_lev)
                        actual_lev = try_lev
                        max_notional = 0.0
                        if isinstance(resp, dict):
                            if "leverage" in resp:
                                try:
                                    actual_lev = int(resp["leverage"])
                                except (ValueError, TypeError):
                                    actual_lev = try_lev
                            if "maxNotionalValue" in resp:
                                try:
                                    max_notional = float(resp["maxNotionalValue"])
                                except Exception:
                                    pass
                        self._symbol_leverage[symbol] = actual_lev
                        if max_notional > 0:
                            self._symbol_max_notional[symbol] = max_notional
                        logger.info("Leverage auto-adjusted to %dx for %s (requested %dx, maxNotional: %s)",
                                    actual_lev, symbol, leverage, max_notional)
                        return {"success": True, "leverage": actual_lev, "maxNotionalValue": max_notional, "raw": resp,
                                "adjusted": True, "original": leverage}
                    except Exception:
                        continue
                logger.error("Could not set any leverage for %s", symbol)
                return {"success": False, "error": f"Could not set leverage (tried 1x-{leverage}x): {msg}"}
            # Symbol closed/delisted
            if "-4141" in msg or "Symbol is closed" in msg:
                return {"success": False, "error": f"Symbol {symbol} is delisted/closed. Remove this coin from your list."}
            # Binance throws if leverage is unchanged; treat as success
            if "No need to change leverage" in msg or "leverage not changed" in msg.lower() \
               or "-4046" in msg:
                self._symbol_leverage[symbol] = leverage
                return {"success": True, "leverage": leverage, "raw": msg}
            logger.error("Failed to set leverage for %s: %s", symbol, e)
            return {"success": False, "error": msg}

    def get_max_notional(self, symbol: str) -> float:
        """Get the maximum allowable position notional value for symbol at current leverage.
        Used to prevent error -2027: Exceeded maximum allowable position."""
        symbol = str(symbol).strip().upper()
        if symbol in self._symbol_max_notional and self._symbol_max_notional[symbol] > 0:
            return self._symbol_max_notional[symbol]
        try:
            for method_name in ("leverage_bracket", "futures_leverage_bracket"):
                fn = getattr(self.client, method_name, None)
                if callable(fn):
                    brackets = fn(symbol=symbol)
                    if isinstance(brackets, list) and len(brackets) > 0:
                        b_list = brackets[0].get("brackets", [])
                        cur_lev = self._symbol_leverage.get(symbol, 50)
                        for b in b_list:
                            if b.get("initialLeverage") >= cur_lev:
                                notional_cap = float(b.get("notionalCap", 0))
                                if notional_cap > 0:
                                    self._symbol_max_notional[symbol] = notional_cap
                                    return notional_cap
        except Exception as e:
            logger.debug("[%s] Could not fetch leverage brackets: %s", symbol, e)
        return self._symbol_max_notional.get(symbol, 0.0)

    def get_symbol_filters(self, symbol: str) -> dict:
        """Fetch exchange info filters (LOT_SIZE step, min qty, PRICE_FILTER tick) for a symbol.
        Caches results to avoid repeated API calls.

        Returns:
            dict with keys: step_size, min_qty, tick_size, max_qty
            Falls back to defaults if API fails.
        """
        symbol = symbol.upper()
        if symbol in self._exchange_info_cache:
            return self._exchange_info_cache[symbol]

        defaults = {
            "step_size": 0.001,
            "min_qty": 0.001,
            "max_qty": 1e9,
            "tick_size": 0.01,
        }
        try:
            if _CONNECTOR == "binance-futures-connector":
                info = self.client.exchange_info()
            else:
                info = self.client.futures_exchange_info()

            # Cache all symbols from this single exchange_info call
            for s in info.get("symbols", []):
                sym_name = s.get("symbol", "").upper()
                filters = {f["filterType"]: f for f in s.get("filters", [])}
                lot = filters.get("LOT_SIZE", {})
                market_lot = filters.get("MARKET_LOT_SIZE", {})
                price = filters.get("PRICE_FILTER", {})
                s_step = float(lot.get("stepSize", 0.001))
                s_min = float(lot.get("minQty", 0.001))
                s_max = float(lot.get("maxQty", 1e9))
                if market_lot:
                    m_max = float(market_lot.get("maxQty", 0))
                    if m_max > 0 and m_max < s_max:
                        s_max = m_max
                    m_min = float(market_lot.get("minQty", 0))
                    if m_min > 0:
                        s_min = max(s_min, m_min)
                    m_step = float(market_lot.get("stepSize", 0))
                    if m_step > 0:
                        s_step = m_step
                self._exchange_info_cache[sym_name] = {
                    "step_size": s_step,
                    "min_qty": s_min,
                    "max_qty": s_max,
                    "tick_size": float(price.get("tickSize", 0.01)),
                }

            if symbol in self._exchange_info_cache:
                return self._exchange_info_cache[symbol]

            # Symbol not found in exchange info - use defaults
            self._exchange_info_cache[symbol] = defaults
            return defaults
        except Exception as e:
            logger.warning("Failed to fetch exchange_info for %s: %s. Using defaults.", symbol, e)
            self._exchange_info_cache[symbol] = defaults
            return defaults

    @staticmethod
    def _round_to_step(value: float, step: float) -> float:
        """Round value down to the nearest multiple of step."""
        if step <= 0:
            return value
        # Determine decimal places from step
        import math
        decimals = max(0, int(math.ceil(-math.log10(step))))
        rounded = math.floor(value / step) * step
        return round(rounded, decimals)

    def place_market_order(self, symbol: str, side: str, quantity: float,
                           reduce_only: bool = False,
                           position_side: str = None) -> dict:
        """
        Place a MARKET order. Automatically rounds quantity to the symbol's
        LOT_SIZE step size to avoid Binance error -1111 (Precision over maximum).

        Args:
            symbol: e.g. "BTCUSDT"
            side: "BUY" or "SELL"
            quantity: base-asset quantity (>0)
            reduce_only: if True, only reduces existing position (for exits)
            position_side: "LONG" or "SHORT" for Hedge Mode, or None for One-Way Mode

        Returns:
            dict with success flag and order info.
        """
        side = side.upper()
        if side not in ("BUY", "SELL"):
            return {"success": False, "error": f"Invalid side: {side}"}
        if quantity <= 0:
            return {"success": False, "error": "Quantity must be > 0"}

        # Fetch symbol filters and round quantity properly
        try:
            filters = self.get_symbol_filters(symbol)
            step = filters["step_size"]
            min_qty = filters["min_qty"]
            max_qty = filters.get("max_qty", 1e9)
            quantity = self._round_to_step(quantity, step)
            if max_qty > 0 and quantity > max_qty:
                logger.warning("[%s] Order qty %s exceeds max_qty %s -> clamped to %s", symbol, quantity, max_qty, max_qty)
                quantity = self._round_to_step(max_qty, step)
            if quantity < min_qty:
                return {"success": False,
                        "error": f"Quantity {quantity} below min_qty {min_qty} for {symbol}"}
        except Exception as e:
            logger.warning("Could not apply step size rounding for %s: %s. Using raw qty.", symbol, e)
            quantity = round(quantity, 6)

        try:
            if _CONNECTOR == "binance-futures-connector":
                kwargs = {
                    "symbol": symbol,
                    "side": side,
                    "type": "MARKET",
                    "quantity": quantity,
                }
                if reduce_only:
                    kwargs["reduceOnly"] = "true"
                if position_side:
                    kwargs["positionSide"] = str(position_side).upper()
                resp = self.client.new_order(**kwargs)
            else:
                kwargs = {
                    "symbol": symbol,
                    "side": side,
                    "type": "MARKET",
                    "quantity": quantity,
                }
                if reduce_only:
                    kwargs["reduceOnly"] = True
                if position_side:
                    kwargs["positionSide"] = str(position_side).upper()
                resp = self.client.futures_create_order(**kwargs)

            oid = resp.get("orderId", "?") if isinstance(resp, dict) else "?"
            logger.info("Order placed: %s %s qty=%s reduceOnly=%s posSide=%s -> orderId=%s",
                        side, symbol, quantity, reduce_only, position_side, oid)
            return {"success": True, "order": resp, "quantity": quantity}
        except Exception as e:
            err_msg = str(e)
            # Auto-handle Binance error -2027: Exceeded maximum allowable position at current leverage
            if "-2027" in err_msg or "-4005" in err_msg or "maximum allowable position" in err_msg.lower() or "quantity greater than max" in err_msg.lower():
                for factor in (0.5, 0.25):
                    retry_qty = self._round_to_step(quantity * factor, step)
                    if retry_qty >= min_qty:
                        logger.warning("[%s] Exceeded max allowable position (-2027) -> auto-retrying with safe qty=%s (%.0f%%)",
                                       symbol, retry_qty, factor * 100)
                        try:
                            kwargs["quantity"] = retry_qty
                            if _CONNECTOR == "binance-futures-connector":
                                resp = self.client.new_order(**kwargs)
                            else:
                                resp = self.client.futures_create_order(**kwargs)
                            oid = resp.get("orderId", "?") if isinstance(resp, dict) else "?"
                            logger.info("Order placed after bracket downscale: %s %s qty=%s -> orderId=%s",
                                        side, symbol, retry_qty, oid)
                            return {"success": True, "order": resp, "quantity": retry_qty}
                        except Exception as e2:
                            logger.warning("[%s] Retry with qty=%s failed: %s", symbol, retry_qty, e2)
            logger.error("Order failed: %s", e)
            return {"success": False, "error": str(e), "quantity": quantity}

    def place_limit_order(self, symbol: str, side: str, quantity: float,
                          price: float, post_only: bool = True,
                          reduce_only: bool = False,
                          position_side: str = None) -> dict:
        """
        Place a LIMIT / MAKER order.
        post_only=True enforces Maker order (saves fees: ~0.02% maker vs ~0.06% taker).
        """
        side = side.upper()
        if side not in ("BUY", "SELL"):
            return {"success": False, "error": f"Invalid side: {side}"}
        if quantity <= 0:
            return {"success": False, "error": "Quantity must be > 0"}
        if price <= 0:
            return {"success": False, "error": "Price must be > 0"}

        try:
            filters = self.get_symbol_filters(symbol)
            step = filters["step_size"]
            tick = filters["tick_size"]
            min_qty = filters["min_qty"]
            quantity = self._round_to_step(quantity, step)
            price = self._round_to_step(price, tick)
            if quantity < min_qty:
                return {"success": False,
                        "error": f"Quantity {quantity} below min_qty {min_qty} for {symbol}"}
        except Exception as e:
            logger.warning("Could not apply step/tick size for %s: %s", symbol, e)
            quantity = round(quantity, 6)

        try:
            time_in_force = "GTX" if post_only else "GTC"
            if _CONNECTOR == "binance-futures-connector":
                kwargs = {
                    "symbol": symbol,
                    "side": side,
                    "type": "LIMIT",
                    "quantity": quantity,
                    "price": price,
                    "timeInForce": time_in_force,
                }
                if reduce_only:
                    kwargs["reduceOnly"] = "true"
                if position_side:
                    kwargs["positionSide"] = str(position_side).upper()
                resp = self.client.new_order(**kwargs)
            else:
                kwargs = {
                    "symbol": symbol,
                    "side": side,
                    "type": "LIMIT",
                    "quantity": quantity,
                    "price": price,
                    "timeInForce": time_in_force,
                }
                if reduce_only:
                    kwargs["reduceOnly"] = True
                if position_side:
                    kwargs["positionSide"] = str(position_side).upper()
                resp = self.client.futures_create_order(**kwargs)

            oid = resp.get("orderId", "?") if isinstance(resp, dict) else "?"
            logger.info("Limit/Maker order placed: %s %s qty=%s price=%s TIF=%s posSide=%s -> orderId=%s",
                        side, symbol, quantity, price, time_in_force, position_side, oid)
            return {"success": True, "order": resp, "quantity": quantity, "price": price}
        except Exception as e:
            logger.warning("Limit/Maker order failed (%s): %s", side, e)
            return {"success": False, "error": str(e), "quantity": quantity, "price": price}

    def close_position(self, symbol: str, quantity: float = None) -> dict:
        """Close the current position (or partial quantity) for the symbol.
        1. ALWAYS cancels open orders first to eliminate Binance error -2022 (ReduceOnly rejected).
        2. Auto-detects Hedge Mode (Dual-Side) vs One-Way Mode.
        3. Features robust fallback: if reduceOnly is rejected, retries with exact-quantity market exit.
        """
        symbol = str(symbol).strip().upper()
        pos = self.get_position(symbol)
        if pos.side == "NONE" or abs(pos.size) <= 0:
            return {"success": True, "message": "No position to close"}

        # 1. ALWAYS cancel all open orders on exchange first!
        # Existing open SL/TP or limit orders with reduceOnly already reserve position qty.
        # Without cancelling them first, Binance rejects any new reduce-only market order with -2022.
        try:
            self.cancel_open_orders(symbol)
        except Exception as e:
            logger.warning("[%s] cancel_open_orders before close notice: %s", symbol, e)

        close_side = "SELL" if pos.side == "LONG" else "BUY"
        qty = abs(pos.size) if quantity is None else min(abs(float(quantity)), abs(pos.size))

        # Check if account is in Hedge Mode (Dual-Side Position)
        is_hedge = False
        try:
            if _CONNECTOR == "binance-futures-connector":
                pm = self.client.get_position_mode()
            else:
                pm = self.client.futures_get_position_mode()
            if isinstance(pm, dict):
                is_hedge = bool(pm.get("dualSidePosition", False))
        except Exception as e:
            logger.debug("[%s] get_position_mode check: %s", symbol, e)

        # 2. Place market order to close
        # In Hedge mode: reduceOnly is NOT permitted by Binance; positionSide is required.
        # In One-Way mode: reduceOnly=True is standard.
        res = self.place_market_order(
            symbol=symbol,
            side=close_side,
            quantity=qty,
            reduce_only=(not is_hedge),
            position_side=(pos.side if is_hedge else None),
        )

        if res.get("success"):
            return res

        err_msg = str(res.get("error", ""))
        logger.warning("[%s] Initial close order failed (%s). Executing aggressive close fallback...", symbol, err_msg)

        # 3. Aggressive Fallback:
        # If -2022 or reduceOnly error occurred, cancel open orders again
        try:
            self.cancel_open_orders(symbol)
        except Exception:
            pass

        # Check if position was already closed by an exchange order that filled
        latest_pos = self.get_position(symbol)
        if latest_pos.side == "NONE" or abs(latest_pos.size) <= 0:
            logger.info("[%s] Position verified closed after cancelling open orders", symbol)
            return {"success": True, "message": "Position is closed"}

        qty = abs(latest_pos.size) if quantity is None else min(abs(float(quantity)), abs(latest_pos.size))
        close_side = "SELL" if latest_pos.side == "LONG" else "BUY"

        # Retry with reduce_only=False (exact qty market order closes the remaining position)
        res_fallback = self.place_market_order(
            symbol=symbol,
            side=close_side,
            quantity=qty,
            reduce_only=False,
            position_side=(latest_pos.side if is_hedge else None),
        )
        if res_fallback.get("success"):
            logger.info("[%s] Aggressive fallback close succeeded!", symbol)
            return res_fallback

        return res

    def open_long(self, symbol: str, quantity: float,
                  sl_price: float = None, tp_price: float = None,
                  order_type: str = "market", price: float = None) -> dict:
        """Open a LONG position (market order default for instant momentum fills)."""
        result = None
        if order_type in ("maker", "limit") and price and price > 0:
            result = self.place_limit_order(symbol, "BUY", quantity, price, post_only=(order_type == "maker"))
            if not result.get("success"):
                logger.info("[%s] Maker entry rejected/unfilled -> falling back to MARKET order", symbol)
                result = None
        if not result:
            result = self.place_market_order(symbol, "BUY", quantity, reduce_only=False)

        # SL/TP placed after entry (see docstring for watchdog backup details)
        if result.get("success") and (sl_price or tp_price):
            if sl_price and sl_price > 0:
                sl_result = self.place_stop_loss(symbol, "SELL", sl_price, quantity)
                if not sl_result.get("success"):
                    logger.warning(f"[{symbol}] SL order failed (software watchdog will back up): {sl_result.get('error')}")
            if tp_price and tp_price > 0:
                tp_result = self.place_take_profit(symbol, "SELL", tp_price, quantity)
                if not tp_result.get("success"):
                    logger.warning(f"[{symbol}] TP order failed (software watchdog will back up): {tp_result.get('error')}")
        return result

    def open_short(self, symbol: str, quantity: float,
                   sl_price: float = None, tp_price: float = None,
                   order_type: str = "market", price: float = None) -> dict:
        """Open a SHORT position (market order default for instant momentum fills)."""
        result = None
        if order_type in ("maker", "limit") and price and price > 0:
            result = self.place_limit_order(symbol, "SELL", quantity, price, post_only=(order_type == "maker"))
            if not result.get("success"):
                logger.info("[%s] Maker entry rejected/unfilled -> falling back to MARKET order", symbol)
                result = None
        if not result:
            result = self.place_market_order(symbol, "SELL", quantity, reduce_only=False)

        # SL/TP placed after entry (see docstring for watchdog backup details)
        if result.get("success") and (sl_price or tp_price):
            if sl_price and sl_price > 0:
                sl_result = self.place_stop_loss(symbol, "BUY", sl_price, quantity)
                if not sl_result.get("success"):
                    logger.warning(f"[{symbol}] SL order failed (software watchdog will back up): {sl_result.get('error')}")
            if tp_price and tp_price > 0:
                tp_result = self.place_take_profit(symbol, "BUY", tp_price, quantity)
                if not tp_result.get("success"):
                    logger.warning(f"[{symbol}] TP order failed (software watchdog will back up): {tp_result.get('error')}")
        return result

    # ---------- Stop Loss / Take Profit Orders ----------

    def place_stop_loss(self, symbol: str, side: str, stop_price: float, quantity: float) -> dict:
        """Place a STOP_MARKET order for Stop Loss.
        side: opposite of position side (e.g. 'SELL' for LONG position)."""
        try:
            filters = self.get_symbol_filters(symbol)
            tick = filters["tick_size"]
            stop_price = self._round_to_step(stop_price, tick)
            qty = self._round_to_step(quantity, filters["step_size"])
            if _CONNECTOR == "binance-futures-connector":
                resp = self.client.new_order(
                    symbol=symbol, side=side, type="STOP_MARKET",
                    stopPrice=stop_price, quantity=qty, reduceOnly="true",
                    workingType="MARK_PRICE",
                )
            else:
                resp = self.client.futures_create_order(
                    symbol=symbol, side=side, type="STOP_MARKET",
                    stopPrice=stop_price, quantity=qty, reduceOnly=True,
                    workingType="MARK_PRICE",
                )
            logger.info("SL placed: %s %s qty=%s stopPrice=%s -> orderId=%s",
                        side, symbol, qty, stop_price, resp.get("orderId"))
            return {"success": True, "order": resp}
        except Exception as e:
            logger.error("SL order failed: %s", e)
            return {"success": False, "error": str(e)}

    def place_take_profit(self, symbol: str, side: str, stop_price: float, quantity: float) -> dict:
        """Place a TAKE_PROFIT_MARKET order.
        side: opposite of position side (e.g. 'SELL' for LONG position)."""
        try:
            filters = self.get_symbol_filters(symbol)
            tick = filters["tick_size"]
            stop_price = self._round_to_step(stop_price, tick)
            qty = self._round_to_step(quantity, filters["step_size"])
            if _CONNECTOR == "binance-futures-connector":
                resp = self.client.new_order(
                    symbol=symbol, side=side, type="TAKE_PROFIT_MARKET",
                    stopPrice=stop_price, quantity=qty, reduceOnly="true",
                    workingType="MARK_PRICE",
                )
            else:
                resp = self.client.futures_create_order(
                    symbol=symbol, side=side, type="TAKE_PROFIT_MARKET",
                    stopPrice=stop_price, quantity=qty, reduceOnly=True,
                    workingType="MARK_PRICE",
                )
            logger.info("TP placed: %s %s qty=%s stopPrice=%s -> orderId=%s",
                        side, symbol, qty, stop_price, resp.get("orderId"))
            return {"success": True, "order": resp}
        except Exception as e:
            logger.error("TP order failed: %s", e)
            return {"success": False, "error": str(e)}

    def cancel_open_orders(self, symbol: str) -> dict:
        """Cancel all open orders for a symbol (used before placing new SL/TP or closing position)."""
        try:
            if _CONNECTOR == "binance-futures-connector":
                resp = self.client.cancel_open_orders(symbol=symbol)
            else:
                resp = self.client.futures_cancel_all_open_orders(symbol=symbol)
            return {"success": True, "raw": resp}
        except Exception as e:
            err_msg = str(e)
            if "-2011" in err_msg or "unknown order" in err_msg.lower():
                # Binance returns -2011 if there are no open orders; that is normal and clean
                logger.debug("[%s] cancel_open_orders: no open orders found to cancel", symbol)
                return {"success": True, "message": "No open orders to cancel"}
            logger.warning("[%s] Cancel orders notice: %s", symbol, e)
            return {"success": False, "error": err_msg}

    # ---------- Helpers ----------

    def compute_quantity(self, notional_usdt: float, price: float,
                         leverage: int, qty_step: float = 0.001) -> float:
        """
        Compute base-asset quantity from desired USDT notional exposure.

        quantity = notional_usdt / price
        (Leverage affects margin requirement, not position size, when
        `notional_usdt` represents the user's intended position value.)

        Uses floor-based rounding (rounds DOWN) to never exceed the
        intended position size. Reuses _round_to_step for consistency.
        """
        if price <= 0:
            return 0.0
        raw_qty = notional_usdt / price
        return self._round_to_step(raw_qty, qty_step)

    def get_all_symbols(self) -> list:
        """Fetch ALL available USDT futures symbols from Binance.
        Returns list of symbol strings (e.g. ['BTCUSDT', 'ETHUSDT', ...])."""
        try:
            if _CONNECTOR == "binance-futures-connector":
                info = self._retry_api_call(self.client.exchange_info)
            else:
                info = self._retry_api_call(self.client.futures_exchange_info)
            symbols = []
            for s in info.get("symbols", []):
                if s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL":
                    if s.get("status") == "TRADING":
                        symbols.append(s.get("symbol"))
            symbols.sort()
            logger.info(f"Fetched {len(symbols)} USDT perpetual symbols from Binance")
            return symbols
        except Exception as e:
            logger.error(f"Failed to fetch all symbols: {e}")
            return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
                    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT",
                    "DOTUSDT", "LTCUSDT", "TRXUSDT", "ATOMUSDT", "UNIUSDT"]

    def test_connection(self) -> dict:
        """Test API connection by fetching balance. Returns detailed result."""
        try:
            balance = self.get_balance()
            return {
                "success": True,
                "message": f"Connected successfully! Balance: ${balance:.2f}",
                "balance": balance,
                "exchange": "binance",
                "demo": self.testnet,
            }
        except Exception as e:
            err_str = str(e)
            if "-2015" in err_str or "Invalid API-key" in err_str:
                cause = "API Key or Secret is invalid"
                fix = "Go to Binance Futures → API Management and create new keys"
            elif "-2014" in err_str or "Invalid JSON" in err_str:
                cause = "API key format is wrong"
                fix = "Make sure you copied the full API key and secret without extra spaces"
            elif "timeout" in err_str.lower():
                cause = "Network timeout"
                fix = "Check your internet connection"
            else:
                cause = "Unknown error"
                fix = "Check the bot logs for details"
            return {
                "success": False,
                "error": err_str,
                "cause": cause,
                "fix": fix,
            }

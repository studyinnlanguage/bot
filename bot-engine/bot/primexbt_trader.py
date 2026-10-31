"""
PrimeXBT Trading API (v3) Connector
Integrates PrimeXBT REST API (https://api.primexbt.com/v3/trading)
with Ed25519 PKCS#8 cryptographic request signing.
Supports CFDs, Metals (XAU/USD), Forex, Indices, and Crypto Futures up to 1000x leverage.
"""

import base64
import hashlib
import json
import logging
import math
import re
import time
from typing import Dict, List, Optional, Tuple
import requests
import pandas as pd

try:
    from cryptography.hazmat.primitives.serialization import (
        load_pem_private_key,
        load_der_private_key,
    )
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False
    load_pem_private_key = None
    load_der_private_key = None
    Ed25519PrivateKey = None

logger = logging.getLogger("bot.primexbt_trader")


class PrimeXBTPosition:
    """Standardized position object matching bot-engine expectations."""

    def __init__(
        self,
        symbol: str = "",
        side: str = "NONE",
        size: float = 0.0,
        entry_price: float = 0.0,
        mark_price: float = 0.0,
        unrealized_pnl: float = 0.0,
        leverage: int = 100,
        position_id: Optional[str] = None,
    ):
        self.symbol = symbol
        self.side = side  # 'LONG', 'SHORT', or 'NONE'
        self.size = size
        self.entry_price = entry_price
        self.mark_price = mark_price
        self.unrealized_pnl = unrealized_pnl
        self.leverage = leverage
        self.position_id = position_id

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "size": self.size,
            "entry_price": self.entry_price,
            "mark_price": self.mark_price,
            "unrealized_pnl": self.unrealized_pnl,
            "leverage": self.leverage,
            "position_id": self.position_id,
        }


class PrimeXBTTrader:
    """PrimeXBT Trading API v3 client."""

    BASE_URL = "https://api.primexbt.com"

    # Default fallback symbols for PrimeXBT (CFDs, Metals, Forex, Indices, Crypto)
    DEFAULT_SYMBOLS = [
        "XAU/USD",      # Gold (up to 1000x)
        "GOLD 24/7",    # 24/7 Gold
        "XAG/USD",      # Silver
        "BTC/USD",      # Bitcoin
        "ETH/USD",      # Ethereum
        "SOL/USD",      # Solana
        "XRP/USD",      # Ripple
        "EUR/USD",      # Euro
        "GBP/USD",      # British Pound
        "USTEC",        # Nasdaq 100
        "US30",         # Dow Jones 30
        "GER30",        # DAX 30
    ]

    # ---------------------------------------------------------------------
    # Real market data sources (NO fake/synthetic candles)
    # ---------------------------------------------------------------------
    # PrimeXBT's own REST API does not expose public OHLCV history, so REAL
    # candles are sourced from Binance (futures first, spot fallback), which
    # tracks the same underlying markets:
    #   - Crypto  "BTC/USD"  -> Binance  "BTCUSDT"
    #   - Gold    "XAU/USD"  -> Binance  "PAXGUSDT" (1 PAXG = 1 troy oz gold)
    # Symbols with no real source (silver, indices, most forex) raise a clean
    # "symbol not supported" error so the engine skips them. The old behaviour
    # of generating synthetic sawtooth candles (which made the EMA strategy
    # mathematically unable to trade, and would have traded on noise if it
    # could) has been REMOVED on purpose.
    _GOLD_ALIASES = ("XAU/USD", "XAUUSD", "GOLD", "GOLD/USD", "GOLD24/7",
                     "GOLD 24/7", "XAU/USDT", "PAXG/USD")
    _SRC_TTL = 600.0  # seconds a venue resolution stays cached
    _PROBE_COOLDOWN = 60.0  # seconds to pause Binance probing after a rate-limit hit

    def __init__(self, config: dict):
        self.config = config or {}
        self.api_key = str(self.config.get("api_key", "")).strip()
        self.api_secret = str(self.config.get("api_secret", "")).strip()
        self.testnet = bool(self.config.get("testnet", True))
        self.private_key: Optional[Ed25519PrivateKey] = None
        self._symbol_leverage: Dict[str, int] = {}
        # symbol -> (binance_symbol or None, preferred venue or None, cached_at_ts)
        self._src_cache: Dict[str, Tuple[Optional[str], Optional[str], float]] = {}
        # symbol -> ts until which Binance probing is paused (rate-limit backoff)
        self._probe_cooldown: Dict[str, float] = {}
        self._init_crypto_keys()

    def _init_crypto_keys(self):
        """Parse and load Ed25519 PKCS#8 private key from base64 secret."""
        if not self.api_secret:
            return
        if not HAS_CRYPTOGRAPHY:
            logger.warning("PrimeXBT requires 'cryptography' library for Ed25519 authentication. Run: pip install cryptography")
            return
        try:
            raw_b64 = self.api_secret
            # Remove PEM header/footer if pasted by user
            cleaned = (
                raw_b64.replace("-----BEGIN PRIVATE KEY-----", "")
                .replace("-----END PRIVATE KEY-----", "")
                .replace("\n", "")
                .replace("\r", "")
                .strip()
            )
            key_bytes = base64.b64decode(cleaned)
            try:
                self.private_key = load_der_private_key(key_bytes, password=None)
            except Exception:
                self.private_key = load_pem_private_key(key_bytes, password=None)
            logger.info("PrimeXBT Ed25519 private key loaded successfully.")
        except Exception as e:
            logger.warning("PrimeXBT Ed25519 key load failed: %s (Check secret format)", e)
            self.private_key = None

    def _sign_request(
        self, method: str, path: str, query_string: str = "", body_bytes: bytes = b""
    ) -> Dict[str, str]:
        """Generate mandatory PrimeXBT v3 authentication headers."""
        timestamp = str(int(time.time() * 1000))
        body_hash = hashlib.sha256(body_bytes).hexdigest()

        # PrimeXBT string to sign: 5 lines joined by \n with NO trailing newline
        # 1: HTTP Method (e.g. POST, GET)
        # 2: Request Path exactly as sent (e.g. /v3/trading/...)
        # 3: Query String (or empty string)
        # 4: Timestamp (ms)
        # 5: Lowercase hex SHA-256 hash of body bytes
        message_lines = [
            method.upper(),
            path,
            query_string,
            timestamp,
            body_hash,
        ]
        string_to_sign = "\n".join(message_lines)

        headers = {
            "X-API-KEY": self.api_key,
            "X-API-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
            "User-Agent": "WeexionicBot/2.0",
        }

        if self.private_key:
            try:
                sig_bytes = self.private_key.sign(string_to_sign.encode("utf-8"))
                headers["X-API-SIGNATURE"] = base64.b64encode(sig_bytes).decode("utf-8")
            except Exception as e:
                logger.error("Failed to sign PrimeXBT request: %s", e)

        return headers

    def _request(
        self, method: str, path: str, body: Optional[dict] = None, query: Optional[dict] = None
    ) -> dict:
        """Execute request to PrimeXBT API."""
        query_str = ""
        if query:
            query_str = "&".join(f"{k}={v}" for k, v in sorted(query.items()))

        body_bytes = b""
        if body is not None:
            body_bytes = json.dumps(body, separators=(",", ":")).encode("utf-8")

        headers = self._sign_request(method, path, query_str, body_bytes)
        url = f"{self.BASE_URL}{path}"
        if query_str:
            url += f"?{query_str}"

        try:
            resp = requests.request(
                method=method,
                url=url,
                headers=headers,
                data=body_bytes if body is not None else None,
                timeout=10,
            )
            if resp.status_code in (200, 201):
                try:
                    return resp.json()
                except Exception:
                    return {"success": True, "raw": resp.text}
            else:
                try:
                    err_json = resp.json()
                    desc = err_json.get("description") or err_json.get("code") or resp.text
                except Exception:
                    desc = resp.text
                logger.warning(
                    "PrimeXBT API %s %s returned %d: %s",
                    method,
                    path,
                    resp.status_code,
                    desc,
                )
                return {
                    "success": False,
                    "error": desc,
                    "status_code": resp.status_code,
                }
        except Exception as e:
            logger.error("PrimeXBT network error on %s %s: %s", method, path, e)
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Account & Metrics
    # =========================================================================

    def get_balance(self) -> float:
        """Fetch available margin or wallet balance."""
        if not self.api_key or not self.private_key:
            return 10000.0 if self.testnet else 0.0

        res = self._request("GET", "/v3/trading/metrics")
        if isinstance(res, dict) and "success" not in res:  # Successful response
            # PrimeXBT metrics fields: availableMargin, balance, equity
            avail = res.get("availableMargin") or res.get("balance") or res.get("equity")
            try:
                return float(avail)
            except (ValueError, TypeError):
                pass
        return 10000.0 if self.testnet else 0.0

    # =========================================================================
    # Market Info & Quotes
    # =========================================================================

    def get_mark_price(self, symbol: str) -> float:
        """Fetch current price for symbol (e.g. XAU/USD).

        Order: PrimeXBT authenticated quote (real instrument price) ->
        Binance public price of the resolved real data source. Returns 0.0
        when nothing real is available (the engine then falls back to the
        last candle close). NO fake hard-coded prices.
        """
        clean_sym = symbol.strip().upper()
        # Authenticated PrimeXBT quote — only when keys are present, otherwise
        # every tick would burn 2 doomed 401 requests (latency + log spam).
        if self.api_key and self.private_key:
            res = self._request("POST", "/v3/trading/quotes", body={"symbols": [clean_sym]})
            if isinstance(res, dict) and not res.get("error"):
                quotes = res.get("quotes", [])
                for q in quotes:
                    if str(q.get("symbol", "")).upper() == clean_sym:
                        ask = float(q.get("ask", 0.0) or 0.0)
                        bid = float(q.get("bid", 0.0) or 0.0)
                        if ask > 0 and bid > 0:
                            return (ask + bid) / 2.0
                        return ask or bid

            # Fallback public market quote from PrimeXBT catalogue
            try:
                m_res = self._request("POST", "/v3/trading/markets", body={})
                if isinstance(m_res, dict) and "markets" in m_res:
                    for m in m_res["markets"]:
                        if str(m.get("symbol", "")).upper() == clean_sym:
                            px = float(m.get("price") or m.get("ask") or m.get("bid") or 0.0)
                            if px > 0:
                                return px
            except Exception:
                pass

        # Real public fallback via Binance (futures first, then spot)
        try:
            resolved = self._resolve_binance_source(clean_sym)
        except RuntimeError:
            resolved = None  # rate-limited: engine falls back to last candle close
        if resolved:
            binance_sym, venue = resolved
            for v in ([venue] if venue else ["fapi", "spot"]):
                if v == "fapi":
                    url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={binance_sym}"
                else:
                    url = f"https://api.binance.com/api/v3/ticker/price?symbol={binance_sym}"
                try:
                    r = requests.get(url, timeout=4)
                    px = float(r.json().get("price", 0.0) or 0.0)
                    if px > 0:
                        return px
                except Exception:
                    continue

        return 0.0

    def _binance_klines(self, binance_sym: str, interval: str, limit: int, venue: str):
        """Fetch raw kline rows from Binance futures ('fapi') or spot.

        Returns list-of-rows on success, None when the symbol does not exist
        on that venue (-1121 Invalid symbol), raises RuntimeError on other
        API errors (rate limits, network) so callers can react properly.
        """
        if venue == "fapi":
            url = (f"https://fapi.binance.com/fapi/v1/klines"
                   f"?symbol={binance_sym}&interval={interval}&limit={max(10, min(int(limit), 1000))}")
        else:
            url = (f"https://api.binance.com/api/v3/klines"
                   f"?symbol={binance_sym}&interval={interval}&limit={max(10, min(int(limit), 1000))}")
        r = requests.get(url, timeout=6)
        data = r.json()
        if isinstance(data, list) and data and isinstance(data[0], list):
            return data
        if isinstance(data, dict):
            code = data.get("code")
            msg = str(data.get("msg") or "")
            if code == -1121 or "invalid symbol" in msg.lower():
                return None  # symbol does not exist on this venue
            raise RuntimeError(f"Binance {venue} error {code}: {msg}")
        return None

    def _resolve_binance_source(self, clean_sym: str) -> Optional[Tuple[str, Optional[str]]]:
        """Map a PrimeXBT symbol to a real Binance data source.

        Returns (binance_symbol, preferred_venue) or None when no real source
        exists. Resolutions are cached for _SRC_TTL seconds (including
        negative results) to avoid hammering public endpoints every tick.
        On Binance rate-limit errors a 60s probe cooldown is armed and the
        error re-raised (never misreported as 'unsupported').
        """
        now = time.time()
        # Rate-limit cooldown: fail fast without hitting Binance
        cd_until = self._probe_cooldown.get(clean_sym, 0.0)
        if now < cd_until:
            raise RuntimeError(
                f"Binance rate limit cooldown active for {clean_sym} "
                f"(probe paused {int(cd_until - now)}s more)"
            )

        cached = self._src_cache.get(clean_sym)
        if cached and now - cached[2] < self._SRC_TTL:
            return (cached[0], cached[1]) if cached[0] else None

        binance_sym: Optional[str] = None
        s = clean_sym.upper().replace(" ", "")
        if s in self._GOLD_ALIASES or s.startswith("XAU") or s.startswith("GOLD"):
            binance_sym = "PAXGUSDT"  # 1 PAXG = 1 troy oz — real gold market proxy
        else:
            m = re.match(r"^([A-Z0-9]{2,15})/(USD|USDT)$", s)
            if m and m.group(1) != "XAG":  # silver has no reliable crypto proxy
                binance_sym = f"{m.group(1)}USDT"

        if not binance_sym:
            self._src_cache[clean_sym] = (None, None, now)
            return None

        # Probe which venue actually lists it (futures first).
        # A rate-limited venue is skipped (not fatal): the other venue may
        # still be clean — e.g. fapi banned while spot works keeps the bot
        # trading. Only when BOTH venues are rate-limited do we raise.
        venue: Optional[str] = None
        last_rl_err: Optional[str] = None
        for v in ("fapi", "spot"):
            try:
                probe = self._binance_klines(binance_sym, "5m", 2, v)
            except RuntimeError as e:
                if "429" in str(e) or "418" in str(e) or "too many" in str(e).lower() or "banned" in str(e).lower():
                    last_rl_err = str(e)
                    continue  # try the other venue before giving up
                continue
            if probe:
                venue = v
                break

        if venue:
            self._src_cache[clean_sym] = (binance_sym, venue, now)
            return (binance_sym, venue)
        if last_rl_err:
            # All venues rate-limited: arm a 60s cooldown so we do not
            # hammer Binance every tick, then surface the rate-limit error
            # (never misreport it as 'unsupported').
            self._probe_cooldown[clean_sym] = now + self._PROBE_COOLDOWN
            raise RuntimeError(last_rl_err)
        self._src_cache[clean_sym] = (None, None, now)
        return None

    def get_all_symbols(self) -> List[str]:
        """Fetch all tradable instruments across CFDs, Forex, Metals, and Crypto."""
        try:
            res = self._request("POST", "/v3/trading/markets", body={})
            if isinstance(res, dict) and "markets" in res:
                syms = [m.get("symbol") for m in res["markets"] if m.get("symbol")]
                if syms:
                    return sorted(list(set(syms)))
        except Exception as e:
            logger.warning("PrimeXBT markets catalogue fetch fallback: %s", e)

        return self.DEFAULT_SYMBOLS

    def get_symbol_filters(self, symbol: str) -> dict:
        """Fetch min order quantity, precision, and max leverage for symbol."""
        clean_sym = symbol.strip().upper()
        # Defaults based on asset class
        max_lev = 1000 if ("XAU" in clean_sym or "GOLD" in clean_sym or "EUR" in clean_sym) else 200
        min_qty = 0.01 if ("XAU" in clean_sym or "GOLD" in clean_sym) else 0.001

        try:
            res = self._request("POST", "/v3/trading/settings", body={"symbols": [clean_sym]})
            if isinstance(res, dict) and "settings" in res:
                for s in res["settings"]:
                    if s.get("symbol") == clean_sym:
                        return {
                            "min_qty": float(s.get("minQty", min_qty)),
                            "max_qty": float(s.get("maxQty", 100000)),
                            "qty_step": float(s.get("qtyStep", min_qty)),
                            "max_leverage": int(s.get("maxLeverage", max_lev)),
                        }
        except Exception:
            pass

        return {
            "min_qty": min_qty,
            "max_qty": 100000.0,
            "qty_step": min_qty,
            "max_leverage": max_lev,
        }

    # =========================================================================
    # Leverage & Margin
    # =========================================================================

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        """Configure cross margin leverage (up to 1000x on Metals/Forex, 200x on Crypto)."""
        clean_sym = symbol.strip().upper()
        filters = self.get_symbol_filters(clean_sym)
        max_allowed = filters.get("max_leverage", 1000)
        target_lev = max(1, min(max_allowed, int(leverage)))

        # Attempt remote margin update on PrimeXBT
        res = self._request(
            "POST",
            "/v3/trading/margins/change",
            body={"symbol": clean_sym, "leverage": target_lev},
        )
        self._symbol_leverage[clean_sym] = target_lev
        logger.info("PrimeXBT leverage set to %dx for %s", target_lev, clean_sym)
        return {
            "success": True,
            "leverage": target_lev,
            "adjusted": target_lev != leverage,
            "max_allowed": max_allowed,
            "raw": res,
        }

    # =========================================================================
    # Positions
    # =========================================================================

    def get_position(self, symbol: str) -> PrimeXBTPosition:
        """Get current open position for symbol."""
        clean_sym = symbol.strip().upper()
        if not self.api_key or not self.private_key:
            return PrimeXBTPosition(symbol=clean_sym, side="NONE")

        res = self._request("GET", "/v3/trading/positions")
        if isinstance(res, list):
            positions_list = res
        elif isinstance(res, dict):
            positions_list = res.get("positions", [])
        else:
            positions_list = []

        for p in positions_list:
            p_sym = str(p.get("symbol", "")).strip().upper()
            if p_sym == clean_sym:
                raw_side = str(p.get("side", "")).upper()
                side = "LONG" if raw_side in ("BUY", "LONG") else ("SHORT" if raw_side in ("SELL", "SHORT") else "NONE")
                size = abs(float(p.get("qty") or p.get("size") or 0.0))
                if size <= 0:
                    continue
                entry = float(p.get("entryPrice") or p.get("openPrice") or 0.0)
                pnl = float(p.get("unrealizedPnl") or p.get("pnl") or 0.0)
                lev = int(p.get("leverage") or self._symbol_leverage.get(clean_sym, 100))
                pos_id = str(p.get("id") or p.get("positionId") or "")
                mark = self.get_mark_price(clean_sym) or entry
                return PrimeXBTPosition(
                    symbol=clean_sym,
                    side=side,
                    size=size,
                    entry_price=entry,
                    mark_price=mark,
                    unrealized_pnl=pnl,
                    leverage=lev,
                    position_id=pos_id,
                )

        return PrimeXBTPosition(symbol=clean_sym, side="NONE")

    def get_all_positions(self) -> List[PrimeXBTPosition]:
        """Fetch all open positions across account."""
        if not self.api_key or not self.private_key:
            return []

        res = self._request("GET", "/v3/trading/positions")
        positions_list = res if isinstance(res, list) else (res.get("positions", []) if isinstance(res, dict) else [])
        results = []
        for p in positions_list:
            sym = str(p.get("symbol", "")).strip().upper()
            raw_side = str(p.get("side", "")).upper()
            side = "LONG" if raw_side in ("BUY", "LONG") else ("SHORT" if raw_side in ("SELL", "SHORT") else "NONE")
            size = abs(float(p.get("qty") or p.get("size") or 0.0))
            if size > 0:
                results.append(
                    PrimeXBTPosition(
                        symbol=sym,
                        side=side,
                        size=size,
                        entry_price=float(p.get("entryPrice") or 0.0),
                        mark_price=self.get_mark_price(sym),
                        unrealized_pnl=float(p.get("unrealizedPnl") or 0.0),
                        leverage=int(p.get("leverage") or 100),
                        position_id=str(p.get("id") or ""),
                    )
                )
        return results

    # =========================================================================
    # Orders & Execution
    # =========================================================================

    def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
    ) -> dict:
        """Place market order on PrimeXBT."""
        clean_sym = symbol.strip().upper()
        prime_side = "BUY" if side.upper() in ("BUY", "LONG") else "SELL"
        qty_val = round(float(qty), 4)

        payload = {
            "symbol": clean_sym,
            "side": prime_side,
            "qty": qty_val,
        }

        # If protective stop/profit provided
        if sl_price:
            payload["stopLoss"] = round(float(sl_price), 4)
        if tp_price:
            payload["takeProfit"] = round(float(tp_price), 4)

        logger.info("Placing PrimeXBT %s %s qty=%.4f on %s", order_type, prime_side, qty_val, clean_sym)
        res = self._request("POST", "/v3/trading/orders/market/place", body=payload)

        if isinstance(res, dict) and not res.get("error"):
            order_id = res.get("orderId") or res.get("id")
            return {
                "success": True,
                "order_id": order_id,
                # Engine's _log_order() reads result["order"]["orderId"]
                "order": {"orderId": order_id},
                "symbol": clean_sym,
                "side": prime_side,
                "qty": qty_val,
                "quantity": qty_val,
                "raw": res,
            }

        return {
            "success": False,
            "error": res.get("error") or "Order placement failed",
            "symbol": clean_sym,
        }

    # =========================================================================
    # Engine-compatible order interface (same shape as Binance/WEEX traders)
    # =========================================================================

    def open_long(self, symbol: str, quantity: float,
                  sl_price: Optional[float] = None, tp_price: Optional[float] = None,
                  order_type: str = "market", price: Optional[float] = None) -> dict:
        """Open a LONG position (market) with optional exchange-side SL/TP."""
        return self.place_order(symbol, "BUY", quantity, order_type="MARKET",
                                sl_price=sl_price, tp_price=tp_price)

    def open_short(self, symbol: str, quantity: float,
                   sl_price: Optional[float] = None, tp_price: Optional[float] = None,
                   order_type: str = "market", price: Optional[float] = None) -> dict:
        """Open a SHORT position (market) with optional exchange-side SL/TP."""
        return self.place_order(symbol, "SELL", quantity, order_type="MARKET",
                                sl_price=sl_price, tp_price=tp_price)

    def compute_quantity(self, notional_usdt: float, price: float,
                         leverage: int, qty_step: float = 0.001) -> float:
        """Convert USDT notional into base-asset quantity, rounded DOWN to step."""
        if price <= 0:
            return 0.0
        raw_qty = notional_usdt / price
        return self._round_to_step(raw_qty, qty_step) if qty_step > 0 else round(raw_qty, 8)

    @staticmethod
    def _round_to_step(value: float, step: float) -> float:
        if step <= 0:
            return value
        decimals = max(0, int(math.ceil(-math.log10(step))))
        return round(math.floor(value / step) * step, decimals)

    def close_position(self, symbol: str) -> dict:
        """Market close active position on PrimeXBT."""
        clean_sym = symbol.strip().upper()
        pos = self.get_position(clean_sym)
        if pos.side == "NONE" or pos.size <= 0:
            return {"success": True, "message": "No open position to close"}

        # Attempt position close via PrimeXBT endpoint
        if pos.position_id:
            res = self._request("POST", f"/v3/trading/positions/{pos.position_id}/close", body={})
            if res.get("success") or not res.get("error"):
                return {"success": True, "symbol": clean_sym, "closed_size": pos.size}

        # Fallback to general symbol close
        res = self._request("POST", "/v3/trading/positions/close", body={"symbol": clean_sym})
        return res

    def reverse_position(self, symbol: str) -> dict:
        """Native instant position reversal on PrimeXBT."""
        clean_sym = symbol.strip().upper()
        res = self._request("POST", "/v3/trading/positions/reverse", body={"symbol": clean_sym})
        logger.info("PrimeXBT instant reverse on %s: %s", clean_sym, res)
        return res

    # =========================================================================
    # Candlestick Klines (for EMA strategy calculations)
    # =========================================================================

    def get_klines(self, symbol: str, interval: str = "1m", limit: int = 100) -> Optional[pd.DataFrame]:
        """Fetch REAL candlestick OHLCV data for the EMA strategy.

        PrimeXBT's own REST API does not provide public OHLCV history, so
        candles are sourced from Binance (futures first, spot fallback),
        which tracks the same underlying markets:
            Crypto "BTC/USD" -> BTCUSDT futures; Gold "XAU/USD" -> PAXGUSDT.

        NO synthetic candles are generated: if no real source exists for a
        symbol (e.g. XAG/USD silver, indices USTEC/US30/GER30, most forex),
        a clean "symbol not supported" error is raised and the engine skips
        the symbol instead of silently computing EMAs on noise.
        """
        clean_sym = symbol.strip().upper()
        tf_map = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
                  "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "8h": "8h",
                  "12h": "12h", "1d": "1d", "1w": "1w"}
        b_interval = tf_map.get(str(interval).lower())
        if not b_interval:
            raise ValueError(f"Timeframe '{interval}' not supported on PrimeXBT market data")

        resolved = self._resolve_binance_source(clean_sym)
        if not resolved:
            raise ValueError(
                f"symbol not supported on PrimeXBT market data: {clean_sym} "
                f"(no real candle source available; synthetic candles were removed)"
            )
        binance_sym, venue = resolved

        last_err: Optional[str] = None
        for v in ([venue] if venue else ["fapi", "spot"]):
            for _attempt in range(2):
                try:
                    rows = self._binance_klines(binance_sym, b_interval, limit, v)
                except RuntimeError as e:
                    last_err = str(e)
                    if "429" in last_err or "418" in last_err or "too many" in last_err.lower():
                        raise  # rate limited — engine has a dedicated pause path
                    time.sleep(0.5)
                    continue
                if rows:
                    records = [{
                        "open_time": int(row[0]),
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    } for row in rows]
                    df = pd.DataFrame(records)
                    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
                    df.set_index("open_time", inplace=True)
                    # Remember the working venue for subsequent ticks
                    self._src_cache[clean_sym] = (binance_sym, v, time.time())
                    return df[["open", "high", "low", "close", "volume"]]
                # None => symbol not listed on this venue; try the next venue
                break
        if last_err:
            raise RuntimeError(f"PrimeXBT klines fetch failed for {clean_sym}: {last_err}")
        raise ValueError(
            f"symbol not supported on PrimeXBT market data: {clean_sym} (no real candle source)"
        )

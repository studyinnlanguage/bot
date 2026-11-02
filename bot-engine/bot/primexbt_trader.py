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
        load_ssh_private_key,
    )
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False
    load_pem_private_key = None
    load_der_private_key = None
    load_ssh_private_key = None
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
    # Priority order — the exchange itself first, public markets as backup:
    #   1) PrimeXBT's OWN public price-history feed (GET /v3/trading/bars,
    #      no API key needed) — the same feed the PrimeXBT chart shows.
    #      Covers crypto, forex, metals, indices and tokenized stocks
    #      (BTC/USD, USTEC, US30, GER30, UK100, US500, XAU/USD, XAG/USD,
    #      EUR/USD ... AAPL, TSLA, NVDA ...). PRIMARY for every instrument
    #      the feed carries.
    #   2) Yahoo Finance — fallback for instruments NOT on the PrimeXBT
    #      bars feed (e.g. "GOLD 24/7", USOIL, JP225) and when the feed is
    #      unreachable: indices (^NDX/^DJI/^GDAXI/...), silver (SI=F),
    #      oil (CL=F/BZ=F) and real FX (EURUSD=X ...).
    #   3) Binance (futures first, spot fallback) — last-resort proxy for
    #      crypto ("BTC/USD" -> "BTCUSDT") and gold ("XAU/USD" ->
    #      "PAXGUSDT") when both PrimeXBT and Yahoo fail.
    # Symbols with NO real source anywhere raise a clean "symbol not
    # supported" error so the engine skips them. The old behaviour of
    # generating synthetic sawtooth candles (which made the EMA strategy
    # mathematically unable to trade, and would have traded on noise if it
    # could) has been REMOVED on purpose.
    _GOLD_ALIASES = ("XAU/USD", "XAUUSD", "GOLD", "GOLD/USD", "GOLD24/7",
                     "GOLD 24/7", "XAU/USDT", "PAXG/USD")
    _SRC_TTL = 600.0  # seconds a venue resolution stays cached
    _PROBE_COOLDOWN = 60.0  # seconds to pause Binance probing after a rate-limit hit

    # PrimeXBT barSize values for its own bars feed (note: NO 3m/6h/8h/12h —
    # those timeframes automatically fall back to Yahoo/Binance).
    _PXBT_BAR_SIZES = {"1m": "1M", "5m": "5M", "15m": "15M", "30m": "30M",
                       "1h": "1H", "2h": "2H", "4h": "4H", "1d": "1D", "1w": "1W"}
    _PXBT_BARS_NEG_TTL = 300.0  # seconds to remember symbols the feed rejects (HTTP 400)

    # Paper-mode fallback catalogue: instruments verified live on the
    # PrimeXBT bars feed (plus dashboard favourites served via the Yahoo
    # fallback). With API keys the FULL authenticated catalogue
    # (POST /v3/trading/markets) is used instead — every instrument
    # PrimeXBT carries, fetched straight from the exchange.
    _PAPER_SYMBOLS = [
        # Metals
        "XAU/USD", "XAG/USD", "XPT/USD", "XPD/USD",
        # Crypto CFDs
        "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD", "DOGE/USD",
        "AVAX/USD", "LINK/USD", "DOT/USD", "LTC/USD", "BNB/USD", "TRX/USD",
        "BTC/USDT", "ETH/USDT",
        # Forex majors & crosses
        "EUR/USD", "GBP/USD", "AUD/USD", "NZD/USD",
        "USD/JPY", "USD/CAD", "USD/CHF",
        "EUR/GBP", "EUR/JPY", "EUR/AUD", "GBP/JPY", "AUD/JPY",
        # Indices
        "USTEC", "US30", "US500", "GER30", "UK100", "AUS200",
        # Tokenized stocks (verified on the PrimeXBT bars feed)
        "AAPL", "TSLA", "NVDA", "AMZN", "META", "GOOG", "NFLX", "AMD",
        # Dashboard favourites NOT on the bars feed (served via Yahoo fallback)
        "GOLD 24/7", "USOIL", "UKOIL", "NATGAS", "JP225", "HK50",
    ]

    # ---------------------------------------------------------------------
    # Yahoo Finance real data (indices, silver, commodities, real FX rates)
    # ---------------------------------------------------------------------
    # Binance cannot proxy stock indices (USTEC/US30/GER30), silver or
    # commodities, and its EURUSDT/GBPUSDT order books are thin. Yahoo's free
    # chart API provides real OHLCV for all of them (no API key needed):
    #   USTEC -> ^NDX, US30 -> ^DJI, GER30 -> ^GDAXI, XAG/USD -> SI=F,
    #   EUR/USD -> EURUSD=X, GBP/USD -> GBPUSD=X, ... (generic CCC/CCC rule)
    # Binance stays as the fallback wherever a proxy exists. Indices only
    # produce NEW candles during their exchange's trading hours — outside
    # hours the last session's candles are served (no new signals, harmless).
    _YAHOO_SYMBOL_MAP = {
        "USTEC": "^NDX", "USTEC100": "^NDX", "NAS100": "^NDX", "NDX100": "^NDX",
        "US30": "^DJI", "DOW30": "^DJI", "DJ30": "^DJI", "WALLSTREET": "^DJI",
        "GER30": "^GDAXI", "GER40": "^GDAXI", "DAX30": "^GDAXI", "DAX40": "^GDAXI",
        "UK100": "^FTSE", "FTSE100": "^FTSE",
        "JP225": "^N225", "NIKKEI225": "^N225", "NIKKEI": "^N225",
        "HK50": "^HSI", "AUS200": "^AXJO",
        "XAG/USD": "SI=F", "XAGUSD": "SI=F", "SILVER": "SI=F",
        "USOIL": "CL=F", "WTI": "CL=F", "XTI/USD": "CL=F", "CRUDEOIL": "CL=F",
        "UKOIL": "BZ=F", "BRENT": "BZ=F", "XBR/USD": "BZ=F",
        "NATGAS": "NG=F", "NGAS": "NG=F",
        "XPT/USD": "PL=F", "PLATINUM": "PL=F", "XPD/USD": "PA=F", "PALLADIUM": "PA=F",
    }
    _FX_PAIR_RE = re.compile(r"^([A-Z]{3})/([A-Z]{3})$")  # EUR/USD -> EURUSD=X
    _YAHOO_INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                        "1h": "60m", "1d": "1d", "1w": "1wk"}
    _YAHOO_TTL = 600.0   # seconds a Yahoo symbol resolution stays cached
    _PRICE_TTL = 10.0    # seconds a Yahoo quote stays cached (get_mark_price)

    _PXBT_KEY_RE = re.compile(r"pxk_[A-Za-z0-9_\-]+")
    _PXBT_PRIV_STARTS = ("MC4CAQ", "MCowBQYDK2Vw", "MC4CAQAw", "LS0tLS1CRUdJTi", "-----BEGIN")

    @classmethod
    def _normalize_credentials(cls, config: dict):
        """Return (api_key, api_secret, warning) tolerating classic paste mistakes:
        key + private key merged on one line ("pxk_... MC4CAQ..."), swapped
        fields, the pxk_ token inside the Secret field, extra text/quotes.
        """
        cfg = config or {}
        raw_key = str(cfg.get("api_key") or "")
        raw_secret = str(cfg.get("api_secret") or "")
        key = " ".join(raw_key.split()).strip().strip('"').strip("'")
        secret = " ".join(raw_secret.split()).strip().strip('"').strip("'")
        warning = None

        def _has_pxk(s: str) -> bool:
            return bool(cls._PXBT_KEY_RE.search(s))

        def _priv_token(s: str):
            cands = [t for t in s.split() if t.startswith(cls._PXBT_PRIV_STARTS)]
            return max(cands, key=len) if cands else None

        if _has_pxk(key) and _priv_token(key) and not secret:
            secret = _priv_token(key)
            key = cls._PXBT_KEY_RE.search(key).group(0)
            warning = "API key and PRIVATE KEY were pasted together on one line - auto-split"
        elif _has_pxk(secret) and _priv_token(secret) and not key:
            key = cls._PXBT_KEY_RE.search(secret).group(0)
            secret = _priv_token(secret)
            warning = "API key and PRIVATE KEY were pasted together on one line - auto-split"
        elif _has_pxk(secret) and not _has_pxk(key) and _priv_token(key):
            key, secret = cls._PXBT_KEY_RE.search(secret).group(0), _priv_token(key)
            warning = "API Key and Secret fields were swapped - auto-corrected"
        else:
            if _has_pxk(key):
                m = cls._PXBT_KEY_RE.search(key)
                if m.group(0) != key:
                    key = m.group(0)
                    warning = "API key had extra text around it - auto-cleaned"
            if _has_pxk(secret):
                s2 = cls._PXBT_KEY_RE.sub("", secret).strip()
                if s2 != secret and _priv_token(s2):
                    secret = s2
                    warning = "Secret field contained the API key - cleaned"

        return key, secret, warning

    def __init__(self, config: dict):
        self.config = config or {}
        self.api_key, self.api_secret, self.credential_warning = self._normalize_credentials(self.config)
        if self.credential_warning:
            logger.warning("PrimeXBT credentials: %s", self.credential_warning)
        self.testnet = bool(self.config.get("testnet", True))
        self.private_key: Optional[Ed25519PrivateKey] = None
        self._symbol_leverage: Dict[str, int] = {}
        # symbol -> (binance_symbol or None, preferred venue or None, cached_at_ts)
        self._src_cache: Dict[str, Tuple[Optional[str], Optional[str], float]] = {}
        # symbol -> ts until which Binance probing is paused (rate-limit backoff)
        self._probe_cooldown: Dict[str, float] = {}
        # symbol -> (yahoo_symbol or None, cached_at_ts)
        self._yahoo_cache: Dict[str, Tuple[Optional[str], float]] = {}
        # symbol -> (price, cached_at_ts) — short-TTL cache for Yahoo quotes
        self._price_cache: Dict[str, Tuple[float, float]] = {}
        # symbol -> ts until which the PrimeXBT bars feed is not probed again
        # (HTTP 400 = instrument not on the feed; avoid re-probing every tick)
        self._pxbt_bars_neg: Dict[str, float] = {}
        # last full catalogue fetched with API keys (stale-cache fallback)
        self._catalogue_cache: Optional[List[str]] = None
        self._init_crypto_keys()

    def _init_crypto_keys(self):
        """Load the PrimeXBT Ed25519 private key from the Secret Key field.

        Users paste the key in MANY shapes depending on where/how it was
        generated, so EVERY common format is tried before giving up:
          1. Raw base64 of PKCS#8 DER          (PrimeXBT's default display)
          2. PEM PKCS#8 ("-----BEGIN PRIVATE KEY-----")
          3. OpenSSH ("-----BEGIN OPENSSH PRIVATE KEY-----")
        Quotes, whitespace, newlines and surrounding armor text are tolerated.

        A key that fails to load is reported LOUDLY (error, not a quiet
        warning): without it PrimeXBT rejects every order with the cryptic
        "Sign the request: X-API-KEY, X-API-TIMESTAMP and X-API-SIGNATURE
        are all required" - while market data keeps working (it is public),
        so the failure otherwise only surfaces at trade time.
        """
        self.private_key = None
        if not self.api_secret:
            logger.error(
                "PrimeXBT: Secret Key is EMPTY - orders will be REJECTED "
                "(market data still works because it is public). Paste the "
                "Ed25519 PRIVATE KEY from PrimeXBT API settings."
            )
            return
        if not HAS_CRYPTOGRAPHY:
            logger.error(
                "PrimeXBT: 'cryptography' library missing - orders will be "
                "REJECTED. Install it with: pip install cryptography"
            )
            return

        raw = str(self.api_secret).strip().strip('"').strip("'")
        candidates: List[str] = [raw]
        # Base64 body with all PEM/SSH armor lines stripped (one long string)
        body = "".join(
            ln.strip() for ln in raw.splitlines()
            if ln.strip() and not ln.strip().startswith("-----")
        )
        if body and body != raw:
            candidates.append(body)

        for cand in candidates:
            # 1) base64 -> PKCS#8 DER (padding-tolerant)
            try:
                padded = cand + "=" * (-len(cand) % 4)
                der = base64.b64decode(padded, validate=False)
                self.private_key = load_der_private_key(der, password=None)
                break
            except Exception:
                self.private_key = None
            # 2) as-is PEM (PKCS#8)
            try:
                self.private_key = load_pem_private_key(cand.encode("utf-8"), password=None)
                break
            except Exception:
                self.private_key = None
            # 3) as-is OpenSSH format
            try:
                if load_ssh_private_key is not None:
                    self.private_key = load_ssh_private_key(cand.encode("utf-8"), password=None)
                    break
            except Exception:
                self.private_key = None

        if self.private_key is not None and not isinstance(self.private_key, Ed25519PrivateKey):
            logger.error(
                "PrimeXBT: Secret Key is a valid private key but NOT Ed25519 "
                "(%s) - PrimeXBT requires Ed25519. Re-create the API key on "
                "PrimeXBT and paste the new PRIVATE KEY.",
                type(self.private_key).__name__,
            )
            self.private_key = None

        if self.private_key is not None:
            logger.info("PrimeXBT Ed25519 private key loaded successfully.")
        else:
            logger.error(
                "PrimeXBT: Secret Key could NOT be parsed as an Ed25519 "
                "private key (tried base64 DER, PEM and OpenSSH formats) - "
                "orders will be REJECTED by PrimeXBT. Re-create the API key "
                "on PrimeXBT and paste the PRIVATE KEY into the Secret Key "
                "field."
            )

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

    def get_balance_or_none(self) -> Optional[float]:
        """REAL balance from /v3/trading/metrics, or None when unavailable.

        Unlike get_balance() this never returns the fake paper fallback
        ($10,000 / 0), so callers can honestly tell a LIVE balance apart
        from "no data" (keys missing, network error, bad signature).
        """
        if not self.api_key or not self.private_key:
            return None
        res = self._request("GET", "/v3/trading/metrics")
        if isinstance(res, dict) and "success" not in res:
            avail = (res.get("availableMargin")
                     or res.get("balance")
                     or res.get("equity"))
            try:
                return float(avail)
            except (TypeError, ValueError):
                return None
        return None

    def env_label(self) -> str:
        # PrimeXBT has NO demo/testnet server: keys loaded = REAL account.
        return "LIVE" if (self.api_key and self.private_key) else "PAPER"

    def validate_credentials(self, timeout: int = 15) -> dict:
        """PrimeXBT pre-flight check (read-only signed /v3/trading/metrics).

        Same uniform structure as the Binance validator so the engine and the
        dashboard can treat every exchange identically. No order is placed.
        """
        result = {
            "ok": False,
            "error_code": None,
            "error": None,
            "message": "",
            "balance": None,
            "can_trade": None,   # PrimeXBT API exposes no read-only canTrade flag
            "env": self.env_label(),
            "exchange": "primexbt",
            "demo": False,       # PrimeXBT has no demo server — always real
        }
        if not self.api_key:
            result["message"] = ("PrimeXBT API Key missing. Settings mein API Key paste karo.")
            return result
        if not self.private_key:
            result["error_code"] = 401
            result["error"] = "Ed25519 private key not loaded"
            result["message"] = (
                "PrimeXBT Secret Key load NAHI hua (Ed25519 PRIVATE KEY chahiye, "
                "public key ya HMAC secret nahi). PrimeXBT API settings se "
                "PRIVATE KEY copy karke Secret Key field mein paste karo.")
            return result
        bal = self.get_balance_or_none()
        if bal is not None:
            result["ok"] = True
            result["balance"] = bal
            result["message"] = (f"Auth OK (LIVE) - Balance ${bal:,.2f} "
                                 f"(PrimeXBT has no demo server - every order is REAL)")
            return result
        res = self._request("GET", "/v3/trading/metrics")
        status_code = res.get("status_code") if isinstance(res, dict) else None
        err = res.get("error") if isinstance(res, dict) else str(res)
        result["error_code"] = status_code
        result["error"] = err
        if status_code == 401:
            result["message"] = (
                "PrimeXBT auth REJECTED (401 Invalid API key or signature): "
                "1) API Key sahi ho 2) Secret Key field mein Ed25519 PRIVATE KEY ho "
                "3) API key active ho aur trading permission ON ho.")
        else:
            result["message"] = f"PrimeXBT auth failed: {str(err)[:200]}"
        return result

    def test_connection(self) -> dict:
        """PrimeXBT-specific connection test with HONEST mode labeling.

        The base-class test_connection() hardcodes exchange="binance" and
        demo=self.testnet - both wrong for PrimeXBT. PrimeXBT has NO
        demo/testnet server: with keys loaded every request hits the REAL
        account, so a successful check always says LIVE. Without keys the
        bot runs in paper mode (fake balance) and says so explicitly.
        """
        if not self.api_key or not self.private_key:
            return {
                "success": False,
                "error": "PrimeXBT API keys missing - paper mode (fake balance)",
                "cause": ("API Key is not set, or the Secret Key could not be "
                          "loaded as an Ed25519 private key"),
                "fix": ("Paste the API Key and the Ed25519 PRIVATE KEY (from "
                        "PrimeXBT API settings) into Settings, then restart "
                        "the bot"),
                "exchange": "primexbt",
                "demo": True,
            }
        bal = self.get_balance_or_none()
        if bal is not None:
            return {
                "success": True,
                "message": (f"Connected to PrimeXBT LIVE! Balance: ${bal:,.2f} "
                            f"(real account - PrimeXBT has no demo server)"),
                "balance": bal,
                "exchange": "primexbt",
                "demo": False,
            }
        return {
            "success": False,
            "error": ("PrimeXBT /v3/trading/metrics call failed - balance "
                      "unavailable (signature or network problem)"),
            "cause": ("The signed metrics request was rejected or timed out; "
                      "market data works but the private account is unreadable"),
            "fix": ("Check that the Secret Key field holds the Ed25519 PRIVATE "
                    "KEY (not the public key), then restart the bot"),
            "exchange": "primexbt",
            "demo": False,
        }

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

        # PrimeXBT's OWN public price: last close of the exchange's bars feed
        # (real instrument price, no key needed — the same feed as the chart).
        now_ts = time.time()
        pc_px = self._price_cache.get(("pxbt", clean_sym))
        if pc_px and now_ts - pc_px[1] < 5.0:
            return pc_px[0]
        try:
            pdf = self._pxbt_bars(clean_sym, "5m", 2)
        except Exception:
            pdf = None
        if pdf is not None and len(pdf) > 0:
            px = float(pdf["close"].iloc[-1])
            if px > 0:
                self._price_cache[("pxbt", clean_sym)] = (px, now_ts)
                return px

        # Real public quote from Yahoo for instruments Binance cannot price
        # (indices, silver, commodities, real FX) — cached a few seconds.
        try:
            y_sym = self._resolve_yahoo_source(clean_sym)
        except Exception:
            y_sym = None
        if y_sym:
            now_ts = time.time()
            pc = self._price_cache.get(clean_sym)
            if pc and now_ts - pc[1] < self._PRICE_TTL:
                return pc[0]
            try:
                px = self._yahoo_quote(y_sym)
                if px > 0:
                    self._price_cache[clean_sym] = (px, now_ts)
                    return px
            except Exception as e:
                logger.warning("Yahoo quote failed for %s (%s): %s", clean_sym, y_sym, e)

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
            # Binance price failed (rate limit / ban) — Yahoo aggregate quote
            # for crypto ("BTCUSDT" -> "BTC-USD") as a last real-data resort.
            s2 = binance_sym[:-4] if binance_sym.endswith("USDT") else binance_sym
            if s2 and s2 != "PAXG":
                try:
                    px = self._yahoo_quote(f"{s2}-USD")
                    if px > 0:
                        return px
                except Exception:
                    pass

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

    # ---------------------------------------------------------------------
    # Yahoo Finance helpers
    # ---------------------------------------------------------------------

    def _resolve_yahoo_source(self, clean_sym: str) -> Optional[str]:
        """Map a PrimeXBT symbol to a Yahoo Finance chart symbol (cached).

        Returns None when the symbol is a pure crypto-style pair that Yahoo
        does not serve (those are handled by the Binance path).
        """
        now = time.time()
        cached = self._yahoo_cache.get(clean_sym)
        if cached and now - cached[1] < self._YAHOO_TTL:
            return cached[0]
        s = clean_sym.upper().replace(" ", "")
        y_sym = self._YAHOO_SYMBOL_MAP.get(s) or self._YAHOO_SYMBOL_MAP.get(clean_sym.upper())
        if not y_sym:
            m = self._FX_PAIR_RE.match(s)
            # XAU/USD is handled by Binance PAXG (Yahoo has no XAUUSD=X)
            if m and m.group(1) != "XAU":
                y_sym = f"{m.group(1)}{m.group(2)}=X"  # e.g. EUR/USD -> EURUSD=X
        self._yahoo_cache[clean_sym] = (y_sym, now)
        return y_sym

    def _yahoo_chart(self, yahoo_sym: str, y_interval: str, rng: str) -> Optional[dict]:
        """GET Yahoo chart payload. Returns result[0] dict, or None when the
        symbol is unknown / has no data. Raises RuntimeError on rate limits
        and network failures so callers can distinguish real errors."""
        url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
               + requests.utils.quote(yahoo_sym, safe="")
               + f"?interval={y_interval}&range={rng}&includePrePost=false")
        r = requests.get(url, timeout=8, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) trading-bot/2.0"})
        if r.status_code == 429:
            raise RuntimeError("Yahoo rate limit (429)")
        try:
            data = r.json()
        except Exception:
            raise RuntimeError(f"Yahoo bad response (HTTP {r.status_code})")
        result = ((data or {}).get("chart") or {}).get("result") or []
        if not result:
            return None
        return result[0]

    def _yahoo_klines(self, yahoo_sym: str, b_interval: str, limit: int) -> Optional[pd.DataFrame]:
        """Fetch real OHLCV from Yahoo and return a Binance-style DataFrame.

        Timeframes Yahoo does not offer natively (2h..12h, 3m) are aggregated
        from the closest native interval. Returns None when no usable data;
        raises RuntimeError on rate limits/network failures.
        """
        y_interval = self._YAHOO_INTERVALS.get(b_interval)
        resample_rule: Optional[str] = None
        if y_interval is None:
            if b_interval in ("2h", "4h", "6h", "8h", "12h"):
                y_interval, resample_rule = "60m", b_interval
            elif b_interval == "3m":
                y_interval, resample_rule = "1m", "3min"
            else:
                return None
        if y_interval == "1m":
            rng = "7d"            # Yahoo caps 1m history per request
        elif y_interval in ("5m", "15m", "30m"):
            rng = "1mo"           # intraday history up to 60d; 1mo is plenty
        elif y_interval == "60m":
            rng = "3mo"
        elif y_interval == "1d":
            rng = "1y"
        else:
            rng = "5y"

        res: Optional[dict] = None
        last_err: Optional[str] = None
        for attempt in range(2):
            try:
                res = self._yahoo_chart(yahoo_sym, y_interval, rng)
                break
            except RuntimeError as e:
                last_err = str(e)
                if attempt == 0:
                    time.sleep(0.8)
                    continue
        if res is None:
            if last_err:
                raise RuntimeError(f"Yahoo fetch failed for {yahoo_sym}: {last_err}")
            return None

        ts = res.get("timestamp") or []
        quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        vols = quote.get("volume") or []

        records = []
        for i, t in enumerate(ts):
            if i >= len(opens) or i >= len(highs) or i >= len(lows) or i >= len(closes):
                break
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            if o is None or h is None or l is None or c is None:
                continue
            v = vols[i] if i < len(vols) and vols[i] is not None else 0.0
            records.append({
                "open_time": int(t) * 1000,
                "open": float(o), "high": float(h), "low": float(l),
                "close": float(c), "volume": float(v),
            })
        if not records:
            return None
        df = pd.DataFrame(records)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        if resample_rule:
            df = (df.resample(resample_rule, label="left", closed="left")
                    .agg({"open": "first", "high": "max", "low": "min",
                          "close": "last", "volume": "sum"})
                    .dropna(subset=["open", "high", "low", "close"]))
        return df[["open", "high", "low", "close", "volume"]]

    def _yahoo_quote(self, yahoo_sym: str) -> float:
        """Latest real price from Yahoo (regularMarketPrice, else last close)."""
        res = self._yahoo_chart(yahoo_sym, "5m", "1d")
        if not res:
            return 0.0
        meta = res.get("meta") or {}
        try:
            px = float(meta.get("regularMarketPrice") or 0.0)
        except (TypeError, ValueError):
            px = 0.0
        if px > 0:
            return px
        quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
        closes = [c for c in (quote.get("close") or []) if c is not None]
        return float(closes[-1]) if closes else 0.0

    def get_all_symbols(self) -> List[str]:
        """Full PrimeXBT catalogue: crypto, forex, metals, indices, stocks.

        With API keys the authenticated /v3/trading/markets endpoint returns
        the complete live catalogue (every tradable instrument PrimeXBT
        carries, straight from the exchange). Without keys (paper mode) the
        verified PrimeXBT-native instrument list is served instead.
        """
        if self.api_key and self.private_key:
            try:
                res = self._request("POST", "/v3/trading/markets", body={})
                if isinstance(res, dict) and "markets" in res:
                    syms = sorted({str(m.get("symbol")).strip().upper()
                                   for m in res["markets"]
                                   if m.get("symbol") and m.get("tradable", True)})
                    if syms:
                        self._catalogue_cache = syms
                        logger.info("PrimeXBT catalogue: %d tradable instruments", len(syms))
                        return syms
            except Exception as e:
                logger.warning("PrimeXBT markets catalogue fetch failed: %s", e)
            # Stale catalogue beats an empty list (network blip mid-run)
            if self._catalogue_cache:
                return list(self._catalogue_cache)
        return list(self._PAPER_SYMBOLS)

    # =========================================================================
    # PrimeXBT's own price history (PRIMARY candle source)
    # =========================================================================

    def _pxbt_bars(self, clean_sym: str, b_interval: str, limit: int) -> Optional[pd.DataFrame]:
        """Fetch REAL candles from PrimeXBT's own public price-history feed.

        GET /v3/trading/bars needs no API key and serves the same feed the
        PrimeXBT chart shows (bars of the market bid, oldest first, up to
        500 per request). Returns a DataFrame ([open, high, low, close,
        volume] indexed by open time) or None when the instrument is not on
        the feed (HTTP 400 / empty) or the request failed — callers then
        fall back to Yahoo/Binance. Feed rejections are remembered for
        _PXBT_BARS_NEG_TTL seconds; transient errors are never cached.
        """
        bar_size = self._PXBT_BAR_SIZES.get(b_interval)
        if not bar_size:
            return None  # timeframe the feed does not offer (3m/6h/8h/12h)
        now_ts = time.time()
        neg = self._pxbt_bars_neg.get(clean_sym)
        if neg and now_ts < neg:
            return None
        try:
            r = requests.get(
                f"{self.BASE_URL}/v3/trading/bars",
                params={"symbol": clean_sym, "barSize": bar_size,
                        "limit": max(10, min(int(limit), 500))},
                timeout=8,
            )
            if r.status_code == 400:
                # Instrument exists on PrimeXBT but has no entry on this
                # public feed (e.g. "GOLD 24/7", USOIL, JP225) — stop
                # probing it for a while, Yahoo/Binance serve instead.
                self._pxbt_bars_neg[clean_sym] = now_ts + self._PXBT_BARS_NEG_TTL
                return None
            if r.status_code != 200:
                logger.warning("PrimeXBT bars HTTP %s for %s — using fallback sources",
                               r.status_code, clean_sym)
                return None
            bars = (r.json() or {}).get("bars") or []
            if not bars:
                self._pxbt_bars_neg[clean_sym] = now_ts + self._PXBT_BARS_NEG_TTL
                return None
            df = pd.DataFrame([{
                "open_time": int(b["time"]),
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": float(b.get("volume") or 0.0),
            } for b in bars])
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
            df.set_index("open_time", inplace=True)
            out = df[["open", "high", "low", "close", "volume"]]
            logger.info("PrimeXBT bars: %d real candles for %s (%s) — exchange feed",
                        len(out), clean_sym, bar_size)
            return out
        except Exception as e:
            logger.warning("PrimeXBT bars request failed for %s: %s — using fallback sources",
                           clean_sym, e)
            return None

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
        """Configure cross margin leverage (up to 1000x on Metals/Forex, 200x on Crypto).

        HONEST result: the PrimeXBT API response is respected — a failed
        remote update is reported as success=False with the real error
        instead of silently claiming success.
        """
        clean_sym = symbol.strip().upper()
        filters = self.get_symbol_filters(clean_sym)
        max_allowed = filters.get("max_leverage", 1000)
        target_lev = max(1, min(max_allowed, int(leverage)))

        # Paper/testnet mode without API keys: no remote call would ever
        # succeed (unsigned requests get 401) — store locally and say so.
        if not self.api_key or not self.private_key:
            self._symbol_leverage[clean_sym] = target_lev
            logger.info(
                "PrimeXBT leverage %dx stored locally for %s (paper mode — no API keys)",
                target_lev, clean_sym,
            )
            return {
                "success": True,
                "leverage": target_lev,
                "adjusted": target_lev != leverage,
                "max_allowed": max_allowed,
                "note": "paper mode — no PrimeXBT API keys, leverage stored locally only",
            }

        # Attempt remote margin update on PrimeXBT.
        # The official ChangeMarginRequest schema REQUIRES marginType
        # (enum: CROSS | ISOLATED) next to symbol — omitting it makes
        # PrimeXBT reject the request with "marginType is required".
        # CROSS is PrimeXBT's standard mode (hedge accounts support cross
        # only); override in Settings via margin_type if ever needed.
        margin_type = str((self.config.get("margin_type") or "CROSS")).strip().upper()
        if margin_type not in ("CROSS", "ISOLATED"):
            margin_type = "CROSS"
        res = self._request(
            "POST",
            "/v3/trading/margins/change",
            body={"symbol": clean_sym, "marginType": margin_type,
                  "leverage": target_lev},
        )
        ok = isinstance(res, dict) and not res.get("error")
        if ok:
            self._symbol_leverage[clean_sym] = target_lev
            logger.info("PrimeXBT leverage set to %dx for %s", target_lev, clean_sym)
            return {
                "success": True,
                "leverage": target_lev,
                "adjusted": target_lev != leverage,
                "max_allowed": max_allowed,
                "raw": res,
            }
        err = res.get("error") if isinstance(res, dict) else str(res)
        logger.warning("PrimeXBT leverage update FAILED for %s (%dx): %s", clean_sym, target_lev, err)
        return {
            "success": False,
            "leverage": target_lev,
            "adjusted": False,
            "max_allowed": max_allowed,
            "error": f"PrimeXBT margin update failed: {err}",
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

        # Refuse EARLY when the Ed25519 private key is not usable. Sending the
        # order unsigned only earns PrimeXBT's cryptic "Sign the request:
        # X-API-KEY, X-API-TIMESTAMP and X-API-SIGNATURE are all required" -
        # a clear, actionable error is far better on a live signal.
        if self.private_key is None:
            logger.error(
                "PrimeXBT order REFUSED for %s: private key not loaded - "
                "check the Secret Key in settings (must be the Ed25519 "
                "PRIVATE KEY from PrimeXBT API settings).",
                clean_sym,
            )
            return {
                "success": False,
                "error": ("PrimeXBT: Secret Key missing/invalid - order cannot "
                          "be signed. Paste the Ed25519 PRIVATE KEY from "
                          "PrimeXBT API settings into the Secret Key field, "
                          "then restart the bot."),
                "symbol": clean_sym,
            }

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

        Priority — the exchange itself first, public markets as backup:
            1) PrimeXBT's OWN public price-history feed (GET
               /v3/trading/bars, no key needed) — the same data the
               PrimeXBT chart shows; covers crypto, forex, metals, indices
               and tokenized stocks.
            2) Yahoo Finance — instruments not on the PrimeXBT feed
               ("GOLD 24/7", USOIL, JP225, ...) and feed outages:
               indices "USTEC" -> ^NDX, "US30" -> ^DJI, "GER30" -> ^GDAXI,
               silver "XAG/USD" -> SI=F, commodities, real FX
               ("EUR/USD" -> EURUSD=X, "GBP/USD" -> GBPUSD=X).
            3) Binance (futures first, spot fallback) — crypto "BTC/USD" ->
               BTCUSDT, gold "XAU/USD" -> PAXGUSDT; also the fallback proxy
               for FX pairs (EURUSDT/GBPUSDT) when Yahoo is unreachable.

        NO synthetic candles are generated: if no real source exists for a
        symbol on any venue, a clean "symbol not supported" error is
        raised and the engine skips the symbol instead of silently computing
        EMAs on noise.
        """
        clean_sym = symbol.strip().upper()
        tf_map = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
                  "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "8h": "8h",
                  "12h": "12h", "1d": "1d", "1w": "1w"}
        b_interval = tf_map.get(str(interval).lower())
        if not b_interval:
            raise ValueError(f"Timeframe '{interval}' not supported on PrimeXBT market data")

        # --- 1) PrimeXBT's OWN public bars feed (the exchange itself) ---
        # NOTE: no freshness guard here on purpose — this IS the exchange's
        # own feed. On closed markets (weekend indices) the last session's
        # candles are exactly what the PrimeXBT chart shows; re-routing to
        # Yahoo/Binance would only serve the same closed-market data.
        pdf = self._pxbt_bars(clean_sym, b_interval, limit)
        if pdf is not None and len(pdf) > 0:
            return pdf.tail(max(10, int(limit)))
        # Not on the feed (or feed hiccup) — real public fallbacks below.

        # --- 2) Yahoo real data (indices, silver, commodities, real FX) ---
        y_sym: Optional[str] = None
        yahoo_status = "none"  # none | ok | no_data | error
        try:
            y_sym = self._resolve_yahoo_source(clean_sym)
        except Exception:
            y_sym = None
        if y_sym:
            try:
                ydf = self._yahoo_klines(y_sym, b_interval, limit)
                if ydf is not None and len(ydf) > 0:
                    yahoo_status = "ok"
                    return ydf.tail(max(10, int(limit)))
                yahoo_status = "no_data"  # Yahoo knows the symbol class but has no data for it
            except RuntimeError as e:
                yahoo_status = "error"  # transient (rate limit / network) — not 'unsupported'
                logger.warning("Yahoo klines failed for %s (%s): %s", clean_sym, y_sym, e)
            except Exception as e:
                yahoo_status = "error"
                logger.warning("Yahoo klines error for %s (%s): %s", clean_sym, y_sym, e)
            # fall through: a Binance proxy (e.g. EURUSDT for EUR/USD) may still exist

        # --- 3) Binance real data (crypto, PAXG gold, FX USDT proxies) ---
        binance_rate_limited = False
        resolved = None
        try:
            resolved = self._resolve_binance_source(clean_sym)
        except RuntimeError:
            # Probe hit a Binance rate limit / IP ban — remember and try the
            # Yahoo crypto fallback instead of crashing the tick.
            binance_rate_limited = True
        if not resolved:
            if binance_rate_limited:
                df_fb = self._yahoo_crypto_fallback(clean_sym, b_interval, limit)
                if df_fb is not None:
                    return df_fb
                raise RuntimeError(
                    f"Real market data temporarily unavailable for {clean_sym} "
                    f"(Binance rate-limited and no Yahoo source for this symbol)"
                )
            if y_sym:
                if yahoo_status == "error":
                    # Yahoo serves this symbol class but failed just now — do
                    # NOT misreport it as 'unsupported' (transient issue).
                    raise RuntimeError(
                        f"Real market data temporarily unavailable for {clean_sym} "
                        f"(Yahoo: {y_sym}; no Binance source for this symbol)"
                    )
                # Yahoo answered cleanly with no data -> the symbol genuinely
                # has no real source anywhere.
                raise ValueError(
                    f"symbol not supported on PrimeXBT market data: {clean_sym} "
                    f"(no real candle source available; synthetic candles were removed)"
                )
            raise ValueError(
                f"symbol not supported on PrimeXBT market data: {clean_sym} "
                f"(no real candle source available; synthetic candles were removed)"
            )
        binance_sym, venue = resolved

        last_err: Optional[str] = None
        best_df: Optional[pd.DataFrame] = None
        for v in ([venue] if venue else ["fapi", "spot"]):
            for _attempt in range(2):
                try:
                    rows = self._binance_klines(binance_sym, b_interval, limit, v)
                except RuntimeError as e:
                    last_err = str(e)
                    low = last_err.lower()
                    if ("429" in last_err or "418" in last_err or "-1003" in last_err
                            or "too many" in low or "too much" in low or "banned" in low):
                        binance_rate_limited = True
                        break  # stop hammering Binance — Yahoo fallback below
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
                    out = df[["open", "high", "low", "close", "volume"]]
                    # Freshness guard: a venue whose last candle is far behind
                    # (halted/delisted contract) must not be trusted — try the
                    # next venue (and finally Yahoo) before using stale data.
                    if self._df_is_fresh(df, b_interval):
                        # Remember the working venue for subsequent ticks
                        self._src_cache[clean_sym] = (binance_sym, v, time.time())
                        return out
                    logger.warning(
                        "Binance %s data for %s looks stale (last candle %s) — trying next venue/source",
                        v, binance_sym, df.index[-1])
                    if best_df is None:
                        best_df = out
                    break
                # None => symbol not listed on this venue; try the next venue
                break
            if binance_rate_limited:
                break

        if binance_rate_limited or best_df is not None:
            df_fb = self._yahoo_crypto_fallback(clean_sym, b_interval, limit)
            if df_fb is not None:
                return df_fb
        if best_df is not None:
            # Every venue stale and no Yahoo fallback — serve the freshest
            # real data we have (better than failing the tick entirely).
            return best_df
        if last_err:
            raise RuntimeError(f"PrimeXBT klines fetch failed for {clean_sym}: {last_err}")
        if y_sym:
            if yahoo_status == "error":
                raise RuntimeError(
                    f"Real market data temporarily unavailable for {clean_sym} "
                    f"(Yahoo: {y_sym}; no Binance source for this symbol)"
                )
            raise ValueError(
                f"symbol not supported on PrimeXBT market data: {clean_sym} (no real candle source)"
            )
        raise ValueError(
            f"symbol not supported on PrimeXBT market data: {clean_sym} (no real candle source)"
        )

    def _df_is_fresh(self, df: pd.DataFrame, b_interval: str) -> bool:
        """True when the last candle is recent enough for a 24/7 market.
        Generous 3-candle window so slow markets are never misjudged."""
        try:
            mult = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
                    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
                    "12h": 43200, "1d": 86400, "1w": 604800}[b_interval]
        except KeyError:
            return True
        try:
            last_ms = int(df.index[-1].value // 10**6)
        except Exception:
            return True
        return (int(time.time() * 1000) - last_ms) <= mult * 1000 * 3 + 120_000

    def _yahoo_crypto_fallback(self, clean_sym: str, b_interval: str, limit: int) -> Optional[pd.DataFrame]:
        """When Binance is rate-limited/IP-banned, serve REAL candles for
        crypto pairs from Yahoo's aggregate market ("BTC/USD" -> "BTC-USD").
        Returns None when no Yahoo data exists (caller raises the real error).
        """
        s = clean_sym.upper().replace(" ", "")
        # Gold aliases (XAU/USD, GOLD 24/7, GOLD/USD, ...) -> COMEX futures.
        # NOTE: "GOLD 24/7" does NOT match the crypto regex below (quote is
        # neither USD nor USDT), so gold must be detected before it.
        if s.startswith("XAU") or s.startswith("GOLD") or s in self._GOLD_ALIASES:
            # Gold: PAXG on Binance is primary; COMEX gold futures (GC=F) is
            # the Yahoo resilience fallback (trades ~23h/day).
            try:
                ydf = self._yahoo_klines("GC=F", b_interval, limit)
            except Exception:
                return None
            if ydf is not None and len(ydf) > 0:
                logger.warning("Binance unavailable for %s — served real candles from Yahoo (GC=F)",
                               clean_sym)
                return ydf.tail(max(10, int(limit)))
            return None
        m = re.match(r"^([A-Z0-9]{2,15})/(USD|USDT)$", s)
        if not m:
            return None
        base = m.group(1)
        try:
            ydf = self._yahoo_klines(f"{base}-USD", b_interval, limit)
        except Exception:
            return None
        if ydf is not None and len(ydf) > 0:
            logger.warning("Binance unavailable for %s — served real candles from Yahoo (%s-USD)",
                           clean_sym, base)
            return ydf.tail(max(10, int(limit)))
        return None

/* ─────────────────────────────────────────────────────────────────────────
 * wx-market.ts — REAL market data layer (Binance public REST, no keys).
 *
 * The Python bot reads live klines from the exchange; this module gives the
 * Weexionic engine the exact same inputs:
 *   - real candles per (symbol, timeframe)  → GET /api/v3/klines
 *   - live last price (all symbols, 1 call) → GET /api/v3/ticker/price
 *   - 24h change (batched)                  → GET /api/v3/ticker/24hr
 *
 * Everything is cached with sane TTLs and served stale on network failure so
 * the engine never crashes because of a data hiccup. Host failover included.
 * ──────────────────────────────────────────────────────────────────────── */

export interface Candle { t: number; o: number; h: number; l: number; c: number; }

export const SYMBOL_META: Record<string, { color: string; name: string; meme: boolean }> = {
  BTCUSDT:  { color: "#F7931A", name: "Bitcoin",  meme: false },
  ETHUSDT:  { color: "#A8A29E", name: "Ethereum", meme: false },
  SOLUSDT:  { color: "#9945FF", name: "Solana",   meme: false },
  BNBUSDT:  { color: "#F0B90B", name: "BNB",      meme: false },
  XRPUSDT:  { color: "#64748B", name: "XRP",      meme: false },
  DOGEUSDT: { color: "#C2A633", name: "Dogecoin", meme: true  },
};

export const ALL_SYMBOLS = Object.keys(SYMBOL_META);

export const TIMEFRAME_MS: Record<string, number> = {
  "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
  "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "1d": 86_400_000, "1w": 604_800_000,
};

const KLINES_LIMIT = 150;

/* Kline refresh cadence per timeframe (mirrors the Python bot poll pacing) */
function klineTtl(tf: string): number {
  switch (tf) {
    case "1m": return 8_000;
    case "3m": return 12_000;
    case "5m": return 15_000;
    case "15m": return 30_000;
    case "30m": return 45_000;
    case "1h": return 60_000;
    case "2h": return 90_000;
    case "4h": return 120_000;
    default: return 180_000; // 1d / 1w
  }
}

/* ───────────────────── Host failover ───────────────────── */

const HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"];
let goodHostIdx = 0;

async function fetchJson(path: string, timeoutMs = 9000): Promise<unknown | null> {
  for (let attempt = 0; attempt < HOSTS.length; attempt++) {
    const host = HOSTS[(goodHostIdx + attempt) % HOSTS.length];
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
      const res = await fetch(host + path, { signal: ctrl.signal, cache: "no-store" });
      clearTimeout(timer);
      if (!res.ok) continue;
      goodHostIdx = (goodHostIdx + attempt) % HOSTS.length;
      return await res.json();
    } catch {
      /* try next host */
    }
  }
  return null;
}

/* ───────────────────── Caches ───────────────────── */

interface CandleCache { candles: Candle[]; fetchedAt: number; }
interface PriceCache { prices: Record<string, number>; fetchedAt: number; }
interface ChangeCache { change: Record<string, number>; fetchedAt: number; }

const candleCache = new Map<string, CandleCache>();   // `${sym}:${tf}`
const inflight = new Map<string, Promise<Candle[] | null>>();
let priceCache: PriceCache = { prices: {}, fetchedAt: 0 };
let changeCache: ChangeCache = { change: {}, fetchedAt: 0 };

/* ───────────────────── Klines ───────────────────── */

export async function getCandles(symbol: string, timeframe: string): Promise<Candle[] | null> {
  const tf = TIMEFRAME_MS[timeframe] ? timeframe : "5m";
  const key = `${symbol}:${tf}`;
  const cached = candleCache.get(key);
  const now = Date.now();
  if (cached && now - cached.fetchedAt < klineTtl(tf)) return cached.candles;

  if (inflight.has(key)) return inflight.get(key)!;
  const p = (async () => {
    try {
      const raw = await fetchJson(
        `/api/v3/klines?symbol=${symbol}&interval=${tf}&limit=${KLINES_LIMIT}`);
      if (!Array.isArray(raw) || raw.length === 0) throw new Error("bad klines");
      const candles: Candle[] = (raw as (string | number)[][]).map(k => ({
        t: Number(k[0]),
        o: parseFloat(String(k[1])),
        h: parseFloat(String(k[2])),
        l: parseFloat(String(k[3])),
        c: parseFloat(String(k[4])),
      }));
      const last = candles[candles.length - 1];
      if (!Number.isFinite(last.c) || last.c <= 0) throw new Error("bad candle");
      candleCache.set(key, { candles, fetchedAt: Date.now() });
      return candles;
    } catch {
      return cached ? cached.candles : null;   // serve stale on failure
    } finally {
      inflight.delete(key);
    }
  })();
  inflight.set(key, p);
  return p;
}

/* ───────────────────── Live prices (batched) ───────────────────── */

async function refreshPrices(): Promise<void> {
  const now = Date.now();
  if (now - priceCache.fetchedAt < 3000) return;
  const q = encodeURIComponent(JSON.stringify(ALL_SYMBOLS));
  const raw = await fetchJson(`/api/v3/ticker/price?symbols=${q}`, 6000);
  if (Array.isArray(raw)) {
    const prices: Record<string, number> = { ...priceCache.prices };
    for (const row of raw as { symbol: string; price: string }[]) {
      const v = parseFloat(row.price);
      if (Number.isFinite(v) && v > 0) prices[row.symbol] = v;
    }
    priceCache = { prices, fetchedAt: now };
  }
}

export async function getPrice(symbol: string): Promise<number | null> {
  await refreshPrices();
  return priceCache.prices[symbol] ?? null;
}

/* ───────────────────── 24h change (batched) ───────────────────── */

export async function getChange24h(symbol: string): Promise<number> {
  const now = Date.now();
  if (now - changeCache.fetchedAt > 60_000) {
    const q = encodeURIComponent(JSON.stringify(ALL_SYMBOLS));
    const raw = await fetchJson(`/api/v3/ticker/24hr?symbols=${q}`, 8000);
    if (Array.isArray(raw)) {
      const change: Record<string, number> = {};
      for (const row of raw as { symbol: string; priceChangePercent: string }[]) {
        const v = parseFloat(row.priceChangePercent);
        if (Number.isFinite(v)) change[row.symbol] = v;
      }
      changeCache = { change, fetchedAt: now };
    }
  }
  return changeCache.change[symbol] ?? 0;
}

/* ───────────────────── Health ───────────────────── */

export function marketDataHealthy(): boolean {
  return Date.now() - priceCache.fetchedAt < 60_000;
}

/* ─────────────────────────────────────────────────────────────────────────
 * wx-engine.ts — Weexionic Quad-Trend Engine (REAL bot logic port)
 *
 * This is a 1:1 TypeScript port of the Python bot strategy
 * (bot-repo/bot-engine/bot/strategy.py + engine.py risk model):
 *
 *  • EMA 8/13/21/55 quad-trend fan, evaluated on the last CLOSED candle
 *      BUY : EMA55 below ALL lines  &&  EMA8 >= EMA13 >= EMA21
 *      SELL: EMA55 above ALL lines  &&  EMA8 <= EMA13 <= EMA21
 *  • Adaptive anti-chop spread filter (EMA8↔EMA55 separation in %,
 *    timeframe-aware defaults, meme coins +0.10%)
 *  • Fresh-cross window (default 6 candles, cross_age <= window-1)
 *  • Anti-whipsaw state machine (_trade_entered_for_signal / _last_trend_side)
 *  • Trend re-entry after reentry_cooldown_candles (default 10) since last entry
 *  • STRICT 1:1 risk lock: SL% = TP% (config, default 2.0%, floor 0.5%),
 *    ROE-scaled by leverage with the 80% cap: dist% = min(sl%×lev, 80)/lev
 *  • Fee guard: TP distance must be ≥ 0.15% of price
 *  • EMA55 reversal exit, max 3 concurrent positions, 1 per symbol,
 *    mode filter (long/short/both), 30s per-symbol entry pacing
 *  • REAL market data from wx-market.ts (Binance public klines/prices)
 * ──────────────────────────────────────────────────────────────────────── */

import { db } from "@/lib/db";
import {
  ALL_SYMBOLS, SYMBOL_META, TIMEFRAME_MS, Candle,
  getCandles, getPrice, getChange24h,
} from "@/lib/wx-market";

/* ─────────────────────────── Types ─────────────────────────── */

export interface Position {
  id: string;
  symbol: string;
  side: "LONG" | "SHORT";
  entry: number;
  qty: number;
  size: number;      // margin in USDT
  leverage: number;
  tpPrice: number;
  slPrice: number;
  slPct: number;     // price-distance % (after leverage ROE cap)
  openedAt: number;
}

export interface ClosedTrade {
  id: string;
  symbol: string;
  side: "LONG" | "SHORT";
  entry: number;
  exit: number;
  pnl: number;
  pnlPct: number;   // on margin (ROE)
  reason: "TP" | "SL" | "MANUAL" | "REVERSAL";
  openedAt: number;
  closedAt: number;
}

export interface LogEntry { t: number; level: "info" | "success" | "warn" | "error"; msg: string; }

export interface EngineRuntime {
  userId: string;
  running: boolean;
  balance: number;
  startBal: number;
  leverage: number;
  timeframe: string;
  tradeSize: number;
  stopLossPct: number;
  mode: "both" | "long" | "short";
  symbols: string[];
  positions: Position[];
  history: ClosedTrade[];
  logs: LogEntry[];
  lastTickAt: number;
  dirty: boolean;
  ticking: boolean;   // in-memory only — prevents concurrent ticks
  _reversalJustClosed?: string | null;   // transient — symbol just closed by reversal (allows instant flip)
}

/* Latest known live price per symbol (filled on every tick / snapshot). */
const lastPrices = new Map<string, number>();

/* ─────────────────────── Strategy constants (exact bot values) ─────────────────────── */

const EMA_SHORT = 8, EMA_MID1 = 13, EMA_MID2 = 21, EMA_LONG = 55;

/** Adaptive spread defaults — EMA8-to-EMA55 separation in % (strategy.py). */
const TIMEFRAME_SPREAD_DEFAULTS: Record<string, number> = {
  "1m": 0.15, "3m": 0.22, "5m": 0.30, "15m": 0.40, "30m": 0.50,
  "1h": 0.60, "2h": 0.80, "4h": 1.00, "1d": 1.50, "1w": 2.00,
};

const FRESH_CROSS_WINDOW = 6;         // candles
const REENTRY_COOLDOWN_CANDLES = 10;  // candles
const STRICT_SL_MIN = 0.5;            // hard floor on stop_loss_pct
const ROE_CAP = 80.0;                 // SL/TP can never exceed 80% ROE
const MIN_FEE_BUFFER_PCT = 0.15;      // min TP distance in % of price
const MAX_CONCURRENT = 3;             // max_concurrent_trades
const ENTRY_PACE_MS = 30_000;         // 30s cooldown between entries per symbol
const MIN_CANDLES = EMA_LONG + 5;     // strategy.analyze() length guard

/* ─────────────────────── Indicators (identical recursion to pandas ewm) ─────────────────────── */

function ema(values: number[], period: number): number[] {
  if (values.length === 0) return [];
  const k = 2 / (period + 1);
  const out: number[] = [values[0]];
  for (let i = 1; i < values.length; i++) out.push(values[i] * k + out[i - 1] * (1 - k));
  return out;
}

function minSpread(symbol: string, timeframe: string): number {
  const base = TIMEFRAME_SPREAD_DEFAULTS[timeframe] ?? 0.30;
  return SYMBOL_META[symbol]?.meme ? base + 0.10 : base;
}

/* ─────────────────────── Per-symbol strategy state (anti-whipsaw machine) ─────────────────────── */

interface StratState {
  tradeEnteredForSignal: boolean;
  lastTrendSide: "BUY" | "SELL" | null;   // stored as SIGNAL (exactly like Python _last_trend_side)
  lastEntryCandleTs: number | null;
  seeded: boolean;
}

const stratStates = new Map<string, StratState>();   // `${userId}:${symbol}`
const entryPace = new Map<string, number>();         // `${userId}:${symbol}` → last entry ts

function stratKey(userId: string, symbol: string): string {
  return `${userId}:${symbol}`;
}

/* ─────────────────────── Runtime persistence ─────────────────────── */

const runtimes = new Map<string, EngineRuntime>();

function defaultRuntime(userId: string): EngineRuntime {
  return {
    userId, running: false, balance: 10000, startBal: 10000,
    leverage: 20, timeframe: "5m", tradeSize: 180,
    stopLossPct: 2.0, mode: "both",
    symbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    positions: [], history: [], logs: [],
    lastTickAt: 0, dirty: false, ticking: false,
  };
}

export async function loadRuntime(userId: string): Promise<EngineRuntime> {
  let rt = runtimes.get(userId);
  if (rt) return rt;
  rt = defaultRuntime(userId);
  const row = await db.engineState.findUnique({ where: { userId } });
  if (row) {
    rt.running = row.running;
    rt.balance = row.balance;
    rt.startBal = row.startBal;
    rt.leverage = row.leverage;
    rt.timeframe = TIMEFRAME_MS[row.timeframe] ? row.timeframe : "5m";
    rt.tradeSize = row.tradeSize;
    rt.stopLossPct = row.stopLossPct > 0 ? row.stopLossPct : 2.0;
    rt.mode = row.mode === "long" || row.mode === "short" ? row.mode : "both";
    try { rt.symbols = JSON.parse(row.symbols); } catch { /* keep default */ }
    try { rt.positions = JSON.parse(row.positions); } catch { rt.positions = []; }
    try { rt.history = JSON.parse(row.history); } catch { rt.history = []; }
    try { rt.logs = JSON.parse(row.logs); } catch { rt.logs = []; }
  } else {
    await db.engineState.create({ data: { userId, symbols: JSON.stringify(rt.symbols) } });
  }
  runtimes.set(userId, rt);
  return rt;
}

async function persist(rt: EngineRuntime): Promise<void> {
  rt.dirty = false;
  try {
    await db.engineState.update({
      where: { userId: rt.userId },
      data: {
        running: rt.running, balance: rt.balance, startBal: rt.startBal,
        leverage: rt.leverage, timeframe: rt.timeframe, tradeSize: rt.tradeSize,
        stopLossPct: rt.stopLossPct, mode: rt.mode,
        symbols: JSON.stringify(rt.symbols),
        positions: JSON.stringify(rt.positions),
        history: JSON.stringify(rt.history.slice(-100)),
        logs: JSON.stringify(rt.logs.slice(-60)),
      },
    });
  } catch { /* non-fatal */ }
}

/* ─────────────────────── Helpers ─────────────────────── */

function log(rt: EngineRuntime, level: LogEntry["level"], msg: string) {
  rt.logs.push({ t: Date.now(), level, msg });
  if (rt.logs.length > 60) rt.logs.splice(0, rt.logs.length - 60);
  rt.dirty = true;
}

function fmt(n: number): string {
  if (!Number.isFinite(n)) return "--";
  return n >= 1000 ? n.toLocaleString("en-US", { maximumFractionDigits: 2 })
    : n >= 10 ? n.toFixed(2) : n.toFixed(4);
}

/** 1:1 risk lock with leverage ROE cap — engine.py `_set_software_sl_tp`. */
function riskPrices(entry: number, side: "LONG" | "SHORT", slPct: number, leverage: number) {
  const safeRoe = Math.min(slPct * leverage, ROE_CAP);
  const distPct = safeRoe / leverage;          // % of price
  const dist = entry * (distPct / 100);
  return {
    distPct,
    tp: side === "LONG" ? entry + dist : entry - dist,
    sl: side === "LONG" ? entry - dist : entry + dist,
  };
}

function openPosition(rt: EngineRuntime, symbol: string, side: "LONG" | "SHORT",
                      entry: number, reason: string): Position {
  const notional = rt.tradeSize * rt.leverage;
  const r = riskPrices(entry, side, rt.stopLossPct, rt.leverage);
  const pos: Position = {
    id: Math.random().toString(36).slice(2, 10),
    symbol, side, entry,
    qty: notional / entry,
    size: rt.tradeSize, leverage: rt.leverage,
    tpPrice: r.tp, slPrice: r.sl, slPct: r.distPct,
    openedAt: Date.now(),
  };
  rt.positions.push(pos);
  rt.balance -= 0; // margin tracked virtually; PnL credited on close
  log(rt, "info",
    `🚀 ${side} ${symbol} @ $${fmt(entry)} — ${reason} · 1:1 lock TP $${fmt(r.tp)} / SL $${fmt(r.sl)} (${rt.leverage}x, ${r.distPct.toFixed(2)}%)`);
  rt.dirty = true;
  return pos;
}

function closePositionAt(rt: EngineRuntime, pos: Position, exit: number, reason: ClosedTrade["reason"]): ClosedTrade {
  const dir = pos.side === "LONG" ? 1 : -1;
  const pnl = (exit - pos.entry) * dir * pos.qty;
  const pnlPct = (pnl / pos.size) * 100;
  const trade: ClosedTrade = {
    id: pos.id, symbol: pos.symbol, side: pos.side,
    entry: pos.entry, exit, pnl, pnlPct, reason,
    openedAt: pos.openedAt, closedAt: Date.now(),
  };
  rt.positions = rt.positions.filter(p => p.id !== pos.id);
  rt.history.push(trade);
  if (rt.history.length > 100) rt.history.splice(0, rt.history.length - 100);
  rt.balance += pnl;
  const tag = reason === "TP" ? "🎯 1:1 TAKE PROFIT HIT"
    : reason === "SL" ? "🛑 STOP LOSS HIT"
    : reason === "REVERSAL" ? "🔄 EMA55 REVERSAL"
    : "✋ MANUAL CLOSE";
  log(rt, pnl >= 0 ? "success" : "warn",
    `${tag} — ${pos.side} ${pos.symbol} @ $${fmt(exit)} · ${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)} (${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(1)}% ROE)`);
  rt.dirty = true;
  return trade;
}

/* ─────────────────────── Signal evaluation (strategy.py port) ─────────────────────── */

interface SignalEval {
  signal: "BUY" | "SELL" | "HOLD";
  e8: number; e13: number; e21: number; e55: number;
  sepPct: number;
  reason: string;
  blockedReason: string;
  fresh: boolean;
  reentryOk: boolean;
  crossAge: number;
}

function ema55AtExtreme(e8: number, e13: number, e21: number, e55: number, side: "BUY" | "SELL"): boolean {
  if (side === "BUY") return e55 < e8 && e55 < e13 && e55 < e21;
  return e55 > e8 && e55 > e13 && e55 > e21;
}

/** Consecutive closed candles BEFORE the signal candle with EMA55 at same extreme. */
function consecutiveExtreme(emas: { e8: number[]; e13: number[]; e21: number[]; e55: number[] },
                            closedIdx: number, side: "BUY" | "SELL"): number {
  let count = 0;
  let i = closedIdx - 1;
  while (i >= 0 && count < 200) {
    if (ema55AtExtreme(emas.e8[i], emas.e13[i], emas.e21[i], emas.e55[i], side)) {
      count++; i--;
    } else break;
  }
  return count;
}

function evalSignal(candles: Candle[], symbol: string, timeframe: string,
                    state: StratState): SignalEval | null {
  if (candles.length < MIN_CANDLES) return null;
  const closes = candles.map(c => c.c);
  const e8 = ema(closes, EMA_SHORT), e13 = ema(closes, EMA_MID1);
  const e21 = ema(closes, EMA_MID2), e55 = ema(closes, EMA_LONG);
  const emas = { e8, e13, e21, e55 };

  // last candle is the forming candle — signals come from the CLOSED candle
  const i = closes.length - 2;
  const c8 = e8[i], c13 = e13[i], c21 = e21[i], c55 = e55[i];
  if (![c8, c13, c21, c55].every(Number.isFinite)) return null;

  const sepPct = (Math.abs(c8 - c55) / c55) * 100;
  const minSep = minSpread(symbol, timeframe);

  const isBuyCandidate = c55 < c8 && c55 < c13 && c55 < c21 && c8 >= c13 && c13 >= c21;
  const isSellCandidate = c55 > c8 && c55 > c13 && c55 > c21 && c8 <= c13 && c13 <= c21;

  let signal: "BUY" | "SELL" | "HOLD" = "HOLD";
  let reason = "EMA55 tangled / inside lines (no full cross) -> HOLD";
  let blockedReason = "";

  if (sepPct < minSep && (isBuyCandidate || isSellCandidate)) {
    blockedReason = `spread_filter (${sepPct.toFixed(3)}% < ${minSep.toFixed(3)}%)`;
    reason = `Flat market chop (EMA spread ${sepPct.toFixed(3)}% < ${minSep.toFixed(3)}% required) -> HOLD`;
  } else if (isBuyCandidate) {
    signal = "BUY";
    reason = `EMA55 crossed below ALL lines & 8>=13>=21 (spread=${sepPct.toFixed(2)}%) -> BUY (LONG)`;
  } else if (isSellCandidate) {
    signal = "SELL";
    reason = `EMA55 crossed above ALL lines & 8<=13<=21 (spread=${sepPct.toFixed(2)}%) -> SELL (SHORT)`;
  }

  // Fresh-cross check (v2 anti-missed-trade logic)
  let crossAge = 0;
  let fresh = false;
  if (signal === "BUY" || signal === "SELL") {
    crossAge = consecutiveExtreme(emas, i, signal);
    fresh = crossAge <= FRESH_CROSS_WINDOW - 1;
    if (!fresh && !blockedReason) {
      blockedReason = `not_fresh (cross_age=${crossAge} > window=${FRESH_CROSS_WINDOW})`;
    }
  }

  // Anti-whipsaw state transition — only an OPPOSITE signal resets the entered flag
  if (signal === "BUY" || signal === "SELL") {
    if (signal !== state.lastTrendSide) {
      state.tradeEnteredForSignal = false;
      state.lastTrendSide = signal;
    }
  }

  // Trend re-entry: same-side signal still active after cooldown candles
  let reentryOk = false;
  if (signal === "BUY" || signal === "SELL") {
    if (!state.tradeEnteredForSignal && state.lastTrendSide === signal && state.lastEntryCandleTs !== null) {
      const closedTs = candles[i].t;
      const tfSec = (TIMEFRAME_MS[timeframe] ?? 300_000) / 1000;
      if (closedTs - state.lastEntryCandleTs >= REENTRY_COOLDOWN_CANDLES * tfSec * 1000) {
        reentryOk = true;
      }
    }
  }

  return { signal, e8: c8, e13: c13, e21: c21, e55: c55, sepPct, reason, blockedReason, fresh, reentryOk, crossAge };
}

/* ─────────────────────── Tick ─────────────────────── */

const loggedSignals = new Map<string, string>();   // `${userId}:${symbol}` → last logged signal+blocked

export async function tickEngine(rt: EngineRuntime): Promise<void> {
  if (rt.ticking) return;
  rt.ticking = true;
  try {
    const now = Date.now();

    // 1) Refresh live prices (single batched call, cached 3s)
    const priceFetches = new Map<string, number | null>();
    const uniq = new Set<string>([...rt.symbols, ...rt.positions.map(p => p.symbol)]);
    for (const sym of uniq) {
      const p = await getPrice(sym);
      priceFetches.set(sym, p);
      if (p) lastPrices.set(sym, p);
    }

    // 2) EMA55 reversal exit — opposite FRESH signal closes the position instantly
    if (rt.positions.length > 0) {
      for (const pos of [...rt.positions]) {
        const key = stratKey(rt.userId, pos.symbol);
        let state = stratStates.get(key);
        if (!state) {
          state = { tradeEnteredForSignal: false, lastTrendSide: null, lastEntryCandleTs: null, seeded: false };
          stratStates.set(key, state);
        }
        const candles = await getCandles(pos.symbol, rt.timeframe);
        if (!candles) continue;
        if (!state.seeded) {
          const probe = evalSignal(candles, pos.symbol, rt.timeframe, state);
          state.lastTrendSide = probe && probe.signal !== "HOLD" ? probe.signal : null;
          state.tradeEnteredForSignal = true;
          state.seeded = true;
          continue;
        }
        const ev = evalSignal(candles, pos.symbol, rt.timeframe, state);
        if (!ev || ev.signal === "HOLD" || !ev.fresh) continue;
        const opposite: "LONG" | "SHORT" = ev.signal === "BUY" ? "LONG" : "SHORT";
        if (pos.side !== opposite) continue;          // only opposite signal reverses
        const price = priceFetches.get(pos.symbol) ?? lastPrices.get(pos.symbol);
        if (!price) continue;
        closePositionAt(rt, pos, price, "REVERSAL");
        entryPace.delete(key);                         // allow the flip entry immediately
        rt._reversalJustClosed = pos.symbol;
      }
    }

    // 2) Manage open positions every tick regardless of running flag (software watchdog)
    for (const pos of [...rt.positions]) {
      const price = priceFetches.get(pos.symbol) ?? await getPrice(pos.symbol);
      if (!price) continue;
      if (pos.side === "LONG") {
        if (price <= pos.slPrice) closePositionAt(rt, pos, pos.slPrice, "SL");
        else if (price >= pos.tpPrice) closePositionAt(rt, pos, pos.tpPrice, "TP");
      } else {
        if (price >= pos.slPrice) closePositionAt(rt, pos, pos.slPrice, "SL");
        else if (price <= pos.tpPrice) closePositionAt(rt, pos, pos.tpPrice, "TP");
      }
    }

    // 3) Scan for entries (only while running)
    if (rt.running) {
      for (const symbol of rt.symbols) {
        if (rt.positions.length >= MAX_CONCURRENT) break;
        if (rt.positions.some(p => p.symbol === symbol)) continue;

        const key = stratKey(rt.userId, symbol);
        let state = stratStates.get(key);
        if (!state) {
          state = { tradeEnteredForSignal: false, lastTrendSide: null, lastEntryCandleTs: null, seeded: false };
          stratStates.set(key, state);
        }

        const candles = await getCandles(symbol, rt.timeframe);
        if (!candles) continue;

        // Lazy startup seed (strategy.py seed_startup_state): lock to the currently
        // visible signal so the engine never chases a pre-existing trend on start.
        if (!state.seeded) {
          const probe = evalSignal(candles, symbol, rt.timeframe, state);
          state.lastTrendSide = probe && probe.signal !== "HOLD" ? probe.signal : null;
          state.tradeEnteredForSignal = true;
          state.seeded = true;
          log(rt, "info", `Strategy seeded on ${symbol} — waiting for a fresh cross`);
          continue;
        }

        const ev = evalSignal(candles, symbol, rt.timeframe, state);
        if (!ev) continue;

        // Log signals only on transition (no per-tick spam)
        const sigKey = `${ev.signal}|${ev.blockedReason}`;
        if (loggedSignals.get(key) !== sigKey) {
          loggedSignals.set(key, sigKey);
          if (ev.signal === "HOLD" && ev.blockedReason.startsWith("spread_filter")) {
            log(rt, "warn", `Signal candidate ${symbol} blocked: ${ev.blockedReason}`);
          } else if (ev.signal !== "HOLD" && ev.blockedReason) {
            log(rt, "info", `Signal ${ev.signal === "BUY" ? "BUY" : "SELL"} ${symbol} blocked: ${ev.blockedReason}`);
          } else if (ev.signal !== "HOLD") {
            log(rt, "info", `Signal ${ev.signal === "BUY" ? "BUY" : "SELL"} ${symbol} — ${ev.reason}`);
          }
        }

        if (ev.signal === "HOLD") continue;

        // mode filter
        if (rt.mode === "long" && ev.signal === "SELL") continue;
        if (rt.mode === "short" && ev.signal === "BUY") continue;

        // entry pacing (30s per symbol)
        const lastOpen = entryPace.get(key) || 0;
        const justReversed = rt._reversalJustClosed === symbol;
        if (!justReversed && now - lastOpen < ENTRY_PACE_MS) continue;

        const mayEnter = (ev.fresh && !state.tradeEnteredForSignal) || ev.reentryOk;
        if (!mayEnter) continue;

        // fee guard — TP distance must clear minimum fee buffer
        const entryPrice = priceFetches.get(symbol) ?? lastPrices.get(symbol) ?? (await getPrice(symbol));
        if (!entryPrice) continue;
        const r = riskPrices(entryPrice, ev.signal === "BUY" ? "LONG" : "SHORT", rt.stopLossPct, rt.leverage);
        if (r.distPct < MIN_FEE_BUFFER_PCT) {
          log(rt, "warn", `${symbol} entry skipped: fee_guard (TP dist ${r.distPct.toFixed(3)}% < ${MIN_FEE_BUFFER_PCT}%)`);
          continue;
        }

        // margin check
        if (rt.balance < rt.tradeSize) {
          log(rt, "error", `Insufficient margin for ${symbol} — need $${fmt(rt.tradeSize)}, have $${fmt(rt.balance)}`);
          continue;
        }

        const side: "LONG" | "SHORT" = ev.signal === "BUY" ? "LONG" : "SHORT";
        openPosition(rt, symbol, side, entryPrice, ev.reason);
        state.tradeEnteredForSignal = true;
        state.lastEntryCandleTs = candles[candles.length - 2].t;
        entryPace.set(key, now);
      }
    }

    rt._reversalJustClosed = null;
    rt.lastTickAt = now;
    if (rt.dirty) await persist(rt);   // awaited: floating promises die after response in Next.js
  } finally {
    rt.ticking = false;
  }
}

/* ─────────────────────── Actions ─────────────────────── */

export function actionStart(rt: EngineRuntime): void {
  if (rt.running) return;
  rt.running = true;
  // reset strategy states — lazy seed locks them to the current signal on first tick
  for (const sym of rt.symbols) {
    const st = { tradeEnteredForSignal: true, lastTrendSide: null, lastEntryCandleTs: null, seeded: false };
    stratStates.set(stratKey(rt.userId, sym), st);
  }
  log(rt, "success",
    `Quad-Trend Engine STARTED — EMA 8/13/21/55 · TF ${rt.timeframe} · ${rt.symbols.join(", ")} · strict 1:1 ${rt.stopLossPct.toFixed(1)}% (${rt.leverage}x) · mode ${rt.mode}`);
  rt.dirty = true;
}

export function actionStop(rt: EngineRuntime): void {
  if (!rt.running) return;
  rt.running = false;
  log(rt, "warn", "Engine stopped by user — open positions keep their 1:1 TP/SL brackets");
  rt.dirty = true;
}

export function actionConfig(rt: EngineRuntime, cfg: Partial<{
  leverage: number; timeframe: string; tradeSize: number;
  stopLossPct: number; mode: string; symbols: string[];
}>): void {
  if (cfg.leverage !== undefined) rt.leverage = Math.max(1, Math.min(125, Math.round(cfg.leverage)));
  if (cfg.tradeSize !== undefined) rt.tradeSize = Math.max(10, Math.min(2000, cfg.tradeSize));
  if (cfg.timeframe !== undefined && TIMEFRAME_MS[cfg.timeframe]) rt.timeframe = cfg.timeframe;
  if (cfg.stopLossPct !== undefined) {
    rt.stopLossPct = Math.max(STRICT_SL_MIN, Math.min(10, Number(cfg.stopLossPct) || 2));
  }
  if (cfg.mode === "long" || cfg.mode === "short" || cfg.mode === "both") rt.mode = cfg.mode;
  if (cfg.symbols !== undefined) {
    const valid = cfg.symbols.filter(s => ALL_SYMBOLS.includes(s)).slice(0, 4);
    if (valid.length > 0) rt.symbols = valid;
  }
  rt.dirty = true;
}

/** Manual entry at live market price. */
export async function actionManual(rt: EngineRuntime, symbol: string, side: "LONG" | "SHORT"): Promise<{ ok: boolean; error?: string }> {
  if (rt.positions.length >= MAX_CONCURRENT) return { ok: false, error: `Max ${MAX_CONCURRENT} open positions (risk cap)` };
  if (rt.positions.some(p => p.symbol === symbol)) return { ok: false, error: `${symbol} already has an open position` };
  if (rt.balance < rt.tradeSize) return { ok: false, error: "Insufficient balance for margin" };
  const price = await getPrice(symbol);
  if (!price) return { ok: false, error: "Live price unavailable — try again" };
  openPosition(rt, symbol, side, price, "manual override from terminal");
  entryPace.set(stratKey(rt.userId, symbol), Date.now());
  rt.dirty = true;
  return { ok: true };
}

export async function actionClose(rt: EngineRuntime, id: string): Promise<void> {
  const pos = rt.positions.find(p => p.id === id);
  if (!pos) return;
  const price = await getPrice(pos.symbol);
  if (!price) return;
  closePositionAt(rt, pos, price, "MANUAL");
  await persist(rt);
}

export async function actionCloseAll(rt: EngineRuntime): Promise<void> {
  for (const pos of [...rt.positions]) {
    const price = await getPrice(pos.symbol);
    if (!price) continue;
    closePositionAt(rt, pos, price, "MANUAL");
  }
  await persist(rt);
}

export function resetAccount(rt: EngineRuntime): void {
  rt.balance = 10000; rt.startBal = 10000;
  rt.positions = []; rt.history = []; rt.logs = [];
  for (const sym of rt.symbols) {
    const st = { tradeEnteredForSignal: true, lastTrendSide: null, lastEntryCandleTs: null, seeded: false };
    stratStates.set(stratKey(rt.userId, sym), st);
  }
  log(rt, "info", "Account reset to $10,000.00 paper balance — strategy state re-seeded");
  rt.dirty = true;
}

/* ─────────────────────── Awaitable persistence (route layer) ───────────────────────
 * Next.js route handlers kill floating promises once the response is sent — so the
 * route MUST await these, otherwise user config (symbols/leverage/…) never reaches
 * the DB and silently resets on the next server restart. */

export async function persistRuntime(rt: EngineRuntime): Promise<void> {
  await persist(rt);
}

export async function persistIfDirty(rt: EngineRuntime): Promise<void> {
  if (rt.dirty) await persist(rt);
}

/* ─────────────────────── Snapshot for client ─────────────────────── */

export function unrealized(rt: EngineRuntime): number {
  let total = 0;
  for (const p of rt.positions) {
    const price = lastPrices.get(p.symbol) ?? p.entry;
    const dir = p.side === "LONG" ? 1 : -1;
    total += (price - p.entry) * dir * p.qty;
  }
  return total;
}

export function snapshotState(rt: EngineRuntime) {
  const positions = rt.positions.map(p => {
    const price = lastPrices.get(p.symbol) ?? p.entry;
    const dir = p.side === "LONG" ? 1 : -1;
    const pnl = (price - p.entry) * dir * p.qty;
    return { ...p, price, pnl, pnlPct: (pnl / p.size) * 100 };
  });
  const uPnl = unrealized(rt);
  const closed = rt.history;
  const wins = closed.filter(t => t.pnl > 0).length;
  const todayStart = new Date(); todayStart.setHours(0, 0, 0, 0);
  const pnlToday = closed.filter(t => t.closedAt >= todayStart.getTime()).reduce((a, t) => a + t.pnl, 0);
  return {
    running: rt.running,
    balance: rt.balance,
    equity: rt.balance + uPnl,
    unrealized: uPnl,
    leverage: rt.leverage,
    timeframe: rt.timeframe,
    tradeSize: rt.tradeSize,
    stopLossPct: rt.stopLossPct,
    mode: rt.mode,
    symbols: rt.symbols,
    positions,
    history: [...closed].reverse(),
    logs: [...rt.logs].reverse(),
    stats: {
      totalTrades: closed.length,
      wins,
      losses: closed.length - wins,
      winRate: closed.length ? (wins / closed.length) * 100 : 0,
      pnlToday,
      totalPnl: rt.balance - rt.startBal,
    },
  };
}

/* ─────────────────────── Market snapshot (per user timeframe) ─────────────────────── */

export interface SymbolIndicators {
  ema8: number; ema13: number; ema21: number; ema55: number;
  sepPct: number; signal: "BUY" | "SELL" | "HOLD";
}

export async function marketSnapshot(timeframe: string): Promise<Record<string, {
  price: number; change24h: number; color: string; name: string;
  candles: Candle[]; spark: number[]; indicators: SymbolIndicators | null;
}>> {
  const out: Record<string, {
    price: number; change24h: number; color: string; name: string;
    candles: Candle[]; spark: number[]; indicators: SymbolIndicators | null;
  }> = {};
  for (const sym of ALL_SYMBOLS) {
    const meta = SYMBOL_META[sym];
    const candles = await getCandles(sym, timeframe);
    const price = (await getPrice(sym))
      ?? (candles ? candles[candles.length - 1].c : 0);
    if (price) lastPrices.set(sym, price);
    const change24h = await getChange24h(sym);

    let indicators: SymbolIndicators | null = null;
    if (candles && candles.length >= MIN_CANDLES) {
      const closes = candles.map(c => c.c);
      const e8 = ema(closes, EMA_SHORT), e13 = ema(closes, EMA_MID1);
      const e21 = ema(closes, EMA_MID2), e55 = ema(closes, EMA_LONG);
      const i = closes.length - 1;   // display values from the forming candle
      const sepPct = (Math.abs(e8[i] - e55[i]) / e55[i]) * 100;
      const minSep = minSpread(sym, timeframe);
      let signal: "BUY" | "SELL" | "HOLD" = "HOLD";
      if (sepPct >= minSep) {
        if (e55[i] < e8[i] && e55[i] < e13[i] && e55[i] < e21[i] && e8[i] >= e13[i] && e13[i] >= e21[i]) signal = "BUY";
        else if (e55[i] > e8[i] && e55[i] > e13[i] && e55[i] > e21[i] && e8[i] <= e13[i] && e13[i] <= e21[i]) signal = "SELL";
      }
      indicators = { ema8: e8[i], ema13: e13[i], ema21: e21[i], ema55: e55[i], sepPct, signal };
    }

    out[sym] = {
      price, change24h, color: meta.color, name: meta.name,
      candles: candles ? candles.slice(-72) : [],
      spark: candles ? candles.slice(-40).map(c => c.c) : [],
      indicators,
    };
  }
  return out;
}

/* ─────────────────────── Heartbeat (engine runs even with no client) ─────────────────────── */

let heartbeatStarted = false;

export function startHeartbeat(): void {
  if (heartbeatStarted) return;
  heartbeatStarted = true;
  const TICK_MS = 4000;
  setInterval(() => {
    const now = Date.now();
    for (const [userId, rt] of [...runtimes.entries()]) {
      // prune idle runtimes out of memory (state is persisted)
      if (!rt.running && rt.positions.length === 0 && now - rt.lastTickAt > 30 * 60_000) {
        runtimes.delete(userId);
        continue;
      }
      if (rt.running || rt.positions.length > 0) {
        void tickEngine(rt).catch(() => { /* keep heartbeat alive */ });
      }
    }
  }, TICK_MS);
}

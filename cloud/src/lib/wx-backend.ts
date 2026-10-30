/* ─────────────────────────────────────────────────────────────────────────
 * wx-backend.ts — Weexionic REAL bot backend client (Flask SaaS + engine).
 *
 * The demo TypeScript paper engine (wx-engine.ts) has been RETIRED. Every
 * number on the web dashboard / Android app now comes from the REAL bot:
 *
 *   - accounts, licenses, referral, payouts … Flask SaaS  (127.0.0.1:5001)
 *   - strategy, positions, orders, balance  … per-user bot-engine process
 *     (Python, EMA 8/13/21/55 — untouched original strategy code)
 *
 * This module only proxies/ translates. It never invents trading data.
 * ──────────────────────────────────────────────────────────────────────── */

import { getCandles, getPrice, getChange24h, SYMBOL_META, ALL_SYMBOLS } from "@/lib/wx-market";
import type { Candle } from "@/lib/wx-market";

const FLASK = process.env.INTERNAL_API || "http://127.0.0.1:5001";

/* ─────────────────────── Flask HTTP helper ─────────────────────── */

export interface FlaskResult {
  status: number;
  data: Record<string, unknown> & { success?: boolean; error?: string };
  setCookie?: string;
}

export async function flask(
  path: string,
  opts: { method?: string; body?: unknown; token?: string; captureCookie?: boolean } = {},
): Promise<FlaskResult> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.token) headers["Authorization"] = `Bearer ${opts.token}`;
  try {
    const res = await fetch(FLASK + path, {
      method: opts.method || "GET",
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      cache: "no-store",
    });
    let data: FlaskResult["data"] = {};
    try { data = await res.json(); } catch { /* empty body */ }
    const out: FlaskResult = { status: res.status, data };
    if (opts.captureCookie) {
      const sc = res.headers.get("set-cookie");
      if (sc) out.setCookie = sc.split(";")[0];
    }
    return out;
  } catch {
    return { status: 502, data: { success: false, error: "Bot backend unreachable" } };
  }
}

/** Bearer token → Flask user context (or null when invalid). */
interface BotConfigPayload {
  has_api_key?: boolean;
  exchange?: string; testnet?: boolean; symbols_list?: string[];
  timeframe?: string; leverage?: number; amount_mode?: string;
  amount?: number; amount_pct?: number; stop_loss_pct?: number; tp_mode?: string;
  mode?: string; max_concurrent_trades?: number;
  api_key_masked?: string; api_secret_masked?: string;
  [k: string]: unknown;
}

export interface BotUserContext {
  user: { id: string; email: string; name: string; role?: string };
  subscription: { active?: boolean; plan?: string; status?: string; days_left?: number; expires_at?: string | null };
  license_key: string | null;
  referral_code: string;
  botConfig: BotConfigPayload;
  botRunning: boolean;
}

export async function flaskUser(token: string): Promise<BotUserContext | null> {
  const r = await flask("/api/auth/me", { token });
  if (r.status !== 200 || !r.data.success) return null;
  const d = r.data as {
    user: { id: string; email: string; name: string; role?: string };
    subscription: BotUserContext["subscription"];
    license_key: string | null;
    referral_code: string;
    bot_config?: BotConfigPayload;
    bot_running?: boolean;
  };
  return {
    user: d.user,
    subscription: d.subscription || {},
    license_key: d.license_key ?? null,
    referral_code: d.referral_code || "",
    botConfig: d.bot_config || {},
    botRunning: !!d.bot_running,
  };
}

/* ─────────────────────── Engine data fetchers ─────────────────────── */

export interface EnginePosition {
  symbol: string; side: string; size: number; entry_price: number;
  mark_price: number; unrealized_pnl: number; leverage: number;
  tp_price: number | null; sl_price: number | null; tp_mode?: string;
}

export interface EngineTrade {
  id: string; symbol: string; side: string; status: string;
  entry_price: number | null; exit_price: number | null;
  qty: number; leverage: number; pnl: number; roe_pct: number;
  close_reason: string | null; opened_ts: number; closed_ts: number | null;
  opened_at?: string; closed_at?: string | null;
}

async function engineGet(token: string, path: string): Promise<Record<string, unknown> | null> {
  const r = await flask(path, { token });
  if (r.status !== 200) return null;
  return r.data;
}

export async function enginePositions(token: string): Promise<EnginePosition[]> {
  const d = await engineGet(token, "/api/bot/positions");
  return Array.isArray(d?.positions) ? (d!.positions as EnginePosition[]) : [];
}

export async function engineTrades(token: string): Promise<EngineTrade[]> {
  const d = await engineGet(token, "/api/bot/trades");
  return Array.isArray(d?.trades) ? (d!.trades as EngineTrade[]) : [];
}

export async function engineBalance(token: string): Promise<{ balance: number; exchange: string; testnet: boolean } | null> {
  const d = await engineGet(token, "/api/bot/balance");
  if (!d || d.success === false) return null;
  const b = typeof d.balance === "number" ? d.balance : parseFloat(String(d.balance ?? ""));
  return { balance: Number.isFinite(b) ? b : 0, exchange: String(d.exchange ?? "binance"), testnet: !!d.testnet };
}

export async function engineLogs(token: string): Promise<string[]> {
  const d = await engineGet(token, "/api/bot/logs");
  return Array.isArray(d?.logs) ? (d!.logs as string[]) : [];
}

/* ─────────────────────── Snapshot builder (cloud contract) ─────────────────────── */

export interface CloudPosition {
  id: string; symbol: string; side: "LONG" | "SHORT";
  entry: number; qty: number; size: number; leverage: number;
  tpPrice: number; slPrice: number; openedAt: number;
  price: number; pnl: number; pnlPct: number;
}

export interface CloudTrade {
  id: string; symbol: string; side: "LONG" | "SHORT";
  entry: number; exit: number; pnl: number; pnlPct: number;
  reason: "TP" | "SL" | "MANUAL" | "REVERSAL";
  openedAt: number; closedAt: number;
}

export interface CloudLog { t: number; level: "info" | "success" | "warn" | "error"; msg: string; }

function mapReason(reason: string | null | undefined): CloudTrade["reason"] {
  const r = (reason || "").toUpperCase();
  if (r.includes("REVERSAL") || r.includes("EMA")) return "REVERSAL";
  if (r.includes("SL") || r.includes("STOP")) return "SL";
  if (r.includes("TP") || r.includes("PROFIT") || r.includes("TRAIL")) return "TP";
  return "MANUAL";
}

function parseEngineLogLine(line: string): CloudLog | null {
  // Engine log format: "2026-10-30 06:39:12,345 INFO [BTCUSDT] message…"
  const m = line.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})[,.]\d*\s+(INFO|WARNING|ERROR|CRITICAL|DEBUG)\s+(.*)$/);
  if (!m) {
    if (!line.trim()) return null;
    return { t: Date.now(), level: "info", msg: line.trim().slice(0, 300) };
  }
  const t = new Date(m[1].replace(" ", "T") + "Z").getTime();
  const lvlRaw = m[2].toUpperCase();
  const level: CloudLog["level"] =
    lvlRaw === "ERROR" || lvlRaw === "CRITICAL" ? "error" :
    lvlRaw === "WARNING" ? "warn" : "info";
  return { t: Number.isFinite(t) ? t : Date.now(), level, msg: m[3].slice(0, 300) };
}

/** Build the full REAL engine snapshot in the exact shape the web + app parse. */
export async function buildEngineSnapshot(ctx: BotUserContext, token: string) {
  const cfg = ctx.botConfig;
  const running = !!ctx.botRunning;

  const [positions, trades, balance, logLines] = await Promise.all([
    enginePositions(token),
    engineTrades(token),
    engineBalance(token),
    engineLogs(token),
  ]);

  /* positions → PositionView[] */
  const posView: CloudPosition[] = [];
  for (const p of positions) {
    const side = String(p.side || "").toUpperCase();
    if (side !== "LONG" && side !== "SHORT") continue;
    const entry = Number(p.entry_price) || 0;
    const qty = Number(p.size) || 0;                 // engine "size" = base-asset quantity
    const price = Number(p.mark_price) || entry;
    const pnl = Number(p.unrealized_pnl) || 0;
    const notional = entry * qty;
    posView.push({
      id: p.symbol,
      symbol: p.symbol,
      side,
      entry,
      qty,
      size: notional,
      leverage: Number(p.leverage) || Number(cfg.leverage) || 1,
      tpPrice: Number(p.tp_price) || 0,
      slPrice: Number(p.sl_price) || 0,
      openedAt: Date.now(),                          // engine does not expose open time
      price,
      pnl,
      pnlPct: notional > 0 ? (pnl / notional) * 100 : 0,
    });
  }
  const unrealized = posView.reduce((a, p) => a + p.pnl, 0);

  /* trades → ClosedTrade[] (newest first) */
  const closed: CloudTrade[] = [];
  for (const t of trades) {
    if (String(t.status || "").toUpperCase() !== "CLOSED") continue;
    closed.push({
      id: String(t.id),
      symbol: String(t.symbol),
      side: String(t.side).toUpperCase() === "SHORT" ? "SHORT" : "LONG",
      entry: Number(t.entry_price) || 0,
      exit: Number(t.exit_price) || 0,
      pnl: Number(t.pnl) || 0,
      pnlPct: Number(t.roe_pct) || 0,
      reason: mapReason(t.close_reason),
      openedAt: Number(t.opened_ts) || Date.parse(String(t.opened_at)) || Date.now(),
      closedAt: Number(t.closed_ts) || Date.parse(String(t.closed_at)) || Date.now(),
    });
  }
  closed.sort((a, b) => b.closedAt - a.closedAt);

  /* logs → newest first */
  const logs: CloudLog[] = [];
  for (const line of logLines) {
    const e = parseEngineLogLine(line);
    if (e) logs.push(e);
  }
  logs.reverse();

  /* stats — REAL closed trades only */
  const wins = closed.filter(t => t.pnl > 0).length;
  const todayStart = new Date(); todayStart.setHours(0, 0, 0, 0);
  const pnlToday = closed.filter(t => t.closedAt >= todayStart.getTime()).reduce((a, t) => a + t.pnl, 0);
  const totalPnl = closed.reduce((a, t) => a + t.pnl, 0);

  const bal = balance ? balance.balance : 0;
  const amountMode = String(cfg.amount_mode || "fixed");

  return {
    running,
    balance: bal,
    equity: bal + unrealized,
    unrealized,
    leverage: Number(cfg.leverage) || 10,
    timeframe: String(cfg.timeframe || "5m"),
    tradeSize: amountMode === "percent" ? Number(cfg.amount_pct) || 10 : Number(cfg.amount) || 100,
    symbols: Array.isArray(cfg.symbols_list) && cfg.symbols_list.length ? cfg.symbols_list : ["BTCUSDT"],
    stopLossPct: Number(cfg.stop_loss_pct) || 2,
    mode: (String(cfg.mode || "both") as "both" | "long" | "short"),
    positions: posView,
    history: closed,
    logs,
    stats: {
      totalTrades: closed.length,
      wins,
      losses: closed.length - wins,
      winRate: closed.length ? (wins / closed.length) * 100 : 0,
      pnlToday,
      totalPnl,
    },
    exchange: balance?.exchange || String(cfg.exchange || "binance"),
    testnet: balance?.testnet ?? (cfg.testnet !== false),
    hasApiKey: !!cfg.has_api_key,
    licenseActive: (ctx.subscription?.status === "active") || ctx.user.role === "admin",
    daysLeft: Number(ctx.subscription?.days_left ?? 0),
  };
}

/* ─────────────────────── Market snapshot (REAL Binance data) ─────────────────────── */

const EMA_SHORT = 8, EMA_MID1 = 13, EMA_MID2 = 21, EMA_LONG = 55;
const MIN_CANDLES = EMA_LONG + 5;

const TIMEFRAME_SPREAD_DEFAULTS: Record<string, number> = {
  "1m": 0.15, "3m": 0.22, "5m": 0.30, "15m": 0.40, "30m": 0.50,
  "1h": 0.60, "2h": 0.80, "4h": 1.00, "1d": 1.50, "1w": 2.00,
};

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

export interface SymbolIndicators {
  ema8: number; ema13: number; ema21: number; ema55: number;
  sepPct: number; signal: "BUY" | "SELL" | "HOLD";
}

export type MarketSnapshot = Record<string, {
  price: number; change24h: number; color: string; name: string;
  candles: Candle[]; spark: number[]; indicators: SymbolIndicators | null;
}>;

export async function marketSnapshot(timeframe: string): Promise<MarketSnapshot> {
  const out: MarketSnapshot = {};
  for (const sym of ALL_SYMBOLS) {
    const meta = SYMBOL_META[sym];
    const candles = await getCandles(sym, timeframe);
    const price = (await getPrice(sym)) ?? (candles ? candles[candles.length - 1].c : 0);
    const change24h = await getChange24h(sym);

    let indicators: SymbolIndicators | null = null;
    if (candles && candles.length >= MIN_CANDLES) {
      const closes = candles.map(c => c.c);
      const e8 = ema(closes, EMA_SHORT), e13 = ema(closes, EMA_MID1);
      const e21 = ema(closes, EMA_MID2), e55 = ema(closes, EMA_LONG);
      const i = closes.length - 1;
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

/* ─────────────────────── /api/me translation helpers ─────────────────────── */

export interface CloudKeyRow {
  id: string; exchange: string; label: string;
  keyMasked: string; secretMasked: string; createdAt: string;
}

export interface CloudTxn {
  id: string; type: string; amount: number;
  note: string; status: string; createdAt: string;
}

export function keysFromConfig(cfg: BotUserContext["botConfig"]): CloudKeyRow[] {
  if (!cfg.has_api_key) return [];
  return [{
    id: "primary",
    exchange: String(cfg.exchange || "binance").toUpperCase(),
    label: "Main Account",
    keyMasked: String(cfg.api_key_masked || "----"),
    secretMasked: String(cfg.api_secret_masked || "•••"),
    createdAt: new Date().toISOString(),
  }];
}

interface FlaskReferral {
  referral_code?: string;
  referral_link?: string;
  referral_count?: number;
  referral_earnings?: number;
  available_balance?: number;
  total_withdrawn?: number;
  pending_payout?: number;
  payout_wallet?: string;
  referral_history?: { order_id?: string; buyer_email?: string; buyer_name?: string; package_name?: string; bonus_amount?: number | string; timestamp?: string; status?: string; [k: string]: unknown }[];
  payout_requests?: { id?: string; amount?: number | string; wallet_address?: string; status?: string; created_at?: string; paid_at?: string; [k: string]: unknown }[];
  [k: string]: unknown;
}

export function txnsFromReferral(ref: FlaskReferral): CloudTxn[] {
  const out: CloudTxn[] = [];
  for (const h of ref.referral_history || []) {
    const amount = Number(h.bonus_amount ?? 0);
    out.push({
      id: `ref_${String(h.order_id ?? out.length)}`,
      type: "COMMISSION",
      amount,
      note: `Referral bonus — ${h.package_name || "license"} (${h.buyer_name || h.buyer_email || "friend"})`,
      status: String(h.status || "PAID").toUpperCase(),
      createdAt: String(h.timestamp || new Date().toISOString()),
    });
  }
  for (const p of ref.payout_requests || []) {
    const amount = Number(p.amount ?? 0);
    out.push({
      id: String(p.id || `po_${out.length}`),
      type: "PAYOUT",
      amount: -Math.abs(amount),
      note: `Payout to USDT wallet ${p.wallet_address ? String(p.wallet_address).slice(0, 8) + "…" : ""}`.trim(),
      status: String(p.status || "PENDING").toUpperCase(),
      createdAt: String(p.created_at || new Date().toISOString()),
    });
  }
  out.sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
  return out.slice(0, 50);
}

export async function referralInfo(token: string): Promise<FlaskReferral> {
  const r = await flask("/api/user/referral", { token });
  if (r.status !== 200) return {};
  return (r.data.data ?? r.data) as FlaskReferral;
}

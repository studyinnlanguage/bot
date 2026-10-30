export interface Candle { t: number; o: number; h: number; l: number; c: number; }

export interface PositionView {
  id: string; symbol: string; side: "LONG" | "SHORT";
  entry: number; qty: number; size: number; leverage: number;
  tpPrice: number; slPrice: number; openedAt: number;
  price: number; pnl: number; pnlPct: number;
}

export interface ClosedTrade {
  id: string; symbol: string; side: "LONG" | "SHORT";
  entry: number; exit: number; pnl: number; pnlPct: number;
  reason: "TP" | "SL" | "MANUAL" | "REVERSAL"; openedAt: number; closedAt: number;
}

export interface LogEntry { t: number; level: "info" | "success" | "warn" | "error"; msg: string; }

export interface EngineSnapshot {
  running: boolean; balance: number; equity: number; unrealized: number;
  leverage: number; timeframe: string; tradeSize: number; symbols: string[];
  stopLossPct?: number; mode?: "both" | "long" | "short";
  positions: PositionView[];
  history: ClosedTrade[];
  logs: LogEntry[];
  stats: { totalTrades: number; wins: number; losses: number; winRate: number; pnlToday: number; totalPnl: number };
  /** REAL bot fields (from the Python engine / Flask SaaS) */
  exchange?: string; testnet?: boolean; hasApiKey?: boolean;
  licenseActive?: boolean; daysLeft?: number;
}

export interface WxUser {
  id: string; email: string; name: string; plan: string;
  planValidUntil: string | null; referralCode: string;
  walletBalance: number; lifetimeEarn: number; friendsInvited: number;
  createdAt?: string;
}

export interface MarketEntry {
  price: number; change24h: number; color: string; name: string;
  candles: Candle[]; spark: number[];
  indicators?: { ema8: number; ema13: number; ema21: number; ema55: number; sepPct: number; signal: "BUY" | "SELL" | "HOLD" } | null;
}
export type MarketData = Record<string, MarketEntry>;

export interface EngineResponse {
  ok: boolean; engine: EngineSnapshot; market: MarketData; user: WxUser; error?: string;
}

export interface ApiKeyRow {
  id: string; exchange: string; label: string; keyMasked: string; secretMasked: string; createdAt: string;
}

export interface Txn { id: string; type: string; amount: number; note: string; status: string; createdAt: string; }

export interface WalletInfo {
  balance: number; lifetimeEarnings: number; friendsInvited: number;
  activeReferrals: number; referralCode: string;
}

export const YELLOW = "#F5C518";
export const GREEN = "#16C784";
export const RED = "#FF4D5E";

export function fmtUsd(n: number, dp = 2): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

export function fmtPrice(n: number): string {
  if (n >= 1000) return fmtUsd(n, 2);
  if (n >= 10) return fmtUsd(n, 2);
  if (n >= 1) return fmtUsd(n, 3);
  return fmtUsd(n, 5);
}

export function fmtPct(n: number): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

export function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

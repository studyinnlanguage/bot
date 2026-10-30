import { NextRequest } from "next/server";
import {
  flaskUser, flask, buildEngineSnapshot, marketSnapshot, referralInfo,
} from "@/lib/wx-backend";

/**
 * GET /api/engine → REAL bot snapshot.
 * Everything comes from the user's own Python bot-engine (EMA 8/13/21/55,
 * untouched strategy) through the Flask SaaS. Market candles/prices come
 * from Binance public REST (wx-market.ts). No paper/demo data anywhere.
 */
export async function GET(req: NextRequest) {
  const header = req.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return Response.json({ ok: false, error: "Session expired — please log in again" }, { status: 401 });

  const ctx = await flaskUser(token);
  if (!ctx) return Response.json({ ok: false, error: "Session expired — please log in again" }, { status: 401 });

  const [engine, market, ref] = await Promise.all([
    buildEngineSnapshot(
      { user: ctx.user, subscription: ctx.subscription, license_key: ctx.license_key, botConfig: ctx.botConfig, botRunning: ctx.bot_running },
      token,
    ),
    marketSnapshot(String(ctx.botConfig.timeframe || "5m")),
    referralInfo(token),
  ]);

  const planActive = ctx.subscription?.status === "active" || ctx.user.role === "admin";
  return Response.json({
    ok: true,
    engine,
    market,
    user: {
      id: ctx.user.id, name: ctx.user.name, email: ctx.user.email,
      plan: ctx.user.role === "admin" ? "ADMIN" : planActive ? String(ctx.subscription?.plan || "PRO").toUpperCase() : "FREE",
      planValidUntil: ctx.subscription?.expires_at || null,
      referralCode: ref.referral_code || ctx.referral_code || "",
      walletBalance: Number(ref.available_balance ?? 0),
      lifetimeEarn: Number(ref.referral_earnings ?? 0),
      friendsInvited: Number(ref.referral_count ?? 0),
    },
  });
}

/**
 * POST /api/engine → REAL bot control.
 *   start    → Flask /api/bot/start   (spawns the user's engine process)
 *   stop     → Flask /api/bot/stop
 *   config   → Flask /api/bot/config  (live-synced to the engine)
 *   close    → Flask /api/bot/close   (real exchange order)
 *   closeAll → Flask /api/bot/close_all
 */
export async function POST(req: NextRequest) {
  const header = req.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return Response.json({ ok: false, error: "Session expired — please log in again" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const action = String(body.action || "");

  let r: { status: number; data: Record<string, unknown> & { success?: boolean; error?: string } };
  switch (action) {
    case "start":
      r = await flask("/api/bot/start", { method: "POST", token, body: {} });
      break;
    case "stop":
      r = await flask("/api/bot/stop", { method: "POST", token, body: {} });
      break;
    case "config": {
      const cfg = (body.config || {}) as Record<string, unknown>;
      const payload: Record<string, unknown> = {};
      if (cfg.timeframe !== undefined) payload.timeframe = String(cfg.timeframe);
      if (cfg.leverage !== undefined) payload.leverage = Number(cfg.leverage);
      if (cfg.tradeSize !== undefined) {
        // Engine amount_mode: "fixed" (USDT) — percent mode kept via amountMode
        if (cfg.amountMode !== undefined) payload.amount_mode = String(cfg.amountMode);
        if (String(payload.amount_mode || "fixed") === "percent") payload.amount_pct = Number(cfg.tradeSize);
        else payload.amount = Number(cfg.tradeSize);
      }
      if (cfg.amountMode !== undefined) payload.amount_mode = String(cfg.amountMode);
      if (cfg.stopLossPct !== undefined) payload.stop_loss_pct = Number(cfg.stopLossPct);
      if (cfg.mode !== undefined) payload.mode = String(cfg.mode);
      if (cfg.symbols !== undefined) payload.symbols_list = Array.isArray(cfg.symbols) ? cfg.symbols.map(s => String(s).toUpperCase()) : String(cfg.symbols).split(",").map(s => s.trim().toUpperCase()).filter(Boolean);
      if (cfg.testnet !== undefined) payload.testnet = !!cfg.testnet;
      if (cfg.exchange !== undefined) payload.exchange = String(cfg.exchange).toLowerCase();
      if (cfg.tpMode !== undefined) payload.tp_mode = String(cfg.tpMode);
      if (cfg.maxConcurrentTrades !== undefined) payload.max_concurrent_trades = Number(cfg.maxConcurrentTrades);
      r = await flask("/api/bot/config", { method: "POST", token, body: payload });
      break;
    }
    case "close": {
      const symbol = String(body.symbol || body.id || "").toUpperCase();
      if (!symbol) return Response.json({ ok: false, error: "symbol is required" }, { status: 400 });
      r = await flask("/api/bot/close", { method: "POST", token, body: { symbol } });
      break;
    }
    case "closeAll":
      r = await flask("/api/bot/close_all", { method: "POST", token, body: {} });
      break;
    case "manual":
      return Response.json({
        ok: false,
        error: "Manual trading removed — the bot trades the EMA 8/13/21/55 strategy automatically",
      }, { status: 400 });
    case "reset":
      return Response.json({
        ok: false,
        error: "Demo reset removed — this bot trades your real exchange account",
      }, { status: 400 });
    default:
      return Response.json({ ok: false, error: "Unknown action" }, { status: 400 });
  }

  if (r.status !== 200 || r.data.success === false) {
    return Response.json(
      { ok: false, error: String(r.data.error || r.data.message || "Action failed") },
      { status: r.status >= 400 && r.status < 600 ? r.status : 502 },
    );
  }

  // Return the refreshed snapshot so the UI updates immediately
  const ctx = await flaskUser(token);
  if (!ctx) return Response.json({ ok: false, error: "Session expired" }, { status: 401 });
  const [engine, market] = await Promise.all([
    buildEngineSnapshot(
      { user: ctx.user, subscription: ctx.subscription, license_key: ctx.license_key, botConfig: ctx.botConfig, botRunning: ctx.bot_running },
      token,
    ),
    marketSnapshot(String(ctx.botConfig.timeframe || "5m")),
  ]);
  return Response.json({ ok: true, engine, market });
}

import { NextRequest } from "next/server";
import {
  flaskUser, flask, keysFromConfig, txnsFromReferral, referralInfo,
} from "@/lib/wx-backend";

/**
 * GET /api/me → REAL account data from the bot SaaS:
 * user, subscription/license, exchange keys, referral wallet + history.
 * Same response shape the web dashboard and Android app already parse.
 */
export async function GET(req: NextRequest) {
  const header = req.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return Response.json({ ok: false, error: "Session expired — please log in again" }, { status: 401 });

  const ctx = await flaskUser(token);
  if (!ctx) return Response.json({ ok: false, error: "Session expired — please log in again" }, { status: 401 });

  const ref = await referralInfo(token);
  const txnList = txnsFromReferral(ref);
  const planRaw = String(ctx.subscription?.plan || "");
  const planActive = ctx.subscription?.status === "active" || ctx.user.role === "admin";
  const plan = ctx.user.role === "admin"
    ? "ADMIN"
    : planActive
      ? (planRaw && planRaw !== "none" ? planRaw.toUpperCase() : "PRO")
      : "FREE";

  return Response.json({
    ok: true,
    user: {
      id: ctx.user.id, name: ctx.user.name, email: ctx.user.email,
      plan,
      planValidUntil: ctx.subscription?.expires_at || null,
      referralCode: ref.referral_code || ctx.referral_code || "",
      walletBalance: Number(ref.available_balance ?? 0),
      lifetimeEarn: Number(ref.referral_earnings ?? 0),
      friendsInvited: Number(ref.referral_count ?? 0),
      createdAt: undefined,
    },
    keys: keysFromConfig(ctx.botConfig),
    txns: txnList,
    network: {
      cluster: "WEEXIONIC CLOUD",
      host: "cloud.weexionic.app",
      region: "auto-assigned on login",
      client: "Weexionic App v3.0.0",
      engine: "Quad-Trend Engine — EMA 8/13/21/55",
    },
  });
}

/** POST /api/me → payout wallet update / payout request (real referral system). */
export async function POST(req: NextRequest) {
  const header = req.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return Response.json({ ok: false, error: "Session expired" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  if (body.action === "payout-wallet" && body.wallet) {
    const r = await flask("/api/user/payout-wallet", { method: "POST", token, body: { wallet_address: String(body.wallet) } });
    return Response.json({ ok: r.status === 200 && r.data.success !== false, error: r.data.error }, { status: r.status === 200 ? 200 : 400 });
  }
  if (body.action === "payout") {
    const r = await flask("/api/user/request-payout", { method: "POST", token, body: { wallet_address: String(body.wallet || "") } });
    if (r.status !== 200 || r.data.success === false) {
      return Response.json({ ok: false, error: String(r.data.error || "Payout request failed") }, { status: 400 });
    }
    return Response.json({ ok: true, message: r.data.message });
  }
  return Response.json({ ok: false, error: "Unknown action" }, { status: 400 });
}

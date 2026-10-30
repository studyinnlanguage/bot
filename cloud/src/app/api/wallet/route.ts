import { NextRequest } from "next/server";
import { flaskUser, referralInfo, txnsFromReferral, flask } from "@/lib/wx-backend";

/**
 * GET /api/wallet → REAL referral wallet from the bot SaaS
 * (commissions are earned when referred users buy license packages).
 */
export async function GET(req: NextRequest) {
  const header = req.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return Response.json({ ok: false, error: "Session expired" }, { status: 401 });

  const ctx = await flaskUser(token);
  if (!ctx) return Response.json({ ok: false, error: "Session expired" }, { status: 401 });

  const ref = await referralInfo(token);
  return Response.json({
    ok: true,
    wallet: {
      balance: Number(ref.available_balance ?? 0),
      lifetimeEarnings: Number(ref.referral_earnings ?? 0),
      friendsInvited: Number(ref.referral_count ?? 0),
      activeReferrals: Number(ref.referral_count ?? 0),
      referralCode: ref.referral_code || ctx.referral_code || "",
      payoutWallet: ref.payout_wallet || "",
      pendingPayout: Number(ref.pending_payout ?? 0),
      totalWithdrawn: Number(ref.total_withdrawn ?? 0),
      bonusRates: { yearly: 10, lifetime: 50 },
    },
    txns: txnsFromReferral(ref),
  });
}

/** POST /api/wallet → { action: "payout" | "payout-wallet" } (real payout system). */
export async function POST(req: NextRequest) {
  const header = req.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return Response.json({ ok: false, error: "Session expired" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  if (body.action === "payout") {
    const r = await flask("/api/user/request-payout", {
      method: "POST", token, body: { wallet_address: String(body.wallet || "") },
    });
    if (r.status !== 200 || r.data.success === false) {
      return Response.json({ ok: false, error: String(r.data.error || "Payout request failed") }, { status: 400 });
    }
    return Response.json({ ok: true, message: r.data.message });
  }
  if (body.action === "payout-wallet" && body.wallet) {
    const r = await flask("/api/user/payout-wallet", {
      method: "POST", token, body: { wallet_address: String(body.wallet) },
    });
    if (r.status !== 200 || r.data.success === false) {
      return Response.json({ ok: false, error: String(r.data.error || "Could not save wallet") }, { status: 400 });
    }
    return Response.json({ ok: true });
  }
  return Response.json({ ok: false, error: "Unknown action" }, { status: 400 });
}

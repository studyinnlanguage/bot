import { NextRequest } from "next/server";
import { flask } from "@/lib/wx-backend";

/**
 * POST /api/auth/google → { id_token } verified by the REAL bot SaaS
 * (Flask /api/auth/google against Google tokeninfo, aud-checked).
 * Also bridges the Flask session cookie for the classic bot pages.
 */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const idToken = String(body.id_token || body.credential || "").trim();
  if (!idToken) return Response.json({ ok: false, error: "id_token is required" }, { status: 400 });

  const r = await flask("/api/auth/google", {
    method: "POST",
    body: { id_token: idToken },
    captureCookie: true,
  });

  if (r.status !== 200 || !r.data.success) {
    return Response.json(
      { ok: false, error: String(r.data.error || "Google sign-in failed") },
      { status: r.status === 401 || r.status === 403 ? 401 : 502 },
    );
  }

  const user = r.data.user as Record<string, unknown>;
  const res = Response.json({
    ok: true,
    token: r.data.token,
    user: {
      id: user.id, email: user.email, name: user.name,
      plan: "FREE", planValidUntil: null,
      referralCode: "", walletBalance: 0, lifetimeEarn: 0, friendsInvited: 0,
    },
    subscription: r.data.subscription,
  });
  if (r.setCookie) res.headers.append("Set-Cookie", r.setCookie);
  return res;
}

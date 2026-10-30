import { NextRequest } from "next/server";
import { flask } from "@/lib/wx-backend";

/**
 * POST /api/auth/register → proxied to the REAL bot SaaS (Flask /api/auth/signup).
 * Keeps the exact request/response contract the web + app were built against.
 */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const name = String(body.name || "").trim();
  const email = String(body.email || "").trim().toLowerCase();
  const password = String(body.password || "");
  const referral = String(body.referral || "").trim().toUpperCase();

  if (name.length < 2) return Response.json({ ok: false, error: "Please enter your full name" }, { status: 400 });
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return Response.json({ ok: false, error: "Please enter a valid email address" }, { status: 400 });
  if (password.length < 8) return Response.json({ ok: false, error: "Password must be at least 8 characters" }, { status: 400 });

  const r = await flask("/api/auth/signup", {
    method: "POST",
    body: { name, email, password, referral_code: referral },
    captureCookie: true,
  });

  if (r.status !== 200 || !r.data.success) {
    return Response.json(
      { ok: false, error: String(r.data.error || "Registration failed — please try again") },
      { status: r.status === 429 ? 429 : 409 },
    );
  }

  const res = Response.json({
    ok: true,
    token: r.data.token,
    user: {
      ...(r.data.user as Record<string, unknown>),
      plan: "FREE",
      planValidUntil: null,
      referralCode: "",
      walletBalance: 0,
      lifetimeEarn: 0,
      friendsInvited: 0,
    },
  });
  if (r.setCookie) res.headers.append("Set-Cookie", r.setCookie);
  return res;
}

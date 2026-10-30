import { NextRequest } from "next/server";
import { flask } from "@/lib/wx-backend";

/**
 * POST /api/auth/login → proxied to the REAL bot SaaS (Flask).
 * Returns the API token the web app + Android app store, and bridges the
 * Flask session cookie so the classic bot pages (license/packages/admin)
 * also recognise the login.
 */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  const r = await flask("/api/auth/login", {
    method: "POST",
    body: { email: body.email, password: body.password },
    captureCookie: true,
  });

  if (r.status !== 200 || !r.data.success) {
    return Response.json(
      { ok: false, error: String(r.data.error || "Invalid email or password") },
      { status: r.status === 429 ? 429 : 401 },
    );
  }

  const res = Response.json({
    ok: true,
    token: r.data.token,
    user: r.data.user,
    subscription: r.data.subscription,
  });
  if (r.setCookie) res.headers.append("Set-Cookie", r.setCookie);
  return res;
}

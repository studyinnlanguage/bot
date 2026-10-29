import { NextRequest } from "next/server";

/**
 * GET /api/auth/config → { googleClientId }
 * Public config for the login screens. Empty string = Google button shows a
 * friendly "not configured" note instead of failing.
 */
export async function GET(_req: NextRequest) {
  const clientId = (process.env.GOOGLE_CLIENT_IDS || "").split(",")[0].trim() || "";
  return Response.json({ ok: true, googleClientId: clientId });
}

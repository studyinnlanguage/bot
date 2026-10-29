import { NextRequest } from "next/server";

/**
 * GET /api/health → lets the Android app detect whether the server runs the
 * NEW Weexionic Cloud dashboard (ok:true, api:2) or an old Flask bot (404).
 */
export async function GET(_req: NextRequest) {
  return Response.json({ ok: true, name: "weexionic-cloud", api: 2, time: new Date().toISOString() });
}

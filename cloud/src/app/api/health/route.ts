import { NextRequest } from "next/server";
import { flask } from "@/lib/wx-backend";

/**
 * GET /api/health → reports both halves of the merged deployment:
 * the Next.js frontend and the REAL bot backend (Flask SaaS + engines).
 */
export async function GET(_req: NextRequest) {
  const backend = await flask("/api/health");
  const backendUp = backend.status === 200 && backend.data.success !== false;
  return Response.json({
    ok: true,
    name: "weexionic-cloud",
    api: 2,
    backend: backendUp ? "up" : "down",
    time: new Date().toISOString(),
  });
}

import { NextRequest } from "next/server";
import { flask } from "@/lib/wx-backend";

/** POST /api/auth/logout → stops the user's bot and clears the session. */
export async function POST(req: NextRequest) {
  const header = req.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (token) await flask("/api/auth/logout", { method: "POST", token });
  return Response.json({ ok: true });
}

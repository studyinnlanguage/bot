import { NextRequest } from "next/server";
import { db } from "@/lib/db";
import { jsonError } from "@/lib/wx-auth";

export async function POST(req: NextRequest) {
  const header = req.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return jsonError("No active session", 400);
  await db.session.deleteMany({ where: { id: token } });
  return Response.json({ ok: true });
}

import { NextRequest } from "next/server";
import { db } from "@/lib/db";
import { authUser, jsonError } from "@/lib/wx-auth";

function mask(v: string): string {
  const v2 = v.trim();
  if (v2.length <= 8) return v2.slice(0, 2) + "••••••";
  return v2.slice(0, 4) + "••••••••" + v2.slice(-4);
}

export async function POST(req: NextRequest) {
  const user = await authUser(req);
  if (!user) return jsonError("Session expired — please log in again", 401);

  const body = await req.json().catch(() => ({}));
  const exchange = String(body.exchange || "BINANCE").toUpperCase();
  const apiKey = String(body.apiKey || "").trim();
  const apiSecret = String(body.apiSecret || "").trim();
  const label = String(body.label || "Main Account").trim() || "Main Account";

  if (apiKey.length < 8 || apiSecret.length < 8) return jsonError("API key and secret must be at least 8 characters", 400);

  const count = await db.apiKey.count({ where: { userId: user.id } });
  if (count >= 3) return jsonError("Maximum 3 exchange keys allowed per account", 400);

  const key = await db.apiKey.create({
    data: { userId: user.id, exchange, label, keyMasked: mask(apiKey), secretMasked: mask(apiSecret) },
  });

  return Response.json({ ok: true, key });
}

export async function DELETE(req: NextRequest) {
  const user = await authUser(req);
  if (!user) return jsonError("Session expired — please log in again", 401);

  const id = req.nextUrl.searchParams.get("id") || "";
  const key = await db.apiKey.findUnique({ where: { id } });
  if (!key || key.userId !== user.id) return jsonError("Key not found", 404);

  await db.apiKey.delete({ where: { id } });
  return Response.json({ ok: true });
}

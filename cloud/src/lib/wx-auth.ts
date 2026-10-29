import { NextRequest } from "next/server";
import crypto from "crypto";
import { db } from "@/lib/db";

export interface WxUser {
  id: string;
  email: string;
  name: string;
  plan: string;
  planValidUntil: string | null;
  referralCode: string;
  walletBalance: number;
  lifetimeEarn: number;
  friendsInvited: number;
  createdAt: string;
}

export function hashPassword(password: string): string {
  const salt = crypto.randomBytes(16).toString("hex");
  const hash = crypto.scryptSync(password, salt, 64).toString("hex");
  return `${salt}:${hash}`;
}

export function verifyPassword(password: string, stored: string): boolean {
  const [salt, hash] = stored.split(":");
  if (!salt || !hash) return false;
  const candidate = crypto.scryptSync(password, salt, 64).toString("hex");
  try {
    return crypto.timingSafeEqual(Buffer.from(hash, "hex"), Buffer.from(candidate, "hex"));
  } catch {
    return false;
  }
}

export function makeToken(): string {
  return crypto.randomBytes(24).toString("hex");
}

export function makeReferralCode(): string {
  return "WX" + crypto.randomBytes(4).toString("hex").toUpperCase();
}

export function publicUser(u: {
  id: string; email: string; name: string; plan: string;
  planValidUntil: Date | null; referralCode: string;
  walletBalance: number; lifetimeEarn: number; friendsInvited: number;
  createdAt: Date;
}): WxUser {
  return {
    id: u.id,
    email: u.email,
    name: u.name,
    plan: u.plan,
    planValidUntil: u.planValidUntil ? u.planValidUntil.toISOString() : null,
    referralCode: u.referralCode,
    walletBalance: u.walletBalance,
    lifetimeEarn: u.lifetimeEarn,
    friendsInvited: u.friendsInvited,
    createdAt: u.createdAt.toISOString(),
  };
}

/** Extract Bearer token user from request. Returns null when unauthorized. */
export async function authUser(req: NextRequest) {
  const header = req.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token || token.length < 16) return null;
  const session = await db.session.findUnique({ where: { id: token }, include: { user: true } });
  if (!session) return null;
  return session.user;
}

export function jsonError(message: string, status: number) {
  return Response.json({ ok: false, error: message }, { status });
}

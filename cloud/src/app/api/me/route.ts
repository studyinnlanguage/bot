import { NextRequest } from "next/server";
import { db } from "@/lib/db";
import { authUser, jsonError } from "@/lib/wx-auth";

export async function GET(req: NextRequest) {
  const user = await authUser(req);
  if (!user) return jsonError("Session expired — please log in again", 401);

  const keys = await db.apiKey.findMany({ where: { userId: user.id }, orderBy: { createdAt: "desc" } });
  const txns = await db.walletTxn.findMany({ where: { userId: user.id }, orderBy: { createdAt: "desc" }, take: 30 });

  return Response.json({
    ok: true,
    user: {
      id: user.id, name: user.name, email: user.email, plan: user.plan,
      planValidUntil: user.planValidUntil ? user.planValidUntil.toISOString() : null,
      referralCode: user.referralCode,
      walletBalance: user.walletBalance, lifetimeEarn: user.lifetimeEarn,
      friendsInvited: user.friendsInvited, createdAt: user.createdAt.toISOString(),
    },
    keys,
    txns,
    network: {
      cluster: "WEEXIONIC CLOUD",
      host: "cloud.weexionic.app",
      region: "auto-assigned on login",
      client: "Weexionic App v3.0.0",
      engine: "Native Engine Client",
    },
  });
}

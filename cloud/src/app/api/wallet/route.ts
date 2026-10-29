import { NextRequest } from "next/server";
import { db } from "@/lib/db";
import { authUser, jsonError } from "@/lib/wx-auth";

export async function GET(req: NextRequest) {
  const user = await authUser(req);
  if (!user) return jsonError("Session expired — please log in again", 401);

  const txns = await db.walletTxn.findMany({ where: { userId: user.id }, orderBy: { createdAt: "desc" }, take: 50 });

  return Response.json({
    ok: true,
    wallet: {
      balance: user.walletBalance,
      lifetimeEarnings: user.lifetimeEarn,
      friendsInvited: user.friendsInvited,
      activeReferrals: Math.max(0, user.friendsInvited),
      referralCode: user.referralCode,
    },
    txns,
  });
}

export async function POST(req: NextRequest) {
  const user = await authUser(req);
  if (!user) return jsonError("Session expired — please log in again", 401);

  const body = await req.json().catch(() => ({}));

  if (body.action === "payout") {
    if (user.walletBalance < 20) return jsonError("Minimum payout is $20.00", 400);
    const amount = Math.min(user.walletBalance, Number(body.amount) || user.walletBalance);
    await db.$transaction([
      db.user.update({ where: { id: user.id }, data: { walletBalance: { decrement: amount } } }),
      db.walletTxn.create({ data: { userId: user.id, type: "PAYOUT", amount: -amount, note: "Payout to linked USDT wallet", status: "PENDING" } }),
    ]);
    return Response.json({ ok: true });
  }

  return jsonError("Unknown action", 400);
}

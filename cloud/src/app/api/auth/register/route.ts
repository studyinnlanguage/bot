import { NextRequest } from "next/server";
import { db } from "@/lib/db";
import { hashPassword, makeToken, makeReferralCode, publicUser, jsonError } from "@/lib/wx-auth";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const name = String(body.name || "").trim();
    const email = String(body.email || "").trim().toLowerCase();
    const password = String(body.password || "");
    const referral = String(body.referral || "").trim().toUpperCase();

    if (name.length < 2) return jsonError("Please enter your full name", 400);
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return jsonError("Please enter a valid email address", 400);
    if (password.length < 6) return jsonError("Password must be at least 6 characters", 400);

    const exists = await db.user.findUnique({ where: { email } });
    if (exists) return jsonError("This email is already registered — try logging in", 409);

    let inviter: { id: string } | null = null;
    if (referral) {
      inviter = await db.user.findUnique({ where: { referralCode: referral } });
      if (!inviter) return jsonError("Invalid referral code", 400);
    }

    const planValid = new Date();
    planValid.setDate(planValid.getDate() + 14);

    const user = await db.user.create({
      data: {
        name, email,
        passwordHash: hashPassword(password),
        referralCode: makeReferralCode(),
        plan: "PRO",
        planValidUntil: planValid,
        referredBy: inviter ? inviter.id : null,
      },
    });

    await db.engineState.create({
      data: { userId: user.id, symbols: JSON.stringify(["BTCUSDT", "ETHUSDT", "SOLUSDT"]) },
    });

    if (inviter) {
      await db.$transaction([
        db.user.update({ where: { id: inviter.id }, data: { walletBalance: { increment: 10 }, lifetimeEarn: { increment: 10 }, friendsInvited: { increment: 1 } } }),
        db.walletTxn.create({ data: { userId: inviter.id, type: "COMMISSION", amount: 10, note: "New referral joined Weexionic PRO" } }),
      ]);
    }

    const token = makeToken();
    await db.session.create({ data: { id: token, userId: user.id } });

    return Response.json({ ok: true, token, user: publicUser(user) });
  } catch {
    return jsonError("Registration failed — please try again", 500);
  }
}

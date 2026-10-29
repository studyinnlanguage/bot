import { NextRequest } from "next/server";
import crypto from "crypto";
import { db } from "@/lib/db";
import { hashPassword, makeToken, makeReferralCode, publicUser, jsonError } from "@/lib/wx-auth";

interface GooglePayload {
  aud?: string;
  sub?: string;
  email?: string;
  email_verified?: string | boolean;
  name?: string;
  picture?: string;
  exp?: string;
}

/**
 * POST /api/auth/google  { credential: "<Google ID token>", referral?: "WX..." }
 * Verifies the ID token with Google's tokeninfo endpoint, then either logs the
 * user in (existing email) or creates the account automatically (one-tap signup).
 * Referral attribution works exactly like email signup (+10 to the inviter).
 */
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const credential = String(body.credential || "").trim();
    const referral = String(body.referral || "").trim().toUpperCase();
    if (!credential || credential.length < 20) return jsonError("Google credential missing", 400);

    // 1) Verify the ID token with Google (signature + expiry validated by Google).
    const verifyRes = await fetch(
      `https://oauth2.googleapis.com/tokeninfo?id_token=${encodeURIComponent(credential)}`,
      { cache: "no-store" }
    );
    if (!verifyRes.ok) return jsonError("Google login verify nahi hui — dobara koshish karein", 401);
    const gp = (await verifyRes.json()) as GooglePayload;

    // 2) Expiry + email verification checks.
    const exp = Number(gp.exp || 0);
    if (!gp.email || !gp.sub) return jsonError("Google account se email nahi mila", 400);
    if (exp * 1000 < Date.now() - 60_000) return jsonError("Google session expire ho gayi — dobara try karein", 401);
    const verified = gp.email_verified === true || gp.email_verified === "true";
    if (!verified) return jsonError("Google email verified nahi hai", 400);

    // 3) Audience check — strict when GOOGLE_CLIENT_IDS env is configured,
    //    lenient (any Google-issued token for a verified email) otherwise.
    const configured = (process.env.GOOGLE_CLIENT_IDS || "").split(",").map(s => s.trim()).filter(Boolean);
    if (configured.length > 0 && gp.aud && !configured.includes(gp.aud)) {
      return jsonError("Google client mismatch — app update karein", 401);
    }

    // 4) Referral resolution (same rules as email signup).
    let inviter: { id: string } | null = null;
    if (referral) {
      inviter = await db.user.findUnique({ where: { referralCode: referral } });
      if (!inviter) return jsonError("Invalid referral code", 400);
    }

    // 5) Existing user → straight login. New user → auto signup.
    let user = await db.user.findUnique({ where: { email: gp.email.toLowerCase() } });
    if (!user) {
      const planValid = new Date();
      planValid.setDate(planValid.getDate() + 14);
      user = await db.user.create({
        data: {
          name: (gp.name || gp.email.split("@")[0] || "Weexionic Trader").slice(0, 60),
          email: gp.email.toLowerCase(),
          passwordHash: hashPassword(crypto.randomBytes(24).toString("hex")), // un-guessable; email login disabled for Google accounts
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
          db.walletTxn.create({ data: { userId: inviter.id, type: "COMMISSION", amount: 10, note: "New referral joined via Google signup" } }),
        ]);
      }
    }

    const token = makeToken();
    await db.session.create({ data: { id: token, userId: user.id } });
    return Response.json({ ok: true, token, user: publicUser(user) });
  } catch {
    return jsonError("Google login fail hui — thodi dair baad koshish karein", 500);
  }
}

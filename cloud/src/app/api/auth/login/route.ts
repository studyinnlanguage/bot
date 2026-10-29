import { NextRequest } from "next/server";
import { db } from "@/lib/db";
import { verifyPassword, makeToken, publicUser, jsonError } from "@/lib/wx-auth";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const email = String(body.email || "").trim().toLowerCase();
    const password = String(body.password || "");

    if (!email || !password) return jsonError("Email and password are required", 400);

    const user = await db.user.findUnique({ where: { email } });
    if (!user || !verifyPassword(password, user.passwordHash)) {
      return jsonError("Wrong email or password — workers could not verify you", 401);
    }

    const token = makeToken();
    await db.session.create({ data: { id: token, userId: user.id } });

    return Response.json({ ok: true, token, user: publicUser(user) });
  } catch {
    return jsonError("Login failed — please try again", 500);
  }
}

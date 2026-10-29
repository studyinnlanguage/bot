import { NextRequest } from "next/server";
import { authUser, jsonError } from "@/lib/wx-auth";
import {
  loadRuntime, tickEngine, snapshotState, marketSnapshot,
  actionStart, actionStop, actionConfig, actionManual, actionClose, actionCloseAll, resetAccount,
  persistRuntime, persistIfDirty,
} from "@/lib/wx-engine";

export async function GET(req: NextRequest) {
  const user = await authUser(req);
  if (!user) return jsonError("Session expired — please log in again", 401);

  const rt = await loadRuntime(user.id);
  await tickEngine(rt);
  await persistIfDirty(rt);   // awaited — floating promises are killed after response

  return Response.json({
    ok: true,
    engine: snapshotState(rt),
    market: await marketSnapshot(rt.timeframe),
    user: {
      id: user.id, name: user.name, email: user.email, plan: user.plan,
      planValidUntil: user.planValidUntil ? user.planValidUntil.toISOString() : null,
      referralCode: user.referralCode,
      walletBalance: user.walletBalance, lifetimeEarn: user.lifetimeEarn,
      friendsInvited: user.friendsInvited,
    },
  });
}

export async function POST(req: NextRequest) {
  const user = await authUser(req);
  if (!user) return jsonError("Session expired — please log in again", 401);

  const body = await req.json().catch(() => ({}));
  const action = String(body.action || "");
  const rt = await loadRuntime(user.id);
  await tickEngine(rt);

  switch (action) {
    case "start": actionStart(rt); break;
    case "stop": actionStop(rt); break;
    case "config": actionConfig(rt, body.config || {}); break;
    case "manual": {
      const res = await actionManual(rt, String(body.symbol), body.side === "SHORT" ? "SHORT" : "LONG");
      if (!res.ok) return Response.json({ ok: false, error: res.error }, { status: 400 });
      break;
    }
    case "close": await actionClose(rt, String(body.id)); break;
    case "closeAll": await actionCloseAll(rt); break;
    case "reset": resetAccount(rt); break;
    default: return jsonError("Unknown action", 400);
  }

  await persistRuntime(rt);   // awaited — config/positions must reach the DB before responding

  return Response.json({ ok: true, engine: snapshotState(rt), market: await marketSnapshot(rt.timeframe) });
}

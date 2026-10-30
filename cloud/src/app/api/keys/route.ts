import { NextRequest } from "next/server";
import { flaskUser, flask, keysFromConfig } from "@/lib/wx-backend";

function maskLocal(v: string): string {
  const v2 = v.trim();
  if (v2.length <= 8) return v2.slice(0, 2) + "••••••";
  return v2.slice(0, 4) + "••••••••" + v2.slice(-4);
}

/** GET /api/keys → the user's REAL exchange keys (masked) from bot config. */
export async function GET(req: NextRequest) {
  const header = req.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return Response.json({ ok: false, error: "Session expired" }, { status: 401 });

  const ctx = await flaskUser(token);
  if (!ctx) return Response.json({ ok: false, error: "Session expired" }, { status: 401 });
  return Response.json({ ok: true, keys: keysFromConfig(ctx.botConfig) });
}

/**
 * POST /api/keys → stores REAL exchange API keys in the bot config
 * (encrypted at rest by the SaaS) and live-pushes them to the running engine.
 */
export async function POST(req: NextRequest) {
  const header = req.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return Response.json({ ok: false, error: "Session expired" }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const exchange = String(body.exchange || "BINANCE").toUpperCase();
  const apiKey = String(body.apiKey || "").trim();
  const apiSecret = String(body.apiSecret || "").trim();

  if (apiKey.length < 8 || apiSecret.length < 8) {
    return Response.json({ ok: false, error: "API key and secret must be at least 8 characters" }, { status: 400 });
  }

  const ex = exchange === "WEEX" ? "weex" : "binance";
  const r = await flask("/api/bot/config", {
    method: "POST",
    token,
    body: { exchange: ex, api_key: apiKey, api_secret: apiSecret },
  });

  if (r.status !== 200 || r.data.success === false) {
    return Response.json({ ok: false, error: String(r.data.error || "Could not save key") }, { status: 400 });
  }

  const config = (r.data.config || {}) as Record<string, unknown>;
  return Response.json({
    ok: true,
    key: {
      id: "primary",
      exchange: ex.toUpperCase(),
      label: "Main Account",
      keyMasked: String(config.api_key_masked || maskLocal(apiKey)),
      secretMasked: "***",
      createdAt: new Date().toISOString(),
    },
  });
}

/** DELETE /api/keys?id=… → clears stored exchange keys. */
export async function DELETE(req: NextRequest) {
  const header = req.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  if (!token) return Response.json({ ok: false, error: "Session expired" }, { status: 401 });

  const r = await flask("/api/bot/config", { method: "POST", token, body: { clear_keys: true } });
  if (r.status !== 200 || r.data.success === false) {
    return Response.json({ ok: false, error: String(r.data.error || "Could not remove key") }, { status: 400 });
  }
  return Response.json({ ok: true });
}

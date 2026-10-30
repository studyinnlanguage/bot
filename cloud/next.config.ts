import type { NextConfig } from "next";

/* Flask SaaS (the REAL bot backend) runs on an internal port inside the same
 * container. The classic bot pages — license activation, packages/payment,
 * admin panel, legal pages and the full classic dashboard — are proxied here
 * so they live on the SAME domain as the new Weexionic frontend.
 * API endpoints used by the new frontend (/api/auth, /api/me, /api/engine,
 * /api/keys, /api/wallet, /api/health) are Next.js routes and are NOT proxied. */
const FLASK = process.env.INTERNAL_API || "http://127.0.0.1:5001";
const ADMIN_PATH = (process.env.ADMIN_SECRET_PATH || "/x7k2-admin").replace(/\/$/, "");

const nextConfig: NextConfig = {
  output: "standalone",
  typescript: {
    ignoreBuildErrors: true,
  },
  reactStrictMode: false,
  async rewrites() {
    // Classic bot SaaS pages + their APIs (session-cookie authenticated)
    const sources = [
      "/home", "/login", "/license", "/packages", "/payment/:path*", "/admin",
      "/legal", "/privacy", "/terms", "/security", "/disclaimer", "/risk-disclaimer",
      "/static/:path*", "/auth/google", "/auth/google/callback", "/favicon-old.ico",
      "/bot/:path*", "/bot",
      "/api/packages", "/api/orders/:path*", "/api/license/:path*",
      "/api/admin/:path*", "/api/user/referral", "/api/user/payout-wallet",
      "/api/user/request-payout", "/api/debug/:path*",
      ADMIN_PATH, `${ADMIN_PATH}/:path*`,
    ];
    const out: { source: string; destination: string }[] = [];
    for (const s of sources) out.push({ source: s, destination: `${FLASK}${s}` });
    return out;
  },
};

export default nextConfig;

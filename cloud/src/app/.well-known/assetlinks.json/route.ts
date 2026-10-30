import { NextRequest } from "next/server";

/**
 * GET /.well-known/assetlinks.json — Android App Links verification for the
 * Weexionic app (https://<server>/r/<CODE> auto-opens the app).
 * Set APP_SHA256 env (colon-less SHA-256 of the signing cert) on the server to
 * enable full verification; fingerprints can be comma-separated.
 */
export async function GET(_req: NextRequest) {
  const sha256s = (process.env.APP_SHA256 || "")
    .split(",")
    .map(s => s.trim().replace(/:/g, "").toUpperCase())
    .filter(s => s.length === 64);

  const statements = [
    {
      relation: ["delegate_permission/common.handle_all_urls"],
      target: {
        namespace: "android_app",
        package_name: "com.exionic.trader",
        sha256_cert_fingerprints: sha256s,
      },
    },
  ];
  return Response.json(statements, { headers: { "Content-Type": "application/json" } });
}

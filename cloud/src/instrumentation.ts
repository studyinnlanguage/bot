/* Next.js instrumentation — starts the engine heartbeat once per server
 * process so the Quad-Trend engine keeps trading even when no client polls. */
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    const { startHeartbeat } = await import("@/lib/wx-engine");
    startHeartbeat();
  }
}

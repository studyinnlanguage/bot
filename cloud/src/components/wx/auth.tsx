"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Eye, EyeOff, Check, ArrowRight, Send, Globe, Loader2 } from "lucide-react";
import { YELLOW } from "./types";

const CHECKS = [
  "Funds stay on your exchange — always",
  "Strict 1:1 risk locked on every trade",
  "Instant alerts on Telegram & WhatsApp",
];

function WxLogo({ size = "md" }: { size?: "md" | "lg" }) {
  const box = size === "lg" ? "h-12 w-12 rounded-2xl text-2xl" : "h-9 w-9 rounded-xl text-lg";
  return (
    <div className="flex items-center gap-2.5">
      <div className={`${box} flex items-center justify-center font-black text-black`} style={{ background: YELLOW }}>W</div>
      <div className={`font-extrabold tracking-tight ${size === "lg" ? "text-2xl" : "text-xl"}`}>
        <span style={{ color: YELLOW }}>WEEX</span><span className="text-white">IONIC</span>
      </div>
    </div>
  );
}

interface Props { onAuthed: (token: string, remember: boolean) => void; }

export function AuthScreen({ onAuthed }: Props) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [referral, setReferral] = useState("");
  const [showReferral, setShowReferral] = useState(false);
  const [showPass, setShowPass] = useState(false);
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [googleClientId, setGoogleClientId] = useState<string | null>(null);
  const [refApplied, setRefApplied] = useState("");

  /* referral landing page (/r/CODE) saved the code — auto-apply it */
  useEffect(() => {
    try {
      const r = localStorage.getItem("wx_ref");
      if (r) { setReferral(r.toUpperCase()); setShowReferral(true); setRefApplied(r.toUpperCase()); }
    } catch { /* ignore */ }
  }, []);

  /* fetch Google client config once */
  useEffect(() => {
    fetch("/api/auth/config").then(r => r.json()).then(d => {
      if (d && d.ok && d.googleClientId) setGoogleClientId(d.googleClientId);
    }).catch(() => { /* Google button will show the not-configured note */ });
  }, []);

  async function googleCredential(credential: string) {
    setError(""); setBusy(true);
    try {
      const res = await fetch("/api/auth/google", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential, referral }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) { setError(data.error || "Google login fail"); setBusy(false); return; }
      onAuthed(data.token, true);
    } catch {
      setError("Network error — please try again"); setBusy(false);
    }
  }

  async function googleFlow() {
    setError("");
    if (!googleClientId) {
      setError("Google login server par abhi configure nahi hui — email se signup karein");
      return;
    }
    try {
      if (!(window as any).google?.accounts?.id) {
        await new Promise<void>((resolve, reject) => {
          const s = document.createElement("script");
          s.src = "https://accounts.google.com/gsi/client";
          s.async = true; s.defer = true;
          s.onload = () => resolve();
          s.onerror = () => reject(new Error("gsi"));
          document.head.appendChild(s);
        });
      }
      const gsi = (window as any).google?.accounts?.id;
      if (!gsi) throw new Error("gsi");
      gsi.initialize({ client_id: googleClientId, callback: (resp: { credential?: string }) => {
        if (resp?.credential) googleCredential(resp.credential);
      } });
      gsi.prompt();
    } catch {
      setError("Google login load nahi hui — dobara try karein");
    }
  }

  async function submit() {
    setError("");
    setBusy(true);
    try {
      const url = mode === "login" ? "/api/auth/login" : "/api/auth/register";
      const payload = mode === "login" ? { email, password } : { name, email, password, referral };
      const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await res.json();
      if (!res.ok || !data.ok) { setError(data.error || "Something went wrong"); setBusy(false); return; }
      onAuthed(data.token, remember);
    } catch {
      setError("Network error — please try again");
      setBusy(false);
    }
  }

  const field = "bg-[#0A0E15] border-white/[0.08] text-white placeholder:text-[#4A5265] h-11 rounded-lg focus-visible:ring-[#F5C518]/40 text-sm";

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-[#05070B] px-5 pb-8 pt-10">
      <WxLogo />

      {mode === "login" ? (
        <div className="mt-7">
          <h1 className="text-[26px] font-extrabold leading-tight text-white">
            Log in.<br />Let the bot do the <span style={{ color: YELLOW }}>watching.</span>
          </h1>
          <p className="mt-2.5 text-[12.5px] leading-relaxed text-[#8A93A6]">
            Your workers are already polling the market every 5 seconds — fresh crossovers don&apos;t wait for anyone.
          </p>
          <ul className="mt-4 space-y-2">
            {CHECKS.map(c => (
              <li key={c} className="flex items-center gap-2 text-[11.5px] text-[#B7BECF]">
                <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full" style={{ background: `${YELLOW}22` }}>
                  <Check className="h-2.5 w-2.5" style={{ color: YELLOW }} />
                </span>
                {c}
              </li>
            ))}
          </ul>
          <div className="mt-4 grid grid-cols-3 gap-2">
            {[["3", "EXCHANGES"], ["24/7", "AUTOPILOT"], ["1:1", "RISK LOCK"]].map(([v, l]) => (
              <div key={l} className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-2 py-2 text-center">
                <div className="text-sm font-bold" style={{ color: YELLOW }}>{v}</div>
                <div className="text-[8.5px] font-semibold tracking-wider text-[#6B7488]">{l}</div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-7">
          <h1 className="text-[26px] font-extrabold leading-tight text-white">
            Create your account.<br />Zero setup, <span style={{ color: YELLOW }}>zero servers.</span>
          </h1>
          <p className="mt-2.5 text-[12.5px] leading-relaxed text-[#8A93A6]">
            Register once — your terminal, positions, history and keys are saved to your ID and restored on every login.
          </p>
        </div>
      )}

      <div className="mt-5 rounded-xl border border-white/[0.07] bg-[#0A0D13] p-4">
        <h2 className="text-base font-bold text-white">{mode === "login" ? "Welcome back" : "Get started free"}</h2>
        <p className="mt-0.5 text-[11px] text-[#6B7488]">
          {mode === "login"
            ? "Log in to your trading terminal — workers resume exactly where they left off."
            : "Set up your terminal in under a minute — no card, no server URL, no config."}
        </p>

        <div className="mt-4 space-y-3">
          {mode === "register" && (
            <div>
              <label className="mb-1.5 block text-[9.5px] font-bold tracking-[0.12em] text-[#6B7488]">FULL NAME</label>
              <Input className={field} placeholder="e.g. Block Chain" value={name} onChange={e => setName(e.target.value)} />
            </div>
          )}
          <div>
            <label className="mb-1.5 block text-[9.5px] font-bold tracking-[0.12em] text-[#6B7488]">EMAIL ADDRESS</label>
            <Input className={field} type="email" placeholder="trader@example.com" value={email} onChange={e => setEmail(e.target.value)} />
          </div>
          <div>
            <label className="mb-1.5 block text-[9.5px] font-bold tracking-[0.12em] text-[#6B7488]">PASSWORD</label>
            <div className="relative">
              <Input className={`${field} pr-10`} type={showPass ? "text" : "password"} placeholder="••••••••••" value={password}
                onChange={e => setPassword(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !busy) submit(); }} />
              <button type="button" onClick={() => setShowPass(v => !v)} aria-label="Toggle password visibility"
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[#6B7488] hover:text-white">
                {showPass ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>
          {mode === "register" && (
            <div>
              {showReferral ? (
                <>
                  <label className="mb-1.5 block text-[9.5px] font-bold tracking-[0.12em] text-[#6B7488]">REFERRAL CODE (OPTIONAL)</label>
                  <Input className={`${field} font-mono uppercase`} placeholder="WX4F2A1C" value={referral} onChange={e => setReferral(e.target.value)} />
                  {refApplied && referral === refApplied && (
                    <p className="mt-1 text-[10.5px] font-medium text-[#22C55E]">✓ Referral auto-applied from invite link</p>
                  )}
                </>
              ) : (
                <button type="button" className="text-[11px] font-medium" style={{ color: YELLOW }} onClick={() => setShowReferral(true)}>
                  + Have a referral code?
                </button>
              )}
            </div>
          )}
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-[#FF4D5E]/30 bg-[#FF4D5E]/[0.08] px-3 py-2 text-[11.5px] text-[#FF4D5E]">
            {error}
          </div>
        )}

        {mode === "login" && (
          <div className="mt-3.5 flex items-center justify-between">
            <label className="flex cursor-pointer items-center gap-2 text-[11.5px] text-[#8A93A6]">
              <Checkbox checked={remember} onCheckedChange={v => setRemember(v === true)} className="border-white/20 data-[state=checked]:bg-[#F5C518] data-[state=checked]:border-[#F5C518] data-[state=checked]:text-black" />
              Remember me
            </label>
            <button type="button" className="text-[11.5px] font-medium" style={{ color: YELLOW }}
              onClick={() => setError("")}>Forgot password?</button>
          </div>
        )}

        <Button disabled={busy} onClick={submit}
          className="mt-4 h-11 w-full rounded-lg text-[13.5px] font-bold text-black hover:opacity-90"
          style={{ background: YELLOW }}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : mode === "login" ? <>Log In to Terminal <ArrowRight className="ml-1 h-4 w-4" /></> : <>Create Account <ArrowRight className="ml-1 h-4 w-4" /></>}
        </Button>

        <div className="my-3.5 flex items-center gap-3">
          <div className="h-px flex-1 bg-white/[0.07]" />
          <span className="text-[10px] text-[#4A5265]">or continue with</span>
          <div className="h-px flex-1 bg-white/[0.07]" />
        </div>
        <div className="grid grid-cols-2 gap-2.5">
          <Button variant="outline" className="h-10 rounded-lg border-white/[0.09] bg-transparent text-[12px] text-[#C7CEDE] hover:bg-white/[0.04] hover:text-white"
            onClick={() => setError("")}>
            <Send className="mr-1.5 h-3.5 w-3.5" /> Telegram
          </Button>
          <Button variant="outline" disabled={busy} className="h-10 rounded-lg border-white/[0.09] bg-transparent text-[12px] text-[#C7CEDE] hover:bg-white/[0.04] hover:text-white"
            onClick={googleFlow}>
            <Globe className="mr-1.5 h-3.5 w-3.5" /> Google
          </Button>
        </div>

        <p className="mt-4 text-center text-[11.5px] text-[#6B7488]">
          {mode === "login" ? "New to WEEXIONIC?" : "Already have a terminal?"}{" "}
          <button type="button" className="font-semibold" style={{ color: YELLOW }}
            onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
            {mode === "login" ? "Create your account →" : "Log in →"}
          </button>
        </p>
      </div>

      <p className="mt-4 text-center text-[9.5px] leading-relaxed text-[#3E4658]">
        Demo build — data is simulated paper-trading on live-shaped market feeds.<br />
        Your exchange keys never leave this server in plain text.
      </p>
      {refApplied && (
        <p className="mt-1 text-center text-[9.5px] text-[#22C55E]">Invite link se aaye ho — signup par referral ({refApplied}) automatically lagega.</p>
      )}
    </div>
  );
}

export function ConnectingScreen({ name }: { name: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center bg-[#05070B] px-8">
      <div className="animate-pulse">
        <WxLogo size="lg" />
      </div>
      <div className="mt-8 w-full max-w-[240px] space-y-2.5">
        {[
          `Authenticating ${name.split(" ")[0]}…`,
          "Allocating Weexionic Cloud server…",
          "Restoring positions, keys & history…",
          "Syncing live market feed…",
        ].map((s, i) => (
          <div key={s} className="flex items-center gap-2.5" style={{ animation: `wx-fade 0.5s ease ${i * 0.35}s both` }}>
            <span className="flex h-4 w-4 items-center justify-center rounded-full" style={{ background: `${YELLOW}22` }}>
              <Check className="h-2.5 w-2.5" style={{ color: YELLOW }} />
            </span>
            <span className="text-[11.5px] text-[#8A93A6]">{s}</span>
          </div>
        ))}
      </div>
      <style>{`@keyframes wx-fade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }`}</style>
    </div>
  );
}

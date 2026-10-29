"use client";

import { useEffect, useState } from "react";
import { Check, ArrowRight, Smartphone } from "lucide-react";
import { YELLOW } from "@/components/wx/types";

/**
 * Referral landing page — weexionic.duckdns.org/r/WX4F2A1C
 * Stores the code locally; the dashboard auto-applies it at signup.
 * On Android, the same URL opens the app directly (App Links) — this page is
 * the fallback for browsers/iOS.
 */
export default function ReferralClient({ code }: { code: string }) {
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem("wx_ref", code);
      setSaved(true);
    } catch {
      setSaved(false);
    }
  }, [code]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[#05070B] px-6 py-10">
      <div className="w-full max-w-sm rounded-2xl border border-white/[0.08] bg-[#0A0D13] p-6 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl text-2xl font-black text-black" style={{ background: YELLOW }}>
          W
        </div>
        <h1 className="mt-4 text-xl font-extrabold text-white">
          Friend ne aapko <span style={{ color: YELLOW }}>Weexionic</span> invite kiya hai
        </h1>
        {saved ? (
          <div className="mt-4 flex items-center justify-center gap-2 rounded-lg border border-[#22C55E]/30 bg-[#22C55E]/[0.08] px-3 py-2 text-[12.5px] text-[#22C55E]">
            <Check className="h-3.5 w-3.5" />
            Referral applied: <span className="font-mono font-bold">{code}</span>
          </div>
        ) : (
          <p className="mt-4 text-[12px] text-[#8A93A6]">Referral code save nahi ho saka — signup ke waqt manually enter karein.</p>
        )}
        <p className="mt-3 text-[12.5px] leading-relaxed text-[#8A93A6]">
          Account banate hi dono ko <span className="font-bold text-white">PRO trial</span> milta hai — invite karne wale ko wallet mein <span className="font-bold text-white">$10</span> credit.
        </p>
        <a href="/" className="mt-5 flex h-11 w-full items-center justify-center rounded-lg text-[13.5px] font-bold text-black hover:opacity-90" style={{ background: YELLOW }}>
          Create Account <ArrowRight className="ml-1.5 h-4 w-4" />
        </a>
        <a href={`weexionic://ref/${code}`} className="mt-2.5 flex h-10 w-full items-center justify-center gap-1.5 rounded-lg border border-white/[0.09] text-[12px] text-[#C7CEDE] hover:bg-white/[0.04]">
          <Smartphone className="h-3.5 w-3.5" /> Open in Weexionic app
        </a>
      </div>
      <p className="mt-5 text-center text-[10px] text-[#3E4658]">Quad-Trend Engine · EMA 8/13/21/55 · strict 1:1 risk lock</p>
    </div>
  );
}

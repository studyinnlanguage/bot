"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Copy, Send, Share2, Users, Wallet as WalletIcon, BadgeCheck, KeyRound, Trash2, LogOut, Cloud, ChevronRight, Bell, Globe, Loader2, Check } from "lucide-react";
import { SectionCard } from "./home-markets";
import { fmtUsd, fmtDate, YELLOW, GREEN, RED } from "./types";
import type { WxUser, ApiKeyRow, Txn } from "./types";

/* ───────────────────────────── WALLET ───────────────────────────── */

interface WalletProps {
  user: WxUser;
  txns: Txn[];
  onToast: (msg: string) => void;
  onPayout: () => void;
}

export function WalletTab({ user, txns, onToast, onPayout }: WalletProps) {
  const [tab, setTab] = useState<"referral" | "payouts" | "history">("referral");
  const link = `weexionic.app/r/${user.referralCode}`;

  const payouts = txns.filter(t => t.type === "PAYOUT");
  const others = txns.filter(t => t.type !== "PAYOUT");

  const TxnRow = ({ t }: { t: Txn }) => (
    <div className="flex items-center justify-between border-b border-white/[0.04] px-3.5 py-2.5 last:border-0">
      <div className="flex items-center gap-2.5">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg"
          style={{ background: t.amount >= 0 ? `${GREEN}14` : `${RED}12` }}>
          {t.amount >= 0 ? <BadgeCheck className="h-3.5 w-3.5" style={{ color: GREEN }} /> : <WalletIcon className="h-3.5 w-3.5" style={{ color: RED }} />}
        </span>
        <div>
          <p className="text-[11px] font-bold text-white">{t.note}</p>
          <p className="text-[9px] text-[#6B7488]">{fmtDate(t.createdAt)} · {t.status}</p>
        </div>
      </div>
      <span className="font-mono text-[11.5px] font-bold" style={{ color: t.amount >= 0 ? GREEN : RED }}>
        {t.amount >= 0 ? "+" : "-"}${fmtUsd(Math.abs(t.amount))}
      </span>
    </div>
  );

  return (
    <div className="space-y-3 px-4 pb-6 pt-3">
      <h1 className="text-[22px] font-extrabold text-white">Wallet &amp; Rewards</h1>

      <div className="flex gap-4 border-b border-white/[0.07]">
        {(["referral", "payouts", "history"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className="relative pb-2 text-[11px] font-bold uppercase tracking-wider transition-colors"
            style={{ color: tab === t ? YELLOW : "#6B7488" }}>
            {t}
            {tab === t && <span className="absolute inset-x-0 -bottom-px h-0.5 rounded" style={{ background: YELLOW }} />}
          </button>
        ))}
      </div>

      {tab === "referral" && (
        <>
          <div className="rounded-2xl border p-4 text-center" style={{ borderColor: "rgba(245,197,24,0.22)", background: "linear-gradient(160deg, rgba(245,197,24,0.08), rgba(12,16,23,0.95))" }}>
            <p className="text-[9px] font-bold tracking-[0.16em] text-[#8A93A6]">AVAILABLE BALANCE</p>
            <p className="mt-1 font-mono text-[34px] font-bold leading-none" style={{ color: YELLOW }}>${fmtUsd(user.walletBalance)}</p>
            <p className="mt-1.5 text-[10px] text-[#6B7488]">Lifetime earnings ${fmtUsd(user.lifetimeEarn)}</p>
          </div>

          <SectionCard className="p-3.5">
            <p className="text-[9px] font-bold tracking-[0.14em] text-[#6B7488]">YOUR SHAREABLE LINK</p>
            <div className="mt-2 flex items-center gap-2">
              <div className="flex h-10 flex-1 items-center rounded-lg border border-white/[0.08] bg-[#0A0E15] px-3 font-mono text-[11.5px]" style={{ color: YELLOW }}>{link}</div>
              <Button onClick={() => { onToast("Referral link copied"); try { void navigator.clipboard.writeText(`https://${link}`); } catch { /* clipboard blocked */ } }}
                className="h-10 rounded-lg px-4 text-[11px] font-bold text-black hover:opacity-90" style={{ background: YELLOW }}>
                Copy
              </Button>
            </div>
            <div className="mt-2.5 grid grid-cols-2 gap-2.5">
              <Button variant="outline" className="h-10 rounded-lg border-[1.5px] text-[11.5px] font-bold hover:bg-[#16C784]/10"
                style={{ borderColor: GREEN, color: GREEN }} onClick={() => onToast("Opening WhatsApp share (demo)")}>
                <Send className="mr-1.5 h-3.5 w-3.5" /> WhatsApp
              </Button>
              <Button variant="outline" className="h-10 rounded-lg border-white/[0.12] text-[11.5px] font-bold text-[#C7CEDE] hover:bg-white/[0.04]"
                onClick={() => onToast("Opening Telegram share (demo)")}>
                <Share2 className="mr-1.5 h-3.5 w-3.5" /> Telegram
              </Button>
            </div>
          </SectionCard>

          <SectionCard className="p-3.5">
            <p className="flex items-center gap-1.5 text-[11px] font-bold text-white">
              <Users className="h-3.5 w-3.5" style={{ color: YELLOW }} /> Instant Commission Structure
            </p>
            <div className="mt-2.5 space-y-2">
              {[
                ["1-Year License Invite ($79)", "+$10.00"],
                ["Lifetime License Invite ($500)", "+$50.00"],
              ].map(([l, v]) => (
                <div key={l} className="flex items-center justify-between rounded-lg border border-white/[0.05] bg-white/[0.02] px-3 py-2">
                  <span className="text-[11px] text-[#B7BECF]">{l}</span>
                  <span className="font-mono text-[11px] font-bold" style={{ color: GREEN }}>{v}</span>
                </div>
              ))}
              <div className="grid grid-cols-2 gap-2.5 pt-1">
                <div className="rounded-lg border border-white/[0.05] bg-white/[0.02] px-3 py-2 text-center">
                  <p className="text-[8.5px] font-bold tracking-wider text-[#6B7488]">FRIENDS INVITED</p>
                  <p className="font-mono text-sm font-bold text-white">{user.friendsInvited}</p>
                </div>
                <div className="rounded-lg border border-white/[0.05] bg-white/[0.02] px-3 py-2 text-center">
                  <p className="text-[8.5px] font-bold tracking-wider text-[#6B7488]">ACTIVE REFERRALS</p>
                  <p className="font-mono text-sm font-bold" style={{ color: YELLOW }}>{user.friendsInvited}</p>
                </div>
              </div>
            </div>
          </SectionCard>
        </>
      )}

      {tab === "payouts" && (
        <>
          <Button onClick={onPayout} className="h-11 w-full rounded-lg text-[12.5px] font-bold text-black hover:opacity-90" style={{ background: YELLOW }}>
            <WalletIcon className="mr-1.5 h-4 w-4" /> Request Payout (min $20)
          </Button>
          <SectionCard className="overflow-hidden">
            {payouts.length === 0 && <p className="px-3.5 py-6 text-center text-[10.5px] text-[#4A5265]">No payouts yet — commissions yahan aayengi</p>}
            {payouts.map(t => <TxnRow key={t.id} t={t} />)}
          </SectionCard>
        </>
      )}

      {tab === "history" && (
        <SectionCard className="overflow-hidden">
          {txns.length === 0 && <p className="px-3.5 py-6 text-center text-[10.5px] text-[#4A5265]">No transactions yet</p>}
          {txns.map(t => <TxnRow key={t.id} t={t} />)}
        </SectionCard>
      )}
    </div>
  );
}

/* ───────────────────────────── PROFILE ───────────────────────────── */

interface ProfileProps {
  user: WxUser;
  keys: ApiKeyRow[];
  network: { cluster: string; host: string; region: string; client: string; engine: string };
  onLogout: () => void;
  onToast: (msg: string) => void;
  onAddKey: (data: { exchange: string; apiKey: string; apiSecret: string; label: string }) => Promise<boolean>;
  onDeleteKey: (id: string) => void;
}

export function ProfileTab({ user, keys, network, onLogout, onToast, onAddKey, onDeleteKey }: ProfileProps) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [exchange, setExchange] = useState("BINANCE");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [label, setLabel] = useState("Main Account");
  const [saving, setSaving] = useState(false);
  const [confirmLogout, setConfirmLogout] = useState(false);

  async function saveKey() {
    setSaving(true);
    const ok = await onAddKey({ exchange, apiKey, apiSecret, label });
    setSaving(false);
    if (ok) { setDialogOpen(false); setApiKey(""); setApiSecret(""); }
  }

  return (
    <div className="space-y-3 px-4 pb-6 pt-3">
      {/* Identity */}
      <div className="flex items-center gap-3.5 pt-1">
        <div className="flex h-14 w-14 items-center justify-center rounded-full text-xl font-black text-black" style={{ background: YELLOW }}>
          {user.name.slice(0, 1).toUpperCase()}
        </div>
        <div>
          <p className="text-lg font-extrabold text-white">{user.name}</p>
          <p className="text-[11px] text-[#6B7488]">{user.email}</p>
          <p className="mt-0.5 font-mono text-[9px] text-[#4A5265]">ID · {user.id.slice(0, 12)}…</p>
        </div>
      </div>

      {/* Subscription */}
      <SectionCard className="p-3.5">
        <p className="text-[9px] font-bold tracking-[0.14em] text-[#6B7488]">SUBSCRIPTION</p>
        <div className="mt-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="rounded-md px-2.5 py-1 text-[10px] font-black tracking-wider text-black" style={{ background: YELLOW }}>{user.plan}</span>
            <span className="text-[11px] text-[#B7BECF]">valid until {fmtDate(user.planValidUntil)}</span>
          </div>
          <ChevronRight className="h-4 w-4 text-[#4A5265]" />
        </div>
        <p className="mt-1.5 text-[9.5px] text-[#6B7488]">Every update included · all 3 exchanges · 24/7 autopilot · 1:1 risk lock</p>
      </SectionCard>

      {/* Network — auto server assignment */}
      <SectionCard className="p-3.5">
        <p className="text-[9px] font-bold tracking-[0.14em] text-[#6B7488]">NETWORK</p>
        <div className="mt-2 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg" style={{ background: `${GREEN}14` }}>
              <Cloud className="h-4 w-4" style={{ color: GREEN }} />
            </span>
            <div>
              <p className="text-[12px] font-bold text-white">{network.cluster}</p>
              <p className="font-mono text-[9.5px] text-[#8A93A6]">{network.host}</p>
            </div>
          </div>
          <span className="flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[8.5px] font-bold tracking-wider" style={{ background: `${GREEN}14`, color: GREEN }}>
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: GREEN, boxShadow: `0 0 6px ${GREEN}` }} /> CONNECTED
          </span>
        </div>
        <div className="mt-2.5 space-y-1.5 border-t border-white/[0.05] pt-2.5">
          {[
            ["Server assignment", network.region],
            ["Client", network.client],
            ["Engine", network.engine],
          ].map(([k, v]) => (
            <div key={k} className="flex items-center justify-between">
              <span className="text-[10px] text-[#6B7488]">{k}</span>
              <span className="text-[10px] font-semibold text-[#B7BECF]">{v}</span>
            </div>
          ))}
        </div>
        <p className="mt-2 rounded-lg px-2.5 py-1.5 text-[9px] leading-relaxed" style={{ background: `${YELLOW}0D`, color: "#C9B458" }}>
          Server login par auto-assign hota hai — koi URL enter karne ki zaroorat nahi. Trades, balance, history aur keys sab aapki ID se cloud par save hain.
        </p>
      </SectionCard>

      {/* API keys */}
      <SectionCard className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/[0.06] px-3.5 py-2.5">
          <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-wide text-white">
            <KeyRound className="h-3.5 w-3.5" style={{ color: YELLOW }} /> EXCHANGE &amp; KEYS
          </p>
          <button onClick={() => setDialogOpen(true)} className="text-[10px] font-bold" style={{ color: YELLOW }}>+ ADD KEY</button>
        </div>
        {keys.length === 0 && (
          <p className="px-3.5 py-4 text-[10.5px] leading-relaxed text-[#6B7488]">
            Koi key linked nahi — Binance API key add karein to engine live exchange par trade karega. Tab tak paper trading chalega.
          </p>
        )}
        {keys.map(k => (
          <div key={k.id} className="flex items-center justify-between border-b border-white/[0.04] px-3.5 py-2.5 last:border-0">
            <div className="flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg font-black text-[9px] text-black" style={{ background: "#F0B90B" }}>
                {k.exchange.slice(0, 2)}
              </span>
              <div>
                <p className="text-[11.5px] font-bold text-white">{k.exchange} <span className="font-medium text-[#6B7488]">· {k.label}</span></p>
                <p className="font-mono text-[9.5px] text-[#8A93A6]">{k.keyMasked} / {k.secretMasked}</p>
              </div>
            </div>
            <button onClick={() => onDeleteKey(k.id)} aria-label={`Delete ${k.exchange} key`} className="text-[#6B7488] hover:text-[#FF4D5E]">
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </SectionCard>

      {/* Settings rows */}
      <SectionCard className="overflow-hidden">
        {[
          { icon: Bell, label: "Trade & signal alerts", sub: "Telegram + WhatsApp + push", toast: "Alert settings (demo)" },
          { icon: Globe, label: "Language", sub: "English", toast: "Language picker (demo)" },
        ].map(({ icon: Icon, label, sub, toast }) => (
          <button key={label} onClick={() => onToast(toast)}
            className="flex w-full items-center justify-between border-b border-white/[0.04] px-3.5 py-3 text-left last:border-0 hover:bg-white/[0.02]">
            <div className="flex items-center gap-2.5">
              <Icon className="h-4 w-4 text-[#8A93A6]" />
              <div>
                <p className="text-[11.5px] font-bold text-white">{label}</p>
                <p className="text-[9px] text-[#6B7488]">{sub}</p>
              </div>
            </div>
            <ChevronRight className="h-4 w-4 text-[#4A5265]" />
          </button>
        ))}
      </SectionCard>

      {/* Logout */}
      <Button variant="outline" onClick={() => setConfirmLogout(true)}
        className="h-11 w-full rounded-xl border-[1.5px] text-[12.5px] font-bold tracking-wide hover:bg-[#FF4D5E]/10"
        style={{ borderColor: `${RED}88`, color: RED }}>
        <LogOut className="mr-1.5 h-4 w-4" /> LOG OUT
      </Button>

      <p className="pb-1 text-center text-[9px] text-[#3E4658]">Weexionic App v3.0.0 · Native Engine Client</p>

      {/* Add key dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-[330px] rounded-2xl border-white/[0.1] bg-[#0C1017] p-4">
          <DialogHeader className="space-y-1">
            <DialogTitle className="text-[14px] font-bold text-white">Add Exchange API Key</DialogTitle>
            <p className="text-[10px] leading-relaxed text-[#6B7488]">Keys masked ho kar store hoti hain. Withdrawal permission kabhi mat dein.</p>
          </DialogHeader>
          <div className="mt-2 space-y-3">
            <div>
              <label className="mb-1 block text-[9px] font-bold tracking-wider text-[#6B7488]">EXCHANGE</label>
              <div className="flex gap-1.5">
                {["BINANCE", "BYBIT", "OKX"].map(x => (
                  <button key={x} onClick={() => setExchange(x)}
                    className="flex-1 rounded-md border px-1 py-1.5 text-[9.5px] font-bold"
                    style={x === exchange ? { borderColor: YELLOW, color: YELLOW, background: `${YELLOW}12` } : { borderColor: "rgba(255,255,255,0.08)", color: "#6B7488" }}>
                    {x}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="mb-1 block text-[9px] font-bold tracking-wider text-[#6B7488]">LABEL</label>
              <Input value={label} onChange={e => setLabel(e.target.value)} className="h-9 rounded-lg border-white/[0.08] bg-[#0A0E15] text-[12px] text-white" />
            </div>
            <div>
              <label className="mb-1 block text-[9px] font-bold tracking-wider text-[#6B7488]">API KEY</label>
              <Input value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="Bn7xKq…" className="h-9 rounded-lg border-white/[0.08] bg-[#0A0E15] font-mono text-[12px] text-white" />
            </div>
            <div>
              <label className="mb-1 block text-[9px] font-bold tracking-wider text-[#6B7488]">API SECRET</label>
              <Input value={apiSecret} onChange={e => setApiSecret(e.target.value)} type="password" placeholder="••••••••••" className="h-9 rounded-lg border-white/[0.08] bg-[#0A0E15] font-mono text-[12px] text-white" />
            </div>
            <Button disabled={saving || apiKey.length < 8 || apiSecret.length < 8} onClick={saveKey}
              className="h-10 w-full rounded-lg text-[12px] font-bold text-black hover:opacity-90 disabled:opacity-40" style={{ background: YELLOW }}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <><Check className="mr-1 h-3.5 w-3.5" /> Save &amp; Link Exchange</>}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Logout confirm */}
      <Dialog open={confirmLogout} onOpenChange={setConfirmLogout}>
        <DialogContent className="max-w-[300px] rounded-2xl border-white/[0.1] bg-[#0C1017] p-4">
          <DialogHeader>
            <DialogTitle className="text-[14px] font-bold text-white">Log out of Weexionic?</DialogTitle>
            <p className="text-[10.5px] leading-relaxed text-[#6B7488]">Aapka data, positions aur keys sab cloud par ID ke saath safe rahenge. Dobara login par sab restore ho jayega.</p>
          </DialogHeader>
          <div className="mt-3 grid grid-cols-2 gap-2.5">
            <Button variant="outline" className="h-10 rounded-lg border-white/[0.12] text-[12px] text-[#C7CEDE]" onClick={() => setConfirmLogout(false)}>Cancel</Button>
            <Button className="h-10 rounded-lg text-[12px] font-bold text-white" style={{ background: RED }} onClick={onLogout}>Log Out</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

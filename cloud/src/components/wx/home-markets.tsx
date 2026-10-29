"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Search, ArrowUpRight, ArrowDownRight, Play, Square, Zap, ListOrdered, History, BellRing } from "lucide-react";
import { Sparkline } from "./chart";
import { fmtUsd, fmtPct, fmtPrice, fmtTime, fmtDate, YELLOW, GREEN, RED } from "./types";
import type { EngineSnapshot, MarketData, WxUser, LogEntry } from "./types";

export function SectionCard({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-white/[0.07] bg-[#0C1017] ${className}`}>{children}</div>;
}

export function RunningPill({ running }: { running: boolean }) {
  return (
    <span className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[9.5px] font-bold tracking-wider"
      style={running
        ? { borderColor: `${GREEN}55`, background: `${GREEN}14`, color: GREEN }
        : { borderColor: "rgba(138,147,166,0.3)", background: "rgba(138,147,166,0.08)", color: "#8A93A6" }}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: running ? GREEN : "#8A93A6", boxShadow: running ? `0 0 6px ${GREEN}` : "none" }} />
      {running ? "RUNNING" : "STOPPED"}
    </span>
  );
}

/* ───────────────────────────── HOME ───────────────────────────── */

interface HomeProps {
  user: WxUser; engine: EngineSnapshot;
  keysCount: number;
  onStart: () => void; onStop: () => void;
  goto: (tab: string) => void;
  onReset: () => void;
}

export function HomeTab({ user, engine, keysCount, onStart, onStop, goto, onReset }: HomeProps) {
  const equity = engine.equity;
  const pnlToday = engine.stats.pnlToday + engine.unrealized;

  return (
    <div className="space-y-3.5 px-4 pb-6 pt-3">
      <div>
        <p className="text-[11px] text-[#6B7488]">Welcome back, {user.name.split(" ")[0]}</p>
        <h1 className="text-[22px] font-extrabold text-white">Overview</h1>
      </div>

      {/* Equity hero card */}
      <div className="relative overflow-hidden rounded-2xl border p-4"
        style={{ borderColor: "rgba(245,197,24,0.22)", background: "linear-gradient(135deg, rgba(245,197,24,0.09) 0%, rgba(12,16,23,0.9) 45%, rgba(12,16,23,0.95) 100%)" }}>
        <div className="absolute -right-8 -top-10 h-36 w-36 rounded-full opacity-25"
          style={{ background: "radial-gradient(circle, rgba(245,197,24,0.5) 0%, transparent 70%)" }} />
        <div className="flex items-center justify-between">
          <span className="text-[9.5px] font-bold tracking-[0.14em]" style={{ color: YELLOW }}>TOTAL EQUITY · USDT</span>
          <span className="rounded-md border border-white/[0.08] bg-black/30 px-1.5 py-0.5 font-mono text-[8.5px] text-[#8A93A6]">PAPER · DEMO</span>
        </div>
        <div className="mt-1.5 flex items-end gap-2.5">
          <span className="font-mono text-[32px] font-bold leading-none text-white">${fmtUsd(equity)}</span>
          <span className={`mb-1 flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[10.5px] font-bold ${pnlToday >= 0 ? "" : ""}`}
            style={{ background: pnlToday >= 0 ? `${GREEN}1A` : `${RED}1A`, color: pnlToday >= 0 ? GREEN : RED }}>
            {pnlToday >= 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
            {pnlToday >= 0 ? "+" : "-"}${fmtUsd(Math.abs(pnlToday))} today
          </span>
        </div>
        <p className="mt-1 text-[10px] text-[#6B7488]">Unrealized ${fmtUsd(engine.unrealized)} · Balance ${fmtUsd(engine.balance)}</p>
      </div>

      {/* Exchange connection status */}
      {keysCount === 0 ? (
        <div className="flex items-start gap-2.5 rounded-xl border px-3.5 py-3" style={{ borderColor: `${RED}44`, background: `${RED}0E` }}>
          <span className="mt-0.5 text-sm font-black" style={{ color: RED }}>!</span>
          <p className="text-[11.5px] leading-relaxed" style={{ color: "#FFB4BB" }}>
            Exchange se connect nahi ho raha — <button className="font-bold underline underline-offset-2" onClick={() => goto("profile")}>Profile → API Keys</button> mein key add karein. Paper trading abhi demo balance par chalega.
          </p>
        </div>
      ) : (
        <div className="flex items-start gap-2.5 rounded-xl border px-3.5 py-3" style={{ borderColor: `${GREEN}44`, background: `${GREEN}0E` }}>
          <span className="mt-0.5 text-sm font-black" style={{ color: GREEN }}>✓</span>
          <p className="text-[11.5px] leading-relaxed" style={{ color: "#9FE8C8" }}>
            {keysCount === 1 ? "1 exchange key" : `${keysCount} exchange keys`} linked — engine orders will route to your exchange (demo routes paper).
          </p>
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-2.5">
        <SectionCard className="p-3.5">
          <p className="text-[9px] font-bold tracking-[0.12em] text-[#6B7488]">WIN RATE</p>
          <p className="mt-1 font-mono text-lg font-bold" style={{ color: engine.stats.winRate >= 50 ? GREEN : "#EDEFF5" }}>
            {engine.stats.winRate.toFixed(0)}%
          </p>
          <p className="mt-0.5 text-[9.5px] text-[#6B7488]">{engine.stats.wins}W · {engine.stats.losses}L of {engine.stats.totalTrades}</p>
        </SectionCard>
        <SectionCard className="p-3.5">
          <p className="text-[9px] font-bold tracking-[0.12em] text-[#6B7488]">TOTAL P&L</p>
          <p className="mt-1 font-mono text-lg font-bold" style={{ color: engine.stats.totalPnl >= 0 ? GREEN : RED }}>
            {engine.stats.totalPnl >= 0 ? "+" : "-"}${fmtUsd(Math.abs(engine.stats.totalPnl))}
          </p>
          <p className="mt-0.5 text-[9.5px] text-[#6B7488]">Today {pnlToday >= 0 ? "+" : "-"}${fmtUsd(Math.abs(pnlToday))}</p>
        </SectionCard>
        <SectionCard className="p-3.5">
          <p className="text-[9px] font-bold tracking-[0.12em] text-[#6B7488]">ACTIVE COINS</p>
          <p className="mt-1 font-mono text-lg font-bold text-white">{engine.symbols.length}</p>
          <p className="mt-0.5 text-[9.5px] text-[#6B7488]">{engine.positions.length} open position{engine.positions.length === 1 ? "" : "s"}</p>
        </SectionCard>
        <SectionCard className="p-3.5">
          <p className="text-[9px] font-bold tracking-[0.12em] text-[#6B7488]">LEVERAGE / TF</p>
          <p className="mt-1 font-mono text-lg font-bold" style={{ color: YELLOW }}>{engine.leverage}x <span className="text-sm text-white">{engine.timeframe}</span></p>
          <p className="mt-0.5 text-[9.5px] text-[#6B7488]">Size ${fmtUsd(engine.tradeSize, 0)} per trade</p>
        </SectionCard>
      </div>

      {/* Quick actions */}
      <div className="grid grid-cols-4 gap-2.5">
        {[
          { icon: Zap, label: "Terminal", tab: "bot" },
          { icon: ListOrdered, label: "Positions", tab: "bot" },
          { icon: History, label: "History", tab: "bot" },
          { icon: BellRing, label: "Alerts", tab: "wallet" },
        ].map(({ icon: Icon, label, tab }) => (
          <button key={label} onClick={() => goto(tab)}
            className="flex flex-col items-center gap-1.5 rounded-xl border border-white/[0.07] bg-[#0C1017] py-3 transition-colors hover:border-white/[0.14]">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg" style={{ background: `${YELLOW}16` }}>
              <Icon className="h-4 w-4" style={{ color: YELLOW }} />
            </span>
            <span className="text-[9.5px] font-semibold text-[#B7BECF]">{label}</span>
          </button>
        ))}
      </div>

      {/* Active bots */}
      <SectionCard className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/[0.06] px-3.5 py-2.5">
          <p className="text-[11px] font-bold tracking-wide text-white">ACTIVE BOTS</p>
          <span className="text-[9px] font-semibold tracking-wider" style={{ color: YELLOW }}>MANAGE ›</span>
        </div>
        {engine.symbols.map(sym => {
          const pos = engine.positions.find(p => p.symbol === sym);
          return (
            <div key={sym} className="flex items-center justify-between border-b border-white/[0.04] px-3.5 py-2.5 last:border-0">
              <div className="flex items-center gap-2.5">
                <span className="flex h-8 w-8 items-center justify-center rounded-full font-black text-[11px] text-black"
                  style={{ background: sym.startsWith("BTC") ? "#F7931A" : sym.startsWith("ETH") ? "#A8A29E" : "#9945FF" }}>
                  {sym.slice(0, 1)}
                </span>
                <div>
                  <p className="text-[12px] font-bold text-white">{sym}</p>
                  <p className="text-[9.5px] text-[#6B7488]">
                    {pos ? `${pos.side} @ $${fmtPrice(pos.entry)} · ${pos.pnl >= 0 ? "+" : "-"}$${fmtUsd(Math.abs(pos.pnl))}` : "flat — awaiting fresh cross"}
                  </p>
                </div>
              </div>
              <span className="rounded-full px-2 py-0.5 text-[8.5px] font-bold tracking-wider"
                style={pos
                  ? { background: `${GREEN}18`, color: GREEN }
                  : { background: "rgba(138,147,166,0.12)", color: "#8A93A6" }}>
                {pos ? "RUNNING" : engine.running ? "SCANNING" : "IDLE"}
              </span>
            </div>
          );
        })}
        <button onClick={() => goto("bot")} className="w-full py-2 text-[10px] font-semibold text-[#6B7488] hover:text-white">
          open full terminal ›
        </button>
      </SectionCard>

      {/* Engine control — like their current app */}
      <SectionCard className="p-4" >
        <div className="flex items-center justify-between">
          <p className="text-[12px] font-extrabold tracking-[0.08em] text-white">QUAD-TREND ENGINE</p>
          <RunningPill running={engine.running} />
        </div>
        <p className="mt-1.5 text-[10.5px] text-[#8A93A6]">
          BINANCE <span style={{ color: YELLOW }}>·</span> EMA 8/13/21/55 <span style={{ color: YELLOW }}>·</span> strict 1:1 RR
        </p>
        <div className="mt-3 grid grid-cols-2 gap-2.5">
          <Button onClick={onStart} disabled={engine.running}
            className="h-10 rounded-lg text-[12px] font-bold text-black hover:opacity-90 disabled:opacity-35"
            style={{ background: YELLOW }}>
            <Play className="mr-1 h-3.5 w-3.5" /> START BOT
          </Button>
          <Button onClick={onStop} disabled={!engine.running} variant="outline"
            className="h-10 rounded-lg border-[1.5px] text-[12px] font-bold hover:bg-[#FF4D5E]/10"
            style={{ borderColor: RED, color: RED }}>
            <Square className="mr-1 h-3.5 w-3.5" /> STOP BOT
          </Button>
        </div>
        <button onClick={onReset} className="mt-2.5 w-full text-center text-[9.5px] text-[#4A5265] hover:text-[#8A93A6]">
          reset demo account to $10,000
        </button>
      </SectionCard>

      {/* Live activity */}
      <SectionCard className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/[0.06] px-3.5 py-2.5">
          <p className="text-[11px] font-bold tracking-wide text-white">LIVE ACTIVITY</p>
          <span className="flex items-center gap-1 text-[9px] font-semibold text-[#6B7488]">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ background: YELLOW }} /> LIVE
          </span>
        </div>
        <div className="max-h-40 overflow-y-auto">
          {engine.logs.length === 0 && <p className="px-3.5 py-4 text-center text-[10.5px] text-[#4A5265]">Engine start karein — activity yahan live aayegi</p>}
          {engine.logs.slice(0, 12).map((l: LogEntry, i: number) => (
            <div key={`${l.t}-${i}`} className="flex items-start gap-2 border-b border-white/[0.03] px-3.5 py-2 last:border-0">
              <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ background: l.level === "success" ? GREEN : l.level === "warn" ? "#FF8A3D" : l.level === "error" ? RED : "#8A93A6" }} />
              <p className="flex-1 text-[10px] leading-relaxed text-[#B7BECF]">{l.msg}</p>
              <span className="shrink-0 font-mono text-[8.5px] text-[#4A5265]">{fmtTime(l.t)}</span>
            </div>
          ))}
        </div>
      </SectionCard>

      {/* Subscription strip */}
      <SectionCard className="flex items-center justify-between p-3.5">
        <div className="flex items-center gap-2.5">
          <span className="rounded-md px-2 py-0.5 text-[9px] font-black tracking-wider text-black" style={{ background: YELLOW }}>{user.plan}</span>
          <span className="text-[10px] text-[#8A93A6]">valid until {fmtDate(user.planValidUntil)}</span>
        </div>
        <button className="text-[10px] font-semibold" style={{ color: YELLOW }} onClick={() => goto("profile")}>Manage ›</button>
      </SectionCard>
    </div>
  );
}

/* ───────────────────────────── MARKETS ───────────────────────────── */

export function MarketsTab({ market, onSelect }: { market: MarketData; onSelect: (sym: string) => void }) {
  const [q, setQ] = useState("");
  const syms = Object.keys(market).filter(s => s.toLowerCase().includes(q.toLowerCase()));

  return (
    <div className="px-4 pb-6 pt-3">
      <h1 className="text-[22px] font-extrabold text-white">Markets</h1>
      <p className="mt-0.5 text-[10.5px] text-[#6B7488]">Live perp prices · tap to trade on terminal</p>

      <div className="relative mt-3">
        <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#4A5265]" />
        <Input value={q} onChange={e => setQ(e.target.value)} placeholder="Search pairs…" aria-label="Search markets"
          className="h-10 rounded-lg border-white/[0.08] bg-[#0A0E15] pl-9 text-sm text-white placeholder:text-[#4A5265] focus-visible:ring-[#F5C518]/40" />
      </div>

      <div className="mt-3 space-y-2">
        {syms.map(sym => {
          const m = market[sym];
          const up = m.change24h >= 0;
          return (
            <button key={sym} onClick={() => onSelect(sym)}
              className="flex w-full items-center justify-between rounded-xl border border-white/[0.06] bg-[#0C1017] px-3.5 py-3 text-left transition-colors hover:border-white/[0.14]">
              <div className="flex items-center gap-2.5">
                <span className="flex h-9 w-9 items-center justify-center rounded-full text-[10px] font-black text-black" style={{ background: m.color }}>
                  {sym.slice(0, 1)}
                </span>
                <div>
                  <p className="text-[12.5px] font-bold text-white">{sym.replace("USDT", "")}<span className="text-[9px] font-medium text-[#6B7488]">/USDT</span></p>
                  <p className="text-[9.5px] text-[#6B7488]">{m.name}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Sparkline values={m.spark} up={up} />
                <div className="text-right">
                  <p className="font-mono text-[12.5px] font-bold text-white">${fmtPrice(m.price)}</p>
                  <span className="rounded px-1.5 py-0.5 font-mono text-[9.5px] font-bold"
                    style={{ background: up ? `${GREEN}1A` : `${RED}1A`, color: up ? GREEN : RED }}>
                    {fmtPct(m.change24h)}
                  </span>
                </div>
              </div>
            </button>
          );
        })}
        {syms.length === 0 && (
          <p className="py-10 text-center text-[11px] text-[#4A5265]">No pairs match &quot;{q}&quot;</p>
        )}
      </div>
    </div>
  );
}

export function MiniStat({ label, value, color = "#EDEFF5", sub }: { label: string; value: string; color?: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-2.5 py-2 text-center">
      <p className="text-[8.5px] font-bold tracking-wider text-[#6B7488]">{label}</p>
      <p className="mt-0.5 font-mono text-[13px] font-bold" style={{ color }}>{value}</p>
      {sub && <p className="text-[8.5px] text-[#4A5265]">{sub}</p>}
    </div>
  );
}

export const TrendIcon = ({ up, className }: { up: boolean; className?: string }) =>
  up ? <ArrowUpRight className={className} style={{ color: GREEN }} /> : <ArrowDownRight className={className} style={{ color: RED }} />;


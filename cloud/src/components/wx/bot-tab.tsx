"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { X, Lock, Layers } from "lucide-react";
import { WxChart, EmaLegend } from "./chart";
import { SectionCard, RunningPill, MiniStat } from "./home-markets";
import { fmtUsd, fmtPrice, fmtPct, fmtTime, fmtDate, YELLOW, GREEN, RED } from "./types";
import type { EngineSnapshot, MarketData, ClosedTrade } from "./types";

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"];
const SIZE_PRESETS = [100, 180, 250, 500];

interface BotProps {
  engine: EngineSnapshot;
  market: MarketData;
  symbol: string;
  setSymbol: (s: string) => void;
  busy: string | null;
  onConfig: (cfg: { leverage?: number; timeframe?: string; tradeSize?: number; stopLossPct?: number }) => void;
  onClose: (id: string) => void;
  onCloseAll: () => void;
}

export function BotTab({ engine, market, symbol, setSymbol, onConfig, onClose, onCloseAll }: BotProps) {
  const m = market[symbol];
  const [tf, setTf] = useState(engine.timeframe);
  const [size, setSize] = useState(String(engine.tradeSize));
  const [lev, setLev] = useState(engine.leverage);
  const up = m ? m.change24h >= 0 : true;

  const tpPct = engine.stopLossPct ?? 2;   // live engine SL% — strict 1:1 (ROE-capped by leverage)
  const notional = (parseFloat(size) || 0) * lev;

  return (
    <div className="space-y-3 px-4 pb-6 pt-3">
      {/* Pair selector */}
      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none]">
        {Object.keys(market).map(sym => (
          <button key={sym} onClick={() => setSymbol(sym)}
            className="shrink-0 rounded-full border px-3 py-1.5 text-[11px] font-bold transition-colors"
            style={sym === symbol
              ? { borderColor: YELLOW, background: `${YELLOW}1A`, color: YELLOW }
              : { borderColor: "rgba(255,255,255,0.08)", background: "#0C1017", color: "#8A93A6" }}>
            {sym.replace("USDT", "")}
          </button>
        ))}
      </div>

      {/* Price header */}
      {m && (
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-extrabold text-white">{symbol.replace("USDT", "")}<span className="text-[11px] font-medium text-[#6B7488]">/USDT</span></h1>
              <span className="rounded border border-white/[0.08] px-1.5 py-0.5 text-[8px] font-bold tracking-wider text-[#8A93A6]">BINANCE · PERP</span>
            </div>
            <div className="mt-0.5 flex items-center gap-2">
              <span className="font-mono text-[19px] font-bold text-white">${fmtPrice(m.price)}</span>
              <span className="rounded px-1.5 py-0.5 font-mono text-[10px] font-bold" style={{ background: up ? `${GREEN}1A` : `${RED}1A`, color: up ? GREEN : RED }}>
                {fmtPct(m.change24h)}
              </span>
            </div>
          </div>
          <RunningPill running={engine.running} />
        </div>
      )}

      {/* Chart card */}
      <SectionCard className="overflow-hidden p-2.5">
        <div className="mb-1.5 flex gap-1.5">
          {TIMEFRAMES.map(t => (
            <button key={t} onClick={() => { setTf(t); onConfig({ timeframe: t }); }}
              className="rounded-md px-2.5 py-1 text-[10px] font-bold transition-colors"
              style={t === tf ? { background: `${YELLOW}1A`, color: YELLOW } : { color: "#6B7488" }}>
              {t}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-1 text-[9px] font-semibold text-[#6B7488]">
            <Layers className="h-3 w-3" /> {m ? m.candles.length : 0} candles
          </div>
        </div>
        {m ? <WxChart candles={m.candles} height={200} /> : <div className="flex h-[200px] items-center justify-center text-[11px] text-[#4A5265]">Bot start karein — chart yahan live aayega</div>}
        <div className="mt-1.5"><EmaLegend /></div>
      </SectionCard>

      {/* Order panel */}
      <SectionCard className="p-3.5">
        <div className="flex items-center justify-between">
          <p className="text-[11px] font-bold tracking-wide text-white">ORDER SETTINGS</p>
          <span className="flex items-center gap-1 rounded-md px-2 py-1 text-[8.5px] font-black tracking-wider" style={{ background: `${YELLOW}16`, color: YELLOW }}>
            <Lock className="h-2.5 w-2.5" /> 1:1 RISK LOCK
          </span>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2.5">
          <div>
            <label className="mb-1 block text-[8.5px] font-bold tracking-wider text-[#6B7488]">SIZE (USDT)</label>
            <Input value={size} onChange={e => setSize(e.target.value.replace(/[^0-9.]/g, ""))} onBlur={() => onConfig({ tradeSize: parseFloat(size) || 180 })}
              inputMode="decimal" aria-label="Trade size in USDT"
              className="h-9 rounded-lg border-white/[0.08] bg-[#0A0E15] font-mono text-[13px] text-white focus-visible:ring-[#F5C518]/40" />
          </div>
          <div>
            <label className="mb-1 block text-[8.5px] font-bold tracking-wider text-[#6B7488]">LEVERAGE</label>
            <div className="flex h-9 items-center rounded-lg border border-white/[0.08] bg-[#0A0E15]">
              <button className="h-full w-8 text-[#8A93A6] hover:text-white" onClick={() => { const v = Math.max(5, lev - 5); setLev(v); onConfig({ leverage: v }); }} aria-label="Decrease leverage">−</button>
              <span className="flex-1 text-center font-mono text-[13px] font-bold" style={{ color: YELLOW }}>{lev}x</span>
              <button className="h-full w-8 text-[#8A93A6] hover:text-white" onClick={() => { const v = Math.min(125, lev + 5); setLev(v); onConfig({ leverage: v }); }} aria-label="Increase leverage">+</button>
            </div>
          </div>
        </div>

        <div className="mt-2 flex gap-1.5">
          {SIZE_PRESETS.map(v => (
            <button key={v} onClick={() => { setSize(String(v)); onConfig({ tradeSize: v }); }}
              className="flex-1 rounded-md border px-1 py-1 font-mono text-[9.5px] font-bold transition-colors"
              style={String(v) === size ? { borderColor: `${YELLOW}66`, color: YELLOW } : { borderColor: "rgba(255,255,255,0.07)", color: "#6B7488" }}>
              ${v}
            </button>
          ))}
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2.5">
          <MiniStat label="TAKE PROFIT" value={`+${tpPct}%`} color={GREEN} sub={`+$${fmtUsd((parseFloat(size) || 0) * lev * (tpPct / 100))} at ${lev}x`} />
          <MiniStat label="STOP LOSS" value={`-${tpPct}%`} color={RED} sub={`-$${fmtUsd((parseFloat(size) || 0) * lev * (tpPct / 100))} at ${lev}x`} />
        </div>

        <div className="mt-2.5 flex items-center justify-between rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
          <div>
            <p className="text-[10.5px] font-bold text-white">Auto-Manage Brackets</p>
            <p className="text-[8.5px] text-[#6B7488]">strict mode — TP/SL always attached</p>
          </div>
          <Switch checked disabled aria-readonly className="data-[state=checked]:bg-[#F5C518]" />
        </div>

        <p className="mt-2 text-center font-mono text-[9px] text-[#4A5265]">notional ${fmtUsd(notional, 0)} · margin ${fmtUsd(parseFloat(size) || 0, 0)}</p>
      </SectionCard>

      {/* Signal info — the engine trades automatically on EMA 8/13/21/55 crosses */}
      <SectionCard className="p-3.5">
        <div className="flex items-center justify-between">
          <p className="text-[11px] font-bold tracking-wide text-white">AUTO-TRADE ENGINE</p>
          <span className="flex items-center gap-1 rounded-md px-2 py-1 text-[8.5px] font-black tracking-wider" style={{ background: `${YELLOW}16`, color: YELLOW }}>
            <Lock className="h-2.5 w-2.5" /> 1:1 RISK LOCK
          </span>
        </div>
        <p className="mt-1.5 text-[10px] leading-relaxed text-[#8A93A6]">
          Bot khud scan karta hai — jahan fresh EMA 8/13/21/55 cross milega wahan entry khud lega, TP/SL ke saath. Koi manual trade ki zaroorat nahi.
        </p>
        {m?.indicators && (
          <div className="mt-2 flex items-center justify-between rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
            <span className="text-[10px] font-bold text-[#B7BECF]">{symbol.replace("USDT", "")} live signal</span>
            <span className="rounded px-1.5 py-0.5 font-mono text-[9.5px] font-black"
              style={{ background: m.indicators.signal === "BUY" ? `${GREEN}1A` : m.indicators.signal === "SELL" ? `${RED}1A` : "rgba(138,147,166,0.12)", color: m.indicators.signal === "BUY" ? GREEN : m.indicators.signal === "SELL" ? RED : "#8A93A6" }}>
              {m.indicators.signal}
            </span>
          </div>
        )}
      </SectionCard>

      {/* Open positions */}
      <SectionCard className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/[0.06] px-3.5 py-2.5">
          <p className="text-[11px] font-bold tracking-wide text-white">OPEN POSITIONS <span className="ml-1 font-mono" style={{ color: YELLOW }}>{engine.positions.length}</span></p>
          {engine.positions.length > 0 && (
            <button onClick={onCloseAll} className="text-[9.5px] font-bold" style={{ color: RED }}>CLOSE ALL</button>
          )}
        </div>
        {engine.positions.length === 0 && (
          <p className="px-3.5 py-5 text-center text-[10.5px] text-[#4A5265]">
            {engine.running ? "Scanning for fresh EMA crosses…" : "No open positions — engine band hai ya signal ka intezaar"}
          </p>
        )}
        {engine.positions.map(p => (
          <div key={p.id} className="border-b border-white/[0.04] px-3.5 py-2.5 last:border-0">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="rounded px-1.5 py-0.5 text-[8.5px] font-black tracking-wider" style={{ background: p.side === "LONG" ? `${GREEN}1A` : `${RED}1A`, color: p.side === "LONG" ? GREEN : RED }}>{p.side}</span>
                <span className="text-[11.5px] font-bold text-white">{p.symbol}</span>
                <span className="font-mono text-[9px] text-[#6B7488]">{p.leverage}x · ${fmtUsd(p.size, 0)}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[11.5px] font-bold" style={{ color: p.pnl >= 0 ? GREEN : RED }}>
                  {p.pnl >= 0 ? "+" : "-"}${fmtUsd(Math.abs(p.pnl))} <span className="text-[9px]">({fmtPct(p.pnlPct)})</span>
                </span>
                <button onClick={() => onClose(p.id)} aria-label={`Close ${p.symbol} position`} className="text-[#6B7488] hover:text-white"><X className="h-3.5 w-3.5" /></button>
              </div>
            </div>
            <div className="mt-1 flex items-center gap-3 font-mono text-[8.5px] text-[#6B7488]">
              <span>entry ${fmtPrice(p.entry)}</span>
              <span style={{ color: GREEN }}>TP ${fmtPrice(p.tpPrice)}</span>
              <span style={{ color: RED }}>SL ${fmtPrice(p.slPrice)}</span>
              <span className="ml-auto">{fmtTime(p.openedAt)}</span>
            </div>
          </div>
        ))}
      </SectionCard>

      {/* Trade history */}
      <SectionCard className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/[0.06] px-3.5 py-2.5">
          <p className="text-[11px] font-bold tracking-wide text-white">TRADE HISTORY</p>
          <span className="text-[9px] text-[#6B7488]">{engine.stats.totalTrades} closed</span>
        </div>
        {engine.history.length === 0 && <p className="px-3.5 py-5 text-center text-[10.5px] text-[#4A5265]">No closed trades yet</p>}
        {engine.history.slice(0, 8).map((t: ClosedTrade) => (
          <div key={t.id} className="flex items-center justify-between border-b border-white/[0.04] px-3.5 py-2 last:border-0">
            <div className="flex items-center gap-2">
              <span className="w-9 rounded px-1 py-0.5 text-center text-[8px] font-black" style={{ background: t.reason === "TP" ? `${GREEN}1A` : t.reason === "SL" ? `${RED}1A` : "rgba(138,147,166,0.12)", color: t.reason === "TP" ? GREEN : t.reason === "SL" ? RED : "#8A93A6" }}>{t.reason}</span>
              <div>
                <p className="text-[10.5px] font-bold text-white">{t.side} {t.symbol}</p>
                <p className="font-mono text-[8.5px] text-[#6B7488]">${fmtPrice(t.entry)} → ${fmtPrice(t.exit)} · {fmtDate(new Date(t.closedAt).toISOString())} {fmtTime(t.closedAt)}</p>
              </div>
            </div>
            <span className="font-mono text-[11px] font-bold" style={{ color: t.pnl >= 0 ? GREEN : RED }}>{t.pnl >= 0 ? "+" : "-"}${fmtUsd(Math.abs(t.pnl))}</span>
          </div>
        ))}
      </SectionCard>
    </div>
  );
}

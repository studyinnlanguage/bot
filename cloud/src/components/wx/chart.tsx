"use client";

import { useEffect, useRef } from "react";
import type { Candle } from "./types";

const EMA_COLORS: Record<number, string> = { 8: "#F5C518", 13: "#16C784", 21: "#FF8A3D", 55: "#FF4D5E" };

export function emaSeries(values: number[], period: number): number[] {
  if (!values.length) return [];
  const k = 2 / (period + 1);
  const out = [values[0]];
  for (let i = 1; i < values.length; i++) out.push(values[i] * k + out[i - 1] * (1 - k));
  return out;
}

interface Props { candles: Candle[]; height?: number; showEma?: boolean; }

export function WxChart({ candles, height = 216, showEma = true }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap || candles.length < 5) return;

    const draw = () => {
      const w = wrap.clientWidth;
      if (w < 40) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = w * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${height}px`;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, height);

      const padR = 52, padT = 8, padB = 8;
      const plotW = w - padR, plotH = height - padT - padB;
      const slot = plotW / 60;
      const visible = candles.slice(-60);
      const closes = visible.map(c => c.c);

      const emas = showEma
        ? { 8: emaSeries(closes, 8), 13: emaSeries(closes, 13), 21: emaSeries(closes, 21), 55: emaSeries(closes, 55) }
        : null;

      let lo = Math.min(...visible.map(c => c.l));
      let hi = Math.max(...visible.map(c => c.h));
      if (emas) for (const p of [8, 13, 21, 55]) {
        for (const v of emas[p as keyof typeof emas]) { if (v < lo) lo = v; if (v > hi) hi = v; }
      }
      const range = hi - lo || 1;
      lo -= range * 0.06; hi += range * 0.06;
      const y = (v: number) => padT + plotH - ((v - lo) / (hi - lo)) * plotH;

      // grid + price labels
      ctx.font = "9px 'Geist Mono', monospace";
      ctx.textAlign = "left";
      for (let i = 0; i <= 4; i++) {
        const v = lo + ((hi - lo) / 4) * i;
        const yy = y(v);
        ctx.strokeStyle = "rgba(255,255,255,0.045)";
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(plotW, yy); ctx.stroke();
        ctx.fillStyle = "rgba(138,147,166,0.85)";
        ctx.fillText(v >= 1000 ? v.toFixed(0) : v >= 1 ? v.toFixed(2) : v.toFixed(4), plotW + 6, yy + 3);
      }

      // candles
      visible.forEach((c, i) => {
        const cx = i * slot + slot / 2;
        const up = c.c >= c.o;
        ctx.strokeStyle = up ? "#16C784" : "#FF4D5E";
        ctx.fillStyle = up ? "rgba(22,199,132,0.9)" : "rgba(255,77,94,0.9)";
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(cx, y(c.h)); ctx.lineTo(cx, y(c.l)); ctx.stroke();
        const bw = Math.max(1.5, slot * 0.58);
        const yo = y(c.o), yc = y(c.c);
        const top = Math.min(yo, yc);
        ctx.fillRect(cx - bw / 2, top, bw, Math.max(1.2, Math.abs(yc - yo)));
      });

      // EMA lines
      if (emas) {
        for (const period of [8, 13, 21, 55]) {
          const series = emas[period as keyof typeof emas];
          ctx.strokeStyle = EMA_COLORS[period];
          ctx.lineWidth = 1.4;
          ctx.beginPath();
          series.forEach((v, i) => {
            const cx = i * slot + slot / 2;
            if (i === 0) ctx.moveTo(cx, y(v)); else ctx.lineTo(cx, y(v));
          });
          ctx.stroke();
        }
      }

      // last price line + tag
      const last = visible[visible.length - 1];
      const prev = visible[visible.length - 2] || last;
      const upTrend = last.c >= prev.c;
      const ly = y(last.c);
      ctx.setLineDash([4, 3]);
      ctx.strokeStyle = upTrend ? "rgba(22,199,132,0.7)" : "rgba(255,77,94,0.7)";
      ctx.beginPath(); ctx.moveTo(0, ly); ctx.lineTo(plotW, ly); ctx.stroke();
      ctx.setLineDash([]);
      const tag = last.c >= 1000 ? last.c.toFixed(1) : last.c >= 1 ? last.c.toFixed(3) : last.c.toFixed(5);
      ctx.fillStyle = upTrend ? "#16C784" : "#FF4D5E";
      const tagW = padR - 4;
      ctx.fillRect(plotW + 2, ly - 8, tagW, 16);
      ctx.fillStyle = "#05070B";
      ctx.font = "bold 9px 'Geist Mono', monospace";
      ctx.fillText(tag, plotW + 6, ly + 3);
    };

    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [candles, height, showEma]);

  return (
    <div ref={wrapRef} className="w-full" style={{ height }}>
      <canvas ref={canvasRef} aria-label="Live candlestick chart with EMA 8/13/21/55 overlays" />
    </div>
  );
}

export function Sparkline({ values, up }: { values: number[]; up: boolean }) {
  if (values.length < 3) return <div className="h-6 w-16" />;
  const lo = Math.min(...values), hi = Math.max(...values);
  const range = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 64},${22 - ((v - lo) / range) * 20}`).join(" ");
  return (
    <svg width="64" height="24" viewBox="0 0 64 24" className="shrink-0" aria-hidden="true">
      <polyline points={pts} fill="none" stroke={up ? "#16C784" : "#FF4D5E"} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

export function EmaLegend() {
  return (
    <div className="flex items-center justify-center gap-3 text-[9px] font-mono text-[#8A93A6]">
      {[8, 13, 21, 55].map(p => (
        <span key={p} className="flex items-center gap-1">
          <span className="h-[2px] w-3 rounded" style={{ background: EMA_COLORS[p] }} />
          EMA {p}
        </span>
      ))}
    </div>
  );
}

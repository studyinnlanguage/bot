// Candlestick chart with EMA 8/13/21/55 overlays — pure react-native-svg.
// Data comes from the engine's chart_data socket events (real candles only).
import React, { useMemo } from 'react';
import Svg, { Rect, Line, Polyline, Text as SvgText } from 'react-native-svg';
import { C } from '../theme/theme';

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}
export interface Emas {
  ema8?: { time: number; value: number }[];
  ema13?: { time: number; value: number }[];
  ema21?: { time: number; value: number }[];
  ema55?: { time: number; value: number }[];
}

const W = 350;
const H = 260;
const PAD_R = 8;
const PAD_T = 10;
const PAD_B = 18;

export function CandleChart({ candles, emas }: { candles: Candle[]; emas?: Emas }) {
  const view = useMemo(() => {
    const data = (candles || []).slice(-90);
    if (!data.length) return null;
    const values: number[] = [];
    data.forEach(d => {
      values.push(d.high, d.low);
    });
    Object.values(emas || {}).forEach(series => {
      ((series || []) as { time: number; value: number }[]).forEach((pt: { time: number; value: number }) =>
        values.push(pt.value),
      );
    });
    let hi = Math.max(...values);
    let lo = Math.min(...values);
    if (!isFinite(hi) || !isFinite(lo) || hi === lo) {
      hi = (hi || 1) * 1.01;
      lo = (lo || 0) * 0.99;
    }
    const range = hi - lo;
    const plotH = H - PAD_T - PAD_B;
    const plotW = W - PAD_R;
    const n = data.length;
    const step = plotW / n;
    const cw = Math.max(2, step * 0.62);
    const x = (i: number) => i * step + step / 2;
    const y = (v: number) => PAD_T + (1 - (v - lo) / range) * plotH;
    const candlesOut = data.map((d, i) => ({
      x: x(i), o: y(d.open), c: y(d.close), h: y(d.high), l: y(d.low),
      up: d.close >= d.open, w: cw,
    }));
    const lineFor = (series?: { time: number; value: number }[] | { x?: number }) =>
      series && (series as any).length > 1
        ? (series as { time: number; value: number }[])
            .slice(-90)
            .map((pt: { time: number; value: number }, i: number) => `${x(i)},${y(pt.value)}`)
            .join(' ')
        : null;
    return {
      candles: candlesOut,
      ema8: lineFor(emas?.ema8),
      ema13: lineFor(emas?.ema13),
      ema21: lineFor(emas?.ema21),
      ema55: lineFor(emas?.ema55),
      gridLines: [0.25, 0.5, 0.75].map(f => PAD_T + f * plotH),
      hiLabel: hi.toFixed(hi > 1000 ? 0 : 2),
      loLabel: lo.toFixed(lo > 1000 ? 0 : 2),
      y: (v: number) => y(v),
      hi, lo,
    };
  }, [candles, emas]);

  if (!view) {
    return (
      <Svg width="100%" height={H}>
        <SvgText x={W / 2} y={H / 2} fill={C.dim2} fontSize={12} textAnchor="middle">
          Waiting for market data…
        </SvgText>
      </Svg>
    );
  }

  const emaSeries: Array<[string | null, string]> = [
    [view.ema8, C.blue],
    [view.ema13, C.neon2],
    [view.ema21, C.purple],
    [view.ema55, C.loss],
  ];

  return (
    <Svg width="100%" height={H}>
      {view.gridLines.map((gy, i) => (
        <Line key={i} x1={0} x2={W - PAD_R} y1={gy} y2={gy} stroke="rgba(240, 185, 11,0.10)" strokeWidth={1} />
      ))}
      {view.candles.map((d, i) => (
        <React.Fragment key={i}>
          <Line x1={d.x} x2={d.x} y1={d.h} y2={d.l} stroke={d.up ? C.profit : C.loss} strokeWidth={1} />
          <Rect
            x={d.x - d.w / 2}
            y={Math.min(d.o, d.c)}
            width={d.w}
            height={Math.max(1, Math.abs(d.c - d.o))}
            fill={d.up ? C.profit : C.loss}
          />
        </React.Fragment>
      ))}
      {emaSeries.map(([pts, color], i) =>
        pts ? <Polyline key={`e${i}`} points={pts} stroke={color} strokeWidth={1.4} fill="none" opacity={0.9} /> : null,
      )}
      <SvgText x={4} y={PAD_T + 8} fill={C.dim} fontSize={9}>{view.hiLabel}</SvgText>
      <SvgText x={4} y={H - PAD_B} fill={C.dim} fontSize={9}>{view.loLabel}</SvgText>
    </Svg>
  );
}

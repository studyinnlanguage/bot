// WEEXIONIC Black & Yellow Design System (matching web terminal & dashboard).
// Deep Obsidian Black × Binance Gold/Yellow — green = profit/BUY, red = loss/SELL/danger.
export const C = {
  bg: '#0b0e11',
  bg2: '#12161f',
  bg3: '#181a20',
  card: '#12161f',
  cardBorder: 'rgba(240, 185, 11, 0.22)',
  neon: '#f0b90b',         // Brand Yellow / Gold
  neon2: '#fcd535',        // Bright Gold / Highlight
  neonGlow: 'rgba(240, 185, 11, 0.35)',
  cyan: '#37c6ff',
  gold: '#f0b90b',
  goldB: '#fcd535',
  goldD: '#b38600',
  txt: '#eaecef',
  dim: '#848e9c',
  dim2: '#5e6673',
  profit: '#2ecf8a',
  loss: '#f6465d',
  blue: '#5B8DEF',
  orange: '#ffb020',   // EMA13 amber
  warn: '#f0b90b',
  purple: '#A06BF0',
};

export const S = {
  screen: { flex: 1, backgroundColor: C.bg } as const,
  pad: { paddingHorizontal: 16 } as const,
  card: {
    backgroundColor: C.card,
    borderColor: C.cardBorder,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
  } as const,
  row: { flexDirection: 'row' as const, alignItems: 'center' },
  between: { flexDirection: 'row' as const, alignItems: 'center', justifyContent: 'space-between' as const },
  lbl: { fontSize: 10, letterSpacing: 1.6, color: C.dim, fontWeight: '700' as const },
  h1: { fontSize: 22, fontWeight: '800' as const, color: C.txt },
  h2: { fontSize: 16, fontWeight: '700' as const, color: C.txt },
  num: { fontSize: 20, fontWeight: '800' as const, color: C.txt } as const,
  goldText: { color: C.neon2, fontWeight: '800' as const },
  sep: { height: 1, backgroundColor: 'rgba(240, 185, 11, 0.16)', marginVertical: 10 } as const,
};

export const money = (v: number | null | undefined, sign = false) => {
  if (v == null || isNaN(v as any)) return '--';
  const s = v < 0 ? '-' : sign ? '+' : '';
  return `${s}$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export const pct = (v: number | null | undefined) =>
  v == null || isNaN(v as any) ? '--' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`;

export const price = (v: number | null | undefined) =>
  v == null || isNaN(v as any) ? '--' : `$${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;

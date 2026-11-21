// WEEXIONIC Obsidian & Yellow Design System (100% matched to Web Terminal Variant B).
// Deep Obsidian #0b0b0c × Neutral Cards #151517 × Binance Gold #f0b90b — green = profit, red = loss.
export const C = {
  bg: '#0b0b0c',
  bg2: '#151517',
  bg3: '#1b1b1e',
  card: '#151517',
  cardBorder: '#26262a',
  inputBg: '#1b1b1e',
  inputBorder: '#2a2a2e',
  neon: '#f0b90b',         // Brand Yellow / Gold
  neon2: '#f0b90b',        // Active Highlight
  neonGlow: 'rgba(240, 185, 11, 0.35)',
  cyan: '#37c6ff',
  gold: '#f0b90b',
  goldB: '#fcd535',
  goldD: '#7a7a80',
  txt: '#fafafa',
  dim: '#a3a3a3',
  dim2: '#6b6b6b',
  profit: '#2ecf8a',
  loss: '#f6465d',
  blue: '#5B8DEF',
  orange: '#ffb020',   // EMA13 amber
  warn: '#f0b90b',
  purple: '#A06BF0',
};

export const S = {
  screen: { flex: 1, backgroundColor: C.bg } as const,
  pad: { paddingHorizontal: 14 } as const,
  card: {
    backgroundColor: C.card,
    borderColor: C.cardBorder,
    borderWidth: 1,
    borderRadius: 12,
    padding: 15,
  } as const,
  row: { flexDirection: 'row' as const, alignItems: 'center' },
  between: { flexDirection: 'row' as const, alignItems: 'center', justifyContent: 'space-between' as const },
  lbl: { fontSize: 10.5, letterSpacing: 1.4, color: C.dim, fontWeight: '700' as const },
  h1: { fontSize: 21, fontWeight: '800' as const, color: C.txt },
  h2: { fontSize: 15.5, fontWeight: '700' as const, color: C.txt },
  num: { fontSize: 20, fontWeight: '800' as const, color: C.txt } as const,
  goldText: { color: C.neon, fontWeight: '800' as const },
  sep: { height: 1, backgroundColor: '#232326', marginVertical: 10 } as const,
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

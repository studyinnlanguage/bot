// WEEXIONIC MIDNIGHT Design System v4 (shared with web terminal).
// Deep navy × electric blue — green = profit/BUY, red = loss/SELL/danger only.
export const C = {
  bg: '#05070d',
  bg2: '#0d1220',
  bg3: '#111a2c',
  card: '#111a2c',
  cardBorder: 'rgba(61, 139, 255, 0.22)',
  neon: '#3d8bff',
  neon2: '#6ba6ff',
  neonGlow: 'rgba(61, 139, 255, 0.30)',
  cyan: '#37c6ff',
  // Backwards-compatible aliases mapped to MIDNIGHT (no gold/yellow, red = danger only):
  gold: '#3d8bff',
  goldB: '#6ba6ff',
  goldD: '#1a4fa8',
  txt: '#f2f5fa',
  dim: '#9aa7bd',
  dim2: '#5d6b82',
  profit: '#2ecf8a',
  loss: '#f6465d',
  blue: '#5B8DEF',
  orange: '#ffb020',   // EMA13 amber
  warn: '#ffb020',
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
  sep: { height: 1, backgroundColor: 'rgba(61, 139, 255, 0.14)', marginVertical: 10 } as const,
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

// WEEXIONIC REDLINE Design System v3 (shared with web terminal).
// Dark Black × Neon Red — silver = profit/BUY, red = loss/SELL.
export const C = {
  bg: '#060607',
  bg2: '#0b0b0d',
  bg3: '#101013',
  card: '#0e0e11',
  cardBorder: 'rgba(255, 45, 60, 0.22)',
  neon: '#ff3b46',
  neon2: '#ff2734',
  neonGlow: 'rgba(255, 59, 70, 0.30)',
  // Backwards-compatible aliases mapped strictly to REDLINE (No gold, yellow or green):
  gold: '#ff3b46',
  goldB: '#ff6b73',
  goldD: '#8f0f1a',
  txt: '#f2f2f4',
  dim: '#9a9aa5',
  dim2: '#5c5c66',
  profit: '#f5f5f7',
  loss: '#ff3b46',
  blue: '#00E5FF',
  orange: '#ff3b46', // Mapped to REDLINE (Strict No Orange rule)
  warn: '#ff8552',   // Mapped to REDLINE warning
  purple: '#B388FF',
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
  sep: { height: 1, backgroundColor: 'rgba(255, 45, 60, 0.14)', marginVertical: 10 } as const,
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

// WEEXIONIC Premium Neon-Green Design System (shared with web terminal).
export const C = {
  bg: '#0b0e11',
  bg2: '#12161f',
  bg3: '#141C17',
  card: '#12161f',
  cardBorder: 'rgba(240, 185, 11, 0.20)',
  neon: '#fcd535',
  neon2: '#f0b90b',
  neonGlow: 'rgba(240, 185, 11, 0.25)',
  // Backwards-compatible aliases mapped strictly to Neon Green (No gold, yellow or orange):
  gold: '#fcd535',
  goldB: '#ffd647',
  goldD: '#00B359',
  txt: '#eaecef',
  dim: '#848e9c',
  dim2: '#526056',
  profit: '#f0b90b',
  loss: '#FF5252',
  blue: '#00E5FF',
  orange: '#f0b90b', // Mapped to Neon Green (Strict No Orange rule)
  warn: '#fcd535',   // Mapped to Neon Green
  purple: '#B388FF',
};

export const S = {
  screen: { flex: 1, backgroundColor: C.bg } as const,
  pad: { paddingHorizontal: 16 } as const,
  card: {
    backgroundColor: C.card,
    borderColor: C.cardBorder,
    borderWidth: 1,
    borderRadius: 16,
    padding: 14,
  } as const,
  row: { flexDirection: 'row' as const, alignItems: 'center' },
  between: { flexDirection: 'row' as const, alignItems: 'center', justifyContent: 'space-between' as const },
  lbl: { fontSize: 10, letterSpacing: 1.6, color: C.dim, fontWeight: '700' as const },
  h1: { fontSize: 22, fontWeight: '800' as const, color: C.txt },
  h2: { fontSize: 16, fontWeight: '700' as const, color: C.txt },
  num: { fontSize: 20, fontWeight: '800' as const, color: C.txt } as const,
  goldText: { color: C.neon2, fontWeight: '800' as const },
  sep: { height: 1, backgroundColor: 'rgba(240, 185, 11, 0.12)', marginVertical: 10 } as const,
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

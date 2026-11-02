// WEEXIONIC Premium Neon-Green Design System (shared with web terminal).
export const C = {
  bg: '#080B0A',
  bg2: '#101613',
  bg3: '#141C17',
  card: '#101613',
  cardBorder: 'rgba(0, 230, 118, 0.22)',
  neon: '#39FF14',
  neon2: '#00E676',
  neonGlow: 'rgba(57, 255, 20, 0.25)',
  // Backwards-compatible aliases for gold tokens across existing components:
  gold: '#00E676',
  goldB: '#39FF14',
  goldD: '#00A854',
  txt: '#F2F7F3',
  dim: '#89958D',
  dim2: '#526056',
  profit: '#00E676',
  loss: '#FF5252',
  blue: '#00E5FF',
  orange: '#FFB74D',
  warn: '#FFB74D',
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
  sep: { height: 1, backgroundColor: 'rgba(0, 230, 118, 0.12)', marginVertical: 10 } as const,
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

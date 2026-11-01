// WEEXIONIC Luxury Gold-Dark design system (shared with the web dashboard).
export const C = {
  bg: '#0A0908',
  bg2: '#080706',
  card: 'rgba(255,255,255,0.034)',
  cardBorder: 'rgba(212,175,55,0.17)',
  gold: '#D4AF37',
  goldB: '#F0D98C',
  goldD: '#8C6D1F',
  txt: '#F5F0E1',
  dim: '#99917E',
  dim2: '#6A6455',
  profit: '#16C784',
  loss: '#EA3943',
  blue: '#5B8DEF',
  orange: '#F0A03C',
  purple: '#A06BF0',
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
  goldText: { color: C.gold, fontWeight: '800' as const },
  sep: { height: 1, backgroundColor: 'rgba(212,175,55,0.10)', marginVertical: 10 } as const,
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

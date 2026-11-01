// Ledger — trade history, filters, stats.
import React, { useCallback, useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Card, Chip, Empty, ErrorNote, GlassButton, Lbl, SectionTitle } from '../components/ui';
import { botApi } from '../api/endpoints';
import { C, money, price } from '../theme/theme';

export function LedgerScreen() {
  const [trades, setTrades] = useState<any[]>([]);
  const [stats, setStats] = useState<any>({});
  const [filter, setFilter] = useState<'ALL' | 'CLOSED' | 'OPEN'>('ALL');
  const [err, setErr] = useState<string | null>(null);

  const pull = useCallback(async () => {
    try {
      const r = await botApi.trades(200);
      setTrades(r.trades || []);
      setStats(r.stats || {});
      setErr(null);
    } catch (e: any) {
      setErr(e?.status === 403 ? 'Subscription inactive.' : e?.message || 'History unavailable (bot not running).');
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      pull();
    }, [pull]),
  );

  const shown = trades.filter(t => (filter === 'ALL' ? true : t.status === filter));

  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14, paddingBottom: 30 }}>
      <SectionTitle
        right={
          <Text style={{ color: C.dim, fontSize: 11 }} onPress={pull}>
            REFRESH
          </Text>
        }>
        LEDGER · TRADE HISTORY
      </SectionTitle>
      <ErrorNote msg={err} />

      <Card>
        <View style={{ flexDirection: 'row' }}>
          <View style={{ flex: 1 }}>
            <Lbl>NET PNL</Lbl>
            <Text style={{ color: (stats.net_pnl || 0) >= 0 ? C.profit : C.loss, fontWeight: '900', fontSize: 18, marginTop: 2 }}>
              {money(stats.net_pnl, true)}
            </Text>
          </View>
          <View style={{ flex: 1 }}>
            <Lbl>WIN RATE</Lbl>
            <Text style={{ color: C.txt, fontWeight: '900', fontSize: 18, marginTop: 2 }}>
              {stats.win_rate_pct != null ? `${stats.win_rate_pct.toFixed(0)}%` : '--'}
            </Text>
          </View>
          <View style={{ flex: 1 }}>
            <Lbl>FEES</Lbl>
            <Text style={{ color: C.dim, fontWeight: '800', fontSize: 18, marginTop: 2 }}>
              {money(stats.total_fees)}
            </Text>
          </View>
        </View>
        <View style={{ height: 8 }} />
        <Text style={{ color: C.dim2, fontSize: 11 }}>
          {stats.total_trades ?? 0} trades · wins {stats.wins ?? 0} · losses {stats.losses ?? 0} · best {money(stats.best_pnl, true)} · worst {money(stats.worst_pnl, true)}
        </Text>
      </Card>

      <View style={{ flexDirection: 'row', marginTop: 12, marginBottom: 4 }}>
        {(['ALL', 'CLOSED', 'OPEN'] as const).map(f => (
          <Chip key={f} label={f} active={filter === f} onPress={() => setFilter(f)} small />
        ))}
      </View>

      {shown.length === 0 ? (
        <Card>
          <Empty text="No trades yet — the engine records every entry and exit here." />
        </Card>
      ) : (
        shown.map(t => (
          <Card key={t.id} style={{ marginBottom: 10, paddingVertical: 12 }}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <Text style={{ color: C.txt, fontWeight: '900', fontSize: 13.5 }}>{t.symbol}</Text>
                <Text style={{ color: t.side === 'LONG' ? C.profit : C.loss, fontWeight: '800', fontSize: 11.5 }}>{t.side}</Text>
                <Text style={{ color: C.dim2, fontSize: 10.5 }}>{t.leverage}x</Text>
              </View>
              <Text style={{ color: (t.pnl || 0) >= 0 ? C.profit : C.loss, fontWeight: '900', fontSize: 14 }}>
                {t.status === 'OPEN' ? 'OPEN' : money(t.pnl, true)}
              </Text>
            </View>
            <View style={{ height: 6 }} />
            <Text style={{ color: C.dim, fontSize: 11 }}>
              Entry {price(t.entry_price)} → {t.exit_price ? price(t.exit_price) : '—'} · ROE {t.roe_pct != null ? `${Number(t.roe_pct).toFixed(1)}%` : '—'}
            </Text>
            <Text style={{ color: C.dim2, fontSize: 10.5, marginTop: 3 }}>
              {t.close_reason ? String(t.close_reason) : 'Position open'}{t.closed_at ? ` · ${String(t.closed_at).slice(0, 16).replace('T', ' ')}` : ''}
            </Text>
          </Card>
        ))
      )}

      {trades.length > 0 ? (
        <GlassButton
          danger
          title="CLEAR CLOSED HISTORY"
          onPress={() => botApi.clearTrades().then(pull).catch(() => {})}
          style={{ marginTop: 4 }}
        />
      ) : null}
    </ScrollView>
  );
}

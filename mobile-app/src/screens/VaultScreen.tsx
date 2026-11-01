// Vault — open positions with manual close + emergency close-all.
import React, { useCallback, useState } from 'react';
import { Alert, ScrollView, Text, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Card, Empty, ErrorNote, GlassButton, Lbl, SectionTitle } from '../components/ui';
import { botApi } from '../api/endpoints';
import { C, money, price } from '../theme/theme';

export function VaultScreen() {
  const [positions, setPositions] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const pull = useCallback(async () => {
    try {
      const r = await botApi.positions();
      setPositions(r.positions || []);
      setErr(null);
    } catch (e: any) {
      if (e?.status === 403) setErr('Subscription inactive — activate a package to trade.');
      else setErr(e?.message || 'Bot not running — start it from the Cockpit.');
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      pull();
      const t = setInterval(pull, 4000); // live polling like the web Vault tab
      return () => clearInterval(t);
    }, [pull]),
  );

  const close = (sym: string) => {
    Alert.alert('Close position', `Manually close the ${sym} position at market?`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Close',
        style: 'destructive',
        onPress: async () => {
          setBusy(true);
          try {
            await botApi.close(sym);
            setNote(`Close order sent for ${sym}.`);
            await pull();
          } catch (e: any) {
            setErr(e?.message || 'Close failed');
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  };

  const closeAll = () => {
    Alert.alert('Close ALL positions', 'Every open position will be closed at market. Continue?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'CLOSE ALL',
        style: 'destructive',
        onPress: async () => {
          setBusy(true);
          try {
            await botApi.closeAll();
            setNote('Close-all sent to the engine.');
            await pull();
          } catch (e: any) {
            setErr(e?.message || 'Close-all failed');
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  };

  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14, paddingBottom: 30 }}>
      <SectionTitle right={<Text style={{ color: C.dim, fontSize: 11 }}>{positions.length} OPEN</Text>}>
        VAULT · POSITIONS
      </SectionTitle>
      <ErrorNote msg={err} />
      {note ? (
        <View style={{ backgroundColor: 'rgba(22,199,132,0.1)', borderColor: 'rgba(22,199,132,0.4)', borderWidth: 1, borderRadius: 10, padding: 10, marginBottom: 10 }}>
          <Text style={{ color: C.profit, fontSize: 12.5 }}>{note}</Text>
        </View>
      ) : null}

      {positions.length === 0 ? (
        <Card>
          <Empty text="No open positions right now." />
        </Card>
      ) : (
        positions.map(p => (
          <Card key={p.symbol} style={{ marginBottom: 12, borderColor: p.side === 'LONG' ? 'rgba(22,199,132,0.4)' : p.side === 'SHORT' ? 'rgba(234,57,67,0.4)' : C.cardBorder }}>
            {p.side === 'NONE' ? (
              <Text style={{ color: C.dim2, fontSize: 12 }}>{p.symbol}: flat</Text>
            ) : (
              <>
                <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text style={{ color: C.txt, fontWeight: '900', fontSize: 15 }}>{p.symbol}</Text>
                  <Text style={{ color: p.side === 'LONG' ? C.profit : C.loss, fontWeight: '900', fontSize: 13, letterSpacing: 1 }}>
                    {p.side} · {p.leverage}x
                  </Text>
                </View>
                <View style={{ height: 10 }} />
                <View style={{ flexDirection: 'row' }}>
                  <View style={{ flex: 1 }}>
                    <Lbl>ENTRY</Lbl>
                    <Text style={{ color: C.txt, fontWeight: '700', fontSize: 13.5, marginTop: 2 }}>{price(p.entry_price)}</Text>
                    <Lbl style={{ marginTop: 8 }}>SIZE</Lbl>
                    <Text style={{ color: C.txt, fontWeight: '700', fontSize: 13.5, marginTop: 2 }}>{p.size}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Lbl>MARK</Lbl>
                    <Text style={{ color: C.txt, fontWeight: '700', fontSize: 13.5, marginTop: 2 }}>{price(p.mark_price)}</Text>
                    <Lbl style={{ marginTop: 8 }}>UNREALIZED PNL</Lbl>
                    <Text style={{ color: (p.unrealized_pnl || 0) >= 0 ? C.profit : C.loss, fontWeight: '900', fontSize: 13.5, marginTop: 2 }}>
                      {money(p.unrealized_pnl, true)}
                    </Text>
                  </View>
                </View>
                <View style={{ height: 10 }} />
                <Text style={{ color: C.dim, fontSize: 11 }}>
                  TP: {p.tp_price ? price(p.tp_price) : '—'}   ·   SL: {p.sl_price ? price(p.sl_price) : '—'}   ·   {String(p.tp_mode || 'fixed').toUpperCase()}
                </Text>
                <View style={{ height: 12 }} />
                <GlassButton danger title="✕ CLOSE POSITION" onPress={() => close(p.symbol)} />
              </>
            )}
          </Card>
        ))
      )}

      {positions.some(p => p.side !== 'NONE') ? (
        <GlassButton danger title="⚡ CLOSE ALL POSITIONS" onPress={closeAll} style={{ marginTop: 4 }} />
      ) : null}
    </ScrollView>
  );
}

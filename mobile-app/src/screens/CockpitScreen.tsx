// Cockpit — live bot dashboard: status, balance, chart, signals, workers, controls.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Platform,
  RefreshControl,
  ScrollView,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Card, Empty, ErrorNote, GlassButton, GoldButton, KV, Lbl, SectionTitle, StatusPill } from '../components/ui';
import { CandleChart, type Candle, type Emas } from '../components/CandleChart';
import { botApi } from '../api/endpoints';
import { getSocket } from '../socket/ws';
import { C, money, price } from '../theme/theme';
import { useAuth } from '../store/auth';

export function CockpitScreen({ navigation }: any) {
  const { user, refreshUser } = useAuth();
  const [engineRunning, setEngineRunning] = useState(false);
  const [balance, setBalance] = useState<number | null>(null);
  const [statusData, setStatusData] = useState<any>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [emas, setEmas] = useState<Emas>({});
  const [indicators, setIndicators] = useState<any>(null);
  const [signal, setSignal] = useState<any>(null);
  const [position, setPosition] = useState<any>(null);
  const [activeSymbol, setActiveSymbol] = useState<string>('');
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const staleTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const pull = useCallback(async () => {
    try {
      const s = await botApi.status();
      setEngineRunning(!!s.engine_running);
      setStatusData(s.engine);
      setBalance(s.balance?.balance ?? null);
      if (s.engine?.symbols?.length && !activeSymbol) setActiveSymbol(s.engine.symbols[0]);
    } catch (e: any) {
      if (e?.status !== 403) setErr(e?.message || 'Failed to load status');
    }
  }, [activeSymbol]);

  useFocusEffect(
    useCallback(() => {
      pull();
      refreshUser();
      let alive = true;
      let sockRef: any = null;
      const bind = async () => {
        const sock = await getSocket();
        if (!alive) return;
        sockRef = sock;
        sock.on('status', (d: any) => {
          setEngineRunning(!!d?.running);
          setStatusData(d);
          setStale(false);
        });
        sock.on('balance', (d: any) => setBalance(d?.balance ?? null));
        sock.on('indicators', (d: any) => {
          if (!activeSymbol || d.symbol === activeSymbol) {
            setIndicators(d);
            setStale(false);
          }
        });
        sock.on('chart_data', (d: any) => {
          if (!activeSymbol || d.symbol === activeSymbol) {
            setCandles(d.candles || []);
            setEmas(d.emas || {});
            setStale(false);
          }
        });
        sock.on('signal', (d: any) => {
          if (!activeSymbol || d.symbol === activeSymbol) setSignal(d);
        });
        sock.on('position', (d: any) => {
          if (!activeSymbol || d.symbol === activeSymbol) setPosition(d);
        });
      };
      bind();
      // stale-data watchdog: 15s without pushes → mark stale
      staleTimer.current = setInterval(() => setStale(true), 15000);
      return () => {
        alive = false;
        if (staleTimer.current) clearInterval(staleTimer.current);
        if (sockRef) sockRef.off('status').off('balance').off('indicators').off('chart_data').off('signal').off('position');
      };
    }, [pull, activeSymbol, refreshUser]),
  );

  const act = async (name: string, fn: () => Promise<any>) => {
    setBusy(name);
    setErr(null);
    try {
      await fn();
      await pull();
    } catch (e: any) {
      setErr(e?.message || 'Action failed');
    } finally {
      setBusy(null);
    }
  };

  const workers = Object.entries(statusData?.workers || {});
  const testnet = user?.bot_config?.testnet ?? true;
  const exchange = statusData?.exchange || user?.bot_config?.exchange || 'binance';

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: C.bg }}
      contentContainerStyle={{ padding: 14, paddingBottom: 30 }}
      refreshControl={<RefreshControl refreshing={false} onRefresh={pull} tintColor={C.gold} />}>
      <View style={[{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }]}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Text style={{ color: C.neon, fontWeight: '900', fontSize: 17, letterSpacing: 2 }}>COCKPIT</Text>
          {stale && engineRunning ? (
            <Text style={{ color: C.neon2, fontSize: 10, letterSpacing: 1 }}>STALE</Text>
          ) : null}
        </View>
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <TouchableOpacity onPress={() => navigation.navigate('Radar')} style={iconBtn}>
            <Text style={{ color: C.neon2, fontSize: 12, fontWeight: '700' }}>RADAR</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => navigation.navigate('Pulse')} style={iconBtn}>
            <Text style={{ color: C.neon2, fontSize: 12, fontWeight: '700' }}>PULSE</Text>
          </TouchableOpacity>
        </View>
      </View>

      <ErrorNote msg={err} />

      <Card>
        <StatusPill running={engineRunning} testnet={testnet} exchange={exchange} />
        <View style={{ height: 12 }} />
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
          <View style={{ flex: 1 }}>
            <Lbl>{testnet ? 'DEMO BALANCE (SIMULATED)' : 'LIVE USDT BALANCE'}</Lbl>
            <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 2 }}>
              {balance == null && engineRunning ? (
                <ActivityIndicator size="small" color={C.neon2} style={{ marginRight: 6 }} />
              ) : null}
              <Text style={{ color: C.neon, fontSize: 24, fontWeight: '900' }}>
                {balance == null ? (engineRunning ? 'SYNCING…' : '--') : money(balance)}
              </Text>
            </View>
          </View>
          <View style={{ alignItems: 'flex-end' }}>
            <Lbl>TRADES TODAY</Lbl>
            <Text style={{ color: C.txt, fontSize: 24, fontWeight: '900', marginTop: 2 }}>
              {statusData?.trades_today ?? 0}
            </Text>
          </View>
        </View>

        <View style={{ height: 14 }} />
        <View style={{ flexDirection: 'row', gap: 10 }}>
          <View style={{ flex: 1 }}>
            {engineRunning ? (
              <GlassButton danger title={busy === 'stop' ? 'STOPPING…' : '■ STOP BOT'} onPress={() => act('stop', botApi.stop)} />
            ) : (
              <GoldButton title={busy === 'start' ? 'STARTING…' : '▶ START BOT'} onPress={() => act('start', botApi.start)} loading={busy === 'start'} />
            )}
          </View>
          <View style={{ flex: 1 }}>
            <GlassButton title="⚙ ENGINE" onPress={() => navigation.navigate('Engine')} />
          </View>
        </View>
      </Card>

      <View style={{ height: 14 }} />

      <Card>
        <SectionTitle
          right={
            activeSymbol ? (
              <Text style={{ color: C.goldB, fontWeight: '800', fontSize: 13 }}>{activeSymbol}</Text>
            ) : null
          }>
          LIVE CHART · EMA 8/13/21/55
        </SectionTitle>
        <CandleChart candles={candles} emas={emas} />
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 8, gap: 4 }}>
          {[['EMA8', C.blue], ['EMA13', C.neon2], ['EMA21', C.purple], ['EMA55', C.loss]].map(([n, c]) => (
            <View key={n as string} style={{ flexDirection: 'row', alignItems: 'center', marginRight: 10 }}>
              <View style={{ width: 8, height: 3, backgroundColor: c as string, marginRight: 4 }} />
              <Text style={{ color: C.dim, fontSize: 10 }}>{n}</Text>
            </View>
          ))}
        </View>
        {indicators ? (
          <View style={{ marginTop: 10 }}>
            <View style={S.sep} />
            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <View>
                <Lbl>SIGNAL</Lbl>
                <Text style={{ color: indicators.signal === 'BUY' ? C.profit : indicators.signal === 'SELL' ? C.loss : C.dim, fontSize: 16, fontWeight: '900', marginTop: 2 }}>
                  {indicators.signal || 'HOLD'}
                </Text>
              </View>
              <View style={{ alignItems: 'flex-end' }}>
                <Lbl>MARK PRICE</Lbl>
                <Text style={{ color: C.txt, fontSize: 16, fontWeight: '800', marginTop: 2 }}>
                  {price(indicators.mark_price || indicators.close)}
                </Text>
              </View>
            </View>
            {signal?.reason ? (
              <Text style={{ color: C.dim, fontSize: 11, marginTop: 8 }}>{String(signal.reason).slice(0, 160)}</Text>
            ) : null}
          </View>
        ) : null}
      </Card>

      <View style={{ height: 14 }} />

      {position && position.side && position.side !== 'NONE' ? (
        <Card style={{ borderColor: position.side === 'LONG' ? 'rgba(22,199,132,0.4)' : 'rgba(234,57,67,0.4)' }}>
          <SectionTitle right={<Text style={{ color: position.side === 'LONG' ? C.profit : C.loss, fontWeight: '900' }}>{position.side}</Text>}>
            OPEN POSITION
          </SectionTitle>
          <View style={{ flexDirection: 'row' }}>
            <View style={{ flex: 1 }}>
              <KV k="ENTRY" v={price(position.entry_price)} />
              <KV k="SIZE" v={String(position.size ?? '--')} />
              <KV k="LEVERAGE" v={`${position.leverage ?? '--'}x`} />
            </View>
            <View style={{ flex: 1 }}>
              <KV k="UNREALIZED PNL" v={money(position.unrealized_pnl, true)}
                  color={(position.unrealized_pnl || 0) >= 0 ? C.profit : C.loss} />
              <KV k="TP (1:1)" v={position.tp_price ? price(position.tp_price) : '—'} />
              <KV k="SL" v={position.sl_price ? price(position.sl_price) : '—'} />
            </View>
          </View>
          <GlassButton
            danger
            title={busy === 'close' ? 'CLOSING…' : `✕ CLOSE ${position.symbol || ''}`}
            onPress={() => act('close', () => botApi.close(position.symbol))}
          />
        </Card>
      ) : null}

      <Card style={{ marginTop: 14 }}>
        <SectionTitle>ENGINE WORKERS · {workers.filter(([, w]: any) => w?.alive).length}/{workers.length} ALIVE</SectionTitle>
        {workers.length === 0 ? (
          <Empty text="Start the bot to spawn workers." />
        ) : (
          workers.map(([sym, w]: any) => (
            <View key={sym} style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 7, borderBottomColor: 'rgba(240, 185, 11,0.10)', borderBottomWidth: 1 }}>
              <TouchableOpacity onPress={() => setActiveSymbol(sym)}>
                <Text style={{ color: sym === activeSymbol ? C.goldB : C.txt, fontWeight: '800', fontSize: 12.5 }}>{sym}</Text>
              </TouchableOpacity>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
                <Text style={{ color: C.dim, fontSize: 10.5 }}>{w.candles_processed} candles</Text>
                <Text style={{ color: w.last_signal === 'BUY' ? C.profit : w.last_signal === 'SELL' ? C.loss : C.dim, fontSize: 10.5, fontWeight: '700' }}>
                  {w.last_signal || '—'}
                </Text>
                <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: w.alive ? C.profit : C.loss }} />
              </View>
            </View>
          ))
        )}
        <View style={{ height: 10 }} />
        <GlassButton danger title={busy === 'reset' ? 'RESETTING…' : '⚠ FORCE RESET (if stuck)'} onPress={() => act('reset', botApi.forceStop)} />
      </Card>
    </ScrollView>
  );
}

const iconBtn = {
  borderColor: 'rgba(240, 185, 11,0.25)',
  borderWidth: 1,
  borderRadius: 10,
  paddingHorizontal: 10,
  paddingVertical: 6,
  backgroundColor: 'rgba(240, 185, 11,0.05)',
} as const;

const S = {
  sep: { height: 1, backgroundColor: 'rgba(240, 185, 11,0.1)', marginVertical: 8 },
};

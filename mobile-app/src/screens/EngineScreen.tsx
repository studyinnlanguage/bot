// Engine — complete bot configuration. Every backend field is surfaced here.
import React, { useCallback, useState } from 'react';
import { Alert, ScrollView, Text, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Card, Chip, ErrorNote, Field, GlassButton, GoldButton, Lbl, OkNote, SectionTitle } from '../components/ui';
import { botApi } from '../api/endpoints';
import { C } from '../theme/theme';
import { useAuth } from '../store/auth';

const EXCHANGES = [
  { id: 'binance', label: 'Binance', maxLev: 125, note: 'USDT-M Futures' },
  { id: 'weex', label: 'WEEX', maxLev: 500, note: 'Passphrase required' },
  { id: 'primexbt', label: 'PrimeXBT', maxLev: 1000, note: 'PXTrader 2.0 API (Demo & Live)' },
];
const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '1d'];
const MODES = ['both', 'long', 'short'];

export function EngineScreen() {
  const { user, refreshUser } = useAuth();
  const [exchange, setExchange] = useState('binance');
  const [testnet, setTestnet] = useState(true);
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [passphrase, setPassphrase] = useState('');
  const [symbolsText, setSymbolsText] = useState('');
  const [timeframe, setTimeframe] = useState('5m');
  const [leverage, setLeverage] = useState('10');
  const [amountMode, setAmountMode] = useState<'fixed' | 'percent'>('fixed');
  const [amount, setAmount] = useState('100');
  const [amountPct, setAmountPct] = useState('10');
  const [stopLossPct, setStopLossPct] = useState('2');
  const [mode, setMode] = useState('both');
  const [maxTrades, setMaxTrades] = useState('3');
  const [minSpread, setMinSpread] = useState('0');
  const [freshWindow, setFreshWindow] = useState('8');
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  useFocusEffect(
    useCallback(() => {
      (async () => {
        try {
          const r = await botApi.config();
          const cfg = r.config || {};
          setExchange(cfg.exchange || 'binance');
          setTestnet(!!cfg.testnet);
          setSymbolsText((cfg.symbols_list || []).join(', '));
          setTimeframe(cfg.timeframe || '5m');
          setLeverage(String(cfg.leverage ?? 10));
          setAmountMode(cfg.amount_mode === 'percent' ? 'percent' : 'fixed');
          setAmount(String(cfg.amount ?? 100));
          setAmountPct(String(cfg.amount_pct ?? 10));
          setStopLossPct(String(cfg.stop_loss_pct ?? 2));
          setMode(cfg.mode || 'both');
          setMaxTrades(String(cfg.max_concurrent_trades ?? 3));
          setMinSpread(String(cfg.min_ema_spread ?? 0));
          setFreshWindow(String(cfg.fresh_window ?? 8));
        } catch (e: any) {
          setErr(e?.message || 'Failed to load config');
        }
      })();
    }, []),
  );

  const ex = EXCHANGES.find(e => e.id === exchange) || EXCHANGES[0];
  const hasKeys = user?.bot_config?.has_api_key && user?.bot_config?.has_api_secret;

  const save = async () => {
    setBusy(true);
    setErr(null);
    setOk(null);
    try {
      const patch: Record<string, any> = {
        exchange, testnet, symbols_list: symbolsText, timeframe,
        leverage: Number(leverage), amount_mode: amountMode,
        amount: Number(amount), amount_pct: Number(amountPct),
        stop_loss_pct: Number(stopLossPct), mode,
        max_concurrent_trades: Number(maxTrades),
        min_ema_spread: Number(minSpread), fresh_window: Number(freshWindow),
      };
      if (apiKey.trim()) patch.api_key = apiKey.trim();
      if (apiSecret.trim()) patch.api_secret = apiSecret.trim();
      if (exchange === 'weex' && passphrase.trim()) patch.api_passphrase = passphrase.trim();
      const r = await botApi.saveConfig(patch);
      setOk('Settings saved.' + (r.engine_sync ? ' Live engine synced.' : ' Takes effect on next bot start.'));
      setApiKey('');
      setApiSecret('');
      setPassphrase('');
      refreshUser();
    } catch (e: any) {
      setErr(e?.message || 'Save failed');
    } finally {
      setBusy(false);
    }
  };

  const testConn = async () => {
    setTesting(true);
    setErr(null);
    setOk(null);
    try {
      const r = await botApi.testConnection();
      if (r.success) {
        Alert.alert('Connection OK', `${String(r.exchange || exchange).toUpperCase()}${r.demo ? ' (demo)' : ''} — Balance: $${Number(r.balance ?? 0).toFixed(2)}`);
      } else {
        Alert.alert('Connection failed', r.message || r.error || 'API keys rejected by the exchange.');
      }
    } catch (e: any) {
      Alert.alert('Connection failed', e?.message || 'Bot must be running to test.');
    } finally {
      setTesting(false);
    }
  };

  const quickLev = async (lev: number) => {
    try {
      await botApi.leverage(lev);
      setLeverage(String(lev));
      setOk(`Leverage ${lev}x applied to the active symbol.`);
    } catch (e: any) {
      setErr(e?.message || 'Failed to set leverage (is the bot running?)');
    }
  };

  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14, paddingBottom: 30 }}>
      <SectionTitle>ENGINE · BOT CONFIGURATION</SectionTitle>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />

      <Card>
        <Lbl style={{ marginBottom: 8 }}>EXCHANGE</Lbl>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {EXCHANGES.map(e => (
            <Chip key={e.id} label={e.label} active={exchange === e.id} onPress={() => setExchange(e.id)} />
          ))}
        </View>
        <Text style={{ color: C.dim2, fontSize: 11, marginBottom: 10 }}>{ex.note} · max leverage {ex.maxLev}x</Text>

        <Lbl style={{ marginBottom: 8 }}>ENVIRONMENT</Lbl>
        <View style={{ flexDirection: 'row' }}>
          <Chip
            label={testnet ? '● DEMO — SIMULATED FUNDS' : '● LIVE — REAL MONEY'}
            active
            onPress={() => {
              if (testnet) {
                Alert.alert(
                  'Enable LIVE TRADING?',
                  'LIVE trading places REAL ORDERS with REAL CAPITAL on the live exchange. Ensure your risk parameters and API keys are verified.\n\nSimulated funds will NOT be used in Live mode.',
                  [
                    { text: 'Cancel', style: 'cancel' },
                    { text: 'Switch to LIVE', style: 'destructive', onPress: () => setTestnet(false) },
                  ],
                );
              } else {
                setTestnet(true);
              }
            }}
          />
        </View>
        <Text style={{ color: testnet ? C.neon : C.loss, fontSize: 11, marginBottom: 12, fontWeight: '700' }}>
          {testnet
            ? 'DEMO: Virtual simulated funds only. Completely isolated from live capital.'
            : '⚠️ LIVE TRADING ACTIVE: Every order executes with real money on the live exchange.'}
        </Text>

        <Field label="API KEY" value={apiKey} onChangeText={setApiKey}
          placeholder={user?.bot_config?.has_api_key ? 'Saved — enter to replace' : 'Exchange API key'} secure={!apiKey ? false : true} />
        <Field label="API SECRET" value={apiSecret} onChangeText={setApiSecret}
          placeholder={user?.bot_config?.has_api_secret ? 'Saved — enter to replace' : 'Exchange API secret'} secure />
        {exchange === 'weex' && (
          <Field label="API PASSPHRASE (WEEX REQUIRES IT)" value={passphrase} onChangeText={setPassphrase}
            placeholder={user?.bot_config?.has_passphrase ? 'Saved — enter to replace' : 'WEEX passphrase'} secure />
        )}
        {exchange === 'primexbt' && (
          <Text style={{ color: C.dim, fontSize: 11, marginBottom: 10, lineHeight: 16 }}>
            PrimeXBT PXTrader 2.0 API: Supports PXTrader 2.0 HMAC-SHA256 and Ed25519 signing. DEMO connects to PXTrader 2.0 Demo sandbox.
          </Text>
        )}
        <GlassButton title={testing ? 'TESTING…' : '🔌 TEST CONNECTION (CHECK API KEYS)'} onPress={testConn} />
      </Card>

      <Card style={{ marginTop: 14 }}>
        <SectionTitle>TRADING UNIVERSE</SectionTitle>
        <Field
          label="SYMBOLS (COMMA SEPARATED)"
          value={symbolsText}
          onChangeText={setSymbolsText}
          placeholder="BTCUSDT, ETHUSDT, SOLUSDT"
          hint="Each symbol gets its own engine worker (max 3 concurrent trades overall)."
        />
        <Lbl style={{ marginBottom: 8 }}>TIMEFRAME</Lbl>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {TIMEFRAMES.map(tf => (
            <Chip key={tf} label={tf} active={timeframe === tf} onPress={() => setTimeframe(tf)} small />
          ))}
        </View>
      </Card>

      <Card style={{ marginTop: 14 }}>
        <SectionTitle>RISK</SectionTitle>
        <Field label={`LEVERAGE (1–${ex.maxLev}x)`} value={leverage} onChangeText={setLeverage} keyboardType="numbers-and-punctuation" />
        <View style={{ flexDirection: 'row', marginBottom: 10 }}>
          {[10, 20, 50, 100].map(l => (
            <Chip key={l} label={`${l}x`} active={leverage === String(l)} onPress={() => quickLev(l)} small />
          ))}
        </View>
        <Lbl style={{ marginBottom: 8 }}>POSITION SIZE MODE</Lbl>
        <View style={{ flexDirection: 'row' }}>
          <Chip label="FIXED USDT" active={amountMode === 'fixed'} onPress={() => setAmountMode('fixed')} />
          <Chip label="% OF BALANCE" active={amountMode === 'percent'} onPress={() => setAmountMode('percent')} />
        </View>
        {amountMode === 'fixed' ? (
          <Field label="AMOUNT PER TRADE (USDT)" value={amount} onChangeText={setAmount} keyboardType="numbers-and-punctuation" />
        ) : (
          <Field label="% OF BALANCE PER TRADE (1–100)" value={amountPct} onChangeText={setAmountPct} keyboardType="numbers-and-punctuation" />
        )}
        <Field label="STOP LOSS % (0.5–50) — TP IS STRICT 1:1" value={stopLossPct} onChangeText={setStopLossPct} keyboardType="numbers-and-punctuation"
          hint="Take-profit is automatically placed at the same distance as the stop loss." />
        <Lbl style={{ marginBottom: 8 }}>DIRECTION MODE</Lbl>
        <View style={{ flexDirection: 'row' }}>
          {MODES.map(m => (
            <Chip key={m} label={m.toUpperCase()} active={mode === m} onPress={() => setMode(m)} small />
          ))}
        </View>
        <Field label="MAX CONCURRENT TRADES (1–3)" value={maxTrades} onChangeText={setMaxTrades} keyboardType="numbers-and-punctuation" />
      </Card>

      <Card style={{ marginTop: 14 }}>
        <SectionTitle>STRATEGY TUNING (EMA QUAD)</SectionTitle>
        <Field label="MIN EMA SPREAD % (0 = AUTO: 0.15 MAJORS / 0.20 MEMES)" value={minSpread} onChangeText={setMinSpread} keyboardType="numbers-and-punctuation" />
        <Field label="FRESH CROSS WINDOW (CANDLES, 2–50)" value={freshWindow} onChangeText={setFreshWindow} keyboardType="numbers-and-punctuation"
          hint="Signals are only traded when the EMA55 cross happened within this many candles." />
      </Card>

      <GoldButton title="SAVE ALL SETTINGS" onPress={save} loading={busy} style={{ marginTop: 16 }} />
      <Text style={{ color: C.dim2, fontSize: 10.5, textAlign: 'center', marginTop: 10 }}>
        Saved server-side with atomic backup · API secrets are encrypted at rest and never shown again
      </Text>
    </ScrollView>
  );
}

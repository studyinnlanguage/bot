// Account — profile, subscription, license activation, packages & USDT payment,
// referral program with payout wallet and withdrawals.
import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Modal,
  ScrollView,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import QRCode from 'react-native-qrcode-svg';
import {
  Card,
  ErrorNote,
  Field,
  GlassButton,
  GoldButton,
  KV,
  Lbl,
  OkNote,
  SectionTitle,
} from '../components/ui';
import { accountApi } from '../api/endpoints';
import { api } from '../api/client';
import { C, money } from '../theme/theme';
import { useAuth } from '../store/auth';

export function AccountScreen() {
  const { user, signOut, refreshUser } = useAuth();
  const [tab, setTab] = useState<'profile' | 'packages' | 'referral'>('profile');
  const [licenseKey, setLicenseKey] = useState('');
  const [activating, setActivating] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const activate = async () => {
    setActivating(true);
    setErr(null);
    setMsg(null);
    try {
      const r: any = await api.post('/api/mobile/license/activate', { key: licenseKey.trim() });
      setMsg(`License activated! Plan: ${r.subscription?.plan ?? 'active'}`);
      setLicenseKey('');
      refreshUser();
    } catch (e: any) {
      setErr(e?.message || 'Activation failed');
    } finally {
      setActivating(false);
    }
  };

  const sub = user?.subscription;

  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14, paddingBottom: 30 }}>
      <Card style={{ alignItems: 'center', paddingVertical: 18 }}>
        <View style={{ width: 58, height: 58, borderRadius: 29, backgroundColor: '#12161f', borderWidth: 1.4, borderColor: 'rgba(240, 185, 11,0.6)', alignItems: 'center', justifyContent: 'center' }}>
          <Text style={{ color: C.neon, fontSize: 24, fontWeight: '900', fontStyle: 'italic' }}>W</Text>
        </View>
        <Text style={{ color: C.txt, fontWeight: '900', fontSize: 17, marginTop: 10 }}>{user?.name}</Text>
        <Text style={{ color: C.dim, fontSize: 12.5 }}>{user?.email}</Text>
        <View style={{ flexDirection: 'row', gap: 8, marginTop: 12 }}>
          <View style={{ borderColor: 'rgba(240, 185, 11,0.3)', borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 5 }}>
            <Text style={{ color: sub?.active ? C.neon2 : C.dim, fontSize: 11.5, fontWeight: '800' }}>
              {sub?.active ? `${String(sub.plan).toUpperCase()}${sub.days_left != null ? ` · ${sub.days_left}d LEFT` : ''}` : 'NO ACTIVE PLAN'}
            </Text>
          </View>
          {user?.bot_config?.testnet ? (
            <View style={{ borderColor: 'rgba(255,183,77,0.4)', borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 5 }}>
              <Text style={{ color: C.neon, fontSize: 11.5, fontWeight: '800' }}>DEMO</Text>
            </View>
          ) : (
            <View style={{ borderColor: 'rgba(240, 185, 11,0.4)', borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 5 }}>
              <Text style={{ color: C.neon2, fontSize: 11.5, fontWeight: '800' }}>LIVE</Text>
            </View>
          )}
        </View>
        {sub?.expires_at && sub.active ? (
          <Text style={{ color: C.dim2, fontSize: 10.5, marginTop: 8 }}>
            Expires {String(sub.expires_at).slice(0, 10)}
          </Text>
        ) : null}
      </Card>

      <View style={{ flexDirection: 'row', marginTop: 14, marginBottom: 6 }}>
        {(['profile', 'packages', 'referral'] as const).map(t => (
          <TouchableOpacity key={t} onPress={() => setTab(t)} style={{ flex: 1, alignItems: 'center', paddingVertical: 9, borderRadius: 12, backgroundColor: tab === t ? 'rgba(240, 185, 11,0.15)' : 'transparent', marginRight: 6 }}>
            <Text style={{ color: tab === t ? C.neon : C.dim, fontWeight: '800', fontSize: 12 }}>
              {t === 'profile' ? 'ACCOUNT' : t === 'packages' ? 'PLANS' : 'REFERRALS'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {tab === 'profile' && (
        <>
          <ErrorNote msg={err} />
          <OkNote msg={msg} />
          <Card style={{ marginTop: 6 }}>
            <SectionTitle>LICENSE ACTIVATION</SectionTitle>
            <Field label="LICENSE KEY" value={licenseKey} onChangeText={setLicenseKey} placeholder="TRDBOT-XXXX-XXXX-XXXX-XXXX" />
            <GoldButton title="ACTIVATE" onPress={activate} loading={activating} />
          </Card>
          <Card style={{ marginTop: 14 }}>
            <SectionTitle>ACCOUNT DETAILS</SectionTitle>
            <KV k="MEMBER SINCE" v={user?.created_at ? String(user.created_at).slice(0, 10) : '--'} />
            <KV k="ACCOUNT ROLE" v={String(user?.role || 'user').toUpperCase()} />
            <KV k="EXCHANGE" v={String(user?.bot_config?.exchange || 'binance').toUpperCase()} />
            <KV k="API KEYS" v={user?.bot_config?.has_api_key ? 'Saved (encrypted)' : 'Not configured'} color={user?.bot_config?.has_api_key ? C.profit : C.dim} />
          </Card>
          <GlassButton danger title="SIGN OUT" onPress={signOut} style={{ marginTop: 14 }} />
        </>
      )}

      {tab === 'packages' && <PackagesTab />}
      {tab === 'referral' && <ReferralTab />}
    </ScrollView>
  );
}

function PackagesTab() {
  const [packages, setPackages] = useState<any>({});
  const [orders, setOrders] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [paymentOrder, setPaymentOrder] = useState<any | null>(null);
  const [wallets, setWallets] = useState<any>({});

  const pull = useCallback(async () => {
    try {
      const [p, o] = await Promise.all([accountApi.packages(), accountApi.orders()]);
      setPackages(p.packages || {});
      setWallets(p.wallets || {});
      setOrders(o.orders || []);
    } catch (e: any) {
      setErr(e?.message || 'Failed to load packages');
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      pull();
    }, [pull]),
  );

  const buy = async (packageId: string) => {
    setErr(null);
    try {
      const r = await accountApi.createOrder(packageId);
      setPaymentOrder(r.order);
    } catch (e: any) {
      Alert.alert('Order', e?.body?.order_id ? 'You already have a pending order.' : e?.message || 'Could not create order');
    }
  };

  return (
    <>
      <ErrorNote msg={err} />
      {Object.entries(packages).map(([id, p]: any) => (
        <Card key={id} style={{ marginTop: 8, borderColor: p.popular ? 'rgba(240, 185, 11,0.55)' : C.cardBorder }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <View>
              <Text style={{ color: C.neon, fontWeight: '900', fontSize: 16 }}>{p.name}</Text>
              <Text style={{ color: C.dim, fontSize: 11.5, marginTop: 2 }}>
                {p.days >= 9999 ? 'Never expires' : `${p.days} days`} · ${p.referral_bonus} referral bonus
              </Text>
            </View>
            <Text style={{ color: C.txt, fontWeight: '900', fontSize: 20 }}>${p.price}</Text>
          </View>
          <View style={{ height: 12 }} />
          <GoldButton title="PAY WITH USDT" onPress={() => buy(id)} />
        </Card>
      ))}

      <Card style={{ marginTop: 14 }}>
        <SectionTitle>MY ORDERS</SectionTitle>
        {orders.length === 0 ? (
          <Text style={{ color: C.dim2, fontSize: 12 }}>No orders yet.</Text>
        ) : (
          orders.slice(0, 8).map(o => (
            <View key={o.id} style={{ paddingVertical: 8, borderBottomColor: 'rgba(240, 185, 11,0.08)', borderBottomWidth: 1 }}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                <Text style={{ color: C.txt, fontSize: 12, fontWeight: '700' }}>{o.id}</Text>
                <Text style={{ color: o.status === 'verified' ? C.profit : o.status === 'rejected' ? C.loss : C.neon2, fontSize: 11.5, fontWeight: '800', textTransform: 'uppercase' }}>
                  {o.status === 'submitted' ? 'PENDING VERIFICATION' : o.status}
                </Text>
              </View>
              <Text style={{ color: C.dim2, fontSize: 10.5, marginTop: 2 }}>
                {o.package_name} · {money(o.amount)} · {String(o.created_at).slice(0, 10)}
              </Text>
              {o.status === 'submitted' || o.status === 'pending' ? (
                <TouchableOpacity onPress={() => setPaymentOrder(o)}>
                  <Text style={{ color: C.neon2, fontSize: 11, marginTop: 4 }}>
                    {o.status === 'submitted' ? 'Track verification →' : 'Complete payment →'}
                  </Text>
                </TouchableOpacity>
              ) : null}
            </View>
          ))
        )}
      </Card>

      <PaymentModal
        order={paymentOrder}
        wallets={wallets}
        onClose={() => {
          setPaymentOrder(null);
          pull();
        }}
      />
    </>
  );
}

function PaymentModal({ order, wallets, onClose }: { order: any; wallets: any; onClose: () => void }) {
  const [network, setNetwork] = useState<'trc20' | 'bep20'>('trc20');
  const [txHash, setTxHash] = useState('');
  const [busy, setBusy] = useState(false);
  const [polling, setPolling] = useState(false);
  const [verified, setVerified] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!order || polling) return;
    if (order.status !== 'submitted') return;
    let stop = false;
    setPolling(true);
    const t = setInterval(async () => {
      try {
        const r = await accountApi.checkVerification(order.id);
        if (r.verified) {
          setVerified(r);
          clearInterval(t);
        }
      } catch {}
    }, 6000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [order, polling]);

  if (!order) return null;
  const address = network === 'trc20' ? wallets.trc20 : wallets.bep20;
  const networkLabel = network === 'trc20' ? 'TRC-20 (Tron)' : 'BEP-20 (BNB Smart Chain)';

  const submit = async () => {
    if (!address) {
      setErr(`Wallet address unavailable for ${networkLabel}. Please select another network.`);
      return;
    }
    if (!txHash.trim()) {
      setErr('Please paste the transaction hash (TXID).');
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const r = await accountApi.submitOrder(order.id, txHash.trim());
      if (r.verified) {
        setVerified(r);
      } else {
        Alert.alert('Submitted', r.message || 'Verification in progress — this screen will update automatically.');
      }
    } catch (e: any) {
      setErr(e?.message || 'Submission failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.85)', justifyContent: 'flex-end' }}>
        <View style={{ backgroundColor: C.bg2, borderTopLeftRadius: 22, borderTopRightRadius: 22, padding: 18, maxHeight: '92%', borderColor: 'rgba(240, 185, 11,0.25)', borderWidth: 1 }}>
          {verified ? (
            <View style={{ alignItems: 'center', paddingVertical: 30 }}>
              <Text style={{ color: C.profit, fontSize: 40 }}>✓</Text>
              <Text style={{ color: C.txt, fontWeight: '900', fontSize: 18, marginTop: 10 }}>Payment verified!</Text>
              <Text style={{ color: C.dim, fontSize: 12.5, marginTop: 6, textAlign: 'center' }}>
                Your subscription is active. License: {verified.license_key || order.license_key}
              </Text>
              <GoldButton title="DONE" onPress={onClose} style={{ marginTop: 22, alignSelf: 'stretch' }} />
            </View>
          ) : (
            <ScrollView>
              <SectionTitle right={<Text style={{ color: C.dim, fontSize: 11 }}>{order.id}</Text>}>
                PAY {money(order.amount)} USDT ({order.package_name || 'Plan'})
              </SectionTitle>
              <View style={{ flexDirection: 'row', marginBottom: 12 }}>
                {(['trc20', 'bep20'] as const).map(n => (
                  <TouchableOpacity
                    key={n}
                    onPress={() => setNetwork(n)}
                    style={{
                      flex: 1,
                      alignItems: 'center',
                      paddingVertical: 10,
                      borderRadius: 12,
                      marginRight: 8,
                      backgroundColor: network === n ? 'rgba(240, 185, 11,0.16)' : 'rgba(0,0,0,0.3)',
                      borderWidth: 1,
                      borderColor: network === n ? C.neon2 : 'rgba(240, 185, 11,0.15)',
                    }}>
                    <Text style={{ color: network === n ? C.neon : C.dim, fontWeight: '800', fontSize: 12 }}>
                      {n.toUpperCase()}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
              <View style={{ alignItems: 'center', marginVertical: 10 }}>
                {address ? (
                  <QRCode value={address} size={148} backgroundColor="#FFFFFF" color="#0b0e11" />
                ) : (
                  <View style={{ padding: 24, alignItems: 'center' }}>
                    <Text style={{ color: C.warn, fontSize: 13, textAlign: 'center', lineHeight: 18 }}>
                      ⚠️ {networkLabel} wallet is temporarily unconfigured.{'\n'}Please select another network above.
                    </Text>
                  </View>
                )}
                <Text style={{ color: C.dim2, fontSize: 10.5, marginTop: 8 }}>{networkLabel}</Text>
              </View>
              <View style={{ backgroundColor: 'rgba(0,0,0,0.4)', borderRadius: 10, padding: 10, borderWidth: 1, borderColor: 'rgba(240, 185, 11,0.2)' }}>
                <Text style={{ color: address ? C.neon2 : C.warn, fontSize: 11.5 }} selectable>
                  {address || 'Wallet address unavailable — select other network or contact support.'}
                </Text>
              </View>
              <Text style={{ color: C.dim, fontSize: 11, marginTop: 10, lineHeight: 16 }}>
                Send exactly <Text style={{ color: C.txt, fontWeight: '800' }}>{money(order.amount)} USDT</Text> on {networkLabel}, then paste the transaction hash below. Verification runs automatically on-chain.
              </Text>
              <View style={{ height: 10 }} />
              <ErrorNote msg={err} />
              <Field label="TRANSACTION HASH (TXID)" value={txHash} onChangeText={setTxHash} placeholder="0x… / Tron tx id" />
              <GoldButton
                title={!address ? 'SELECT ACTIVE NETWORK' : 'SUBMIT FOR VERIFICATION'}
                onPress={submit}
                loading={busy}
                disabled={!address}
              />
              <TouchableOpacity onPress={onClose}>
                <Text style={{ color: C.dim2, textAlign: 'center', marginTop: 12, fontSize: 12 }}>Close</Text>
              </TouchableOpacity>
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
}

function ReferralTab() {
  const [data, setData] = useState<any>(null);
  const [wallet, setWallet] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const pull = useCallback(async () => {
    try {
      const r = await accountApi.referral();
      setData(r);
      setWallet(r.payout_wallet || '');
    } catch (e: any) {
      setErr(e?.message || 'Failed to load referral info');
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      pull();
    }, [pull]),
  );

  const saveWallet = async () => {
    setBusy(true);
    setErr(null);
    setOk(null);
    try {
      await accountApi.savePayoutWallet(wallet.trim());
      setOk('Payout wallet saved.');
      pull();
    } catch (e: any) {
      setErr(e?.message || 'Save failed');
    } finally {
      setBusy(false);
    }
  };

  const withdraw = async () => {
    Alert.alert(
      'Request payout',
      `Withdraw ${money(data?.available_balance)} USDT to your saved wallet?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Request',
          onPress: async () => {
            setBusy(true);
            setErr(null);
            try {
              await accountApi.requestPayout();
              setOk('Payout request submitted — the team will process it soon.');
              pull();
            } catch (e: any) {
              setErr(e?.message || 'Request failed');
            } finally {
              setBusy(false);
            }
          },
        },
      ],
    );
  };

  const copyRef = () => {
    Alert.alert('Your referral link', data?.referral_link || '');
  };

  return (
    <>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />
      <Card style={{ marginTop: 6 }}>
        <SectionTitle>YOUR REFERRAL LINK</SectionTitle>
        <TouchableOpacity onPress={copyRef}>
          <View style={{ backgroundColor: 'rgba(0,0,0,0.4)', borderRadius: 10, padding: 10, borderWidth: 1, borderColor: 'rgba(240, 185, 11,0.2)' }}>
            <Text style={{ color: C.goldB, fontSize: 11.5 }} selectable>
              {data?.referral_link || '…'}
            </Text>
          </View>
        </TouchableOpacity>
        <Text style={{ color: C.dim2, fontSize: 11, marginTop: 6 }}>Code: {data?.referral_code || '—'} · $10 per 1-Year, $50 per Lifetime sale</Text>
        <View style={{ flexDirection: 'row', marginTop: 12 }}>
          <View style={{ flex: 1 }}>
            <Lbl>EARNINGS</Lbl>
            <Text style={{ color: C.txt, fontWeight: '900', fontSize: 17, marginTop: 2 }}>{money(data?.total_earnings)}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Lbl>AVAILABLE</Lbl>
            <Text style={{ color: C.profit, fontWeight: '900', fontSize: 17, marginTop: 2 }}>{money(data?.available_balance)}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Lbl>WITHDRAWN</Lbl>
            <Text style={{ color: C.dim, fontWeight: '800', fontSize: 17, marginTop: 2 }}>{money(data?.total_withdrawn)}</Text>
          </View>
        </View>
      </Card>

      <Card style={{ marginTop: 14 }}>
        <SectionTitle>PAYOUT WALLET (USDT)</SectionTitle>
        <Field label="WALLET ADDRESS" value={wallet} onChangeText={setWallet} placeholder="TRC-20 / BEP-20 address" />
        <View style={{ flexDirection: 'row', gap: 10 }}>
          <View style={{ flex: 1 }}>
            <GlassButton title="SAVE WALLET" onPress={saveWallet} />
          </View>
          <View style={{ flex: 1 }}>
            <GoldButton title="WITHDRAW ALL" onPress={withdraw} loading={busy} />
          </View>
        </View>
      </Card>

      <Card style={{ marginTop: 14 }}>
        <SectionTitle>REFERRAL HISTORY</SectionTitle>
        {(data?.referral_history || []).length === 0 ? (
          <Text style={{ color: C.dim2, fontSize: 12 }}>No referral earnings yet.</Text>
        ) : (
          data.referral_history.slice(0, 10).map((h: any, i: number) => (
            <View key={i} style={{ paddingVertical: 7, borderBottomColor: 'rgba(240, 185, 11,0.12)', borderBottomWidth: 1 }}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                <Text style={{ color: C.txt, fontSize: 12 }}>{h.buyer_email || h.buyer_id}</Text>
                <Text style={{ color: C.profit, fontWeight: '800', fontSize: 12.5 }}>{money(h.bonus_amount, true)}</Text>
              </View>
              <Text style={{ color: C.dim2, fontSize: 10.5, marginTop: 2 }}>
                {h.package_name} · {String(h.timestamp).slice(0, 10)}
              </Text>
            </View>
          ))
        )}
      </Card>
    </>
  );
}

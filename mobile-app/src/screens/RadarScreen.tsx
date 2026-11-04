// Radar — notification channels (Telegram / Email / WhatsApp) + test send.
import React, { useCallback, useState } from 'react';
import { ScrollView, Switch, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Card, ErrorNote, Field, GlassButton, GoldButton, Lbl, OkNote, SectionTitle } from '../components/ui';
import { botApi } from '../api/endpoints';
import { C } from '../theme/theme';

export function RadarScreen() {
  const [tgOn, setTgOn] = useState(false);
  const [tgToken, setTgToken] = useState('');
  const [tgChat, setTgChat] = useState('');
  const [emailOn, setEmailOn] = useState(false);
  const [smtpServer, setSmtpServer] = useState('smtp.gmail.com');
  const [smtpPort, setSmtpPort] = useState('587');
  const [emailSender, setEmailSender] = useState('');
  const [emailPassword, setEmailPassword] = useState('');
  const [emailReceiver, setEmailReceiver] = useState('');
  const [waOn, setWaOn] = useState(false);
  const [waPhone, setWaPhone] = useState('');
  const [waKey, setWaKey] = useState('');
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
          setTgOn(!!cfg.telegram_enabled);
          setTgChat(cfg.telegram_chat_id || '');
          setEmailOn(!!cfg.email_enabled);
          setSmtpServer(cfg.email_smtp_server || 'smtp.gmail.com');
          setSmtpPort(String(cfg.email_smtp_port ?? 587));
          setEmailSender(cfg.email_sender || '');
          setEmailReceiver(cfg.email_receiver || '');
          setWaOn(!!cfg.whatsapp_enabled);
          setWaPhone(cfg.whatsapp_phone || '');
        } catch (e: any) {
          setErr(e?.message || 'Failed to load notification settings');
        }
      })();
    }, []),
  );

  const save = async () => {
    setBusy(true);
    setErr(null);
    setOk(null);
    try {
      await botApi.saveConfig({
        telegram_enabled: tgOn,
        telegram_bot_token: tgToken || undefined,
        telegram_chat_id: tgChat,
        email_enabled: emailOn,
        email_smtp_server: smtpServer,
        email_smtp_port: Number(smtpPort) || 587,
        email_sender: emailSender,
        email_password: emailPassword || undefined,
        email_receiver: emailReceiver,
        whatsapp_enabled: waOn,
        whatsapp_phone: waPhone,
        whatsapp_apikey: waKey || undefined,
      });
      setOk('Notification settings saved.');
      setTgToken('');
      setEmailPassword('');
      setWaKey('');
    } catch (e: any) {
      setErr(e?.message || 'Save failed');
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    setTesting(true);
    setErr(null);
    try {
      const r = await botApi.testNotification();
      if (r.success) {
        const parts: string[] = [];
        if (r.results?.telegram) parts.push(`Telegram: ${r.results.telegram.success ? 'sent' : 'FAILED'}`);
        if (r.results?.email) parts.push(`Email: ${r.results.email.success ? 'sent' : 'FAILED'}`);
        if (r.results?.whatsapp) parts.push(`WhatsApp: ${r.results.whatsapp.success ? 'sent' : 'FAILED'}`);
        setOk(parts.join(' · ') || 'Test sent.');
      } else {
        setErr(r.error || 'No notification channel is enabled.');
      }
    } catch (e: any) {
      setErr(e?.message || 'Test failed');
    } finally {
      setTesting(false);
    }
  };

  const toggle = (v: boolean, set: (b: boolean) => void, label: string) => (
    <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
      <Lbl>{label}</Lbl>
      <Switch value={v} onValueChange={set} trackColor={{ true: C.goldD, false: '#222' }} thumbColor={v ? C.gold : '#555'} />
    </View>
  );

  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14, paddingBottom: 30 }}>
      <SectionTitle>RADAR · NOTIFICATIONS</SectionTitle>
      <ErrorNote msg={err} />
      <OkNote msg={ok} />

      <Card>
        {toggle(tgOn, setTgOn, 'TELEGRAM')}
        {tgOn && (
          <>
            <Field label="BOT TOKEN" value={tgToken} onChangeText={setTgToken} placeholder="Saved — enter to replace" secure={!tgToken} />
            <Field label="CHAT ID" value={tgChat} onChangeText={setTgChat} placeholder="123456789" />
          </>
        )}
      </Card>

      <Card style={{ marginTop: 14 }}>
        {toggle(emailOn, setEmailOn, 'EMAIL (SMTP)')}
        {emailOn && (
          <>
            <Field label="SMTP SERVER" value={smtpServer} onChangeText={setSmtpServer} />
            <Field label="SMTP PORT" value={smtpPort} onChangeText={setSmtpPort} keyboardType="numbers-and-punctuation" />
            <Field label="SENDER EMAIL" value={emailSender} onChangeText={setEmailSender} placeholder="bot@gmail.com" />
            <Field label="APP PASSWORD" value={emailPassword} onChangeText={setEmailPassword} placeholder="Saved — enter to replace" secure={!emailPassword} />
            <Field label="RECEIVER EMAIL" value={emailReceiver} onChangeText={setEmailReceiver} placeholder="you@gmail.com" />
          </>
        )}
      </Card>

      <Card style={{ marginTop: 14 }}>
        {toggle(waOn, setWaOn, 'WHATSAPP (CALLMEBOT)')}
        {waOn && (
          <>
            <Field label="PHONE (+COUNTRYCODE)" value={waPhone} onChangeText={setWaPhone} placeholder="+92300…" />
            <Field label="CALLMEBOT API KEY" value={waKey} onChangeText={setWaKey} placeholder="Saved — enter to replace" secure={!waKey} />
          </>
        )}
      </Card>

      <View style={{ flexDirection: 'row', gap: 10, marginTop: 16 }}>
        <View style={{ flex: 1 }}>
          <GlassButton title={testing ? 'SENDING…' : '🔔 SEND TEST'} onPress={test} />
        </View>
        <View style={{ flex: 1 }}>
          <GoldButton title="SAVE SETTINGS" onPress={save} loading={busy} />
        </View>
      </View>
    </ScrollView>
  );
}

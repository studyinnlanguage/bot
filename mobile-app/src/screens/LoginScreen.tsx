import React, { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  Text,
  TouchableOpacity,
  View,
  Linking,
  ActivityIndicator,
} from 'react-native';
import { Card, ErrorNote, Field, GoldButton, Lbl, Logo, OkNote } from '../components/ui';
import { C } from '../theme/theme';
import { useAuth } from '../store/auth';
import { GOOGLE_OAUTH_ENTRY, APP_VERSION } from '../config/env';

export function LoginScreen() {
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [referral, setReferral] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const submit = async () => {
    setErr(null);
    setOk(null);
    setBusy(true);
    try {
      if (mode === 'login') {
        await signIn(email.trim(), password);
      } else {
        await signUp(email.trim(), password, name.trim(), referral.trim());
        setOk('Account created. Welcome to WEEXIONIC!');
      }
    } catch (e: any) {
      setErr(e?.message || 'Something went wrong. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  const google = async () => {
    setErr(null);
    try {
      await Linking.openURL(GOOGLE_OAUTH_ENTRY);
    } catch {
      setErr('Could not open Google sign-in. Please try again.');
    }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: C.bg2 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={{ flexGrow: 1, justifyContent: 'center', padding: 24 }} keyboardShouldPersistTaps="handled">
        <View style={{ alignItems: 'center', marginBottom: 26 }}>
          <Logo size={84} />
          <Text style={{ color: C.neon, fontSize: 26, fontWeight: '900', letterSpacing: 7, marginTop: 14 }}>
            WEEXIONIC
          </Text>
          <Text style={{ color: C.dim, fontSize: 10.5, letterSpacing: 3, marginTop: 4 }}>
            QUAD-TREND QUANTITATIVE ENGINE
          </Text>
        </View>

        <Card style={{ padding: 18 }}>
          <View style={{ flexDirection: 'row', backgroundColor: 'rgba(0,0,0,0.4)', borderRadius: 12, marginBottom: 16 }}>
            {(['login', 'signup'] as const).map(m => (
              <TouchableOpacity
                key={m}
                onPress={() => { setMode(m); setErr(null); setOk(null); }}
                style={{
                  flex: 1, paddingVertical: 11, borderRadius: 12,
                  backgroundColor: mode === m ? C.neon2 : 'transparent',
                  alignItems: 'center',
                }}>
                <Text style={{ color: mode === m ? C.bg : C.dim, fontWeight: '800', fontSize: 13, letterSpacing: 0.5 }}>
                  {m === 'login' ? 'Sign In' : 'Create Account'}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          <ErrorNote msg={err} />
          <OkNote msg={ok} />

          {mode === 'signup' && (
            <Field label="NAME" value={name} onChangeText={setName} placeholder="Your name" />
          )}
          <Field label="EMAIL" value={email} onChangeText={setEmail} placeholder="you@example.com" keyboardType="email-address" />
          <Field label="PASSWORD" value={password} onChangeText={setPassword} placeholder="••••••••" secure />
          {mode === 'signup' && (
            <Field label="REFERRAL CODE (OPTIONAL)" value={referral} onChangeText={setReferral} placeholder="FRIEND-CODE" autoCapitalize="characters" />
          )}

          <GoldButton
            title={mode === 'login' ? 'SIGN IN' : 'CREATE ACCOUNT'}
            onPress={submit}
            loading={busy}
            style={{ marginTop: 6 }}
          />

          <View style={{ flexDirection: 'row', alignItems: 'center', marginVertical: 14 }}>
            <View style={{ flex: 1, height: 1, backgroundColor: 'rgba(0,230,118,0.18)' }} />
            <Text style={{ color: C.dim2, marginHorizontal: 10, fontSize: 11, letterSpacing: 2 }}>OR</Text>
            <View style={{ flex: 1, height: 1, backgroundColor: 'rgba(0,230,118,0.18)' }} />
          </View>

          <TouchableOpacity
            onPress={google}
            activeOpacity={0.85}
            style={{
              flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
              backgroundColor: '#FFFFFF', borderRadius: 14, paddingVertical: 13, gap: 10,
            }}>
            <GoogleG />
            <Text style={{ color: '#1F1F1F', fontWeight: '700', fontSize: 14 }}>
              Continue with Google
            </Text>
          </TouchableOpacity>
        </Card>

        <Text style={{ color: C.dim2, fontSize: 10.5, textAlign: 'center', marginTop: 18, lineHeight: 16 }}>
          Trading futures involves substantial risk of loss.{'\n'}
          WEEXIONIC v{APP_VERSION} · Automated trading engine
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function GoogleG() {
  // Simple Google "G" glyph (brand-accurate colors)
  return (
    <View style={{ width: 20, height: 20 }}>
      <Text style={{ fontSize: 17, fontWeight: '900', color: '#4285F4', marginLeft: 1 }}>G</Text>
    </View>
  );
}

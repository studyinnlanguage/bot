// Auth context — session state + login/register/google/logout actions.
import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { AppState, Linking, NativeModules, Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { authApi, type UserSnapshot } from '../api/endpoints';
import { tokenStore } from '../api/client';
import { GOOGLE_OAUTH_ENTRY } from '../config/env';

const OAUTH_MSID_KEY = 'wx_oauth_msid';
const OAUTH_TTL_MS = 3 * 60 * 1000;

function generateMsid(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let rand = '';
  for (let i = 0; i < 24; i++) {
    rand += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return `wxm_${Date.now().toString(36)}_${rand}`;
}

interface AuthState {
  loading: boolean;
  user: UserSnapshot | null;
  oauthPending: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, name: string, referral?: string) => Promise<void>;
  startGoogleOAuth: () => Promise<void>;
  cancelGoogleOAuth: () => void;
  applyTokens: (access: string, refresh: string) => Promise<void>;
  refreshUser: () => Promise<void>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<AuthState>(null as any);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<UserSnapshot | null>(null);
  const [oauthPending, setOauthPending] = useState(false);

  const userRef = useRef<UserSnapshot | null>(null);
  userRef.current = user;
  const msidRef = useRef<{ msid: string; startedAt: number } | null>(null);
  const pollBusyRef = useRef(false);

  const clearPendingOauth = useCallback(async () => {
    msidRef.current = null;
    setOauthPending(false);
    try {
      await AsyncStorage.removeItem(OAUTH_MSID_KEY);
    } catch {}
  }, []);

  const checkPendingOauth = useCallback(async () => {
    if (userRef.current || pollBusyRef.current) return;
    let active = msidRef.current;
    if (!active) {
      try {
        const raw = await AsyncStorage.getItem(OAUTH_MSID_KEY);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (parsed?.msid && parsed?.startedAt) {
            active = parsed;
            msidRef.current = parsed;
          }
        }
      } catch {}
    }
    if (!active) return;
    if (Date.now() - active.startedAt > OAUTH_TTL_MS) {
      await clearPendingOauth();
      return;
    }

    pollBusyRef.current = true;
    try {
      const res = await authApi.pollOauth(active.msid);
      if (res.ready && res.access_token && res.refresh_token && res.user) {
        await clearPendingOauth();
        await tokenStore.save(res.access_token, res.refresh_token);
        userRef.current = res.user;
        setUser(res.user);
      } else if (res.expired || res.already_consumed) {
        await clearPendingOauth();
      }
    } catch {
      // Transient network error or expired session — keep polling until TTL
    } finally {
      pollBusyRef.current = false;
    }
  }, [clearPendingOauth]);

  const load = async () => {
    try {
      const token = await tokenStore.access();
      if (token) {
        const me = await authApi.me();
        userRef.current = me.user;
        setUser(me.user);
      } else {
        // Cold-start recovery: if Android killed the app while Chrome was open
        // for Google OAuth, check AsyncStorage for an in-flight msid immediately!
        await checkPendingOauth();
      }
    } catch {
      await tokenStore.clear();
      userRef.current = null;
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const handleIncomingUrl = async (url: string | null) => {
    if (!url || userRef.current) return;
    try {
      // Support both weexionic://oauth?... and https://weexionic.duckdns.org/app/oauth?...
      const isOauthScheme = url.startsWith('weexionic://') || url.includes('/app/oauth') || url.includes('oauth');
      if (!isOauthScheme) return;

      const qIndex = url.indexOf('?');
      if (qIndex === -1) return;
      const queryStr = url.substring(qIndex + 1).split('#')[0];
      const params: Record<string, string> = {};
      queryStr.split('&').forEach(part => {
        const eqIdx = part.indexOf('=');
        if (eqIdx > 0) {
          const k = part.substring(0, eqIdx);
          const v = part.substring(eqIdx + 1);
          params[decodeURIComponent(k)] = decodeURIComponent(v);
        }
      });

      if (params.code) {
        setLoading(true);
        pollBusyRef.current = true;
        const res = await authApi.exchangeCode(params.code);
        if (res.access_token && res.refresh_token) {
          await clearPendingOauth();
          await tokenStore.save(res.access_token, res.refresh_token);
          userRef.current = res.user;
          setUser(res.user);
        }
      } else if (params.token && params.refresh_token) {
        await clearPendingOauth();
        await applyTokens(params.token, params.refresh_token);
      }
    } catch (e) {
      // Deep link code may have already been consumed by msid polling — verify
      pollBusyRef.current = false;
      await checkPendingOauth();
      console.warn('OAuth deep link handling note:', e);
    } finally {
      pollBusyRef.current = false;
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // Google OAuth round-trip via single-use auth code or token
    const sub = Linking.addEventListener('url', ({ url }) => {
      handleIncomingUrl(url);
    });
    Linking.getInitialURL().then(url => {
      handleIncomingUrl(url);
    });
    // Whenever user manually switches back from browser to app, poll immediately!
    const appSub = AppState.addEventListener('change', nextState => {
      if (nextState === 'active') {
        checkPendingOauth();
      }
    });
    return () => {
      sub.remove();
      appSub.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!oauthPending || user) return;
    const timer = setInterval(() => {
      checkPendingOauth();
    }, 1500);
    return () => clearInterval(timer);
  }, [oauthPending, user, checkPendingOauth]);

  const applyTokens = async (access: string, refresh: string) => {
    await tokenStore.save(access, refresh);
    const me = await authApi.me();
    userRef.current = me.user;
    setUser(me.user);
  };

  const startGoogleOAuth = useCallback(async () => {
    const msid = generateMsid();
    const record = { msid, startedAt: Date.now() };
    msidRef.current = record;
    setOauthPending(true);
    try {
      await AsyncStorage.setItem(OAUTH_MSID_KEY, JSON.stringify(record));
    } catch {}
    const sep = GOOGLE_OAUTH_ENTRY.includes('?') ? '&' : '?';
    const targetUrl = `${GOOGLE_OAUTH_ENTRY}${sep}msid=${encodeURIComponent(msid)}`;
    if (Platform.OS === 'android' && NativeModules.OAuthCustomTab?.open) {
      await NativeModules.OAuthCustomTab.open(targetUrl);
    } else {
      await Linking.openURL(targetUrl);
    }
  }, []);

  const cancelGoogleOAuth = useCallback(() => {
    clearPendingOauth();
  }, [clearPendingOauth]);

  const value = useMemo<AuthState>(
    () => ({
      loading,
      user,
      oauthPending,
      signIn: async (email, password) => {
        await clearPendingOauth();
        const res = await authApi.login(email, password);
        await tokenStore.save(res.access_token, res.refresh_token);
        userRef.current = res.user;
        setUser(res.user);
      },
      signUp: async (email, password, name, referral) => {
        await clearPendingOauth();
        const res = await authApi.register(email, password, name, referral);
        await tokenStore.save(res.access_token, res.refresh_token);
        userRef.current = res.user;
        setUser(res.user);
      },
      startGoogleOAuth,
      cancelGoogleOAuth,
      applyTokens,
      refreshUser: async () => {
        try {
          const me = await authApi.me();
          userRef.current = me.user;
          setUser(me.user);
        } catch {}
      },
      signOut: async () => {
        await clearPendingOauth();
        try {
          const rt = await tokenStore.refresh();
          if (rt) await authApi.logout(rt);
        } catch {}
        await tokenStore.clear();
        userRef.current = null;
        setUser(null);
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [loading, user, oauthPending, startGoogleOAuth, cancelGoogleOAuth],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);

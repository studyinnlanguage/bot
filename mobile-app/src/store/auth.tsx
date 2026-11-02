// Auth context — session state + login/register/google/logout actions.
import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { Linking } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { authApi, type UserSnapshot } from '../api/endpoints';
import { tokenStore } from '../api/client';
import { DEEP_LINK_OAUTH } from '../config/env';

interface AuthState {
  loading: boolean;
  user: UserSnapshot | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, name: string, referral?: string) => Promise<void>;
  applyTokens: (access: string, refresh: string) => Promise<void>;
  refreshUser: () => Promise<void>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<AuthState>(null as any);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<UserSnapshot | null>(null);

  const load = async () => {
    try {
      const token = await tokenStore.access();
      if (token) {
        const me = await authApi.me();
        setUser(me.user);
      }
    } catch {
      await tokenStore.clear();
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const handleIncomingUrl = async (url: string | null) => {
    if (!url) return;
    try {
      // Support both weexionic://oauth?... and https://weexionic.duckdns.org/app/oauth?...
      const isOauthScheme = url.startsWith('weexionic://') || url.includes('/app/oauth') || url.includes('oauth');
      if (!isOauthScheme) return;

      const qIndex = url.indexOf('?');
      if (qIndex === -1) return;
      const queryStr = url.substring(qIndex + 1);
      const params: Record<string, string> = {};
      queryStr.split('&').forEach(part => {
        const [k, v] = part.split('=');
        if (k && v !== undefined) {
          params[decodeURIComponent(k)] = decodeURIComponent(v);
        }
      });

      if (params.code) {
        setLoading(true);
        const res = await authApi.exchangeCode(params.code);
        if (res.access_token && res.refresh_token) {
          await tokenStore.save(res.access_token, res.refresh_token);
          setUser(res.user);
        }
      } else if (params.token && params.refresh_token) {
        await applyTokens(params.token, params.refresh_token);
      }
    } catch (e) {
      console.warn('OAuth deep link handling failed:', e);
    } finally {
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
    return () => sub.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyTokens = async (access: string, refresh: string) => {
    await tokenStore.save(access, refresh);
    const me = await authApi.me();
    setUser(me.user);
  };

  const value = useMemo<AuthState>(
    () => ({
      loading,
      user,
      signIn: async (email, password) => {
        const res = await authApi.login(email, password);
        await tokenStore.save(res.access_token, res.refresh_token);
        setUser(res.user);
      },
      signUp: async (email, password, name, referral) => {
        const res = await authApi.register(email, password, name, referral);
        await tokenStore.save(res.access_token, res.refresh_token);
        setUser(res.user);
      },
      applyTokens,
      refreshUser: async () => {
        try {
          const me = await authApi.me();
          setUser(me.user);
        } catch {}
      },
      signOut: async () => {
        try {
          const rt = await tokenStore.refresh();
          if (rt) await authApi.logout(rt);
        } catch {}
        await tokenStore.clear();
        setUser(null);
      },
    }),
    [loading, user],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);

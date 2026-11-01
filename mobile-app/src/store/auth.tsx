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

  useEffect(() => {
    load();
    // Google OAuth deep-link round-trip: weexionic://oauth?token=..&refresh_token=..
    const sub = Linking.addEventListener('url', ({ url }) => {
      if (url.startsWith(DEEP_LINK_OAUTH)) {
        try {
          const q = Object.fromEntries(
            url
              .replace(DEEP_LINK_OAUTH + '://oauth?', '')
              .split('&')
              .map(kv => kv.split('=').map(decodeURIComponent) as [string, string]),
          );
          if (q.token && q.refresh_token) {
            applyTokens(q.token, q.refresh_token);
          }
        } catch {
          /* ignore malformed deep links */
        }
      }
    });
    Linking.getInitialURL().then(url => {
      if (url && url.startsWith(DEEP_LINK_OAUTH)) {
        // cold-start deep link — same parsing
        try {
          const q = Object.fromEntries(
            url
              .replace(DEEP_LINK_OAUTH + '://oauth?', '')
              .split('&')
              .map(kv => kv.split('=').map(decodeURIComponent) as [string, string]),
          );
          if (q.token && q.refresh_token) applyTokens(q.token, q.refresh_token);
        } catch {}
      }
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

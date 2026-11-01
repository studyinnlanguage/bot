// WEEXIONIC API client — JWT bearer auth with transparent refresh.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { API_BASE_URL } from '../config/env';

const ACCESS_KEY = 'wx_access';
const REFRESH_KEY = 'wx_refresh';

export const tokenStore = {
  async save(access: string, refresh: string) {
    await AsyncStorage.multiSet([[ACCESS_KEY, access], [REFRESH_KEY, refresh]]);
  },
  async access() {
    return (await AsyncStorage.getItem(ACCESS_KEY)) || '';
  },
  async refresh() {
    return (await AsyncStorage.getItem(REFRESH_KEY)) || '';
  },
  async clear() {
    await AsyncStorage.multiRemove([ACCESS_KEY, REFRESH_KEY]);
  },
};

export class ApiError extends Error {
  status: number;
  body: any;
  constructor(status: number, body: any) {
    super((body && (body.error || body.message)) || `HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    const rt = await tokenStore.refresh();
    if (!rt) return false;
    try {
      const res = await fetch(`${API_BASE_URL}/api/mobile/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      if (!data?.access_token) return false;
      await tokenStore.save(data.access_token, data.refresh_token || rt);
      return true;
    } catch {
      return false;
    } finally {
      setTimeout(() => (refreshing = null), 0);
    }
  })();
  return refreshing;
}

async function rawRequest(method: string, path: string, body?: any, isForm?: FormData): Promise<any> {
  const token = await tokenStore.access();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: any;
  if (isForm) {
    payload = isForm;
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: payload,
  });
  let data: any = {};
  try {
    data = await res.json();
  } catch {
    /* empty body */
  }
  if (res.status === 401 && !path.includes('/auth/')) {
    // access token expired → refresh once and retry
    if (await tryRefresh()) {
      return rawRequest(method, path, body, isForm);
    }
    throw new ApiError(401, { error: 'Session expired' });
  }
  if (!res.ok) {
    throw new ApiError(res.status, data);
  }
  return data;
}

export const api = {
  get: (path: string) => rawRequest('GET', path),
  post: (path: string, body?: any) => rawRequest('POST', path, body),
  form: (path: string, form: FormData) => rawRequest('POST', path, undefined, form),
};

// Typed endpoint helpers — the entire mobile↔backend contract (docs/AUDIT.md §3).
import { api } from './client';

export interface Subscription {
  plan: string;
  status: string;
  expires_at: string | null;
  days_left?: number;
  active: boolean;
}

export interface UserSnapshot {
  id: string;
  email: string;
  name: string;
  role: string;
  created_at?: string;
  subscription: Subscription;
  license_key: string | null;
  bot_config: {
    exchange: string;
    testnet: boolean;
    has_api_key: boolean;
    has_api_secret: boolean;
    has_passphrase: boolean;
  };
}

export interface AuthResponse {
  success: boolean;
  user: UserSnapshot;
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export const authApi = {
  register: (email: string, password: string, name: string, referralCode?: string) =>
    api.post('/api/mobile/auth/register', {
      email, password, name, referral_code: referralCode || undefined,
    }) as Promise<AuthResponse>,
  login: (email: string, password: string) =>
    api.post('/api/mobile/auth/login', { email, password }) as Promise<AuthResponse>,
  googleExchange: (idToken: string) =>
    api.post('/api/mobile/auth/google', { id_token: idToken }) as Promise<AuthResponse>,
  exchangeCode: (code: string) =>
    api.post('/api/mobile/auth/exchange-code', { code }) as Promise<AuthResponse>,
  pollOauth: (msid: string) =>
    api.post('/api/mobile/auth/poll-oauth', { msid }) as Promise<{
      success: boolean;
      ready: boolean;
      expired?: boolean;
      already_consumed?: boolean;
      user?: UserSnapshot;
      access_token?: string;
      refresh_token?: string;
    }>,
  logout: (refreshToken: string) =>
    api.post('/api/mobile/auth/logout', { refresh_token: refreshToken }),
  me: () => api.get('/api/mobile/auth/me') as Promise<{ success: boolean; user: UserSnapshot; bot_running: boolean }>,
};

export const botApi = {
  status: () => api.get('/api/mobile/bot/status') as Promise<any>,
  start: () => api.post('/api/mobile/bot/start') as Promise<any>,
  stop: () => api.post('/api/mobile/bot/stop') as Promise<any>,
  forceStop: () => api.post('/api/mobile/bot/force_stop') as Promise<any>,
  config: () => api.get('/api/mobile/bot/config') as Promise<any>,
  saveConfig: (patch: Record<string, any>) => api.post('/api/mobile/bot/config', patch) as Promise<any>,
  positions: (symbol?: string) =>
    api.get(`/api/mobile/bot/positions${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ''}`) as Promise<any>,
  trades: (limit = 100, symbol?: string) =>
    api.get(`/api/mobile/bot/trades?limit=${limit}${symbol ? `&symbol=${encodeURIComponent(symbol)}` : ''}`) as Promise<any>,
  clearTrades: () => api.post('/api/mobile/bot/trades/clear') as Promise<any>,
  close: (symbol?: string) => api.post('/api/mobile/bot/close', symbol ? { symbol } : {}) as Promise<any>,
  closeAll: () => api.post('/api/mobile/bot/close_all', {}) as Promise<any>,
  symbols: () => api.get('/api/mobile/bot/symbols') as Promise<any>,
  balance: () => api.get('/api/mobile/bot/balance') as Promise<any>,
  price: (symbol: string) => api.get(`/api/mobile/bot/price?symbol=${encodeURIComponent(symbol)}`) as Promise<any>,
  testChart: (symbol: string) => api.get(`/api/mobile/bot/test_chart?symbol=${encodeURIComponent(symbol)}`) as Promise<any>,
  leverage: (leverage: number, symbol?: string) =>
    api.post('/api/mobile/bot/leverage', { leverage, symbol }) as Promise<any>,
  activeSymbol: (symbol: string) => api.post('/api/mobile/bot/active_symbol', { symbol }) as Promise<any>,
  testConnection: (override?: Record<string, any>) =>
    api.post('/api/mobile/bot/test_connection', override || {}) as Promise<any>,
  testNotification: () => api.post('/api/mobile/bot/test_notification', {}) as Promise<any>,
};

export const accountApi = {
  packages: () => api.get('/api/mobile/packages') as Promise<any>,
  orders: () => api.get('/api/mobile/orders/my') as Promise<any>,
  createOrder: (packageId: string) =>
    api.post('/api/mobile/orders/create', { package_id: packageId }) as Promise<any>,
  submitOrder: (orderId: string, txHash: string, screenshot?: any) => {
    const form = new FormData();
    form.append('order_id', orderId);
    form.append('tx_hash', txHash);
    if (screenshot) {
      // @ts-ignore RN FormData file shape
      form.append('screenshot', {
        uri: screenshot.uri,
        name: screenshot.fileName || 'proof.jpg',
        type: screenshot.type || 'image/jpeg',
      });
    }
    return api.form('/api/mobile/orders/submit', form) as Promise<any>;
  },
  checkVerification: (orderId: string) =>
    api.post(`/api/mobile/orders/check-verification/${orderId}`) as Promise<any>,
  referral: () => api.get('/api/mobile/user/referral') as Promise<any>,
  savePayoutWallet: (wallet: string) =>
    api.post('/api/mobile/user/payout-wallet', { wallet_address: wallet }) as Promise<any>,
  requestPayout: (wallet?: string) =>
    api.post('/api/mobile/user/request-payout', wallet ? { wallet_address: wallet } : {}) as Promise<any>,
};

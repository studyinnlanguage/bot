// WEEXIONIC environment configuration.
// Production API base URL is BAKED INTO RELEASE BUILDS — users never see or
// enter any server address (see docs/ARCHITECTURE.md §2).
declare const __DEV__: boolean;

const PROD_API_URL = 'https://weexionic.duckdns.org';
// Dev builds may override via env baked at bundle time (optional):
const DEV_API_URL: string | undefined =
  typeof process !== 'undefined' && (process as any).env?.WEEXIONIC_DEV_URL;

export const API_BASE_URL: string = __DEV__ && DEV_API_URL ? DEV_API_URL : PROD_API_URL;

export const DEEP_LINK_OAUTH = 'weexionic://oauth';
export const GOOGLE_OAUTH_ENTRY = `${API_BASE_URL}/auth/google?client=mobile`;

export const APP_VERSION = '2.1.0';

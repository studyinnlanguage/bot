# Weexionic Android App — v3.0.0 (FULLY NATIVE)

Binance-jaisi **asli native app** — NO WebView, NO website copy. App aur web bilkul alag.

**Download APK:** [apk/Weexionic-App.apk](../apk/Weexionic-App.apk)

## Screens (100% native, code-se render)
- **Home** — USDT balance, RUNNING/STOPPED, trades today, START/STOP
- **Markets** — active coins + native sparklines + live change %
- **Chart** — native candlestick chart (Canvas-drawn) + 4 EMA overlays + Quad-Trend signal
- **Trades** — open positions (PnL/ROE live) + trade history
- **Account** — profile, subscription, logout

## Tech
- Package: com.weexionic.app • versionCode 3 • minSdk 24 • target 34
- Zero third-party libraries — pure android.framework + org.json + Canvas
- Space Grotesk fonts bundled (assets/)
- APIs: /api/auth/login, /api/auth/me, /api/bot/status, /api/bot/proxy (snapshot/trades), /api/bot/start|stop
- Session: 3-strike reconnect (no login loops), cookie auto-refresh

## Build
```bash
scripts/apk_build_v3.sh   # aapt2 -> ECJ -> d8 -> zipalign -> apksigner
```
Requires: build-tools r34, platform-34, ECJ 3.36, JRE 21.

## Keystore (updates ke liye sambhal kar rakhna!)
- File: keystore/weexionic.jks (private — repo mein NAHI hai)
- Alias: weexionic • Store/Key pass: weexionic2026
- Naya APK sign karne ke liye yehi keystore use hota hai

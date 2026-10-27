# Weexionic Android App — v3.7.0 (FULLY NATIVE)

Binance-jaisi **asli native app** — NO WebView, NO website copy. App aur web bilkul alag.
**v3.7.0 = WEE-XIONIC concept-exact UI/UX refresh (UI-only — engine/strategy untouched).**

**Download APK:** [apk/Weexionic-App.apk](../apk/Weexionic-App.apk)

## Screens (100% native, code-se render)
- **Home** — TOTAL EQUITY · USDT hero card + open-PnL pill (real, from open positions),
  Max Leverage / Trades Today / Open PnL stat row, 4 shortcut tiles
  (Terminal / Positions / History / Alerts), Active Bots list with coin dots +
  RUNNING/STANDBY/BUY/SELL pills, gold engine control card
- **Markets** — Binance-style list (coin dot + WHITE last price + colored 24h %),
  column headers, always-live prices: server tickers → **direct Binance public
  fallback → WEEX public fallback** (display-only, engine untouched)
- **Trade** — symbol chips + PERP badge, price header, native candlestick chart
  (Canvas-drawn) + 4 EMA overlays (gold/red/blue/purple), Quad-Trend signal,
  MANUAL OVERRIDE card (real /api/bot/config), POSITIONS/SIGNALS/HISTORY
- **Wallet & Rewards** — gold balance card, shareable link + inline Copy,
  WhatsApp/Telegram, commission structure
- **Profile** — profile, subscription, Bot Settings, logout

## v3.7.0 UI/UX changes (concept-exact)
- WEE-XIONIC palette: near-pure black canvas `#060606`, warm dark cards, bright
  yellow `#F5C518`, Binance green `#2EBD85` / red `#F6465D`
- Top bar: gold **W** badge + "Weexionic / CRYPTO FUTURES TRACKER" + live status pill
- Home hero: equity pill (live open PnL), 3-stat divider row, shortcut tiles
- Login: concept stats footer (3 Exchanges · 24/7 Multicoin · 1:1 Risk Lock)
- Wallet: link + inline gold Copy (concept layout)
- Chart: concept EMA colors + warm grid
- Markets: 100% English + Binance column headers (fixed leftover Urdu subtitle)
- Markets data resilience: direct public price fallback when the server build
  is old (404 on /api/market/tickers) or briefly down

## Tech
- Package: com.weexionic.app • versionCode 10 • minSdk 24 • target 34
- Zero third-party libraries — pure android.framework + org.json + Canvas
- Space Grotesk fonts bundled (assets/)
- APIs: /api/auth/login, /api/auth/me, /api/bot/status, /api/bot/config (GET/POST),
  /api/bot/proxy (snapshot/trades/logs/close), /api/market/tickers,
  /api/user/referral, /api/bot/start|stop
- Session: 3-strike reconnect (no login loops), cookie auto-refresh

## Build
```bash
scripts/apk_build_v3.sh   # aapt2 -> ECJ -> d8 -> zipalign -> apksigner
```
Requires: build-tools r34, platform-34, ECJ 3.36, JRE 21.

## Keystore (updates ke liye sambhal kar rakhna!)
- File: keystore/weexionic.jks (private — repo mein NAHI hai)
- Alias: weexionic • Store/Key pass: weexionic2026
- Naya APK sign karne ke liye yehi ORIGINAL keystore use hota hai
- ⚠️ v3.7.0 APK ek nayi (auto-generated) key se signed hai kyunki original
  keystore private hai — purane install ke UPAR update karne ke liye apne
  original keystore se rebuild karo, warna uninstall/reinstall hoga

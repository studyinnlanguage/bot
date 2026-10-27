# Weexionic Android App v3.3.0

**Download:** [Weexionic-App.apk](apk/Weexionic-App.apk) — file par tap karein → "Download raw" se save karein (~4.1 MB).

## v3.3.0 — "START dabao lekin kuch nahi hota" FIXED + Concept Design
- **Bot Settings ab app ke andar** — Account tab → "Bot Settings": exchange (WEEX/Binance), API keys, coins, timeframe, leverage, order size, stop-loss, TP mode, direction — web jaisa poora control. Save ke baad START dabao, bot inhi settings se chalega
- **START ab real mein start karta hai** — bina API keys/coins ke START dabao to app clearly batata hai kya missing hai aur seedha Bot Settings khol deta hai (pehle chupchap kuch nahi hota tha)
- **RUNNING badge ab sach bolta hai** — pehle engine process idle pada ho tab bhi "RUNNING" dikhta tha. Ab RUNNING ka matlab hai bot sach mein trade kar raha hai
- **Naya diagnostics card** — agar exchange se connect nahi ho raha ya koi coin live nahi to Home pe clearly warning aati hai (ghayab nahi hota)
- **Concept design** — aurora hero card (gold glow + artwork), gold-gradient CTA, mono balance, hero sparkline, premium cards. Concept mockup jaisa look
- **Home pe live sparkline** — active coin ka price trend hero card ke andar

## v3.2.0 (included)
- Remember Me silent auto-relogin + Google in-app login (OAuth bridge — server update zaroori)
- Server baar baar nahi mangay ga

## v3.0/v3.1 core (included)
- 100% NATIVE — zero WebView; 5 native tabs: Home / Markets / Chart / Trades / Account
- Space Grotesk + JetBrains Mono fonts, sound pack, hi-res dark-gold artwork (3.9MB pack)

## Install (IMPORTANT)
1. Purani Weexionic app UNINSTALL karein (nayi signing key — bina uninstall install nahi hogi)
2. APK tap karein → "Install unknown apps" allow karein
3. Login karo → Account tab → **Bot Settings** → exchange + API keys + coins save karo
4. Home pe **START BOT** dabao — bot real mein chalega, chart/markets/trades live aayenge

## Server update
App v3.3.0 ke naye features ke liye server ka naya code zaroori hai:
```bash
cd /path/to/bot   # jahan app.py chalta hai
git pull
# phir server restart (jaise pehle chalate ho)
```
Ye update `/api/bot/status` mein `config_summary` add karta hai (honest state) — bot engine/strategy bilkul untouched.

## Tech
- Package: com.weexionic.app — versionCode 6, versionName 3.3.0
- minSdk 24 (Android 7.0) / targetSdk 34 (Android 14)
- Naya: SettingsActivity (/api/bot/config GET/POST), config_summary diagnostics, aurora design system
- Deep link: weexionic://oauth (Google login bridge, v3.2 se)
- Source: `android-app/` folder

# Weexionic Android App v3.6.0

**Download:** [Weexionic-App.apk](apk/Weexionic-App.apk) — file par tap karein → "Download raw" se save karein (~4.6 MB).

## v3.6.0 — PURA APP DIAGNOSE + 5 BARE MASLE FIX
- **Bot ab sahi se STOP hota hai (root cause fix)** — asli wajah mil gayi thi: server ka watchdog (auto-restart monitor) ghalat purani memory se stopped bot ko har 30 second baad DOBARA ZINDA kar deta tha. Ab watchdog hamesha shared process file (single source of truth) se parhta hai + STOP ke foran baad respawn double-check karta hai. STOP ka matlab ab STOP hai.
- **STOP aur START dono ab VERIFY hote hain** — STOP dabane ke baad app khud 3 dafa check karta hai ke engine waqai band hua ya nahi; agar na ho to saaf message milta hai (chupchap fail hona khatam). START pe bhi pehle jaisa honest confirmation hai.
- **"111" jaise ajeeb errors ka ilaaj: REMOTE ERROR REPORTING (naya)** — ab app ke andar koi bhi error/crash ho to app uski poori detail (HTTP code + server ka asli jawab + crash trace) server ke logs mein bhej deti hai. Iska matlab: aap jo bhi error dekhein, agli baar mujhe uski EXACT wajah server log se mil jayegi — andhere mein teer chalana khatam.
- **Config (Bot Settings) crash fix** — Settings screen ab poori tarah crash-proof hai: har cheez guard mein hai, kabhi app close nahi hogi. Aur agar kabhi masla ho to crash ka poora trace server log mein aayega (upar wali feature se).
- **Market ab hamesha data dikhata hai (naya)** — Markets tab ke liye naya server route `/api/market/tickers`: bot BAND ho to bhi, engine mein coins na hon to bhi, tab bhi LIVE public prices aati hain (Binance → WEEX fallback). "Market mein kuch nahi hai" wala masla khatam.
- **Coins add karna asaan** — agar aapke bot mein koi coin set nahi hai to Home screen seedha gold **"ADD COINS IN BOT SETTINGS"** button dikhata hai (ek tap → settings). Warning card bhi ab tap karne par settings kholti hai.
- **HTTP 403 ka poora explanation** — 403 ab sirf number nahi: app batati hai ke plan inactive/expired hai (kitne din bache, konsa plan) aur kahan se activate karna hai. Agar exchange ne server ki region block ki hai (403 restricted) to warn card CLEAR fix guide deta hai (Bot Settings → Exchange → WEEX).
- **NAYA LOGO — sirf Login screen par** — aapka diya hua naya circular badge (green arrow W) ab SIRF login screen par hai. Splash screen ab sirf wordmark, app ke topbar se logo hat ke jagah status ke liye use hoti hai, launcher icon bhi naye logo se update.
- **Web app mobile bug fix** — home page hero mobile par text/button kaat raha tha (grid blowout bug) — fix ho gaya, ab poora text aur buttons sahi dikhte hain. Web login + favicon par bhi naya logo.
- **App v3.6.0 (versionCode 9)** — same signing key, purani app ke UPAR seedha install hoga (uninstall ki zaroorat nahi).

## v3.5.0 (included) — SIGNALS tab (live engine feed) + real error surfacing
## v3.4.0 (included) — server field KHATAM + 100% English UI + concept tabs
## v3.3.0 (included) — Bot Settings in-app + honest RUNNING badge
## v3.2.0 (included) — Remember Me + Google login
## v3.0/v3.1 core (included) — 100% NATIVE, zero WebView, fonts/sounds/art pack

## Install (IMPORTANT)
1. Purani Weexionic app UNINSTALL karein
2. Upar link se naya APK download karein (raw download)
3. Install karein ("Unknown sources" allow karein agar poochhe)
4. Login karein — server ka address pehle se app mein set hai, kuch poocha nahi jayega

## Server update (VPS par zaroori — naye fixes ke liye)
```bash
cd /path/to/bot
git pull
# phir service restart:
sudo systemctl restart weexionic   # ya jo aapka restart command hai
```

## Notes
- Package: `com.weexionic.app` • versionCode 9 • versionName 3.6.0 • minSdk 24 • target 34
- Signing certificate SHA-256: `1866c81275f61e5c...` (v3.x series ke saath same — upgrade-safe)
- Strategy engine (`bot-engine/bot/strategy.py`) is build mein BILKUL touch nahi hua

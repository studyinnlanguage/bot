# Weexionic Android App v3.2.0

**Download:** [Weexionic-App.apk](apk/Weexionic-App.apk) — file par tap karein → "Download raw" se save karein (~3.9 MB).

## v3.2.0 — Login problems FIXED
- **Remember Me (default ON)** — email+password ek dafa dalo, phir KABHI dobara nahi mangay. Session expire bhi ho jaye to app khud background mein chupchap re-login kar leta hai
- **Google login app ke andar** — "Continue with Google" button: Google page ek dafa browser mein khulta hai, account choose karo, app KHUD wapas khul jati hai (koi typing nahi)
- **Server baar baar nahi mangay ga** — fresh install par sirf ek dafa (app ka data install ke sath clear hota hai), uske baad hamesha yaad rehta hai
- Google-account wale users ka password server pe hota hi nahi — ab app clearly batata hai aur Google button guide karta hai

## v3.1.0 (included)
- 3.9 MB premium pack: Space Grotesk + JetBrains Mono fonts, sound pack, hi-res dark-gold artwork
- Mono numerals (Binance style) + audio feedback

## v3.0.0 core (included)
- 100% NATIVE — zero WebView, browser sirf Google login ke liye ek dafa khulta hai
- 5 native tabs: Home / Markets / Chart / Trades / Account
- App aur web bilkul alag: app ka apna UI, server sirf data deta hai

## Install (IMPORTANT)
1. Purani Weexionic app UNINSTALL karein (v3.2 ki signing key nayi hai — bina uninstall ke install nahi hogi)
2. APK tap karein → "Install unknown apps" allow karein
3. Login: Remember me ON rakho → ek dafa login → hamesha seedha data

## GOOGLE LOGIN KE LIYE SERVER UPDATE ZAROORI
App ka Google button tab tak kaam nahi karega jab tak server pe naya code pull nahi hota:
```bash
cd /path/to/bot   # jahan app.py chalta hai
git pull
# phir server restart (jaise pehle chalate ho)
```
Ye update sirf 2 cheezein add karta hai: `/auth/google?app=1` handoff + `/api/auth/exchange` endpoint. Email/password login purani server pe bhi chalta rahega.

## Tech
- Package: com.weexionic.app — versionCode 5, versionName 3.2.0
- minSdk 24 (Android 7.0) / targetSdk 34 (Android 14)
- Deep link: weexionic://oauth?token=… (one-time exchange token, 180s TTL)
- Source: `android-app/` folder

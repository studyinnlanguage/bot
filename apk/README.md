# Weexionic Android App v3.5.0

**Download:** [Weexionic-App.apk](apk/Weexionic-App.apk) — file par tap karein → "Download raw" se save karein (~4.1 MB).

## v3.5.0 — FULL BOT ON APP + "API error" ka ASLI SABAB ab app pe nazar aata hai
- **SIGNALS TAB (naya)** — Trade tab mein ab 3 sections: **POSITIONS / SIGNALS / HISTORY**. Signals tab engine ka LIVE feed hai — har signal (EMA crossover BUY/SELL), har trade entry/exit, aur har error bilkul waise jaise web dashboard ke Activity Logs mein dikhte hain. Ab app pe bhi web jaisa poora bot nazara hai
- **"API error" mystery solved** — wo message jo aap dekh rahe the wo ENGINE ka diagnostics message hai ("Klines fetch fail … Chart empty - API error") jo pehle SIRF web pe dikhta tha. Ab app ke SIGNALS tab + Home warn card mein ASLI WAJAH ke saath dikhta hai (konsa coin, kya error, kab)
- **Balance error ka asli reason** — balance load na ho to ab app server ka exact error dikhata hai (invalid API keys / IP restriction / engine booting), khali $0.00 nahi
- **License expired? App foran batayega** — agar plan inactive/expired hai to Home pe gold warn banner + START pe clear dialog ("License Required — activate on weexionic.duckdns.org Packages page"). Pehle ye chhupa hua 403 error tha
- **Server hardening (git pull zaroori)** — login exchange errors ab 100% English + broken body par HTML 400 ki jagah clean JSON (app ka parser kabhi fail nahi hoga)
- **Web dashboard 100% English** — engine ke 27 log/alert messages Roman Urdu se English kiye gaye (Close confirmations, Start/Stop, Force Reset, coin loading, Binance leverage rule …)
- **App ke Settings screen ke baqi 4 strings bhi English** (testnet note, keys note, save note, WEEX passphrase hint)

## v3.4.0 (included) — server field KHATAM + 100% English UI + concept tabs
## v3.3.0 (included) — Bot Settings in-app + honest RUNNING badge
## v3.2.0 (included) — Remember Me + Google login
## v3.0/v3.1 core (included) — 100% NATIVE, zero WebView, fonts/sounds/art pack

## Install (IMPORTANT)
1. Purani Weexionic app UNINSTALL karein
2. APK tap karein → "Install unknown apps" allow karein
3. Login karo (Google ya email) — server kabhi nahi poochta
4. **SERVER UPDATE ZAROORI (naye features ke liye):** VPS par `git pull` karke app restart karein — bina iske Signals tab web ke purane code par khaali aayega
5. Profile → **Bot Settings** → exchange + API keys + coins save karo
6. **START** dabao → Trade tab → **SIGNALS** kholo — engine ka poora live feed, positions, history sab app pe

## Notes
- Data na aaye to: Home ka warn card ASLI WAJAH batayega (license / API keys / coins) — Signals tab mein engine ka exact error hoga
- Wallet ka payout request website se hota hai — app mein balance + link + share sab available hai
- Crash kabhi ho to `crash_last.txt` app ki private storage mein hoti hai

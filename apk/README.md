# Weexionic Android App v3.4.0

**Download:** [Weexionic-App.apk](apk/Weexionic-App.apk) — file par tap karein → "Download raw" se save karein (~4.1 MB).

## v3.4.0 — "SERVER kyn mang raha hai" KHATAM + 100% ENGLISH + Concept Design (Web + Mobile dono)
- **SERVER SETTINGS hamesha ke liye gaya** — login screen par ab server ka koi field NAHI hai. Server address app ke andar baked hai. Binance ki tarah: install karo, login karo, bas. (Jis wajah se "Weexionic has stopped" crash bhi fix kar diya gaya hai — global crash guard + error logging laga di hai)
- **App 100% ENGLISH** — ek bhi Roman Urdu/Hindi string nahi bachi. Login, Home, Markets, Trade, Wallet, Profile, Settings, dialogs, toasts — sab English
- **Concept design — bilkul mockup jaisa**:
  - Login: "Log in. Let the bot do the watching." + gold CTA + Google + trust rows (Funds stay on your exchange / Strict 1:1 risk locks / Instant alerts)
  - Bottom nav ab concept ke 5 tabs: **Home / Markets / TRADE (center gold button) / Wallet / Profile**
  - **Trade tab (naya)**: symbol chips + candlestick chart + EMA 8/13/21/55 legend + Quad-Trend Signal + Quick Controls (Order Size / Leverage / Stop Loss / Direction LONG-BOTH-SHORT) + **Apply & Save** — ye REAL hai, /api/bot/config mein save hota hai (TP engine ka 1:1 rule khud set karta hai)
  - **Open Positions ke saath CLOSE button** — koi bhi position market par turant band karo (real /api/close)
  - **Wallet tab (naya, concept Wallet & Rewards)**: AVAILABLE BALANCE, shareable link + Copy, WhatsApp/Telegram share, commission structure (+$10 / +$50), Friends invited, Total earned — sab REAL referral API se
  - **Home**: aurora hero + TOTAL EQUITY + **Active Coins list (live BUY/SELL/HOLD signals)** + START/STOP
- **START verification** — START ke baad app engine ka ASLI trading state check karta hai (5s tak) aur honestly batata hai: "Bot is RUNNING — watching N coins". Chupchap fake kuch nahi hota
- **Web bhi concept-exact**: landing page ab concept ke exact headings ("Automated futures trading with military-grade 1:1 risk discipline", "Everything a disciplined bot needs — nothing it doesn't", "Live in three steps, trading tonight", "One license. Every update included.", "Ready to hand the night shift to a bot?" + Launch Free Demo), login page ab split gold panel ("Log in. Let the bot do the watching.")

## v3.3.0 (included) — START fix + Bot Settings in-app
## v3.2.0 (included) — Remember Me + Google login
## v3.0/v3.1 core (included) — 100% NATIVE, zero WebView, fonts/sounds/art pack

## Install (IMPORTANT)
1. Purani Weexionic app UNINSTALL karein (nayi version — bina uninstall install nahi hogi)
2. APK tap karein → "Install unknown apps" allow karein
3. Login karo (email/password ya Google) — server POCHAY GA HI NAHI
4. Pehli bar: Profile → **Bot Settings** → exchange + API keys + coins save karo (ya phir START dabao — app khud bata dega kya missing hai)
5. **START BOT** dabao — "Bot is RUNNING — watching N coins" toast aayega, phir Trade tab pe live chart/signals/positions sab real

## Notes
- Wallet ka payout request website se hota hai (Wallet page) — app mein balance + link + share sab available hai
- Trade tab ke Quick Controls agle entries par apply hote hain (running positions par nahi)
- Crash kabhi ho to file `crash_last.txt` app ki private storage mein save hoti hai — support se share karne par issue foran pakra jata hai

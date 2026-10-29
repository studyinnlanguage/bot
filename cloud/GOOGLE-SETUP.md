# Google Login/Signup Setup (Roman Urdu) — 10 minute ka kaam

Google login **real** hai — Google ke servers se hi verify hota hai. Iske liye ek dafa
Google Cloud Console par free setup karna parta hai (koi paisa nahi lagta).

App v5.1 mein Google button pehle se laga hua hai. Yeh setup complete karte hi button
**dono jagah** kaam karega — app aur web dashboard.

---

## Step 1 — Google Cloud Console
1. Kholo: https://console.cloud.google.com
2. Upar project dropdown → **New Project** → Naam: `Weexionic` → Create
3. **APIs & Services → OAuth consent screen**:
   - User Type: **External** → Create
   - App name: `Weexionic`, support email apna daalo
   - Baqi default rehne do → Save
   - Test users mein apna Gmail add kar do (publish karne ki zaroorat nahi)

## Step 2 — Android Client ID (app ke liye)
**APIs & Services → Credentials → Create Credentials → OAuth client ID → Android:**
- Package name: `com.exionic.trader`
- SHA-1: `CB:3D:00:7B:EE:3E:9B:4A:66:61:6B:F3:17:53:A8:D1:98:2C:23:B6`

(Create karte hi client ID ban jayega — Android client ki ID app mein nahi lagti,
bas banana zaroori hai taake Google app ko pehchane.)

## Step 3 — Web Client ID (asli chabi 🔑)
**Create Credentials → OAuth client ID → Web application:**
- Name: `Weexionic Web`
- Authorized JavaScript origins:
  - `https://weexionic.duckdns.org`
- Authorized redirect URIs: khali chhod do

Yahan se **Client ID** copy karo (aisa hoga: `1234567890-xxxx.apps.googleusercontent.com`)

## Step 4 — App mein client ID daalo (APK main dobara bana dunga)
File: `app/src/main/res/values/strings.xml`:
```xml
<string name="google_web_client_id">YAHAN-WEB-CLIENT-ID-PASTE-KARO</string>
```
**Mujhe client ID bhej do — main naya APK bana ke de dunga.**

## Step 5 — Server mein client ID daalo
Server par bundle root mein `.env` file kholo (deploy.sh ne banayi hogi):
```env
GOOGLE_CLIENT_IDS=wohi-web-client-id.apps.googleusercontent.com
```
(`#` hata do aur apni ID daalo) Phir: `pm2 restart weexionic-cloud`

## Bas! Ab kya hoga
- App: "Continue with Google" → Google account picker → **pehli dafa account auto-ban
  jayega** (signup alag se karne ki zaroorat nahi), dusri dafa seedha login
- Web dashboard: Google button — same flow
- Referral link se aaya ho to Google signup par bhi **$10 inviter ko auto** milte hain

## Common Errors
| Error | Matlab |
|-------|--------|
| `Google setup adhoora hai (code 10)` | Step 2 ka SHA-1 ya package name galat — dobara check karo |
| `Web Client ID check karein` | Step 4 mein ID paste nahi hui ya galat hai |
| `Google client mismatch` | Server `.env` ka GOOGLE_CLIENT_IDS app ki ID se alag hai |

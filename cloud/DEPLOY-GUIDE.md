# Weexionic Cloud — Server Deploy Guide (Roman Urdu)

## Masla kya tha?
Aapke server (`weexionic.duckdns.org`) par **purana Flask bot dashboard** chal raha tha.
Naya Weexionic Cloud dashboard (register, Google login, referral, wallet) us server par
push hi nahi hua — isliye app se signup karne par **"Account ban nahi saka"** aata tha
(server register endpoint ko 404 deta hai).

Is bundle mein **naya dashboard ka poora code** hai. Deploy karte hi:
- Signup/login dono app se aur web se kaam karenge
- Google login/signup ready (GOOGLE-SETUP.md dekhein)
- Referral links (`/r/CODE`) + inviter ko $10 auto-credit
- App ka "Invite & Earn $10" button bhi chal jayega

---

## Zaroori cheezein (Requirements)
- Ubuntu VPS (jo already aapke paas hai — wohi chalega)
- Node.js 20 ya usse naya (`node -v` se check karein; nahi hai to: `curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs`)
- Port 3000 free (ya koi bhi free port — `PORT=3001 ./deploy.sh`)

---

## Deploy Steps (bas 3 commands)

### 1) Purana bot band karo (Flask jo 80/443 par chal raha hai)
```bash
sudo systemctl stop weexionic-bot 2>/dev/null; pkill -f "python.*app.py" 2>/dev/null
```
> Ghabrao mat — purana Flask code aur uska data waise hi mehfooz rahega.
> Naya dashboard apni alag SQLite DB use karta hai.

### 2) Same repo se code lo (git pull)
```bash
cd ~/bot          # jahan bhi bot repo cloned hai
git pull
cd cloud
```

### 3) Ek command — sab kuch khud ho jayega
```bash
bash deploy.sh
```
Yeh script khud: `.env` banayega (DB path auto) → `npm install` → database banayega →
build karega → server start karega (pm2 ho to pm2 se, warna background mein).

### 4) Nginx/Caddy proxy (weexionic.duckdns.org → port 3000)
Agar **nginx** use karte ho, `/etc/nginx/sites-available/weexionic` mein:
```nginx
server {
    listen 80;
    server_name weexionic.duckdns.org;
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```
```bash
sudo ln -sf /etc/nginx/sites-available/weexionic /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```
Agar **Caddy** use karte ho:
```
weexionic.duckdns.org {
    reverse_proxy 127.0.0.1:3000
}
```
(SSL aapka purana setup already handle kar raha hoga — wohi rakho.)

### 5) Verify
```bash
curl http://localhost:3000/api/health
# expected: {"ok":true,"name":"weexionic-cloud","api":2,...}
```
Browser mein `https://weexionic.duckdns.org` kholo → naya dashboard dikhna chahiye.
Ab app mein signup karo — kaam karega ✓

---

## Optional Settings (.env — deploy.sh pehli baar chalane par khud bana deta hai)
```env
DATABASE_URL=file:/root/weexionic-cloud/db/weexionic.db   # ABSOLUTE path hi rakho

# Google login on karne ke liye (GOOGLE-SETUP.md dekhein):
GOOGLE_CLIENT_IDS=yahan-web-client-id.apps.googleusercontent.com

# Android App Links verify (deploy.sh already set kar deta hai):
APP_SHA256=A9E2C70C583657EDBAA0E9CCEFA73D1BBACC112A452669175C85E2C415E9EF74
```
> **Shortcut:** `.env` manually banane ki zaroorat nahi — `./deploy.sh` khud sab likh deta hai.
> Sirf Google client ID milne ke baad `.env` mein `GOOGLE_CLIENT_IDS=` ki line ka `#` hata kar
> value daalo aur `pm2 restart weexionic-cloud` chalao.

## Aapke app ke signing fingerprints (Google setup ke liye kaam aayenge)
```
SHA-1:   CB:3D:00:7B:EE:3E:9B:4A:66:61:6B:F3:17:53:A8:D1:98:2C:23:B6
SHA-256: A9:E2:C7:0C:58:36:57:ED:BA:A0:E9:CC:EF:A7:3D:1B:BA:CC:11:2A:45:26:69:17:5C:85:E2:C4:15:E9:EF:74
```

## Kuch masla ho to
- `pm2 logs weexionic-cloud` — error log dekho (nohup wale ke liye: `tail -f weexionic.log`)
- Port busy: `pm2 delete weexionic-cloud` phir `PORT=3001 bash deploy.sh` aur proxy bhi update karo
- DB reset karni ho: `db/weexionic.db` delete karo + `bash deploy.sh` dobara

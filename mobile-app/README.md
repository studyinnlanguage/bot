# WEEXIONIC Mobile (React Native)

Native Android/iOS client for the WEEXIONIC trading platform.
- Server URL is compiled in (`src/config/env.ts`) — users never configure anything.
- Screens: Cockpit, Vault, Ledger, Engine, Radar, Pulse, Account (+ payments, referrals).
- Realtime: Socket.IO over the JWT-authenticated SaaS proxy.
- Build/release: see docs/BUILD.md. Security: docs/SECURITY.md.

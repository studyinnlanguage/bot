# WEEXIONIC — Flutter Mobile App

Real-time mobile client for your WEEXIONIC crypto futures trading bot. Connects to your existing Flask + Socket.IO bot-engine backend and shows everything the web dashboard shows — but as a premium Android + iOS app.

> Built with Flutter · Material 3 · Custom dark charcoal + gold theme
> Designed to match Binance / WEEX / MEXC quality

## ✨ Features

- **Real-time data via Socket.IO** (polling transport — matches web client exactly)
- **6 fully-built screens** (Dashboard, Live Terminal, Open Positions, Trade History, Strategy & Settings, Alerts & Channels)
- **Candlestick chart with EMA 8 / 13 / 21 / 55 overlays**
- **Live log stream** with filter tabs (All / Info / Success / Warning / Error)
- **Multi-coin position monitor** with one-tap symbol switch
- **Full bot control** — START / STOP / FORCE RESET, close single / all positions
- **Complete strategy config** — exchange, coins, timeframe, leverage, SL/TP, auto-reversal, concurrent trades
- **3 alert channels** — Telegram, Email SMTP, WhatsApp (CallMeBot)
- **Premium UI** — dark charcoal + gold/amber gradient brand, Material 3 components

## 🔌 Backend Integration

This app connects directly to your existing bot-engine backend at:

```
https://weexionic.duckdns.org/bot/api/*       (REST)
https://weexionic.duckdns.org/bot/             (Socket.IO, polling transport)
```

All REST endpoints and Socket.IO event names are wired **exactly** to match `bot-engine/app.py`:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/config` | GET / POST | Read / save full bot config |
| `/api/status` | GET | Bot running state, workers, stats |
| `/api/positions?symbol=X` | GET | Open positions |
| `/api/trades?limit=100` | GET | Trade history + stats |
| `/api/balance` | GET | USDT balance |
| `/api/start`, `/api/stop`, `/api/force_stop` | POST | Bot lifecycle |
| `/api/close`, `/api/close_all` | POST | Close positions |
| `/api/leverage` | POST | Set leverage |
| `/api/test_connection`, `/api/test_notification` | POST | Test connectivity |
| `/api/active_symbol` | POST | Switch chart symbol |

Socket.IO events: `log`, `status`, `indicators`, `chart_data`, `signal`, `position`, `balance`, `trades_updated`

## 📦 Project Structure

```
lib/
├── main.dart                     # App entry + theme + Provider setup
├── core/
│   ├── config.dart               # Backend URLs, endpoint constants, event names
│   ├── theme.dart                # WEEXIONIC dark + gold Material 3 theme
│   ├── api_service.dart          # REST client (http + X-Bot-Token header)
│   ├── socket_service.dart       # Socket.IO client (polling transport)
│   └── bot_provider.dart         # Central state (Provider/ChangeNotifier)
├── models/
│   ├── position.dart             # Position dataclass
│   ├── trade.dart                # Trade + TradeStats
│   ├── bot_log.dart              # Log entry with parsed symbol
│   ├── bot_config.dart           # Full config (matches /api/config schema)
│   ├── bot_status.dart           # Status + WorkerStatus
│   └── chart_data.dart           # Candle + EmaSeries + Indicators
├── widgets/
│   ├── candlestick_chart.dart    # fl_chart candlestick + EMA overlays
│   ├── status_chip.dart          # Colored pill with pulsing dot
│   ├── stat_card.dart            # Compact stat display
│   ├── bottom_nav.dart           # 5-tab Material bottom nav + FAB
│   └── common.dart               # SectionTitle, SegmentedControl, InfoRow, EmptyState
└── screens/
    ├── main_screen.dart          # Shell with bottom nav + IndexedStack
    ├── dashboard_screen.dart     # Screen 1: balance + chart + position + actions
    ├── terminal_screen.dart      # Screen 2: live log stream + filters
    ├── positions_screen.dart     # Screen 3: position card + multi-coin table
    ├── history_screen.dart       # Screen 4: stats grid + trades table
    ├── settings_screen.dart      # Screen 5: full config (exchange, coins, strategy, risk)
    └── alerts_screen.dart        # Screen 6: Telegram + Email + WhatsApp
```

## 🚀 Getting Started

### Prerequisites

- Flutter SDK 3.13+ (Dart 3.0+)
- Android Studio or VS Code with Flutter extension
- Android SDK (for Android builds) / Xcode (for iOS builds)
- Your bot-engine running at `https://weexionic.duckdns.org/bot/`

### Install & Run

```bash
# 1. Install dependencies
cd weexionic_app
flutter pub get

# 2. Run on connected device/emulator
flutter run

# 3. Or run on specific device
flutter run -d chrome         # Web (for quick testing)
flutter run -d android        # Android device/emulator
flutter run -d ios            # iOS simulator (macOS only)
```

### Configuration

If your server has `BOT_ENGINE_TOKEN` env var set (auth required), open:

```
lib/core/config.dart
```

And set:

```dart
static const String botToken = 'YOUR_BOT_ENGINE_TOKEN_VALUE';
```

If your server is open (token unset), leave `botToken = ''` — no auth needed.

### Backend URL

Default is hardcoded to your production VPS. To change:

```dart
// lib/core/config.dart
static const String baseUrl = 'https://weexionic.duckdns.org';
static const String botPrefix = '/bot';
```

## 🏗️ Build APK / IPA

### Android APK

```bash
flutter build apk --release
# Output: build/app/outputs/flutter-apk/app-release.apk
```

### Android App Bundle (for Play Store)

```bash
flutter build appbundle --release
# Output: build/app/outputs/bundle/release/app-release.aab
```

### iOS

```bash
flutter build ios --release
# Then open build/ios/Runner.xcworkspace in Xcode to archive & upload
```

## 🎨 Design System

| Token | Value | Usage |
|---|---|---|
| `bgBase` | `#0A0E14` | App background (deep charcoal) |
| `bgSurface` | `#131722` | Cards, app bar |
| `bgElevated` | `#1B2028` | Inputs, elevated surfaces |
| `brandGold` | `#F5B800` | Primary accent |
| `brandAmber` | `#FF8A00` | Gradient end |
| `green` | `#0ECB81` | LONG / profit / success |
| `red` | `#F6465D` | SHORT / loss / danger |
| `blue` | `#4A8CFF` | Info / TESTNET badge |

Brand gradient: `linear-gradient(135deg, #F5B800 → #FF8A00)`

## ⚙️ Tech Stack

- **Flutter 3.13+** (Material 3)
- **State management:** Provider (ChangeNotifier)
- **Networking:** `http` (REST) + `socket_io_client` (real-time)
- **Charts:** `fl_chart` (candlestick + EMA lines)
- **Storage:** `shared_preferences` (for future local settings)
- **Fonts:** Roboto + Roboto Mono (Material default + Google Fonts)

## 🔧 Troubleshooting

**Socket.IO won't connect?**
- Verify your server URL: `https://weexionic.duckdns.org/bot/`
- The app uses **polling transport only** (matches web client). Don't change to WebSocket — your Flask server uses `async_mode="threading"`.
- Check server logs for the connect event.

**403 Unauthorized on REST calls?**
- Your server has `BOT_ENGINE_TOKEN` set. Add it to `lib/core/config.dart` → `botToken`.

**Chart not showing?**
- The bot must be RUNNING or monitor mode active for chart_data events.
- Tap START on the Dashboard — chart appears within ~30 seconds.

**No positions showing?**
- Check `Multi-Coin Monitor` table on Positions screen.
- If symbols are empty, your `symbols_list` is empty in config. Go to Settings → Monitoring Coins and select at least one.

## 📋 TODO / Future Enhancements

- [ ] Push notifications (FCM) when SL/TP hits
- [ ] Biometric auth (Face ID / fingerprint)
- [ ] Multi-account support
- [ ] P&L charts (weekly / monthly)
- [ ] Trade detail modal with full SL/TP trail
- [ ] Light theme toggle
- [ ] Localization (Urdu / English)

## 📄 License

Private — proprietary to WEEXIONIC project.

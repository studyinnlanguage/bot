# WEEXIONIC Mobile — Build & Release Guide

## Prerequisites
- Node 20, JDK 17, Android SDK (platforms;android-35, build-tools;35.0.0)
- Signing keystore (kept OUT of the repo): `weexionic-release-2026.keystore`
  - CI injects it via secrets: `ANDROID_KEYSTORE_B64`, `ANDROID_KS_PASS`,
    `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASS` (repo → Settings → Secrets → Actions)

## Local development
```bash
cd mobile-app
npm install                     # JS deps
npm start                       # Metro
# separate terminal — device/emulator running:
cd android && ./gradlew assembleDebug && adb install -r app/build/outputs/apk/debug/app-debug.apk
```
Dev builds talk to production (`src/config/env.ts`). To point a dev build at a
local server instead: `WEEXIONIC_DEV_URL=http://192.168.x.x:5000 npm start`.

## Release builds (signed)
```bash
export ANDROID_KEYSTORE_B64=$(base64 -w0 /path/to/weexionic-release-2026.keystore)
export ANDROID_KS_PASS=...      # same value for ANDROID_KEY_PASS
export ANDROID_KEY_ALIAS=weexionic
cd mobile-app/android
./gradlew assembleRelease bundleRelease --no-daemon
# APK:  app/build/outputs/apk/release/app-release.apk      (direct install)
# AAB:  app/build/outputs/bundle/release/app-release.aab   (Play Store upload)
```

## CI
`.github/workflows/build-mobile.yml` builds signed APK + AAB on every push that
touches `mobile-app/**`, verifies the signature with `apksigner`, and attaches
both to GitHub Releases when a release is published.

## iOS
The `mobile-app/ios/` project is delivered build-ready (Podfile included).
Building requires macOS + Xcode 15+: `cd ios && pod install && xcodebuild -workspace WeexionicApp.xcworkspace -scheme WeexionicApp -configuration Release`. (No macOS environment was available to produce a binary — see docs/TESTING.md.)

## Version bumping
- `mobile-app/android/app/build.gradle` → `versionCode` / `versionName`
- `mobile-app/src/config/env.ts` → `APP_VERSION`
- Google sign-in note: the deep-link flow uses `weexionic://oauth`; the OAuth
  client must keep the server redirect URI configured on the owner's dashboard.

#!/bin/bash
# Weexionic v3 native APK: aapt2 -> ecj -> d8 -> zip -> zipalign -> apksigner
set -e
A=/home/z/my-project/android
APP=$A/app
BT=$A/android-14
PLATFORM=$A/android-34
OUT=$A/out
KS=$A/keystore/weexionic.jks

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"

echo "== 1. aapt2 compile =="
"$BT/aapt2" compile --dir "$APP/res" -o "$OUT/res.zip"

echo "== 2. aapt2 link =="
"$BT/aapt2" link -o "$OUT/base.apk" \
  -I "$PLATFORM/android.jar" \
  --manifest "$APP/AndroidManifest.xml" \
  -R "$OUT/res.zip" \
  --java "$OUT/gen" \
  --min-sdk-version 24 --target-sdk-version 34 \
  --version-code 7 --version-name 3.4.0 \
  --auto-add-overlay

echo "== 3. aapt2 add assets =="
cd "$APP" && zip -qj "$OUT/base.apk" assets/*.ttf 2>/dev/null || echo "(no assets)"
cd "$A"
# assets must go under assets/ path inside APK — repack properly
cd "$OUT" && rm -f assetstmp && mkdir -p assets && cp "$APP"/assets/*.ttf assets/ && zip -qr base.apk assets && cd "$A"

echo "== 4. ECJ compile =="
java -jar "$A/ecj.jar" -nowarn -proc:none \
  -source 1.8 -target 1.8 \
  -cp "$PLATFORM/android.jar" \
  -d "$OUT/classes" \
  $(find "$APP/src" "$OUT/gen" -name "*.java")

echo "== 5. d8 dex =="
"$BT/d8" --release --lib "$PLATFORM/android.jar" --min-api 24 \
  --output "$OUT/dex" \
  $(find "$OUT/classes" -name "*.class")

echo "== 6. zip classes.dex =="
cd "$OUT/dex" && zip -q "$OUT/base.apk" classes.dex && cd "$A"

echo "== 7. zipalign =="
"$BT/zipalign" -f 4 "$OUT/base.apk" "$OUT/aligned.apk"

echo "== 8. keystore =="
if [ ! -f "$KS" ]; then
  mkdir -p "$A/keystore"
  keytool -genkeypair -v -keystore "$KS" -alias weexionic \
    -keyalg RSA -keysize 2048 -validity 10950 \
    -storepass weexionic2026 -keypass weexionic2026 \
    -dname "CN=Weexionic, OU=Trading, O=Weexionic, L=Karachi, C=PK"
fi

echo "== 9. apksigner =="
"$BT/apksigner" sign \
  --ks "$KS" --ks-key-alias weexionic \
  --ks-pass pass:weexionic2026 --key-pass pass:weexionic2026 \
  --out "$OUT/Weexionic-App-v3.apk" "$OUT/aligned.apk"

"$BT/apksigner" verify "$OUT/Weexionic-App-v3.apk" && echo "SIGNED OK"
echo "BUILD OK -> $OUT/Weexionic-App-v3.apk ($(du -h $OUT/Weexionic-App-v3.apk | cut -f1))"

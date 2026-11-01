#!/bin/bash
# ============================================================
# WEEXIONIC Android client — signed APK build (no Gradle)
# Works locally and on GitHub Actions (ubuntu-latest).
# Needs: JDK 11+ (java, keytool) + Android SDK with
#        platforms;android-34 and build-tools;34.0.0
# ============================================================
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-/home/z/my-project/android-sdk}}"
BT="$SDK/build-tools/34.0.0"
PLAT="$SDK/platforms/android-34/android.jar"
OUT="$SRC/build"
VERSION="1.0.0"

[ -x "$BT/aapt2" ] || { echo "build-tools 34.0.0 missing — run: sdkmanager 'platforms;android-34' 'build-tools;34.0.0'"; exit 1; }
[ -f "$PLAT" ] || { echo "platform android-34 missing — run: sdkmanager 'platforms;android-34'"; exit 1; }

# Eclipse compiler jar (no JDK javac needed — runs on plain java)
ECJ="$OUT/ecj.jar"
mkdir -p "$OUT"
if [ ! -f "$ECJ" ]; then
  curl -sS -o "$ECJ" https://repo1.maven.org/maven2/org/eclipse/jdt/ecj/3.36.0/ecj-3.36.0.jar
fi

rm -rf "$OUT/classes" "$OUT/gen" "$OUT/dex"
mkdir -p "$OUT/classes" "$OUT/gen" "$OUT/dex"

echo "[1/7] aapt2 compile resources..."
"$BT/aapt2" compile --dir "$SRC/res" -o "$OUT/res.zip"

echo "[2/7] aapt2 link..."
"$BT/aapt2" link -o "$OUT/base.apk" \
  -I "$PLAT" \
  --manifest "$SRC/AndroidManifest.xml" \
  --min-sdk-version 24 --target-sdk-version 34 \
  -R "$OUT/res.zip" \
  --java "$OUT/gen" \
  --auto-add-overlay

echo "[3/7] compile java..."
java -jar "$ECJ" -source 8 -target 8 -nowarn -encoding UTF-8 \
  -cp "$PLAT" -d "$OUT/classes" \
  $(find "$OUT/gen" "$SRC/java" -name "*.java") > "$OUT/compile.log" 2>&1 || true
grep -E "ERROR in" "$OUT/compile.log" | head -20 && true
if grep -qE "ERROR in" "$OUT/compile.log" || [ ! -f "$OUT/classes/ai/weexionic/app/MainActivity.class" ]; then
  echo "COMPILE FAILED — aborting"; exit 1
fi

echo "[4/7] d8 dex..."
find "$OUT/classes" -name "*.class" > "$OUT/classlist.txt"
"$BT/d8" --release --lib "$PLAT" --output "$OUT/dex" $(cat "$OUT/classlist.txt")

echo "[5/7] pack classes.dex..."
(cd "$OUT/dex" && zip -q -j "$OUT/base.apk" classes.dex)

echo "[6/7] zipalign..."
"$BT/zipalign" -f -p 4 "$OUT/base.apk" "$OUT/aligned.apk"

echo "[7/7] sign..."
KS="$SRC/weexionic.keystore"
if [ ! -f "$KS" ]; then
  keytool -genkeypair -keystore "$KS" -alias weexionic \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass ***REMOVED*** -keypass ***REMOVED*** \
    -dname "CN=WEEXIONIC, O=Weexionic, C=PK"
fi
FINAL="$SRC/WEEXIONIC-v$VERSION.apk"
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:***REMOVED*** \
  --key-pass pass:***REMOVED*** \
  --out "$FINAL" "$OUT/aligned.apk"
"$BT/apksigner" verify "$FINAL" && echo "SIGNED OK"

echo "APK READY: $FINAL"
ls -lh "$FINAL"

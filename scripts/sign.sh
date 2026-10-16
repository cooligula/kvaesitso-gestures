#!/usr/bin/env bash
# Align and sign an unsigned APK: scripts/sign.sh <unsigned.apk> <signed.apk>
# Needs KEYSTORE_PATH, KEYSTORE_PASSWORD, KEY_ALIAS, KEY_PASSWORD in the environment.
# Optional CERT_SHA256: refuse to sign when the key does not match the expected certificate.
set -euo pipefail
in="$1"; out="$2"
bt="$(ls -d "${ANDROID_HOME:-/usr/local/lib/android/sdk}"/build-tools/* | sort -V | tail -n1)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

"$bt/zipalign" -f -P 16 4 "$in" "$tmp/aligned.apk"
"$bt/apksigner" sign \
  --ks "$KEYSTORE_PATH" --ks-key-alias "$KEY_ALIAS" \
  --ks-pass env:KEYSTORE_PASSWORD --key-pass env:KEY_PASSWORD \
  --out "$out" "$tmp/aligned.apk"

"$bt/apksigner" verify --verbose --print-certs "$out" | tee "$tmp/verify.txt"
got="$(grep -m1 'certificate SHA-256 digest' "$tmp/verify.txt" | awk '{print $NF}')"
if [ -n "${CERT_SHA256:-}" ] && [ "${CERT_SHA256,,}" != "${got,,}" ]; then
  echo "certificate $got does not match expected $CERT_SHA256" >&2
  rm -f "$out"
  exit 1
fi

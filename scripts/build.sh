#!/usr/bin/env bash
# Build the unsigned release APK of the prepared source: scripts/build.sh
# Produces dist/kvaesitso-<version>-unsigned.apk and meta.json next to it.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
src="$root/work/kvaesitso"
meta="$src/kvgestures-meta.json"

read -r task apkdir < <(python3 - "$root/upstream.toml" <<'PY'
import sys, tomllib
b = tomllib.load(open(sys.argv[1], "rb"))["build"]
print(b["gradle_task"], b["apk_dir"])
PY
)
version="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['version_name'])" "$meta")"

# R8 needs more than the 4 GB upstream configures.
( cd "$src" && chmod +x gradlew && \
  ./gradlew --no-daemon --stacktrace -Dorg.gradle.jvmargs="-Xmx6g -Dfile.encoding=UTF-8" "$task" )

apk="$(ls "$src/$apkdir"/*.apk | head -n1)"
mkdir -p "$root/dist"
cp "$apk" "$root/dist/kvaesitso-$version-unsigned.apk"
cp "$meta" "$root/dist/meta.json"
echo "built $root/dist/kvaesitso-$version-unsigned.apk"

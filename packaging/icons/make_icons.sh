#!/bin/bash
# Пересобирает AppIcon.icns из icon.svg средствами macOS (qlmanage, sips, iconutil).
# Готовый AppIcon.icns лежит в репозитории: запускать только после правки icon.svg.
set -euo pipefail
cd "$(dirname "$0")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

qlmanage -t -s 1024 -o "$TMP" icon.svg >/dev/null 2>&1
SET="$TMP/AppIcon.iconset"
mkdir -p "$SET"
for size in 16 32 128 256 512; do
  sips -z $size $size "$TMP/icon.svg.png" --out "$SET/icon_${size}x${size}.png" >/dev/null
  sips -z $((size * 2)) $((size * 2)) "$TMP/icon.svg.png" --out "$SET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o AppIcon.icns
echo "Готово: AppIcon.icns"

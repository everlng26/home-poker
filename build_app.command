#!/usr/bin/env bash
# Собирает «Домашний покер.app» и образ диска для текущей архитектуры Mac:
#   dist/HomePoker-<версия>-macOS-AppleSilicon.dmg или ...-macOS-Intel.dmg
# Нужны Python 3.11–3.13 и интернет на время сборки. Готовое приложение работает без Python.
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$PROJECT_DIR"

supported() { "$1" -c 'import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)' 2>/dev/null; }

# Python с python.org собран для старых macOS, поэтому приложение из него запустится на большем числе Mac.
PYTHON_BIN="${PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in \
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 \
    /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 \
    "$(command -v python3.13 || true)" "$(command -v python3.12 || true)" "$(command -v python3.11 || true)" \
    "$(command -v python3 || true)"; do
    if [[ -n "$candidate" && -x "$candidate" ]] && supported "$candidate"; then PYTHON_BIN="$candidate"; break; fi
  done
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Для сборки нужен Python 3.11–3.13. Установите его с https://www.python.org/downloads/macos/ и запустите сборку снова."
  exit 1
fi
echo "Собираю на $("$PYTHON_BIN" --version) ($PYTHON_BIN)"

BUILD_VENV="$PROJECT_DIR/.venv-build"
if [[ ! -x "$BUILD_VENV/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$BUILD_VENV"
fi
BUILD_PYTHON="$BUILD_VENV/bin/python"
"$BUILD_PYTHON" -m pip install --quiet --upgrade pip
"$BUILD_PYTHON" -m pip install --quiet -r requirements.txt -r packaging/requirements-build.txt
"$BUILD_PYTHON" -m PyInstaller packaging/home-poker.spec --noconfirm --clean --distpath dist --workpath build

APP="dist/Домашний покер.app"
# Подпись без сертификата разработчика: без неё на Apple Silicon приложение не запустится вовсе.
codesign --force --deep --sign - "$APP"

VERSION="$("$BUILD_PYTHON" -c 'import app; print(app.__version__)')"
if [[ "$(uname -m)" == "arm64" ]]; then ARCH="AppleSilicon"; else ARCH="Intel"; fi
DMG="dist/HomePoker-${VERSION}-macOS-${ARCH}.dmg"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Программы"
rm -f "$DMG"
hdiutil create -volname "Домашний покер" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG" >/dev/null
echo "Готово: $APP и $DMG"

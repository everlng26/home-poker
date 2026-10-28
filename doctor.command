#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$PROJECT_DIR"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
STATUS=0

if command -v python3 >/dev/null 2>&1; then
  echo "✓ python3: $(python3 --version)"
else
  echo "✗ python3 не найден."
  STATUS=1
fi
if [[ -x "$VENV_PYTHON" ]]; then
  echo "✓ виртуальное окружение найдено."
  if "$VENV_PYTHON" -c 'import fastapi, sqlalchemy, alembic, qrcode' >/dev/null 2>&1; then
    echo "✓ зависимости установлены."
  else
    echo "✗ часть зависимостей отсутствует. Запустите setup.command."
    STATUS=1
  fi
else
  echo "✗ виртуальное окружение не найдено. Запустите setup.command."
  STATUS=1
fi
if /usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "✓ порт 8000 занят работающим приложением или другим процессом."
else
  echo "• порт 8000 свободен."
fi
if [[ -f data/poker.db ]]; then
  echo "✓ база данных найдена."
else
  echo "• рабочая база ещё не создана."
fi
if [[ -x "$VENV_PYTHON" ]]; then
  "$VENV_PYTHON" -m alembic current || STATUS=1
  "$VENV_PYTHON" scripts/network.py || true
  if "$VENV_PYTHON" -c 'from urllib.request import urlopen; urlopen("http://127.0.0.1:8000/health", timeout=1)' >/dev/null 2>&1; then
    echo "✓ health endpoint отвечает."
  else
    echo "• health endpoint недоступен: сервер не запущен или использует другой порт."
  fi
fi
if [[ "$STATUS" -ne 0 ]]; then
  echo "Диагностика выявила проблему. Следуйте рекомендациям выше."
fi
exit "$STATUS"


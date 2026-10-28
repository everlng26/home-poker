#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$PROJECT_DIR"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Не найдено виртуальное окружение. Сначала дважды нажмите setup.command."
  exit 1
fi
if ! "$VENV_PYTHON" -c 'import fastapi, sqlalchemy, alembic, qrcode' >/dev/null 2>&1; then
  echo "Не найдены необходимые зависимости. Сначала дважды нажмите setup.command."
  exit 1
fi
if [[ -f data/poker.db ]]; then
  "$VENV_PYTHON" scripts/backup_db.py
fi
"$VENV_PYTHON" -m alembic upgrade head
if /usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Порт 8000 уже занят. Закройте другое приложение на этом порту и повторите запуск."
  exit 1
fi

echo "Пока это окно Terminal открыто, сервер турнира работает."
echo "Для остановки нажмите Control+C."
"$VENV_PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!
/usr/bin/caffeinate -dims -w "$SERVER_PID" &
CAFFEINATE_PID=$!
cleanup() {
  kill "$SERVER_PID" "$CAFFEINATE_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

for _ in {1..30}; do
  if "$VENV_PYTHON" -c 'from urllib.request import urlopen; urlopen("http://127.0.0.1:8000/health", timeout=1)' >/dev/null 2>&1; then
    echo "Откройте на компьютере: http://localhost:8000"
    "$VENV_PYTHON" scripts/network.py || true
    /usr/bin/open "http://localhost:8000"
    wait "$SERVER_PID"
    exit $?
  fi
  sleep 1
done
echo "Сервер не ответил на health-проверку за 30 секунд."
exit 1

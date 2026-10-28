#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$PROJECT_DIR"

PYTHON_BIN="$(command -v python3 || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Не найден python3. Установите Python 3.11–3.13 с python.org или другим привычным способом и повторите запуск."
  exit 1
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)'; then
  echo "Нужен Python версии от 3.11 до 3.13. Найдено: $("$PYTHON_BIN" --version)"
  exit 1
fi
if command -v git >/dev/null 2>&1; then
  echo "Git найден: $(git --version)"
else
  echo "Git не найден. Приложение будет работать, но checkpoint-коммиты недоступны."
fi

echo "Создаю виртуальное окружение…"
"$PYTHON_BIN" -m venv .venv
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
echo "Устанавливаю зависимости…"
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r requirements.txt -r requirements-dev.txt
mkdir -p data backups
echo "Применяю миграции базы данных…"
"$VENV_PYTHON" -m alembic upgrade head
echo "Запускаю smoke-проверку…"
"$VENV_PYTHON" -m pytest tests/smoke -q
echo "Готово. Теперь дважды нажмите start.command."


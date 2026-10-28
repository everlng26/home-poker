#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$PROJECT_DIR"
if [[ ! -x .venv/bin/python ]]; then
  echo "Не найдено виртуальное окружение. Сначала дважды нажмите setup.command."
  exit 1
fi
echo "Запускаю тесты…"
.venv/bin/python -m pytest
echo "Проверяю стиль кода…"
.venv/bin/python -m ruff check app tests scripts
echo "Все автоматические проверки успешно завершены."


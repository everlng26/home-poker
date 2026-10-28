#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$PROJECT_DIR"
if [[ ! -x .venv/bin/python ]]; then
  echo "Не найдено виртуальное окружение. Сначала дважды нажмите setup.command."
  exit 1
fi
.venv/bin/python scripts/backup_db.py


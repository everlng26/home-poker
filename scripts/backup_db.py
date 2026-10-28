#!/usr/bin/env python3
"""Создание согласованной резервной копии рабочей базы."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app.database import create_backup  # noqa: E402


def main() -> int:
    destination = create_backup()
    if destination is None:
        print("Рабочая база ещё не создана: резервная копия не требуется.")
        return 0
    print(f"Резервная копия создана: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Создание согласованной резервной копии рабочей базы."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app.config import get_settings  # noqa: E402
from app.database import sqlite_backup  # noqa: E402


def main() -> int:
    settings = get_settings()
    source = settings.data_dir / "poker.db"
    if not source.exists():
        print("Рабочая база ещё не создана: резервная копия не требуется.")
        return 0
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    destination = settings.backups_dir / f"poker-{timestamp}.db"
    counter = 1
    while destination.exists():
        destination = settings.backups_dir / f"poker-{timestamp}-{counter}.db"
        counter += 1
    sqlite_backup(source, destination)
    print(f"Резервная копия создана: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

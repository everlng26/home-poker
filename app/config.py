"""Конфигурация приложения без обязательных внешних сервисов."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class Settings:
    project_dir: Path
    data_dir: Path
    backups_dir: Path
    database_url: str
    app_secret_path: Path
    log_level: str


def get_settings() -> Settings:
    # Приложение для macOS хранит данные в ~/Library/Application Support, а не внутри себя.
    data_dir = Path(os.getenv("POKER_DATA_DIR") or PROJECT_DIR / "data")
    backups_dir = Path(os.getenv("POKER_BACKUPS_DIR") or PROJECT_DIR / "backups")
    database_path = data_dir / "poker.db"
    database_url = os.getenv("POKER_DATABASE_URL", f"sqlite:///{database_path}")
    return Settings(
        project_dir=PROJECT_DIR,
        data_dir=data_dir,
        backups_dir=backups_dir,
        database_url=database_url,
        app_secret_path=data_dir / "app_secret.key",
        log_level=os.getenv("POKER_LOG_LEVEL", "INFO").upper(),
    )


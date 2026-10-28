"""Подключение к SQLite и общие настройки надёжности."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings


def _sqlite_connect_settings(dbapi_connection: object, _: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def create_database_engine(settings: Settings | None = None) -> Engine:
    active_settings = settings or get_settings()
    connect_args: dict[str, object] = {"check_same_thread": False, "timeout": 5}
    engine = create_engine(active_settings.database_url, connect_args=connect_args, future=True)
    if active_settings.database_url.startswith("sqlite"):
        event.listen(engine, "connect", _sqlite_connect_settings)
    return engine


settings = get_settings()
engine = create_database_engine(settings)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def ensure_local_directories(active_settings: Settings | None = None) -> None:
    current = active_settings or settings
    current.data_dir.mkdir(parents=True, exist_ok=True)
    current.backups_dir.mkdir(parents=True, exist_ok=True)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_database_connection(active_engine: Engine | None = None) -> bool:
    database_engine = active_engine or engine
    with database_engine.connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one() == 1


def sqlite_backup(source: Path, destination: Path) -> None:
    """Создаёт согласованную копию SQLite средствами самой SQLite."""
    import sqlite3

    with sqlite3.connect(source) as source_connection, sqlite3.connect(destination) as destination_connection:
        source_connection.backup(destination_connection)


def create_backup(active_settings: Settings | None = None) -> Path | None:
    """Копирует рабочую базу в папку резервных копий; None, если базы ещё нет."""
    current = active_settings or get_settings()
    source = current.data_dir / "poker.db"
    if not source.exists():
        return None
    current.backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    destination = current.backups_dir / f"poker-{timestamp}.db"
    counter = 1
    while destination.exists():
        destination = current.backups_dir / f"poker-{timestamp}-{counter}.db"
        counter += 1
    sqlite_backup(source, destination)
    return destination

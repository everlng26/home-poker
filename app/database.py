"""Подключение к SQLite и общие настройки надёжности."""

from __future__ import annotations

from collections.abc import Generator
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


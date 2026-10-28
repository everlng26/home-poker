"""Части приложения macOS, которые не требуют окна: папки, миграции, резервная копия."""

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.config import Settings
from app.database import create_backup
from desktop import launcher


def test_data_folder_is_in_application_support() -> None:
    assert launcher.default_data_dir() == Path.home() / "Library" / "Application Support" / "Домашний покер"


def test_environment_points_server_to_data_folder(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("POKER_DATA_DIR", raising=False)
    monkeypatch.delenv("POKER_BACKUPS_DIR", raising=False)

    launcher.configure_environment(tmp_path)

    assert launcher.os.environ["POKER_DATA_DIR"] == str(tmp_path)
    assert launcher.os.environ["POKER_BACKUPS_DIR"] == str(tmp_path / "backups")


def test_explicit_environment_wins(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("POKER_DATA_DIR", "/elsewhere")
    monkeypatch.delenv("POKER_BACKUPS_DIR", raising=False)

    launcher.configure_environment(tmp_path)

    assert launcher.os.environ["POKER_DATA_DIR"] == "/elsewhere"


def test_migrations_run_without_alembic_ini(monkeypatch, tmp_path: Path) -> None:
    database = tmp_path / "poker.db"
    monkeypatch.setenv("POKER_DATABASE_URL", f"sqlite:///{database}")
    assert (launcher.migrations_dir() / "env.py").exists()

    launcher.run_migrations()

    tables = set(inspect(create_engine(f"sqlite:///{database}")).get_table_names())
    assert {"tournaments", "tournament_players", "blind_levels", "chip_sets", "alembic_version"} <= tables


def test_backup_copies_existing_database(tmp_path: Path) -> None:
    settings = Settings(
        project_dir=tmp_path,
        data_dir=tmp_path / "data",
        backups_dir=tmp_path / "backups",
        database_url=f"sqlite:///{tmp_path / 'data' / 'poker.db'}",
        app_secret_path=tmp_path / "data" / "secret",
        log_level="WARNING",
    )
    assert create_backup(settings) is None

    settings.data_dir.mkdir()
    with sqlite3.connect(settings.data_dir / "poker.db") as connection:
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.execute("INSERT INTO marker VALUES ('ok')")

    first = create_backup(settings)
    second = create_backup(settings)

    assert first is not None and second is not None and first != second
    with sqlite3.connect(first) as connection:
        assert connection.execute("SELECT value FROM marker").fetchone() == ("ok",)


def test_nothing_answers_on_a_closed_port() -> None:
    assert launcher.server_answers(1) is False
    assert launcher.has_active_tournament(1) is False


def test_window_shows_home_folder_short() -> None:
    api = launcher.WindowApi(8000, Path.home() / "Library" / "Application Support" / "Домашний покер")

    assert api.data_folder() == "~/Library/Application Support/Домашний покер"


def test_window_page_and_bundle_recipe_match() -> None:
    page = (launcher.WINDOW_DIR / "index.html").read_text(encoding="utf-8")
    spec = (Path(launcher.__file__).resolve().parents[1] / "packaging" / "home-poker.spec").read_text(encoding="utf-8")

    assert "/static/css/app.css" in page
    assert "window.pywebview?.api" in page and "/api/v1/network" in page
    assert '"migrations"' in spec and '"desktop/window"' in spec and '"app/static"' in spec

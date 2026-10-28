from pathlib import Path

from app.config import PROJECT_DIR, get_settings


def test_data_lives_in_project_by_default(monkeypatch) -> None:
    for name in ("POKER_DATA_DIR", "POKER_BACKUPS_DIR", "POKER_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)

    settings = get_settings()

    assert settings.data_dir == PROJECT_DIR / "data"
    assert settings.backups_dir == PROJECT_DIR / "backups"
    assert settings.database_url == f"sqlite:///{PROJECT_DIR / 'data' / 'poker.db'}"
    assert settings.app_secret_path == PROJECT_DIR / "data" / "app_secret.key"


def test_desktop_app_moves_data_outside_the_bundle(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("POKER_DATABASE_URL", raising=False)
    monkeypatch.setenv("POKER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("POKER_BACKUPS_DIR", str(tmp_path / "backups"))

    settings = get_settings()

    assert settings.data_dir == tmp_path / "data"
    assert settings.backups_dir == tmp_path / "backups"
    assert settings.database_url == f"sqlite:///{tmp_path / 'data' / 'poker.db'}"
    assert settings.app_secret_path == tmp_path / "data" / "app_secret.key"

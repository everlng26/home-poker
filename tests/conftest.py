from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_database_engine_for_test()
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    active_session = factory()
    try:
        yield active_session
    finally:
        active_session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def create_database_engine_for_test():
    return create_database_engine_from_url("sqlite+pysqlite:///:memory:")


def create_database_engine_from_url(url: str):
    from app.config import Settings
    from app.database import create_database_engine
    from pathlib import Path

    temporary_root = Path("/private/tmp/home-poker-tests")
    settings = Settings(
        project_dir=temporary_root,
        data_dir=temporary_root,
        backups_dir=temporary_root,
        database_url=url,
        app_secret_path=temporary_root / "secret",
        log_level="WARNING",
    )
    return create_database_engine(settings)

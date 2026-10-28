from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.database import create_database_engine, get_session
from app.main import app
from app.models import Base


@pytest.fixture
def api_session_factory(tmp_path):
    settings = Settings(
        project_dir=tmp_path,
        data_dir=tmp_path,
        backups_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'chip-api.db'}",
        app_secret_path=Path(tmp_path) / "secret",
        log_level="WARNING",
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def api_client(factory) -> Generator[TestClient, None, None]:
    def override_session():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_chip_set_api_crud_validation_default_and_persistence(api_session_factory) -> None:
    generator = api_client(api_session_factory)
    client = next(generator)
    try:
        created_response = client.post(
            "/api/v1/chip-sets",
            json={
                "name": "Основной набор",
                "is_default": True,
                "denominations": [
                    {"value": 500, "quantity": 80},
                    {"value": 25, "quantity": 100},
                    {"value": 100, "quantity": 100},
                ],
            },
        )
        assert created_response.status_code == 200
        created = created_response.json()
        assert created["is_default"] is True
        assert created["total_chips"] == 280
        assert created["total_value"] == 52_500
        assert [item["value"] for item in created["denominations"]] == [25, 100, 500]

        fetched = client.get(f"/api/v1/chip-sets/{created['id']}")
        assert fetched.status_code == 200
        assert fetched.json() == created

        duplicate = client.post(
            "/api/v1/chip-sets",
            json={
                "name": "Ошибка",
                "denominations": [
                    {"value": 25, "quantity": 100},
                    {"value": 25, "quantity": 50},
                ],
            },
        )
        assert duplicate.status_code == 400
        assert duplicate.json()["detail"]["code"] == "duplicate_denomination"

        second = client.post(
            "/api/v1/chip-sets",
            json={"name": "Маленький кейс", "denominations": [{"value": 100, "quantity": 0}]},
        ).json()
        switched = client.post(f"/api/v1/chip-sets/{second['id']}/default")
        assert switched.status_code == 200
        assert switched.json()["is_default"] is True

        listed = client.get("/api/v1/chip-sets").json()
        assert len(listed) == 2
        assert sum(item["is_default"] for item in listed) == 1
        assert next(item for item in listed if item["id"] == created["id"])["is_default"] is False

        updated = client.put(
            f"/api/v1/chip-sets/{created['id']}",
            json={
                "name": "Основной кейс",
                "denominations": [
                    {"value": 25, "quantity": 100},
                    {"value": 500, "quantity": 75},
                    {"value": 25_000, "quantity": 20},
                ],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Основной кейс"
        assert updated.json()["total_chips"] == 195
        assert updated.json()["total_value"] == 540_000

        deleted = client.delete(f"/api/v1/chip-sets/{second['id']}")
        assert deleted.json() == {"ok": True}
        assert client.get(f"/api/v1/chip-sets/{second['id']}").status_code == 404
        remaining = client.get("/api/v1/chip-sets").json()
        assert len(remaining) == 1
        assert remaining[0]["is_default"] is False
    finally:
        generator.close()


def test_chip_set_api_rejects_invalid_numbers_and_missing_set(api_session_factory) -> None:
    generator = api_client(api_session_factory)
    client = next(generator)
    try:
        for denomination, code in [
            ({"value": 0, "quantity": 1}, "invalid_denomination_value"),
            ({"value": 25, "quantity": -1}, "invalid_denomination_quantity"),
        ]:
            response = client.post(
                "/api/v1/chip-sets",
                json={"name": "Некорректный", "denominations": [denomination]},
            )
            assert response.status_code == 400
            assert response.json()["detail"]["code"] == code
        assert client.get("/api/v1/chip-sets/999999").status_code == 404
        assert client.delete("/api/v1/chip-sets/999999").status_code == 404
    finally:
        generator.close()

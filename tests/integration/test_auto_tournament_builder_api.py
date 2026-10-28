from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.database import create_database_engine, get_session
from app.main import app
from app.models import Base
from app.services.chip_inventory_service import ChipInventoryService


def create_set(session, name, denominations):
    return ChipInventoryService.create(
        session,
        name=name,
        denominations=[{"value": value, "quantity": quantity} for value, quantity in denominations],
    )



@pytest.fixture
def builder_session_factory(tmp_path):
    settings = Settings(
        project_dir=tmp_path,
        data_dir=tmp_path,
        backups_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'auto-builder-api.db'}",
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


def test_auto_builder_api_requires_only_minimal_user_decisions(builder_session_factory) -> None:
    generator = api_client(builder_session_factory)
    client = next(generator)
    try:
        first = client.post(
            "/api/v1/chip-sets",
            json={
                "name": "API A",
                "denominations": [
                    {"value": value, "quantity": quantity}
                    for value, quantity in [
                        (25, 160),
                        (50, 160),
                        (100, 160),
                        (500, 120),
                        (1_000, 120),
                    ]
                ],
            },
        ).json()
        second = client.post(
            "/api/v1/chip-sets",
            json={
                "name": "API B",
                "denominations": [
                    {"value": value, "quantity": quantity}
                    for value, quantity in [
                        (25, 80),
                        (50, 80),
                        (500, 80),
                        (1_000, 80),
                        (5_000, 50),
                    ]
                ],
            },
        ).json()
        response = client.post(
            "/api/v1/auto-tournament-builder",
            json={
                "chip_set_ids": [first["id"], second["id"]],
                "players": 8,
                "max_reentries_per_player": 2,
                "target_duration_minutes": 300,
                "ante_mode": "big_blind",
            },
        )
        assert response.status_code == 200
        result = response.json()
        plan = result["candidates"][0]
        created = client.post(
            "/api/v1/tournaments",
            json={
                "name": "Auto Builder snapshot",
                "buy_in_amount": 1_000,
                "currency_label": "₽",
                "starting_stack": plan["starting_stack"],
                "max_reentries_per_player": 2,
                "pin": "1234",
                "late_registration_end_level_number": 3,
                "players": [f"Игрок {index}" for index in range(1, 9)],
                "payout_percentages": [50, 30, 20],
                "ante_enabled": True,
                "levels": plan["levels"],
                "chip_plan": plan["chip_plan"],
            },
        )
        assert created.status_code == 200, created.text
        tournament_id = created.json()["id"]
        chip_snapshot = client.get(f"/api/v1/tournaments/{tournament_id}/chip-plan").json()
        level_snapshot = client.get(f"/api/v1/tournaments/{tournament_id}/state").json()["levels"]
        client.put(
            f"/api/v1/chip-sets/{first['id']}",
            json={"name": "Изменённый API A", "denominations": [{"value": 25, "quantity": 1}]},
        )
        assert client.get(f"/api/v1/tournaments/{tournament_id}/chip-plan").json() == chip_snapshot
        assert client.get(f"/api/v1/tournaments/{tournament_id}/state").json()["levels"] == level_snapshot
    finally:
        generator.close()

    assert result["max_total_reentries"] == 16
    assert result["candidates"][0]["starting_stack"] > 0
    assert result["candidates"][0]["first_big_blind"] > 0
    assert result["candidates"][0]["levels"]


def test_auto_builder_api_rejects_empty_physical_selection() -> None:
    response = TestClient(app).post(
        "/api/v1/auto-tournament-builder",
        json={
            "chip_set_ids": [],
            "players": 8,
            "max_reentries_per_player": 2,
            "target_duration_minutes": 300,
            "ante_mode": "big_blind",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "invalid_selected_chip_sets",
        "message": "Выберите хотя бы один набор фишек.",
    }


def test_manual_draft_diagnostics_never_return_replacement_levels() -> None:
    draft = [
        {
            "kind": "play",
            "small_blind": 25,
            "big_blind": 50,
            "ante": 0,
            "duration_seconds": 900,
        },
        {
            "kind": "play",
            "small_blind": 35,
            "big_blind": 70,
            "ante": 70,
            "duration_seconds": 1_200,
        },
        {"kind": "break", "duration_seconds": 600},
        {
            "kind": "play",
            "small_blind": 50,
            "big_blind": 100,
            "ante": 100,
            "duration_seconds": 900,
        },
    ]

    response = TestClient(app).post(
        "/api/v1/auto-tournament-builder/diagnostics",
        json={
            "levels": draft,
            "players": 8,
            "starting_stack": 5_000,
            "expected_reentries": 3,
            "target_duration_minutes": 300,
            "chip_denominations": [25, 100, 500, 1_000],
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert "levels" not in result
    assert result["heuristic"]["structure_was_regenerated"] is False
    assert result["summary"]["structure_total_seconds"] == 3_600
    assert any(item["code"] == "unpayable_level" for item in result["diagnostics"])

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
def optimizer_session_factory(tmp_path):
    settings = Settings(
        project_dir=tmp_path,
        data_dir=tmp_path,
        backups_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'optimizer-api.db'}",
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


def create_chip_set(client: TestClient, quantity: int = 480) -> dict:
    response = client.post(
        "/api/v1/chip-sets",
        json={
            "name": "Основной",
            "is_default": True,
            "denominations": [{"value": 1_000, "quantity": quantity}],
        },
    )
    assert response.status_code == 200
    return response.json()


def solve(client: TestClient, chip_set_id: int) -> dict:
    response = client.post(
        "/api/v1/stack-optimizer",
        json={
            "chip_set_ids": [chip_set_id],
            "players": 8,
            "starting_stack": 20_000,
            "max_reentries_per_player": 2,
            "first_small_blind": 100,
            "first_big_blind": 200,
            "first_ante": 200,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_optimizer_api_full_and_partial_coverage(optimizer_session_factory) -> None:
    generator = api_client(optimizer_session_factory)
    client = next(generator)
    try:
        full_set = create_chip_set(client)
        full = solve(client, full_set["id"])
        assert full["max_total_reentries"] == 16
        assert full["max_total_entries"] == 24
        assert full["diagnostics"]["full_coverage"] is True
        assert all(item["covered_reentries"] == 16 for item in full["candidates"])

        partial_set = client.post(
            "/api/v1/chip-sets",
            json={"name": "Partial", "denominations": [{"value": 1_000, "quantity": 340}]},
        ).json()
        partial = solve(client, partial_set["id"])
        assert partial["feasible"] is True
        assert partial["max_total_reentries"] == 16
        assert max(item["covered_reentries"] for item in partial["candidates"]) == 9
        assert all(item["coverage_status"] == "partial" for item in partial["candidates"])
    finally:
        generator.close()


def test_tournament_creation_saves_immutable_chip_plan_snapshot(optimizer_session_factory) -> None:
    generator = api_client(optimizer_session_factory)
    client = next(generator)
    try:
        chip_set = create_chip_set(client)
        solution = solve(client, chip_set["id"])
        candidate = next(item for item in solution["candidates"] if item["recommended"])
        original_inventory = client.get(f"/api/v1/chip-sets/{chip_set['id']}").json()

        created = client.post(
            "/api/v1/tournaments",
            json={
                "name": "Snapshot tournament",
                "buy_in_amount": 1_000,
                "currency_label": "₽",
                "starting_stack": 20_000,
                "max_reentries_per_player": 2,
                "pin": "1234",
                "preset": "standard",
                "late_registration_end_level_number": 3,
                "players": [f"Игрок {index}" for index in range(8)],
                "payout_percentages": [50, 30, 20],
                "chip_plan": {
                    "chip_set_ids": [chip_set["id"]],
                    "initial_distribution": candidate["initial_distribution"],
                },
            },
        )
        assert created.status_code == 200, created.text
        tournament_id = created.json()["id"]
        snapshot = client.get(f"/api/v1/tournaments/{tournament_id}/chip-plan").json()
        assert snapshot["planned_players"] == 8
        assert snapshot["starting_stack"] == 20_000
        assert snapshot["max_reentries_per_player"] == 2
        assert snapshot["max_total_reentries"] == 16
        assert snapshot["covered_reentries"] == 16
        assert snapshot["initial_distribution"] == candidate["initial_distribution"]
        assert client.get(f"/api/v1/chip-sets/{chip_set['id']}").json() == original_inventory

        client.put(
            f"/api/v1/chip-sets/{chip_set['id']}",
            json={"name": "Изменён", "denominations": [{"value": 5_000, "quantity": 1}]},
        )
        assert client.get(f"/api/v1/tournaments/{tournament_id}/chip-plan").json() == snapshot
        assert client.delete(f"/api/v1/chip-sets/{chip_set['id']}").status_code == 200
        assert client.get(f"/api/v1/tournaments/{tournament_id}/chip-plan").json() == snapshot
    finally:
        generator.close()


def test_creation_recomputes_and_rejects_stale_client_plan(optimizer_session_factory) -> None:
    generator = api_client(optimizer_session_factory)
    client = next(generator)
    try:
        chip_set = create_chip_set(client)
        solution = solve(client, chip_set["id"])
        candidate = solution["candidates"][0]
        client.put(
            f"/api/v1/chip-sets/{chip_set['id']}",
            json={"name": "Too small", "denominations": [{"value": 1_000, "quantity": 20}]},
        )

        response = client.post(
            "/api/v1/tournaments",
            json={
                "name": "Stale",
                "buy_in_amount": 1_000,
                "starting_stack": 20_000,
                "max_reentries_per_player": 2,
                "pin": "1234",
                "preset": "standard",
                "late_registration_end_level_number": 3,
                "players": [f"Игрок {index}" for index in range(8)],
                "payout_percentages": [100],
                "chip_plan": {
                    "chip_set_ids": [chip_set["id"]],
                    "initial_distribution": candidate["initial_distribution"],
                },
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "chip_plan_no_longer_feasible"
    finally:
        generator.close()

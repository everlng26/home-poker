from fastapi.testclient import TestClient

from app.main import app


def request_payload(**overrides):
    payload = {
        "players": 8,
        "starting_stack": 20_000,
        "expected_reentries": 2,
        "max_reentries_per_player": 2,
        "first_small_blind": 100,
        "first_big_blind": 200,
        "level_duration_minutes": 15,
        "target_duration_minutes": 300,
        "ante_mode": "big_blind",
        "ante_start_mode": "auto",
        "break_every_levels": 4,
        "break_duration_minutes": 10,
    }
    payload.update(overrides)
    return payload


def test_structure_generator_api_returns_blind_level_compatible_payload() -> None:
    response = TestClient(app).post("/api/v1/structure-generator", json=request_payload())

    assert response.status_code == 200
    result = response.json()
    assert result["summary"]["planned_total_chips"] == 200_000
    assert result["summary"]["starting_depth_bb"] == 100
    assert result["summary"]["expected_reentries"] == 2
    assert result["heuristic"]["actual_duration_is_guaranteed"] is False
    assert any(level["kind"] == "break" for level in result["levels"])
    assert all(
        set(level) >= {"kind", "duration_seconds", "small_blind", "big_blind", "ante"}
        for level in result["levels"]
        if level["kind"] == "play"
    )


def test_structure_generator_api_uses_optional_plan_denominations() -> None:
    response = TestClient(app).post(
        "/api/v1/structure-generator",
        json=request_payload(chip_denominations=[100, 500, 1_000]),
    )

    assert response.status_code == 200
    result = response.json()
    plays = [level for level in result["levels"] if level["kind"] == "play"]
    assert result["summary"]["chip_denominations"] == [100, 500, 1_000]
    assert all(level["small_blind"] % 100 == 0 for level in plays)
    assert all(level["big_blind"] % 100 == 0 for level in plays)


def test_structure_generator_api_reports_domain_errors_as_json() -> None:
    response = TestClient(app).post(
        "/api/v1/structure-generator",
        json=request_payload(expected_reentries=17),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "expected_reentries_exceed_limit"
    assert "текущем лимите" in response.json()["detail"]["message"]

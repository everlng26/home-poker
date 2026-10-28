from fastapi.testclient import TestClient

from app.main import app


def test_stack_optimizer_standalone_and_tournament_creation_ui() -> None:
    client = TestClient(app)
    page = client.get("/stack-optimizer")
    create_page = client.get("/tournaments/new")
    chips_page = client.get("/chips")
    script = client.get("/static/js/stack-optimizer.js")
    create_script = client.get("/static/js/create.js")
    css = client.get("/static/css/app.css")

    assert page.status_code == 200
    assert "Конструктор стеков" in page.text
    assert 'data-stack-optimizer-auto' in page.text
    assert 'data-role="chip-sets"' in page.text
    assert 'data-role="combined-summary"' in page.text
    assert 'data-field="players"' in page.text
    assert 'data-field="starting_stack"' in page.text
    assert 'data-field="max_reentries_per_player"' in page.text
    assert 'data-field="first_small_blind"' in page.text
    assert 'data-action="solve"' in page.text
    assert "stack-optimizer.js?v=20260814-3" in page.text
    assert 'href="/stack-optimizer"' in chips_page.text

    assert 'id="open-stack-optimizer"' in create_page.text
    assert 'id="create-stack-optimizer"' in create_page.text
    assert "Подобрать фишки" in create_page.text
    assert "create.js?v=20260816-4" in create_page.text
    assert "Использовать этот вариант" in script.text
    assert "chip_set_ids" in script.text
    assert "excluded_denominations" in script.text
    assert "max_reentries_per_player" in script.text
    assert "max_allowed_reentries" in script.text
    assert "Полное покрытие" in script.text
    assert "Частичное покрытие" in script.text
    assert "candidate.recommended ? 'Recommended' : candidate.label" not in script.text
    assert "stack-recommended-label" in script.text
    assert "Остаток после резерва" in script.text
    assert "Посмотреть номиналы и количество" in script.text
    assert "Запас на re-entry" in script.text
    assert "Перезапустите Home Poker" in script.text
    assert "response.headers.get('content-type')" in script.text
    assert "План физических фишек" not in create_page.text
    assert "План фишек" in create_page.text
    assert "Выберите физические наборы" in create_page.text
    assert "confirm(" not in script.text
    assert "alert(" not in script.text
    assert "prompt(" not in script.text
    assert "initStackOptimizer" in create_script.text
    assert "data.chip_plan = appliedChipPlan" in create_script.text
    assert "optimizerSignature" in create_script.text
    assert ".stack-candidate" in css.text
    assert ".stack-optimizer-dialog" in css.text
    assert ".stack-quality-highlights" in css.text
    assert ".stack-remaining-chevron" in css.text
    assert "env(safe-area-inset-bottom)" in css.text


def test_missing_api_route_returns_json_and_stale_optimizer_page_has_restart_hint() -> None:
    client = TestClient(app)

    missing_api = client.get("/api/v1/not-a-real-route")
    missing_page = client.get("/not-a-real-page")

    assert missing_api.status_code == 404
    assert missing_api.headers["content-type"].startswith("application/json")
    assert missing_api.json()["detail"]["code"] == "route_not_found"
    assert missing_page.status_code == 404
    assert "Проверьте адрес" in missing_page.text

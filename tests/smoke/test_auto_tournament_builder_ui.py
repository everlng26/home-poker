from fastapi.testclient import TestClient

from app.main import app


def test_auto_builder_is_optional_and_applies_to_existing_creation_editor() -> None:
    client = TestClient(app)
    page = client.get("/tournaments/new")
    script = client.get("/static/js/auto-tournament-builder.js")
    create_script = client.get("/static/js/create.js")
    css = client.get("/static/css/app.css")

    assert page.status_code == 200
    assert 'id="open-auto-tournament-builder"' in page.text
    assert 'id="create-auto-tournament-builder"' in page.text
    assert "Автоматически подобрать турнир" in page.text
    assert 'data-field="players"' in page.text
    assert 'data-field="max_reentries_per_player"' in page.text
    assert 'data-field="target_duration_minutes"' in page.text
    assert 'data-field="ante_mode"' in page.text
    assert 'data-field="starting_stack"' not in page.text.split(
        '<section class="auto-tournament-builder"', 1
    )[1].split("</section>", 1)[0]
    assert 'id="create-level-editor"' in page.text
    assert 'id="add-play"' in page.text
    assert 'id="add-break"' in page.text
    assert 'id="open-stack-optimizer"' in page.text
    assert 'id="open-structure-generator"' in page.text
    assert "create.js?v=20260816-4" in page.text

    assert "/api/v1/auto-tournament-builder" in script.text
    assert "chipSet.is_default" in script.text
    assert "Использовать этот вариант" in script.text
    assert "Посмотреть структуру" in script.text
    assert "initAutoTournamentBuilder" in create_script.text
    assert "renderLevels(plan.levels)" in create_script.text
    assert "plan.structure_denominations" in create_script.text
    assert "/api/v1/auto-tournament-builder/diagnostics" in create_script.text
    assert "Структура не изменена" in create_script.text
    assert "Текущие ручные изменения структуры будут заменены" in create_script.text
    assert "window.confirm" not in create_script.text
    assert "confirm(" not in create_script.text
    assert ".auto-builder-dialog" in css.text
    assert ".auto-draft-diagnostics" in css.text
    assert "env(safe-area-inset-bottom)" in css.text

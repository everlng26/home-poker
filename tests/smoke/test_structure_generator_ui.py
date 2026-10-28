from fastapi.testclient import TestClient

from app.main import app


def test_structure_generator_standalone_and_creation_integration() -> None:
    client = TestClient(app)
    page = client.get("/structure-generator")
    create_page = client.get("/tournaments/new")
    script = client.get("/static/js/structure-generator.js")
    create_script = client.get("/static/js/create.js")
    home_script = client.get("/static/js/home.js")
    css = client.get("/static/css/app.css")

    assert page.status_code == 200
    assert "Генератор структуры" in page.text
    assert "фактическое время окончания" in page.text
    assert 'data-structure-generator-auto' in page.text
    assert 'data-field="expected_reentries"' in page.text
    assert 'data-field="target_duration_minutes"' in page.text
    assert 'data-field="break_every_levels"' in page.text
    assert 'data-field="chip_denominations"' in page.text
    assert "structure-generator.js?v=20260816-2" in page.text

    assert 'id="open-structure-generator"' in create_page.text
    assert 'id="create-structure-generator"' in create_page.text
    assert "Использовать эту структуру" in create_page.text
    assert "create.js?v=20260816-4" in create_page.text
    assert "structure_generator" not in client.get("/api/v1/structure-presets").text

    assert "/api/v1/structure-generator" in script.text
    assert "actual_duration_is_guaranteed" not in script.text
    assert "Ориентировочное окно" in script.text
    assert "parseDenominations" in script.text
    assert "initStructureGenerator" in create_script.text
    assert "renderLevels(result.levels)" in create_script.text
    assert "appliedGeneratorSignature" in create_script.text
    assert "openDialog" in create_script.text
    assert "window.confirm" not in create_script.text
    assert "confirm(" not in create_script.text
    assert 'href="/structure-generator"' in home_script.text
    assert ".structure-generator-dialog" in css.text
    assert ".structure-generator [hidden]" in css.text
    assert "env(safe-area-inset-bottom)" in css.text

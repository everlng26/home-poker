from fastapi.testclient import TestClient

from app.main import app


def test_chip_inventory_pages_and_mobile_ui_assets() -> None:
    client = TestClient(app)
    list_page = client.get("/chips")
    create_page = client.get("/chips/new")
    edit_page = client.get("/chips/7/edit")
    list_script = client.get("/static/js/chips.js")
    form_script = client.get("/static/js/chip-form.js")
    home_script = client.get("/static/js/home.js")
    css = client.get("/static/css/app.css")

    assert list_page.status_code == 200
    assert "Фишки" in list_page.text
    assert 'id="chip-set-list"' in list_page.text
    assert "/chips/new" in list_page.text
    assert "chips.js?v=20261028-1" in list_page.text

    assert create_page.status_code == 200
    assert 'data-chip-set-id=""' in create_page.text
    assert 'id="chip-set-name"' in create_page.text
    assert 'id="chip-set-default"' in create_page.text
    assert 'id="chip-denomination-list"' in create_page.text
    assert 'id="add-denomination"' in create_page.text
    assert 'id="chip-total-count"' in create_page.text
    assert 'id="chip-total-value"' in create_page.text
    assert "chip-form.js?v=20261028-1" in create_page.text

    assert edit_page.status_code == 200
    assert 'data-chip-set-id="7"' in edit_page.text
    assert "Изменить набор фишек" in edit_page.text

    assert "openDialog" in list_script.text
    assert "confirm(" not in list_script.text
    assert "location.reload" not in list_script.text
    assert "Intl.NumberFormat('ru-RU')" in list_script.text
    assert "chipSet.denominations" in list_script.text
    assert "type = 'number'" in form_script.text
    assert "inputMode = 'numeric'" in form_script.text
    assert "quantityInput.min = '0'" in form_script.text
    assert "sortRows()" in form_script.text
    assert "Number.isSafeInteger" in form_script.text
    assert "Такой номинал уже есть" in form_script.text
    assert 'href="/chips"' in home_script.text
    assert ".chip-denomination-row" in css.text
    assert ".chip-remove-denomination" in css.text
    assert "calc(28px + env(safe-area-inset-bottom))" in css.text
    assert "grid-template-columns: minmax(0, 1fr) 20px minmax(0, 1fr)" in css.text

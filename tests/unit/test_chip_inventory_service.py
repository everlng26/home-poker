import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import AppSetting, ChipDenomination, ChipSet
from app.services import ChipInventoryService, DomainError
from app.services.chip_inventory_service import DEFAULT_CHIP_SET_SETTING


MAIN_DENOMINATIONS = [
    {"value": 5_000, "quantity": 40},
    {"value": 25, "quantity": 100},
    {"value": 500, "quantity": 80},
    {"value": 100, "quantity": 100},
    {"value": 1_000, "quantity": 80},
]


def test_create_read_and_server_calculations(session) -> None:
    created = ChipInventoryService.create(
        session,
        name="  Основной набор  ",
        denominations=MAIN_DENOMINATIONS,
    )

    assert created["name"] == "Основной набор"
    assert created["total_chips"] == 400
    assert created["total_value"] == 332_500
    assert [item["value"] for item in created["denominations"]] == [25, 100, 500, 1_000, 5_000]

    session.expunge_all()
    persisted = ChipInventoryService.get(session, created["id"])
    assert persisted == created


def test_update_add_edit_delete_and_recalculate(session) -> None:
    created = ChipInventoryService.create(
        session,
        name="Основной набор",
        denominations=MAIN_DENOMINATIONS,
    )
    updated = ChipInventoryService.update(
        session,
        created["id"],
        name="Большой кейс",
        denominations=[
            {"value": 25, "quantity": 100},
            {"value": 100, "quantity": 100},
            {"value": 500, "quantity": 75},
            {"value": 1_000, "quantity": 80},
            {"value": 25_000, "quantity": 20},
        ],
    )

    assert updated["name"] == "Большой кейс"
    assert updated["total_chips"] == 375
    assert updated["total_value"] == 630_000
    assert updated["updated_at"] > created["updated_at"]
    assert [item["value"] for item in updated["denominations"]] == [25, 100, 500, 1_000, 25_000]
    assert updated["denominations"][2] == {"value": 500, "quantity": 75}


def test_multiple_sets_and_zero_quantity(session) -> None:
    first = ChipInventoryService.create(
        session,
        name="Основной набор",
        denominations=[{"value": 25, "quantity": 0}],
    )
    second = ChipInventoryService.create(
        session,
        name="Маленький кейс",
        denominations=[{"value": 100, "quantity": 50}],
    )

    assert first["total_chips"] == 0
    assert first["total_value"] == 0
    listed = ChipInventoryService.list(session)
    assert [item["id"] for item in listed] == [second["id"], first["id"]]


@pytest.mark.parametrize(
    ("denominations", "code"),
    [
        ([{"value": 0, "quantity": 1}], "invalid_denomination_value"),
        ([{"value": -25, "quantity": 1}], "invalid_denomination_value"),
        ([{"value": 25.5, "quantity": 1}], "invalid_denomination_value"),
        ([{"value": 25, "quantity": -1}], "invalid_denomination_quantity"),
        ([{"value": 25, "quantity": 1.5}], "invalid_denomination_quantity"),
        (
            [{"value": 25, "quantity": 100}, {"value": 25, "quantity": 50}],
            "duplicate_denomination",
        ),
    ],
)
def test_denomination_validation(session, denominations, code) -> None:
    with pytest.raises(DomainError) as captured:
        ChipInventoryService.create(session, name="Набор", denominations=denominations)
    assert captured.value.code == code


def test_default_switch_and_delete_default(session) -> None:
    first = ChipInventoryService.create(
        session,
        name="Первый",
        denominations=[],
        is_default=True,
    )
    second = ChipInventoryService.create(session, name="Второй", denominations=[])

    switched = ChipInventoryService.set_default(session, second["id"])
    assert switched["is_default"] is True
    setting = session.get(AppSetting, DEFAULT_CHIP_SET_SETTING)
    assert setting is not None
    assert setting.value_json == {"id": second["id"]}
    session.rollback()

    listed = ChipInventoryService.list(session)
    assert [item["is_default"] for item in listed] == [True, False]
    session.rollback()

    ChipInventoryService.delete(session, second["id"])
    assert session.get(AppSetting, DEFAULT_CHIP_SET_SETTING) is None
    assert session.get(ChipSet, first["id"]) is not None


def test_delete_cascades_denominations_without_orphans(session) -> None:
    created = ChipInventoryService.create(
        session,
        name="Удаляемый",
        denominations=[{"value": 25, "quantity": 10}, {"value": 100, "quantity": 20}],
    )
    assert session.scalar(select(func.count()).select_from(ChipDenomination)) == 2
    session.rollback()

    ChipInventoryService.delete(session, created["id"])

    assert session.get(ChipSet, created["id"]) is None
    assert session.scalar(select(func.count()).select_from(ChipDenomination)) == 0


def test_database_constraints_reject_duplicate_and_invalid_rows(session) -> None:
    chip_set = ChipSet(name="DB constraint")
    chip_set.denominations = [
        ChipDenomination(value=25, quantity=1),
        ChipDenomination(value=25, quantity=2),
    ]
    session.add(chip_set)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    chip_set = ChipSet(name="DB checks")
    chip_set.denominations = [ChipDenomination(value=100, quantity=-1)]
    session.add(chip_set)
    with pytest.raises(IntegrityError):
        session.commit()

"""Бизнес-логика каталога физических наборов фишек."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.chip_inventory import ChipDenomination, ChipSet, utc_now
from app.models.tournament import AppSetting, as_utc
from app.services.errors import DomainError


DEFAULT_CHIP_SET_SETTING = "default_chip_set_id"


class ChipInventoryService:
    @staticmethod
    def _name(raw_name: Any) -> str:
        name = str(raw_name).strip()
        if not name:
            raise DomainError("invalid_chip_set_name", "Введите название набора фишек.")
        if len(name) > 160:
            raise DomainError(
                "invalid_chip_set_name", "Название набора не должно быть длиннее 160 символов."
            )
        return name

    @staticmethod
    def _integer(raw_value: Any, *, field: str, message: str) -> int:
        if isinstance(raw_value, bool):
            raise DomainError(field, message)
        if isinstance(raw_value, int):
            return raw_value
        if isinstance(raw_value, str):
            candidate = raw_value.strip()
            if candidate and candidate.lstrip("+").isdigit():
                return int(candidate)
        raise DomainError(field, message)

    @classmethod
    def _denominations(cls, raw_items: Any) -> list[tuple[int, int]]:
        if raw_items is None:
            return []
        if not isinstance(raw_items, list):
            raise DomainError("invalid_denominations", "Передайте номиналы списком.")

        normalized: list[tuple[int, int]] = []
        seen: set[int] = set()
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise DomainError("invalid_denominations", "Проверьте строки номиналов.")
            value = cls._integer(
                raw_item.get("value"),
                field="invalid_denomination_value",
                message="Номинал должен быть целым положительным числом.",
            )
            quantity = cls._integer(
                raw_item.get("quantity"),
                field="invalid_denomination_quantity",
                message="Количество должно быть целым неотрицательным числом.",
            )
            if value <= 0:
                raise DomainError(
                    "invalid_denomination_value", "Номинал должен быть целым положительным числом."
                )
            if quantity < 0:
                raise DomainError(
                    "invalid_denomination_quantity",
                    "Количество должно быть целым неотрицательным числом.",
                )
            if value in seen:
                formatted_value = f"{value:,}".replace(",", " ")
                raise DomainError(
                    "duplicate_denomination",
                    f"Номинал {formatted_value} уже есть в этом наборе.",
                )
            seen.add(value)
            normalized.append((value, quantity))
        return sorted(normalized)

    @staticmethod
    def _default_id(session: Session) -> int | None:
        setting = session.get(AppSetting, DEFAULT_CHIP_SET_SETTING)
        if setting is None or not isinstance(setting.value_json, dict):
            return None
        value = setting.value_json.get("id")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _write_default(session: Session, chip_set_id: int | None) -> None:
        setting = session.get(AppSetting, DEFAULT_CHIP_SET_SETTING)
        if chip_set_id is None:
            if setting is not None:
                session.delete(setting)
            return
        if setting is None:
            session.add(AppSetting(key=DEFAULT_CHIP_SET_SETTING, value_json={"id": chip_set_id}))
        else:
            setting.value_json = {"id": chip_set_id}

    @staticmethod
    def _query():
        return select(ChipSet).options(selectinload(ChipSet.denominations))

    @classmethod
    def list(cls, session: Session) -> list[dict[str, Any]]:
        default_id = cls._default_id(session)
        chip_sets = session.scalars(cls._query().order_by(ChipSet.id.desc())).all()
        return [cls.serialize(chip_set, default_id=default_id) for chip_set in chip_sets]

    @classmethod
    def get(cls, session: Session, chip_set_id: int) -> dict[str, Any]:
        chip_set = session.scalar(cls._query().where(ChipSet.id == chip_set_id))
        if chip_set is None:
            raise DomainError("chip_set_not_found", "Набор фишек не найден.")
        return cls.serialize(chip_set, default_id=cls._default_id(session))

    @classmethod
    def create(
        cls,
        session: Session,
        *,
        name: Any,
        denominations: Any,
        is_default: bool = False,
    ) -> dict[str, Any]:
        normalized_name = cls._name(name)
        normalized_denominations = cls._denominations(denominations)
        with session.begin():
            chip_set = ChipSet(name=normalized_name)
            chip_set.denominations = [
                ChipDenomination(value=value, quantity=quantity)
                for value, quantity in normalized_denominations
            ]
            session.add(chip_set)
            session.flush()
            if is_default:
                cls._write_default(session, chip_set.id)
        return cls.serialize(chip_set, default_id=chip_set.id if is_default else None)

    @classmethod
    def update(
        cls,
        session: Session,
        chip_set_id: int,
        *,
        name: Any,
        denominations: Any,
        is_default: bool | None = None,
    ) -> dict[str, Any]:
        normalized_name = cls._name(name)
        normalized_denominations = cls._denominations(denominations)
        resulting_default_id: int | None = None
        with session.begin():
            chip_set = session.scalar(cls._query().where(ChipSet.id == chip_set_id))
            if chip_set is None:
                raise DomainError("chip_set_not_found", "Набор фишек не найден.")
            chip_set.name = normalized_name
            chip_set.updated_at = utc_now()
            for denomination in list(chip_set.denominations):
                session.delete(denomination)
            session.flush()
            chip_set.denominations = [
                ChipDenomination(value=value, quantity=quantity)
                for value, quantity in normalized_denominations
            ]
            if is_default is True:
                cls._write_default(session, chip_set.id)
                resulting_default_id = chip_set.id
            elif is_default is False and cls._default_id(session) == chip_set.id:
                cls._write_default(session, None)
            else:
                resulting_default_id = cls._default_id(session)
        return cls.serialize(chip_set, default_id=resulting_default_id)

    @classmethod
    def set_default(cls, session: Session, chip_set_id: int) -> dict[str, Any]:
        with session.begin():
            chip_set = session.scalar(cls._query().where(ChipSet.id == chip_set_id))
            if chip_set is None:
                raise DomainError("chip_set_not_found", "Набор фишек не найден.")
            cls._write_default(session, chip_set.id)
        return cls.serialize(chip_set, default_id=chip_set.id)

    @classmethod
    def delete(cls, session: Session, chip_set_id: int) -> None:
        with session.begin():
            chip_set = session.get(ChipSet, chip_set_id)
            if chip_set is None:
                raise DomainError("chip_set_not_found", "Набор фишек не найден.")
            if cls._default_id(session) == chip_set.id:
                cls._write_default(session, None)
            session.delete(chip_set)

    @staticmethod
    def serialize(chip_set: ChipSet, *, default_id: int | None) -> dict[str, Any]:
        denominations = sorted(chip_set.denominations, key=lambda item: item.value)
        return {
            "id": chip_set.id,
            "name": chip_set.name,
            "is_default": chip_set.id == default_id,
            "total_chips": sum(item.quantity for item in denominations),
            "total_value": sum(item.value * item.quantity for item in denominations),
            "denominations": [
                {"value": item.value, "quantity": item.quantity} for item in denominations
            ],
            "created_at": as_utc(chip_set.created_at).isoformat(),
            "updated_at": as_utc(chip_set.updated_at).isoformat(),
        }

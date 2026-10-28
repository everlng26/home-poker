"""SQLAlchemy-модели физических наборов покерных фишек."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class ChipSet(Base):
    __tablename__ = "chip_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    denominations: Mapped[list[ChipDenomination]] = relationship(
        back_populates="chip_set",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ChipDenomination.value",
    )


class ChipDenomination(Base):
    __tablename__ = "chip_denominations"

    id: Mapped[int] = mapped_column(primary_key=True)
    chip_set_id: Mapped[int] = mapped_column(
        ForeignKey("chip_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    chip_set: Mapped[ChipSet] = relationship(back_populates="denominations")

    __table_args__ = (
        UniqueConstraint("chip_set_id", "value", name="uq_chip_denominations_chip_set_value"),
        CheckConstraint("value > 0", name="ck_chip_denominations_value_positive"),
        CheckConstraint("quantity >= 0", name="ck_chip_denominations_quantity_nonnegative"),
    )

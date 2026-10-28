"""SQLAlchemy-модели предметной области турнира."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Boolean,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import BountyMode, BlindLevelKind, TimerStatus, TournamentPlayerStatus, TournamentStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Возвращает время в UTC, включая значения, прочитанные SQLite без tzinfo."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def string_enum(enum_class: type[BountyMode | BlindLevelKind | TimerStatus | TournamentPlayerStatus | TournamentStatus]) -> Enum:
    return Enum(
        enum_class,
        values_callable=lambda enum_type: [member.value for member in enum_type],
        native_enum=False,
        create_constraint=True,
    )


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tournament_entries: Mapped[list[TournamentPlayer]] = relationship(back_populates="player")


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    buy_in_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    bounty_mode: Mapped[BountyMode] = mapped_column(
        string_enum(BountyMode), default=BountyMode.NONE, nullable=False
    )
    bounty_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    currency_label: Mapped[str] = mapped_column(String(16), nullable=False, default="₽")
    starting_stack: Mapped[int] = mapped_column(Integer, nullable=False)
    max_reentries_per_player: Mapped[int | None] = mapped_column(Integer)
    ante_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[TournamentStatus] = mapped_column(string_enum(TournamentStatus), default=TournamentStatus.DRAFT, nullable=False)
    is_manually_finished: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_level_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    late_registration_end_level_index: Mapped[int | None] = mapped_column(Integer)
    payouts_finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timer_status: Mapped[TimerStatus] = mapped_column(string_enum(TimerStatus), default=TimerStatus.PAUSED, nullable=False)
    level_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_remaining_seconds: Mapped[int | None] = mapped_column(Integer)
    auto_advance_levels: Mapped[bool] = mapped_column(default=True, nullable=False)
    admin_pin_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    timer_last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timer_last_remaining_seconds: Mapped[int | None] = mapped_column(Integer)
    one_minute_warning_level_index: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    players: Mapped[list[TournamentPlayer]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan", passive_deletes=True
    )
    levels: Mapped[list[BlindLevel]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan", passive_deletes=True, order_by="BlindLevel.order_index"
    )
    events: Mapped[list[TournamentEvent]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan", passive_deletes=True
    )
    payouts: Mapped[list[TournamentPayout]] = relationship(
        back_populates="tournament",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TournamentPayout.place",
    )
    chip_plan: Mapped[TournamentChipPlan | None] = relationship(
        back_populates="tournament",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )

    __table_args__ = (
        CheckConstraint("buy_in_amount >= 0", name="ck_tournaments_buy_in_nonnegative"),
        CheckConstraint(
            "(bounty_mode = 'none' AND bounty_amount = 0) OR "
            "(bounty_mode = 'fixed' AND bounty_amount > 0 AND bounty_amount < buy_in_amount)",
            name="ck_tournaments_bounty_configuration",
        ),
        CheckConstraint("starting_stack > 0", name="ck_tournaments_starting_stack_positive"),
        CheckConstraint(
            "max_reentries_per_player IS NULL OR max_reentries_per_player >= 0",
            name="ck_tournaments_reentry_limit_nonnegative",
        ),
        CheckConstraint("current_level_index >= 0", name="ck_tournaments_current_level_nonnegative"),
        CheckConstraint(
            "late_registration_end_level_index IS NULL OR late_registration_end_level_index >= 0",
            name="ck_tournaments_late_registration_end_nonnegative",
        ),
        CheckConstraint(
            "paused_remaining_seconds IS NULL OR paused_remaining_seconds >= 0",
            name="ck_tournaments_paused_remaining_nonnegative",
        ),
        CheckConstraint("state_version >= 0", name="ck_tournaments_state_version_nonnegative"),
    )


class TournamentChipPlan(Base):
    """Неизменяемый снимок физического плана фишек на момент создания турнира."""

    __tablename__ = "tournament_chip_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    selected_chip_sets_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    combined_inventory_json: Mapped[list[dict[str, int]]] = mapped_column(JSON, nullable=False)
    planned_players: Mapped[int] = mapped_column(Integer, nullable=False)
    starting_stack: Mapped[int] = mapped_column(Integer, nullable=False)
    max_reentries_per_player: Mapped[int] = mapped_column(Integer, nullable=False)
    max_total_reentries: Mapped[int] = mapped_column(Integer, nullable=False)
    covered_reentries: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_distribution_json: Mapped[list[dict[str, int]]] = mapped_column(JSON, nullable=False)
    reentry_distribution_json: Mapped[list[dict[str, int]]] = mapped_column(JSON, nullable=False)
    reserved_quantities_json: Mapped[list[dict[str, int]]] = mapped_column(JSON, nullable=False)
    remaining_inventory_json: Mapped[list[dict[str, int]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    tournament: Mapped[Tournament] = relationship(back_populates="chip_plan")

    __table_args__ = (
        CheckConstraint("planned_players > 0", name="ck_tournament_chip_plans_players_positive"),
        CheckConstraint("starting_stack > 0", name="ck_tournament_chip_plans_stack_positive"),
        CheckConstraint(
            "max_reentries_per_player >= 0",
            name="ck_tournament_chip_plans_reentry_limit_nonnegative",
        ),
        CheckConstraint(
            "max_total_reentries = planned_players * max_reentries_per_player",
            name="ck_tournament_chip_plans_max_reentries_consistent",
        ),
        CheckConstraint(
            "covered_reentries >= 0 AND covered_reentries <= max_total_reentries",
            name="ck_tournament_chip_plans_coverage_range",
        ),
    )


class TournamentPayout(Base):
    __tablename__ = "tournament_payouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    place: Mapped[int] = mapped_column(Integer, nullable=False)
    percentage_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)

    tournament: Mapped[Tournament] = relationship(back_populates="payouts")

    __table_args__ = (
        UniqueConstraint("tournament_id", "place", name="uq_tournament_payouts_tournament_place"),
        CheckConstraint("place > 0", name="ck_tournament_payouts_place_positive"),
        CheckConstraint(
            "percentage_basis_points > 0 AND percentage_basis_points <= 10000",
            name="ck_tournament_payouts_percentage_range",
        ),
    )


class TournamentPlayer(Base):
    __tablename__ = "tournament_players"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="RESTRICT"), nullable=False, index=True)
    seat_number: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[TournamentPlayerStatus] = mapped_column(
        string_enum(TournamentPlayerStatus), default=TournamentPlayerStatus.REGISTERED, nullable=False
    )
    entries_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    elimination_place: Mapped[int | None] = mapped_column(Integer)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    eliminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tournament: Mapped[Tournament] = relationship(back_populates="players")
    player: Mapped[Player] = relationship(back_populates="tournament_entries")

    __table_args__ = (
        UniqueConstraint("tournament_id", "player_id", name="uq_tournament_players_tournament_player"),
        CheckConstraint("entries_count >= 1", name="ck_tournament_players_entries_positive"),
        CheckConstraint("seat_number IS NULL OR seat_number > 0", name="ck_tournament_players_seat_positive"),
        CheckConstraint(
            "elimination_place IS NULL OR elimination_place > 0",
            name="ck_tournament_players_elimination_place_positive",
        ),
        Index(
            "ux_tournament_players_seat",
            "tournament_id",
            "seat_number",
            unique=True,
            sqlite_where=seat_number.is_not(None),
        ),
    )


class BlindLevel(Base):
    __tablename__ = "blind_levels"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[BlindLevelKind] = mapped_column(string_enum(BlindLevelKind), nullable=False)
    small_blind: Mapped[int | None] = mapped_column(Integer)
    big_blind: Mapped[int | None] = mapped_column(Integer)
    ante: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(120))

    tournament: Mapped[Tournament] = relationship(back_populates="levels")

    __table_args__ = (
        UniqueConstraint("tournament_id", "order_index", name="uq_blind_levels_tournament_order"),
        CheckConstraint("order_index >= 0", name="ck_blind_levels_order_nonnegative"),
        CheckConstraint("duration_seconds > 0", name="ck_blind_levels_duration_positive"),
        CheckConstraint("ante IS NULL OR ante >= 0", name="ck_blind_levels_ante_nonnegative"),
        CheckConstraint(
            "(kind = 'play' AND small_blind > 0 AND big_blind >= small_blind) "
            "OR (kind = 'break' AND small_blind IS NULL AND big_blind IS NULL AND ante IS NULL)",
            name="ck_blind_levels_kind_values",
        ),
    )


class TournamentEvent(Base):
    __tablename__ = "tournament_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_reversible: Mapped[bool] = mapped_column(default=False, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversal_event_id: Mapped[int | None] = mapped_column(ForeignKey("tournament_events.id", ondelete="RESTRICT"))

    tournament: Mapped[Tournament] = relationship(back_populates="events")
    reversal_event: Mapped[TournamentEvent | None] = relationship(remote_side=[id], uselist=False)

    __table_args__ = (
        UniqueConstraint("tournament_id", "request_id", name="uq_tournament_events_request"),
        Index("ix_tournament_events_reversible", "tournament_id", "is_reversible", "reversed_at"),
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

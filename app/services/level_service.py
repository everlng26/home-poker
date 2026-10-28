from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import BlindLevelKind, TournamentStatus
from app.models.tournament import BlindLevel, Tournament, as_utc, utc_now
from app.services.errors import DomainError
from app.services.event_service import EventService
from app.services.timer_service import TimerService

STRUCTURE_PRESETS: dict[str, list[dict[str, Any]]] = {
    "fast": [
        {"kind": "play", "small_blind": 25, "big_blind": 50, "ante": 50, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 50, "big_blind": 100, "ante": 100, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 75, "big_blind": 150, "ante": 150, "duration_seconds": 1200},
        {"kind": "break", "duration_seconds": 1200, "title": "Перерыв"},
        {"kind": "play", "small_blind": 100, "big_blind": 200, "ante": 200, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 150, "big_blind": 300, "ante": 300, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 200, "big_blind": 400, "ante": 400, "duration_seconds": 1200},
        {"kind": "break", "duration_seconds": 1200, "title": "Перерыв"},
        {"kind": "play", "small_blind": 300, "big_blind": 600, "ante": 600, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 400, "big_blind": 800, "ante": 800, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 500, "big_blind": 1000, "ante": 1000, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 600, "big_blind": 1200, "ante": 1200, "duration_seconds": 1200},
    ],
    "standard": [
        {"kind": "play", "small_blind": 25, "big_blind": 50, "ante": 50, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 50, "big_blind": 100, "ante": 100, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 75, "big_blind": 150, "ante": 150, "duration_seconds": 1200},
        {"kind": "break", "duration_seconds": 1200, "title": "Перерыв"},
        {"kind": "play", "small_blind": 100, "big_blind": 200, "ante": 200, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 150, "big_blind": 300, "ante": 300, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 200, "big_blind": 400, "ante": 400, "duration_seconds": 1200},
        {"kind": "break", "duration_seconds": 1200, "title": "Перерыв"},
        {"kind": "play", "small_blind": 300, "big_blind": 600, "ante": 600, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 400, "big_blind": 800, "ante": 800, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 500, "big_blind": 1000, "ante": 1000, "duration_seconds": 1200},
        {"kind": "break", "duration_seconds": 1200, "title": "Перерыв"},
        {"kind": "play", "small_blind": 600, "big_blind": 1200, "ante": 1200, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 800, "big_blind": 1600, "ante": 1600, "duration_seconds": 1200},
        {"kind": "play", "small_blind": 1000, "big_blind": 2000, "ante": 2000, "duration_seconds": 1200},
    ],
    "deep": [
        {"kind": "play", "small_blind": 25, "big_blind": 50, "ante": 50, "duration_seconds": 1800},
        {"kind": "play", "small_blind": 50, "big_blind": 100, "ante": 100, "duration_seconds": 1800},
        {"kind": "play", "small_blind": 75, "big_blind": 150, "ante": 150, "duration_seconds": 1800},
        {"kind": "break", "duration_seconds": 900, "title": "Перерыв"},
        {"kind": "play", "small_blind": 100, "big_blind": 200, "ante": 200, "duration_seconds": 1800},
        {"kind": "play", "small_blind": 150, "big_blind": 300, "ante": 300, "duration_seconds": 1800},
        {"kind": "play", "small_blind": 200, "big_blind": 400, "ante": 400, "duration_seconds": 1800},
        {"kind": "break", "duration_seconds": 900, "title": "Перерыв"},
        {"kind": "play", "small_blind": 300, "big_blind": 600, "ante": 600, "duration_seconds": 1800},
        {"kind": "play", "small_blind": 500, "big_blind": 1000, "ante": 1000, "duration_seconds": 1800},
        {"kind": "break", "duration_seconds": 900, "title": "Перерыв"},
        {"kind": "play", "small_blind": 800, "big_blind": 1600, "ante": 1600, "duration_seconds": 1800},
        {"kind": "break", "duration_seconds": 900, "title": "Перерыв"},
        {"kind": "play", "small_blind": 1000, "big_blind": 2000, "ante": 2000, "duration_seconds": 1800},
    ],
}


class LevelService:
    @staticmethod
    def replace_levels(
        session: Session,
        tournament_id: int,
        levels: list[dict[str, Any]],
        request_id: str | None = None,
        late_registration_end_level_index: int | None = None,
    ) -> list[BlindLevel]:
        if not levels:
            raise DomainError("empty_structure", "Добавьте хотя бы один уровень.")
        with session.begin():
            tournament = session.get(Tournament, tournament_id)
            if tournament is None:
                raise DomainError("tournament_not_found", "Турнир не найден.")
            if tournament.status == TournamentStatus.FINISHED:
                raise DomainError("structure_locked", "В завершённом турнире структуру менять нельзя.")
            old_levels = list(
                session.scalars(
                    select(BlindLevel).where(BlindLevel.tournament_id == tournament_id).order_by(BlindLevel.order_index)
                )
            )
            old_current_position = next(
                (index for index, level in enumerate(old_levels) if level.order_index == tournament.current_level_index),
                0,
            )
            old_current = old_levels[old_current_position] if old_levels else None
            if late_registration_end_level_index is None:
                raise DomainError(
                    "invalid_late_registration_end",
                    "Укажите игровой уровень окончания поздней регистрации.",
                )
            if not 0 <= late_registration_end_level_index < len(levels):
                raise DomainError("invalid_late_registration_end", "Выберите уровень окончания поздней регистрации из структуры.")
            try:
                cutoff_kind = BlindLevelKind(levels[late_registration_end_level_index]["kind"])
            except (KeyError, TypeError, ValueError) as error:
                raise DomainError("invalid_late_registration_end", "Выберите игровой уровень окончания поздней регистрации.") from error
            if cutoff_kind != BlindLevelKind.PLAY:
                raise DomainError("invalid_late_registration_end", "Поздняя регистрация должна заканчиваться после игрового уровня.")
            old_remaining = None
            if old_current is not None:
                if tournament.timer_status.value == "running":
                    old_remaining = TimerService.remaining_seconds(tournament, old_current)
                else:
                    old_remaining = tournament.paused_remaining_seconds or old_current.duration_seconds
            for level in old_levels:
                session.delete(level)
            session.flush()
            created: list[BlindLevel] = []
            for index, data in enumerate(levels):
                kind = BlindLevelKind(data["kind"])
                if kind == BlindLevelKind.PLAY:
                    big_blind = int(data["big_blind"])
                    raw_ante = data.get("ante")
                    level = BlindLevel(
                        tournament_id=tournament_id,
                        order_index=index,
                        kind=kind,
                        small_blind=int(data["small_blind"]),
                        big_blind=big_blind,
                        ante=0 if not tournament.ante_enabled else big_blind if raw_ante in (None, "") else int(raw_ante),
                        duration_seconds=int(data["duration_seconds"]),
                        title=data.get("title") or None,
                    )
                else:
                    level = BlindLevel(
                        tournament_id=tournament_id,
                        order_index=index,
                        kind=kind,
                        small_blind=None,
                        big_blind=None,
                        ante=None,
                        duration_seconds=int(data["duration_seconds"]),
                        title="Перерыв",
                    )
                session.add(level)
                created.append(level)
            tournament.late_registration_end_level_index = late_registration_end_level_index
            if created:
                current_position = min(old_current_position, len(created) - 1)
                current = created[current_position]
                tournament.current_level_index = current.order_index
                if tournament.timer_status.value == "running":
                    remaining = min(old_remaining if old_remaining is not None else current.duration_seconds, current.duration_seconds)
                    tournament.level_started_at = as_utc(utc_now()) - timedelta(seconds=current.duration_seconds - remaining)
                    tournament.paused_remaining_seconds = None
                    tournament.timer_last_remaining_seconds = remaining
                elif tournament.timer_status.value == "paused":
                    tournament.level_started_at = None
                    tournament.paused_remaining_seconds = min(
                        old_remaining if old_remaining is not None else current.duration_seconds, current.duration_seconds
                    )
            EventService.record(
                session,
                tournament,
                "structure_replaced",
                {
                    "levels_count": len(created),
                    "late_registration_end_level_index": late_registration_end_level_index,
                },
                request_id=request_id,
            )
            return created

    @staticmethod
    def apply_preset(
        session: Session, tournament_id: int, preset_name: str, request_id: str | None = None
    ) -> list[BlindLevel]:
        preset = STRUCTURE_PRESETS.get(preset_name)
        if preset is None:
            raise DomainError("unknown_preset", "Неизвестная типовая структура.")
        return LevelService.replace_levels(session, tournament_id, preset, request_id=request_id)

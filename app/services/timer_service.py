from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.enums import TimerStatus, TournamentPlayerStatus, TournamentStatus
from app.models.tournament import BlindLevel, Tournament, TournamentPlayer, as_utc, utc_now
from app.services.errors import DomainError
from app.services.bounty_service import BountyService
from app.services.event_service import EventService
from app.services.payout_service import PayoutService

TimerAction = Literal["start", "pause", "resume", "reset", "next", "previous", "jump", "add_60", "subtract_60", "toggle_auto"]


class TournamentLockRegistry:
    def __init__(self) -> None:
        self._guard = Lock()
        self._locks: dict[int, Lock] = {}

    def lock_for(self, tournament_id: int) -> Lock:
        with self._guard:
            return self._locks.setdefault(tournament_id, Lock())


tournament_locks = TournamentLockRegistry()


class TimerService:
    @staticmethod
    def _levels(session: Session, tournament_id: int) -> list[BlindLevel]:
        return list(
            session.scalars(
                select(BlindLevel).where(BlindLevel.tournament_id == tournament_id).order_by(BlindLevel.order_index)
            )
        )

    @staticmethod
    def _reopen_automatic_finish(session: Session, tournament: Tournament, now: datetime) -> None:
        """Возвращает автоматически завершённый турнир в редактируемое состояние."""
        BountyService.revoke_champion_bounty(session, tournament)
        tournament.status = TournamentStatus.PAUSED
        tournament.timer_status = TimerStatus.PAUSED
        tournament.level_started_at = None
        tournament.paused_remaining_seconds = 0
        tournament.timer_last_observed_at = now
        tournament.timer_last_remaining_seconds = 0
        tournament.one_minute_warning_level_index = None
        session.execute(
            update(TournamentPlayer)
            .where(
                TournamentPlayer.tournament_id == tournament.id,
                TournamentPlayer.elimination_place == 1,
            )
            .values(elimination_place=None)
        )
        EventService.record(session, tournament, "tournament_reopened", {"reason": "timer_recovery"})

    @staticmethod
    def remaining_seconds(tournament: Tournament, level: BlindLevel, now: datetime | None = None) -> int:
        now = as_utc(now or utc_now())
        if tournament.timer_status == TimerStatus.PAUSED:
            # Не начатый уровень хранится без остатка: resume и ±60 считают его полным, табло тоже.
            if tournament.paused_remaining_seconds is None:
                return level.duration_seconds
            return max(0, tournament.paused_remaining_seconds)
        if tournament.timer_status != TimerStatus.RUNNING or tournament.level_started_at is None:
            return level.duration_seconds
        started_at = as_utc(tournament.level_started_at)
        return max(0, level.duration_seconds - int((now - started_at).total_seconds()))

    @staticmethod
    def _activate_level(tournament: Tournament, level: BlindLevel, now: datetime) -> None:
        tournament.current_level_index = level.order_index
        tournament.level_started_at = now
        tournament.paused_remaining_seconds = None
        tournament.timer_last_observed_at = now
        tournament.timer_last_remaining_seconds = level.duration_seconds
        tournament.one_minute_warning_level_index = None

    @staticmethod
    def reconcile(session: Session, tournament_id: int, now: datetime | None = None) -> bool:
        """Продвигает уровни после сна или истечения времени. Возвращает факт изменения."""
        now = as_utc(now or utc_now())
        tournament = session.get(Tournament, tournament_id)
        if tournament is None or tournament.timer_status != TimerStatus.RUNNING:
            return False
        levels = TimerService._levels(session, tournament_id)
        if not levels:
            return False
        changed = False
        while True:
            level = next((item for item in levels if item.order_index == tournament.current_level_index), None)
            if level is None:
                raise DomainError("timer_level_missing", "Текущий уровень таймера не найден.")
            remaining = TimerService.remaining_seconds(tournament, level, now)
            tournament.timer_last_observed_at = now
            tournament.timer_last_remaining_seconds = remaining
            if remaining > 60 and tournament.one_minute_warning_level_index is not None:
                tournament.one_minute_warning_level_index = None
                changed = True
            if remaining <= 60 and remaining > 0 and tournament.one_minute_warning_level_index != level.order_index:
                tournament.one_minute_warning_level_index = level.order_index
                changed = True
            if remaining > 0:
                return changed
            changed = True
            current_position = levels.index(level)
            if not tournament.auto_advance_levels:
                tournament.timer_status = TimerStatus.PAUSED
                tournament.status = TournamentStatus.PAUSED
                tournament.paused_remaining_seconds = 0
                return True
            if current_position + 1 >= len(levels):
                tournament.timer_status = TimerStatus.STOPPED
                tournament.status = TournamentStatus.FINISHED
                tournament.paused_remaining_seconds = 0
                PayoutService.reconcile_finalization(session, tournament)
                return True
            next_level = levels[current_position + 1]
            scheduled_start = as_utc(tournament.level_started_at or now) + timedelta(seconds=level.duration_seconds)
            TimerService._activate_level(tournament, next_level, scheduled_start)
            PayoutService.reconcile_finalization(session, tournament)

    @staticmethod
    def command(
        session: Session,
        tournament_id: int,
        action: TimerAction,
        *,
        target_level_index: int | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> Tournament:
        now = as_utc(now or utc_now())
        with tournament_locks.lock_for(tournament_id), session.begin():
            tournament = session.get(Tournament, tournament_id)
            if tournament is None:
                raise DomainError("tournament_not_found", "Турнир не найден.")
            if tournament.is_manually_finished:
                raise DomainError("tournament_locked", "Турнир завершён и заблокирован для изменений.")
            levels = TimerService._levels(session, tournament_id)
            if not levels:
                raise DomainError("structure_required", "Сначала добавьте структуру уровней.")
            TimerService.reconcile(session, tournament_id, now)
            level = next((item for item in levels if item.order_index == tournament.current_level_index), levels[0])
            recovery_actions = {"previous", "jump", "reset", "add_60"}
            if tournament.status == TournamentStatus.FINISHED:
                if action not in recovery_actions:
                    raise DomainError("tournament_finished", "Завершённый турнир нельзя менять.")
                # Автоматическое окончание остаётся обратимым до отдельного
                # подтверждения PIN: администратор может исправить уровень или время.
                TimerService._reopen_automatic_finish(session, tournament, now)
            if action == "start":
                if tournament.timer_status == TimerStatus.RUNNING:
                    raise DomainError("timer_already_running", "Таймер уже запущен.")
                if tournament.timer_status == TimerStatus.PAUSED:
                    if tournament.paused_remaining_seconds is None:
                        TimerService._activate_level(tournament, level, now)
                    else:
                        TimerService._activate_level(
                            tournament,
                            level,
                            now - timedelta(seconds=level.duration_seconds - tournament.paused_remaining_seconds),
                        )
                else:
                    TimerService._activate_level(tournament, level, now)
                tournament.timer_status = TimerStatus.RUNNING
                tournament.status = TournamentStatus.RUNNING
                session.execute(
                    update(TournamentPlayer)
                    .where(
                        TournamentPlayer.tournament_id == tournament_id,
                        TournamentPlayer.status == TournamentPlayerStatus.REGISTERED,
                    )
                    .values(status=TournamentPlayerStatus.ACTIVE)
                )
            elif action == "pause":
                if tournament.timer_status != TimerStatus.RUNNING:
                    raise DomainError("timer_not_running", "Таймер сейчас не запущен.")
                tournament.paused_remaining_seconds = TimerService.remaining_seconds(tournament, level, now)
                tournament.timer_status = TimerStatus.PAUSED
                tournament.status = TournamentStatus.PAUSED
                tournament.level_started_at = None
            elif action == "resume":
                if tournament.timer_status != TimerStatus.PAUSED:
                    raise DomainError("timer_not_paused", "Таймер не находится на паузе.")
                if tournament.paused_remaining_seconds is None:
                    TimerService._activate_level(tournament, level, now)
                else:
                    TimerService._activate_level(
                        tournament,
                        level,
                        now - timedelta(seconds=level.duration_seconds - tournament.paused_remaining_seconds),
                    )
                tournament.timer_status = TimerStatus.RUNNING
                tournament.status = TournamentStatus.RUNNING
                session.execute(
                    update(TournamentPlayer)
                    .where(
                        TournamentPlayer.tournament_id == tournament_id,
                        TournamentPlayer.status == TournamentPlayerStatus.REGISTERED,
                    )
                    .values(status=TournamentPlayerStatus.ACTIVE)
                )
            elif action == "reset":
                if tournament.timer_status == TimerStatus.RUNNING:
                    TimerService._activate_level(tournament, level, now)
                else:
                    tournament.paused_remaining_seconds = level.duration_seconds
            elif action in {"next", "previous", "jump"}:
                if action == "next":
                    position = min(len(levels) - 1, levels.index(level) + 1)
                elif action == "previous":
                    position = max(0, levels.index(level) - 1)
                else:
                    position = next((index for index, item in enumerate(levels) if item.order_index == target_level_index), -1)
                    if position < 0:
                        raise DomainError("unknown_level", "Указанный уровень не найден.")
                next_level = levels[position]
                if tournament.timer_status == TimerStatus.RUNNING:
                    TimerService._activate_level(tournament, next_level, now)
                else:
                    tournament.current_level_index = next_level.order_index
                    tournament.paused_remaining_seconds = next_level.duration_seconds
                    tournament.level_started_at = None
            elif action in {"add_60", "subtract_60"}:
                delta = 60 if action == "add_60" else -60
                if tournament.timer_status == TimerStatus.RUNNING:
                    tournament.level_started_at = as_utc(tournament.level_started_at or now) + timedelta(seconds=delta)
                    TimerService.reconcile(session, tournament_id, now)
                else:
                    base_remaining = (
                        level.duration_seconds
                        if tournament.paused_remaining_seconds is None
                        else tournament.paused_remaining_seconds
                    )
                    tournament.paused_remaining_seconds = max(0, base_remaining + delta)
            elif action == "toggle_auto":
                tournament.auto_advance_levels = not tournament.auto_advance_levels
            else:
                raise DomainError("unknown_timer_command", "Неизвестная команда таймера.")
            PayoutService.reconcile_finalization(session, tournament)
            EventService.record(session, tournament, "timer_command", {"action": action}, request_id=request_id)
            return tournament

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import BlindLevelKind, BountyMode, TimerStatus, TournamentPlayerStatus, TournamentStatus
from app.models.tournament import Tournament, TournamentPlayer
from app.security import verify_pin
from app.services.errors import DomainError
from app.services.bounty_service import BountyService
from app.services.event_service import EventService
from app.services.payout_service import PayoutService


class TournamentService:
    @staticmethod
    def list_summaries(session: Session) -> list[dict[str, Any]]:
        """Короткая сводка по каждому турниру для главной страницы: только чтение."""
        tournaments = session.scalars(
            select(Tournament)
            .options(selectinload(Tournament.players), selectinload(Tournament.levels))
            .order_by(Tournament.id.desc())
        ).all()
        summaries = []
        for tournament in tournaments:
            levels = sorted(tournament.levels, key=lambda level: level.order_index)
            current = next((level for level in levels if level.order_index == tournament.current_level_index), None)
            current_number = None
            if current is not None and current.kind == BlindLevelKind.PLAY:
                current_number = sum(
                    1 for level in levels if level.kind == BlindLevelKind.PLAY and level.order_index <= current.order_index
                )
            summaries.append(
                {
                    "id": tournament.id,
                    "name": tournament.name,
                    "status": tournament.status.value,
                    "timer_status": tournament.timer_status.value,
                    "buy_in_amount": tournament.buy_in_amount,
                    "currency_label": tournament.currency_label,
                    "is_freeroll": tournament.buy_in_amount == 0,
                    "bounty_mode": tournament.bounty_mode.value,
                    "bounty_amount": tournament.bounty_amount if tournament.bounty_mode == BountyMode.FIXED else 0,
                    "registered_players": len(tournament.players),
                    "active_players": sum(entry.status == TournamentPlayerStatus.ACTIVE for entry in tournament.players),
                    "current_level_kind": current.kind.value if current is not None else None,
                    "current_level_number": current_number,
                    "created_at": tournament.created_at.isoformat(),
                }
            )
        return summaries

    @staticmethod
    def finish_manually(session: Session, tournament_id: int, pin: str) -> Tournament:
        """Окончательно завершает турнир по команде администратора."""
        with session.begin():
            tournament = session.get(Tournament, tournament_id)
            if tournament is None:
                raise DomainError("tournament_not_found", "Турнир не найден.")
            if not verify_pin(pin, tournament.admin_pin_hash):
                raise DomainError("invalid_pin", "Неверный PIN администратора.")
            if tournament.is_manually_finished:
                raise DomainError("tournament_finished", "Турнир уже окончательно завершён.")
            tournament.status = TournamentStatus.FINISHED
            tournament.timer_status = TimerStatus.STOPPED
            tournament.level_started_at = None
            tournament.paused_remaining_seconds = 0
            tournament.is_manually_finished = True
            PayoutService.reconcile_finalization(session, tournament)
            remaining = list(
                session.scalars(
                    select(TournamentPlayer).where(
                        TournamentPlayer.tournament_id == tournament.id,
                        TournamentPlayer.status != TournamentPlayerStatus.OUT,
                    )
                )
            )
            if len(remaining) == 1:
                remaining[0].elimination_place = 1
                BountyService.award_champion_bounty(session, tournament, remaining[0])
            EventService.record(session, tournament, "tournament_finished", {"manual": True})
            return tournament

    @staticmethod
    def finish_if_ready(session: Session, tournament: Tournament) -> bool:
        """Завершает турнир, когда окончательно выбыли все игроки кроме одного."""
        total_players = session.scalar(
            select(func.count()).select_from(TournamentPlayer).where(TournamentPlayer.tournament_id == tournament.id)
        ) or 0
        out_players = session.scalar(
            select(func.count()).select_from(TournamentPlayer).where(
                TournamentPlayer.tournament_id == tournament.id,
                TournamentPlayer.status == TournamentPlayerStatus.OUT,
            )
        ) or 0
        if tournament.status == TournamentStatus.FINISHED or total_players < 2 or out_players != total_players - 1:
            return False
        remaining = list(
            session.scalars(
                select(TournamentPlayer)
                .where(
                    TournamentPlayer.tournament_id == tournament.id,
                    TournamentPlayer.status != TournamentPlayerStatus.OUT,
                )
                .order_by(TournamentPlayer.id)
            )
        )
        if len(remaining) != 1:
            return False
        winner = remaining[0]
        winner.elimination_place = 1
        tournament.status = TournamentStatus.FINISHED
        tournament.timer_status = TimerStatus.STOPPED
        tournament.level_started_at = None
        tournament.paused_remaining_seconds = 0
        PayoutService.reconcile_finalization(session, tournament)
        BountyService.award_champion_bounty(session, tournament, winner)
        EventService.record(
            session,
            tournament,
            "tournament_finished",
            {"winner_tournament_player_id": winner.id},
        )
        return True

    @staticmethod
    def create_tournament(
        session: Session,
        *,
        name: str,
        buy_in_amount: int,
        currency_label: str,
        starting_stack: int,
        admin_pin_hash: str,
        max_reentries_per_player: int | None = None,
    ) -> Tournament:
        if not name.strip():
            raise DomainError("invalid_tournament_name", "Введите название турнира.")
        if buy_in_amount < 0 or starting_stack <= 0:
            raise DomainError("invalid_tournament_values", "Проверьте бай-ин и стартовый стек.")
        if max_reentries_per_player is not None and max_reentries_per_player < 0:
            raise DomainError("invalid_reentry_limit", "Лимит re-entry не может быть отрицательным.")
        with session.begin():
            tournament = Tournament(
                name=name.strip(),
                buy_in_amount=buy_in_amount,
                currency_label=currency_label.strip() or "₽",
                starting_stack=starting_stack,
                max_reentries_per_player=max_reentries_per_player,
                admin_pin_hash=admin_pin_hash,
                status=TournamentStatus.DRAFT,
                timer_status=TimerStatus.PAUSED,
            )
            session.add(tournament)
        return tournament

    @staticmethod
    def delete_tournament(session: Session, tournament_id: int, pin: str) -> None:
        """Удаляет турнир вместе с его участниками, структурой и журналом."""
        with session.begin():
            tournament = session.get(Tournament, tournament_id)
            if tournament is None:
                raise DomainError("tournament_not_found", "Турнир не найден.")
            if not verify_pin(pin, tournament.admin_pin_hash):
                raise DomainError("invalid_pin", "Неверный PIN администратора.")
            session.delete(tournament)

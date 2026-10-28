from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.enums import TournamentPlayerStatus, TournamentStatus
from app.models.tournament import Tournament, TournamentEvent, TournamentPlayer, as_utc, utc_now
from app.services.errors import DomainError


def player_state(entry: TournamentPlayer) -> dict[str, Any]:
    return {
        "status": entry.status.value,
        "entries_count": entry.entries_count,
        "elimination_place": entry.elimination_place,
        "eliminated_at": as_utc(entry.eliminated_at).isoformat() if entry.eliminated_at else None,
    }


def restore_player_state(entry: TournamentPlayer, state: dict[str, Any]) -> None:
    entry.status = TournamentPlayerStatus(state["status"])
    entry.entries_count = int(state["entries_count"])
    entry.elimination_place = state["elimination_place"]
    raw_eliminated_at = state["eliminated_at"]
    entry.eliminated_at = datetime.fromisoformat(raw_eliminated_at).astimezone(UTC) if raw_eliminated_at else None


class EventService:
    @staticmethod
    def record(
        session: Session,
        tournament: Tournament,
        event_type: str,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
        reversible: bool = False,
    ) -> TournamentEvent:
        if request_id:
            existing = session.scalar(
                select(TournamentEvent).where(
                    TournamentEvent.tournament_id == tournament.id, TournamentEvent.request_id == request_id
                )
            )
            if existing:
                raise DomainError("duplicate_command", "Эта команда уже была обработана.")
        event = TournamentEvent(
            tournament_id=tournament.id,
            event_type=event_type,
            payload_json=payload,
            request_id=request_id,
            is_reversible=reversible,
        )
        session.add(event)
        tournament.state_version += 1
        return event

    @staticmethod
    def undo_last(session: Session, tournament_id: int, request_id: str | None = None) -> TournamentEvent:
        with session.begin():
            tournament = session.get(Tournament, tournament_id)
            if tournament is None:
                raise DomainError("tournament_not_found", "Турнир не найден.")
            if tournament.is_manually_finished:
                raise DomainError("tournament_locked", "Турнир завершён и заблокирован для изменений.")
            event = session.scalar(
                select(TournamentEvent)
                .where(
                    TournamentEvent.tournament_id == tournament_id,
                    or_(
                        TournamentEvent.is_reversible.is_(True),
                        TournamentEvent.event_type == "player_out",
                    ),
                    TournamentEvent.reversed_at.is_(None),
                )
                .order_by(TournamentEvent.id.desc())
            )
            if event is None:
                raise DomainError("nothing_to_undo", "Нет действия, которое можно безопасно отменить.")
            entry_id = event.payload_json.get("tournament_player_id")
            entry = session.get(TournamentPlayer, entry_id)
            after = event.payload_json.get("after")
            before = event.payload_json.get("before")
            if entry is None or not isinstance(after, dict) or not isinstance(before, dict):
                raise DomainError("event_not_reversible", "Журнал не содержит данных для безопасной отмены.")
            if player_state(entry) != after:
                raise DomainError(
                    "event_has_dependencies",
                    "Последующее действие зависит от этого события; сначала отмените более позднее действие.",
                )
            from app.services.payout_service import PayoutService

            before_stage = PayoutService.current_stage(session, tournament)
            if event.event_type == "player_out" and tournament.status == TournamentStatus.FINISHED:
                finish_event = session.scalar(
                    select(TournamentEvent)
                    .where(
                        TournamentEvent.tournament_id == tournament_id,
                        TournamentEvent.event_type == "tournament_finished",
                        TournamentEvent.id > event.id,
                    )
                    .order_by(TournamentEvent.id.desc())
                )
                finish_payload = finish_event.payload_json if finish_event is not None else {}
                if finish_payload.get("winner_tournament_player_id") is not None:
                    from app.services.timer_service import TimerService

                    TimerService._reopen_automatic_finish(session, tournament, utc_now())
            restore_player_state(entry, before)
            reversal = EventService.record(
                session,
                tournament,
                "event_reversed",
                {"source_event_id": event.id, "tournament_player_id": entry.id},
                request_id=request_id,
            )
            session.flush()
            event.reversed_at = utc_now()
            event.reversal_event_id = reversal.id
            PayoutService.record_stage_transition(session, tournament, before_stage)
            return reversal

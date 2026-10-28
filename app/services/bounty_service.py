from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import BountyMode
from app.models.tournament import Tournament, TournamentEvent, TournamentPlayer, utc_now
from app.services.errors import DomainError


@dataclass(frozen=True, slots=True)
class PlayerBountyResult:
    ko_count: int = 0
    bounty_winnings: int = 0


class BountyService:
    """Fixed Bounty rules; event history is the source of truth for awards and K.O.s."""

    @staticmethod
    def validate_configuration(
        bounty_mode: BountyMode | str | None,
        bounty_amount: Any,
        buy_in_amount: int,
        *,
        is_freeroll: bool = False,
    ) -> tuple[BountyMode, int]:
        try:
            mode = BountyMode(str(bounty_mode or BountyMode.NONE.value).lower())
        except ValueError as error:
            raise DomainError("invalid_bounty_mode", "Выберите обычный или Fixed Bounty турнир.") from error
        try:
            amount = int(bounty_amount or 0)
        except (TypeError, ValueError) as error:
            raise DomainError("invalid_bounty_amount", "Проверьте размер bounty за entry.") from error
        if mode == BountyMode.NONE:
            return mode, 0
        if is_freeroll:
            raise DomainError("freeroll_bounty_conflict", "Фриролл не может быть Bounty-турниром.")
        if amount <= 0 or amount >= buy_in_amount:
            raise DomainError(
                "invalid_bounty_amount",
                "Bounty должен быть больше нуля и меньше общего бай-ина.",
            )
        return mode, amount

    @staticmethod
    def results(session: Session, tournament_id: int) -> dict[int, PlayerBountyResult]:
        events = session.scalars(
            select(TournamentEvent).where(
                TournamentEvent.tournament_id == tournament_id,
                TournamentEvent.event_type.in_(("player_eliminated", "champion_bounty_awarded")),
                TournamentEvent.reversed_at.is_(None),
            )
        )
        mutable: dict[int, list[int]] = {}
        for event in events:
            payload = event.payload_json if isinstance(event.payload_json, dict) else {}
            if event.event_type == "player_eliminated":
                recipient_id = payload.get("killer_tournament_player_id")
                ko_increment = 1
            else:
                recipient_id = payload.get("champion_tournament_player_id")
                ko_increment = 0
            if not isinstance(recipient_id, int):
                continue
            amount = payload.get("bounty_amount_awarded", 0)
            if not isinstance(amount, int) or amount < 0:
                continue
            aggregate = mutable.setdefault(recipient_id, [0, 0])
            aggregate[0] += ko_increment
            aggregate[1] += amount
        return {
            entry_id: PlayerBountyResult(ko_count=values[0], bounty_winnings=values[1])
            for entry_id, values in mutable.items()
        }

    @staticmethod
    def leader(session: Session, tournament: Tournament) -> dict[str, Any] | None:
        events = session.scalars(
            select(TournamentEvent)
            .where(
                TournamentEvent.tournament_id == tournament.id,
                TournamentEvent.event_type == "player_eliminated",
                TournamentEvent.reversed_at.is_(None),
            )
            .order_by(TournamentEvent.id)
        )
        counts: dict[int, int] = {}
        reached_at: dict[int, int] = {}
        for event in events:
            payload = event.payload_json if isinstance(event.payload_json, dict) else {}
            recipient_id = payload.get("killer_tournament_player_id")
            if not isinstance(recipient_id, int):
                continue
            counts[recipient_id] = counts.get(recipient_id, 0) + 1
            reached_at[recipient_id] = event.id
        highest = max(counts.values(), default=0)
        if highest <= 0:
            return None
        leader_id = min(
            (entry_id for entry_id, count in counts.items() if count == highest),
            key=lambda entry_id: reached_at[entry_id],
        )
        leader = next(entry for entry in tournament.players if entry.id == leader_id)
        return {"ko_count": highest, "names": [leader.player.name], "tie": False}

    @staticmethod
    def award_champion_bounty(
        session: Session, tournament: Tournament, champion: TournamentPlayer
    ) -> TournamentEvent | None:
        if tournament.bounty_mode != BountyMode.FIXED:
            return None
        existing = session.scalar(
            select(TournamentEvent).where(
                TournamentEvent.tournament_id == tournament.id,
                TournamentEvent.event_type == "champion_bounty_awarded",
                TournamentEvent.reversed_at.is_(None),
            )
        )
        if existing is not None:
            return existing
        from app.services.event_service import EventService

        return EventService.record(
            session,
            tournament,
            "champion_bounty_awarded",
            {
                "champion_tournament_player_id": champion.id,
                "bounty_amount_awarded": tournament.bounty_amount,
            },
        )

    @staticmethod
    def revoke_champion_bounty(session: Session, tournament: Tournament) -> None:
        award = session.scalar(
            select(TournamentEvent).where(
                TournamentEvent.tournament_id == tournament.id,
                TournamentEvent.event_type == "champion_bounty_awarded",
                TournamentEvent.reversed_at.is_(None),
            )
        )
        if award is None:
            return
        from app.services.event_service import EventService

        reversal = EventService.record(
            session,
            tournament,
            "champion_bounty_revoked",
            {"source_event_id": award.id},
        )
        session.flush()
        award.reversed_at = utc_now()
        award.reversal_event_id = reversal.id

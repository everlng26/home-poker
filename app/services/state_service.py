from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import BlindLevelKind
from app.models.tournament import BlindLevel, Tournament, TournamentEvent, TournamentPlayer
from app.services.calculation_service import CalculationService
from app.services.bounty_service import BountyService, PlayerBountyResult
from app.services.errors import DomainError
from app.services.payout_service import PayoutService
from app.services.registration_service import late_registration_phase
from app.services.timer_service import TimerService


def level_data(
    level: BlindLevel | None, level_number: int | None = None, *, ante_enabled: bool = True
) -> dict[str, Any] | None:
    if level is None:
        return None
    return {
        "id": level.id, "order_index": level.order_index, "level_number": level_number, "kind": level.kind.value,
        "small_blind": level.small_blind, "big_blind": level.big_blind,
        "ante": level.ante if ante_enabled else None,
        "duration_seconds": level.duration_seconds, "title": level.title,
    }


def tournament_state(session: Session, tournament_id: int) -> dict[str, Any]:
    tournament = session.scalar(
        select(Tournament)
        .where(Tournament.id == tournament_id)
        .options(
            selectinload(Tournament.players).selectinload(TournamentPlayer.player),
            selectinload(Tournament.levels),
            selectinload(Tournament.payouts),
        )
        .execution_options(populate_existing=True)
    )
    if tournament is None:
        raise DomainError("tournament_not_found", "Турнир не найден.")
    levels = sorted(tournament.levels, key=lambda level: level.order_index)
    level_numbers: dict[int, int | None] = {}
    play_number = 0
    for level in levels:
        if level.kind == BlindLevelKind.PLAY:
            play_number += 1
            level_numbers[level.order_index] = play_number
        else:
            level_numbers[level.order_index] = None
    current = next((level for level in levels if level.order_index == tournament.current_level_index), None)
    metrics = CalculationService.calculate(tournament, tournament.players, current)
    remaining = 0 if tournament.status.value == "finished" else TimerService.remaining_seconds(tournament, current) if current else 0
    payout_lines = PayoutService.calculate(metrics.prize_pool, list(tournament.payouts))
    payout_amounts = {line.place: line.amount for line in payout_lines}
    bounty_results = BountyService.results(session, tournament.id)
    standings = sorted(
        [
            {
                "id": entry.id,
                "name": entry.player.name,
                "place": entry.elimination_place,
                "entries_count": entry.entries_count,
                "reentries": max(0, entry.entries_count - 1),
                "status": entry.status.value,
                "total_buy_ins": entry.entries_count * tournament.buy_in_amount,
                "main_prize_winnings": payout_amounts.get(entry.elimination_place, 0),
                "bounty_winnings": bounty_results.get(entry.id, PlayerBountyResult()).bounty_winnings,
                "ko_count": bounty_results.get(entry.id, PlayerBountyResult()).ko_count,
                "winnings": payout_amounts.get(entry.elimination_place, 0)
                + bounty_results.get(entry.id, PlayerBountyResult()).bounty_winnings,
                "net_result": payout_amounts.get(entry.elimination_place, 0)
                + bounty_results.get(entry.id, PlayerBountyResult()).bounty_winnings
                - entry.entries_count * tournament.buy_in_amount,
                "itm": entry.elimination_place in payout_amounts,
            }
            for entry in tournament.players
        ],
        key=lambda item: (item["place"] is None, item["place"] or 999999, item["name"].lower()),
    )
    latest_event = session.scalar(
        select(TournamentEvent)
        .where(TournamentEvent.tournament_id == tournament_id)
        .order_by(TournamentEvent.id.desc())
    )
    tournament_created_event_id = session.scalar(
        select(TournamentEvent.id)
        .where(
            TournamentEvent.tournament_id == tournament_id,
            TournamentEvent.event_type == "tournament_created",
        )
        .order_by(TournamentEvent.id.asc())
    )
    public_event_candidates = session.scalars(
        select(TournamentEvent)
        .where(
            TournamentEvent.tournament_id == tournament_id,
            TournamentEvent.event_type.in_(("player_registered", "player_eliminated", "reentry_added")),
            TournamentEvent.reversed_at.is_(None),
        )
        .order_by(TournamentEvent.id.desc())
    ).all()
    latest_public_event = next(
        (
            event
            for event in public_event_candidates
            if event.event_type != "player_registered"
            or (
                bool(event.payload_json.get("public_feed"))
                if isinstance(event.payload_json, dict) and "public_feed" in event.payload_json
                else tournament_created_event_id is None or event.id > tournament_created_event_id
            )
        ),
        None,
    )
    player_names = {entry.id: entry.player.name for entry in tournament.players}
    latest_event_data = None
    if latest_event is not None:
        payload = latest_event.payload_json if isinstance(latest_event.payload_json, dict) else {}
        latest_event_data = {
            "type": latest_event.event_type,
            "player_name": player_names.get(payload.get("tournament_player_id")),
            "created_at": latest_event.created_at.isoformat(),
            "reversed": latest_event.reversed_at is not None,
        }
    latest_public_event_data = None
    if latest_public_event is not None:
        payload = latest_public_event.payload_json if isinstance(latest_public_event.payload_json, dict) else {}
        latest_public_event_data = {
            "id": latest_public_event.id,
            "type": latest_public_event.event_type,
            "player_name": player_names.get(payload.get("tournament_player_id")),
            "killer_name": player_names.get(payload.get("killer_tournament_player_id")),
            "bounty_amount_awarded": payload.get("bounty_amount_awarded", 0),
            "created_at": latest_public_event.created_at.isoformat(),
        }
    registration_phase = late_registration_phase(
        levels,
        tournament.current_level_index,
        tournament.late_registration_end_level_index,
    )
    effective_registration_phase = (
        "closed" if tournament.payouts_finalized_at is not None else registration_phase
    )
    payout_status = PayoutService.stage(tournament, tournament.players, list(tournament.payouts))
    payout_configuration_error = PayoutService.configuration_error(
        len(tournament.payouts), len(tournament.players)
    ) if tournament.payouts and tournament.payouts_finalized_at is not None else None
    latest_payout_event = session.scalar(
        select(TournamentEvent)
        .where(
            TournamentEvent.tournament_id == tournament_id,
            TournamentEvent.event_type.in_(("bubble_reached", "itm_reached")),
        )
        .order_by(TournamentEvent.id.desc())
    )
    latest_payout_event_data = None
    if latest_payout_event is not None:
        payload = latest_payout_event.payload_json if isinstance(latest_payout_event.payload_json, dict) else {}
        latest_payout_event_data = {
            "id": latest_payout_event.id,
            "type": latest_payout_event.event_type,
            "active_players": payload.get("active_players"),
            "paid_places": payload.get("paid_places"),
            "created_at": latest_payout_event.created_at.isoformat(),
        }
    winner = next((item for item in standings if item["place"] == 1), None)
    if tournament.status.value == "finished" and winner is not None:
        public_stage = {"type": "winner", "player_name": winner["name"]}
    elif metrics.active_players == 2:
        public_stage = {"type": "heads_up"}
    elif metrics.active_players == 3:
        public_stage = {"type": "three_players_left"}
    else:
        public_stage = None
    return {
        "id": tournament.id, "name": tournament.name, "status": tournament.status.value,
        "is_manually_finished": tournament.is_manually_finished,
        "is_freeroll": tournament.buy_in_amount == 0,
        "bounty_mode": tournament.bounty_mode.value,
        "bounty_amount": tournament.bounty_amount,
        "currency_label": tournament.currency_label,
        "ante_enabled": tournament.ante_enabled,
        "timer_status": tournament.timer_status.value, "state_version": tournament.state_version,
        "auto_advance_levels": tournament.auto_advance_levels, "current_level_index": tournament.current_level_index,
        "late_registration_end_level_index": tournament.late_registration_end_level_index,
        "late_registration_end_level_number": (
            sum(
                1
                for level in levels
                if level.kind == BlindLevelKind.PLAY
                and level.order_index <= tournament.late_registration_end_level_index
            )
            if tournament.late_registration_end_level_index is not None
            else None
        ),
        "late_registration_ended": effective_registration_phase == "closed",
        "late_registration_phase": effective_registration_phase,
        "remaining_seconds": remaining,
        "current_level": level_data(current, level_numbers.get(current.order_index) if current else None, ante_enabled=tournament.ante_enabled),
        "levels": [level_data(level, level_numbers[level.order_index], ante_enabled=tournament.ante_enabled) for level in levels],
        "players": [
            {
                "id": entry.id, "player_id": entry.player_id, "name": entry.player.name,
                "status": entry.status.value, "entries_count": entry.entries_count,
                "elimination_place": entry.elimination_place,
                "ko_count": bounty_results.get(entry.id, PlayerBountyResult()).ko_count,
                "bounty_winnings": bounty_results.get(entry.id, PlayerBountyResult()).bounty_winnings,
            }
            for entry in tournament.players
        ],
        "metrics": asdict(metrics),
        "standings": standings,
        "latest_event": latest_event_data,
        "public_latest_event": latest_public_event_data,
        "public_payout_event": latest_payout_event_data,
        "public_stage": public_stage,
        "ko_leader": BountyService.leader(session, tournament),
        "payouts": {
            "configured": bool(tournament.payouts) and tournament.buy_in_amount > 0,
            "status": "final" if tournament.payouts_finalized_at is not None else "preliminary",
            "finalized_at": (
                tournament.payouts_finalized_at.isoformat()
                if tournament.payouts_finalized_at is not None
                else None
            ),
            "stage": payout_status,
            "paid_places": len(tournament.payouts),
            "total_percentage_basis_points": sum(
                payout.percentage_basis_points for payout in tournament.payouts
            ),
            "total_amount": sum(line.amount for line in payout_lines),
            "configuration_error": payout_configuration_error,
            "lines": [
                {
                    "place": line.place,
                    "percentage_basis_points": line.percentage_basis_points,
                    "percentage": line.percentage_basis_points / 100,
                    "amount": line.amount,
                }
                for line in payout_lines
            ],
        },
    }

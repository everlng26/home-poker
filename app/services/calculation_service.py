from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import BountyMode, BlindLevelKind, TournamentPlayerStatus
from app.models.tournament import BlindLevel, Tournament, TournamentPlayer


@dataclass(frozen=True, slots=True)
class TournamentMetrics:
    active_players: int
    registered_players: int
    total_entries: int
    total_reentries: int
    prize_pool: int
    bounty_pool: int
    total_collected: int
    main_prize_contribution: int
    total_chips_in_play: int
    average_stack: float | None
    average_stack_bb: float | None


class CalculationService:
    @staticmethod
    def calculate(
        tournament: Tournament, entries: list[TournamentPlayer], current_level: BlindLevel | None
    ) -> TournamentMetrics:
        active_players = sum(item.status == TournamentPlayerStatus.ACTIVE for item in entries)
        registered_players = len(entries)
        total_entries = sum(item.entries_count for item in entries)
        total_reentries = total_entries - registered_players
        bounty_amount = tournament.bounty_amount if tournament.bounty_mode == BountyMode.FIXED else 0
        main_prize_contribution = tournament.buy_in_amount - bounty_amount
        prize_pool = total_entries * main_prize_contribution
        bounty_pool = total_entries * bounty_amount
        total_collected = total_entries * tournament.buy_in_amount
        total_chips_in_play = total_entries * tournament.starting_stack
        average_stack = total_chips_in_play / active_players if active_players else None
        can_calculate_bb = (
            average_stack is not None
            and current_level is not None
            and current_level.kind == BlindLevelKind.PLAY
            and (current_level.big_blind or 0) > 0
        )
        average_stack_bb = average_stack / current_level.big_blind if can_calculate_bb else None
        return TournamentMetrics(
            active_players=active_players,
            registered_players=registered_players,
            total_entries=total_entries,
            total_reentries=total_reentries,
            prize_pool=prize_pool,
            bounty_pool=bounty_pool,
            total_collected=total_collected,
            main_prize_contribution=main_prize_contribution,
            total_chips_in_play=total_chips_in_play,
            average_stack=average_stack,
            average_stack_bb=average_stack_bb,
        )

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import BountyMode, BlindLevelKind, TournamentPlayerStatus, TournamentStatus, TimerStatus
from app.models.tournament import BlindLevel, Player, Tournament, TournamentChipPlan, TournamentPlayer
from app.services.errors import DomainError
from app.services.bounty_service import BountyService
from app.services.event_service import EventService
from app.services.level_service import STRUCTURE_PRESETS
from app.services.payout_service import PayoutService
from app.services.stack_optimizer_service import StackOptimizerService


class TournamentSetupService:
    """Создаёт турнир и его первоначальные данные одной операцией."""

    @staticmethod
    def create(
        session: Session,
        *,
        name: str,
        buy_in_amount: int,
        currency_label: str,
        starting_stack: int,
        admin_pin_hash: str,
        max_reentries_per_player: int | None = None,
        is_freeroll: bool = False,
        ante_enabled: bool = True,
        preset: str = "standard",
        levels: list[dict[str, Any]] | None = None,
        player_names: list[str] | None = None,
        late_registration_end_level_number: int | None = None,
        payout_percentages: list[Any] | None = None,
        bounty_mode: BountyMode | str | None = None,
        bounty_amount: Any = 0,
        chip_plan: dict[str, Any] | None = None,
    ) -> Tournament:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise DomainError("invalid_tournament_name", "Введите название турнира.")
        if is_freeroll:
            buy_in_amount = 0
        if buy_in_amount < 0 or starting_stack <= 0:
            raise DomainError("invalid_tournament_values", "Проверьте бай-ин и стартовый стек.")
        normalized_bounty_mode, normalized_bounty_amount = BountyService.validate_configuration(
            bounty_mode,
            bounty_amount,
            buy_in_amount,
            is_freeroll=is_freeroll,
        )
        if max_reentries_per_player in ("", None):
            max_reentries_per_player = None
        else:
            try:
                max_reentries_per_player = int(max_reentries_per_player)
            except (TypeError, ValueError) as error:
                raise DomainError("invalid_reentry_limit", "Проверьте лимит re-entry.") from error
            if max_reentries_per_player < 0:
                raise DomainError("invalid_reentry_limit", "Лимит re-entry не может быть отрицательным.")

        structure = levels if levels is not None else STRUCTURE_PRESETS.get(preset)
        if structure is None:
            raise DomainError("unknown_preset", "Неизвестная типовая структура.")
        normalized_levels, cutoff_index = TournamentSetupService._normalize_levels(
            structure, late_registration_end_level_number, ante_enabled=ante_enabled
        )
        names = [str(value).strip() for value in (player_names or [])]
        if any(not value for value in names):
            raise DomainError("invalid_player_name", "Имя игрока не может быть пустым.")
        if len({value.casefold() for value in names}) != len(names):
            raise DomainError("duplicate_player_name", "В списке игроков есть повторяющиеся имена.")

        if chip_plan is not None and not isinstance(chip_plan, dict):
            raise DomainError("invalid_chip_plan", "Проверьте выбранный план фишек.")
        if chip_plan is not None and not names:
            raise DomainError("invalid_chip_plan", "Для плана фишек добавьте хотя бы одного игрока.")
        if chip_plan is not None and max_reentries_per_player is None:
            raise DomainError(
                "invalid_chip_plan",
                "Для плана фишек укажите конечный лимит re-entry на одного игрока.",
            )

        with session.begin():
            selected_chip_plan: dict[str, Any] | None = None
            solved_chip_plan: dict[str, Any] | None = None
            if chip_plan is not None:
                first_level = next(
                    level for level in normalized_levels if level["kind"] == BlindLevelKind.PLAY
                )
                solved_chip_plan = StackOptimizerService.evaluate_selection(
                    session,
                    chip_set_ids=chip_plan.get("chip_set_ids"),
                    excluded_denominations=chip_plan.get("excluded_denominations"),
                    players=len(names),
                    starting_stack=starting_stack,
                    max_reentries_per_player=max_reentries_per_player,
                    initial_distribution=chip_plan.get("initial_distribution"),
                    first_small_blind=first_level["small_blind"],
                    first_big_blind=first_level["big_blind"],
                    first_ante=first_level["ante"],
                )
                selected_chip_plan = solved_chip_plan["candidate"]

            tournament = Tournament(
                name=cleaned_name,
                buy_in_amount=buy_in_amount,
                bounty_mode=normalized_bounty_mode,
                bounty_amount=normalized_bounty_amount,
                currency_label=currency_label.strip() or "₽",
                starting_stack=starting_stack,
                max_reentries_per_player=max_reentries_per_player,
                ante_enabled=ante_enabled,
                admin_pin_hash=admin_pin_hash,
                status=TournamentStatus.DRAFT,
                timer_status=TimerStatus.PAUSED,
                late_registration_end_level_index=cutoff_index,
            )
            session.add(tournament)
            session.flush()

            if selected_chip_plan is not None and solved_chip_plan is not None:
                combined = solved_chip_plan["combined_inventory"]
                session.add(
                    TournamentChipPlan(
                        tournament_id=tournament.id,
                        selected_chip_sets_json=combined["chip_sets"],
                        combined_inventory_json=combined["denominations"],
                        planned_players=len(names),
                        starting_stack=starting_stack,
                        max_reentries_per_player=max_reentries_per_player,
                        max_total_reentries=len(names) * max_reentries_per_player,
                        covered_reentries=selected_chip_plan["covered_reentries"],
                        initial_distribution_json=selected_chip_plan["initial_distribution"],
                        reentry_distribution_json=selected_chip_plan["reentry_pack"],
                        reserved_quantities_json=selected_chip_plan["reserved_quantities"],
                        remaining_inventory_json=selected_chip_plan["remaining_inventory"],
                    )
                )

            if not is_freeroll and payout_percentages is not None:
                PayoutService.replace_structure(
                    session,
                    tournament,
                    payout_percentages,
                    record_event=False,
                )

            for order_index, level_data in enumerate(normalized_levels):
                session.add(
                    BlindLevel(
                        tournament_id=tournament.id,
                        order_index=order_index,
                        kind=level_data["kind"],
                        small_blind=level_data.get("small_blind"),
                        big_blind=level_data.get("big_blind"),
                        ante=level_data.get("ante"),
                        duration_seconds=level_data["duration_seconds"],
                        title="Перерыв" if level_data["kind"] == BlindLevelKind.BREAK else None,
                    )
                )

            for name_value in names:
                player = Player(name=name_value)
                session.add(player)
                session.flush()
                entry = TournamentPlayer(
                    tournament_id=tournament.id,
                    player_id=player.id,
                    status=TournamentPlayerStatus.REGISTERED,
                    entries_count=1,
                )
                session.add(entry)
                session.flush()
                EventService.record(
                    session,
                    tournament,
                    "player_registered",
                    {
                        "tournament_player_id": entry.id,
                        "player_id": player.id,
                        "entries_count": 1,
                        "public_feed": False,
                    },
                )

            EventService.record(
                session,
                tournament,
                "tournament_created",
                {
                    "levels_count": len(normalized_levels),
                    "players_count": len(names),
                    "late_registration_end_level_index": cutoff_index,
                    "paid_places": len(tournament.payouts),
                    "bounty_mode": tournament.bounty_mode.value,
                    "bounty_amount": tournament.bounty_amount,
                    "chip_plan_applied": selected_chip_plan is not None,
                },
            )
            return tournament

    @staticmethod
    def _normalize_levels(
        levels: list[dict[str, Any]], late_registration_end_level_number: int | None, *, ante_enabled: bool = True
    ) -> tuple[list[dict[str, Any]], int | None]:
        if not levels:
            raise DomainError("empty_structure", "Добавьте хотя бы один уровень.")
        normalized: list[dict[str, Any]] = []
        play_indexes: list[int] = []
        for index, raw in enumerate(levels):
            try:
                kind = BlindLevelKind(str(raw.get("kind")))
                duration_seconds = int(raw.get("duration_seconds", 0))
            except (TypeError, ValueError) as error:
                raise DomainError("invalid_structure", "Проверьте параметры структуры уровней.") from error
            if duration_seconds <= 0:
                raise DomainError("invalid_structure", "Длительность каждого элемента должна быть больше нуля.")
            if kind == BlindLevelKind.BREAK:
                normalized.append({"kind": kind, "duration_seconds": duration_seconds})
                continue
            try:
                small_blind = int(raw.get("small_blind", 0))
                big_blind = int(raw.get("big_blind", 0))
                ante = 0 if not ante_enabled else int(raw.get("ante", big_blind))
            except (TypeError, ValueError) as error:
                raise DomainError("invalid_structure", "Проверьте значения SB, BB и Ante.") from error
            if small_blind <= 0 or big_blind < small_blind or ante < 0:
                raise DomainError("invalid_structure", "Проверьте значения SB, BB и Ante.")
            play_indexes.append(index)
            normalized.append(
                {
                    "kind": kind,
                    "duration_seconds": duration_seconds,
                    "small_blind": small_blind,
                    "big_blind": big_blind,
                    "ante": ante,
                }
            )
        if not play_indexes:
            raise DomainError("invalid_structure", "Добавьте хотя бы один игровой уровень.")
        if late_registration_end_level_number in (None, 0, ""):
            raise DomainError(
                "invalid_late_registration_end",
                "Укажите игровой уровень окончания поздней регистрации.",
            )
        try:
            cutoff_number = int(late_registration_end_level_number)
        except (TypeError, ValueError) as error:
            raise DomainError("invalid_late_registration_end", "Выберите игровой уровень для окончания поздней регистрации.") from error
        if not 1 <= cutoff_number <= len(play_indexes):
            raise DomainError("invalid_late_registration_end", "Выберите существующий игровой уровень для окончания поздней регистрации.")
        cutoff_index = play_indexes[cutoff_number - 1]
        return normalized, cutoff_index

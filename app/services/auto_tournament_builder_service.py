"""Tournament-wide orchestration for physical Home Poker tournament plans."""

from __future__ import annotations

from functools import reduce
from math import gcd, log
from typing import Any

from sqlalchemy.orm import Session

from app.services.errors import DomainError
from app.services.stack_optimizer_service import StackOptimizerService
from app.services.structure_generator_service import TournamentStructureGeneratorService


# The staged limits are part of the public deterministic search contract.  They
# keep the existing exact stack solver away from a combinatorial cross product.
STACK_CANDIDATE_LIMIT = 10
PROMISING_STACK_LIMIT = 5
BLIND_CANDIDATE_LIMIT = 2
FINAL_TOURNAMENT_POOL_LIMIT = 30

STACK_VALUE_MANTISSAS = (
    (1, 1),
    (5, 4),
    (3, 2),
    (2, 1),
    (5, 2),
    (3, 1),
    (4, 1),
    (5, 1),
    (15, 2),
)
STACK_VALUE_POWER_LIMIT = 12
STACK_CHIP_COUNT_ANCHORS = (16, 20, 24, 28, 32, 36, 40)
TARGET_STARTING_DEPTHS = (100, 125, 80, 150)

# Lower tournament score wins.  Stack Optimizer already owns chip-quality
# scoring; Structure Generator already owns progression scoring.  Builder only
# normalizes their results and adds tournament-wide trade-offs.
SCORE_STACK_QUALITY_WEIGHT = 1.0
SCORE_STRUCTURE_QUALITY_WEIGHT = 0.65
SCORE_COVERAGE_SHORTFALL_WEIGHT = 150.0
SCORE_DEPTH_DISTANCE_WEIGHT = 34.0
SCORE_LEVEL_DURATION_DISTANCE_WEIGHT = 2.2
SCORE_DURATION_WINDOW_DISTANCE_WEIGHT = 0.28
SCORE_FIRST_BLIND_AWKWARD_WEIGHT = 1.25
SCORE_INVENTORY_USAGE_WEIGHT = 10.0
SCORE_BREAK_SCHEDULE_WEIGHT = 8.0

ALTERNATIVE_SCORE_MARGIN = 90.0


class AutoTournamentBuilderService:
    """Compose existing inventory, stack, and structure planning services."""

    @staticmethod
    def _integer(raw: Any, *, code: str, message: str, minimum: int) -> int:
        if isinstance(raw, bool):
            raise DomainError(code, message)
        try:
            value = int(raw)
        except (TypeError, ValueError) as error:
            raise DomainError(code, message) from error
        if value < minimum:
            raise DomainError(code, message)
        return value

    @classmethod
    def build(
        cls,
        session: Session,
        *,
        chip_set_ids: Any,
        players: Any,
        max_reentries_per_player: Any,
        target_duration_minutes: Any,
        ante_mode: Any,
    ) -> dict[str, Any]:
        player_count = cls._integer(
            players,
            code="invalid_players",
            message="Количество игроков должно быть больше нуля.",
            minimum=1,
        )
        reentry_limit = cls._integer(
            max_reentries_per_player,
            code="invalid_reentry_limit",
            message="Укажите неотрицательный лимит re-entry на одного игрока.",
            minimum=0,
        )
        target_minutes = cls._integer(
            target_duration_minutes,
            code="invalid_target_duration",
            message="Целевая продолжительность должна быть больше нуля.",
            minimum=1,
        )
        normalized_ante_mode = str(ante_mode)
        if normalized_ante_mode not in {"none", "big_blind"}:
            raise DomainError("invalid_ante_mode", "Выберите режим без анте или BB Ante.")

        inventory = StackOptimizerService.combine_inventory(session, chip_set_ids)
        positive = tuple((value, quantity) for value, quantity in inventory.quantities if quantity > 0)
        if not positive:
            raise DomainError("empty_inventory", "В выбранных наборах нет доступных фишек.")

        maximum_reentries = player_count * reentry_limit
        expected_reentries, expected_explanation = cls._expected_reentries(
            players=player_count,
            max_reentries_per_player=reentry_limit,
        )
        stack_values = cls._candidate_stack_values(
            quantities=positive,
            players=player_count,
            max_reentries_per_player=reentry_limit,
        )
        preliminary: list[dict[str, Any]] = []
        solve_count = 0
        for stack_value in stack_values:
            solved = StackOptimizerService.solve(
                session,
                chip_set_ids=list(chip_set_ids),
                players=player_count,
                starting_stack=stack_value,
                max_reentries_per_player=reentry_limit,
            )
            solve_count += 1
            if not solved["feasible"]:
                continue
            recommended = next(item for item in solved["candidates"] if item["recommended"])
            preliminary.append(
                {
                    "starting_stack": stack_value,
                    "candidate": recommended,
                }
            )

        if not preliminary:
            raise DomainError(
                "auto_builder_no_feasible_stack",
                "Не удалось собрать точные стартовые стеки для выбранного числа игроков.",
            )
        preliminary.sort(key=cls._preliminary_rank_key)
        promising = preliminary[:PROMISING_STACK_LIMIT]

        tournament_pool: list[dict[str, Any]] = []
        structure_count = 0
        for stack_option in promising:
            stack_value = stack_option["starting_stack"]
            seed_candidate = stack_option["candidate"]
            seed_denominations = cls._plan_denominations(seed_candidate)
            try:
                blind_options = TournamentStructureGeneratorService.starting_blind_candidates(
                    starting_stack=stack_value,
                    chip_denominations=seed_denominations,
                    target_depths=TARGET_STARTING_DEPTHS,
                    limit=BLIND_CANDIDATE_LIMIT,
                )
            except DomainError:
                continue

            for blind_option in blind_options:
                solved = StackOptimizerService.solve(
                    session,
                    chip_set_ids=list(chip_set_ids),
                    players=player_count,
                    starting_stack=stack_value,
                    max_reentries_per_player=reentry_limit,
                    first_small_blind=blind_option["small_blind"],
                    first_big_blind=blind_option["big_blind"],
                    first_ante=0,
                )
                solve_count += 1
                if not solved["feasible"]:
                    continue
                stack_candidate = next(item for item in solved["candidates"] if item["recommended"])
                if not cls._initial_stack_pays_first_level(stack_candidate, blind_option):
                    continue
                plan_denominations = cls._plan_denominations(stack_candidate)
                plan_expected = min(expected_reentries, stack_candidate["covered_reentries"])
                for level_minutes in cls._level_duration_candidates(target_minutes):
                    break_every, break_minutes = cls._break_schedule(
                        target_minutes=target_minutes,
                        level_minutes=level_minutes,
                    )
                    try:
                        structure = TournamentStructureGeneratorService.generate(
                            players=player_count,
                            starting_stack=stack_value,
                            expected_reentries=plan_expected,
                            max_reentries_per_player=reentry_limit,
                            first_small_blind=blind_option["small_blind"],
                            first_big_blind=blind_option["big_blind"],
                            level_duration_minutes=level_minutes,
                            target_duration_minutes=target_minutes,
                            ante_mode=normalized_ante_mode,
                            ante_start_mode="auto",
                            break_every_levels=break_every,
                            break_duration_minutes=break_minutes,
                            chip_denominations=plan_denominations,
                        )
                    except DomainError:
                        continue
                    structure_count += 1
                    tournament_pool.append(
                        cls._tournament_plan(
                            chip_set_ids=list(chip_set_ids),
                            inventory=solved["combined_inventory"],
                            players=player_count,
                            reentry_limit=reentry_limit,
                            target_minutes=target_minutes,
                            ante_mode=normalized_ante_mode,
                            starting_stack=stack_value,
                            first_blinds=blind_option,
                            level_minutes=level_minutes,
                            break_every=break_every,
                            break_minutes=break_minutes,
                            expected_reentries=plan_expected,
                            expected_explanation=expected_explanation,
                            stack_candidate=stack_candidate,
                            structure=structure,
                        )
                    )
                    if len(tournament_pool) >= FINAL_TOURNAMENT_POOL_LIMIT:
                        break
                if len(tournament_pool) >= FINAL_TOURNAMENT_POOL_LIMIT:
                    break
            if len(tournament_pool) >= FINAL_TOURNAMENT_POOL_LIMIT:
                break

        if not tournament_pool:
            raise DomainError(
                "auto_builder_no_feasible_tournament",
                "Стартовые стеки существуют, но для них не удалось подобрать удобную физическую структуру.",
            )

        tournament_pool.sort(key=cls._tournament_rank_key)
        selected = cls._select_variants(tournament_pool)
        for index, plan in enumerate(selected):
            plan["recommended"] = index == 0
            if index == 0:
                plan["variant"] = "recommended"
                plan["label"] = "Рекомендуемый"
            else:
                plan["variant"], plan["label"] = cls._alternative_label(plan, selected[0])

        return {
            "inputs": {
                "chip_set_ids": list(chip_set_ids),
                "players": player_count,
                "max_reentries_per_player": reentry_limit,
                "target_duration_minutes": target_minutes,
                "ante_mode": normalized_ante_mode,
            },
            "max_total_reentries": maximum_reentries,
            "max_total_entries": player_count * (1 + reentry_limit),
            "expected_reentries": expected_reentries,
            "expected_reentries_explanation": expected_explanation,
            "combined_inventory": inventory.serialize(),
            "candidates": selected,
            "search": {
                "stack_values_considered": stack_values,
                "stack_solver_runs": solve_count,
                "structure_generator_runs": structure_count,
                "tournament_candidates_scored": len(tournament_pool),
                "limits": {
                    "stack_candidates": STACK_CANDIDATE_LIMIT,
                    "promising_stacks": PROMISING_STACK_LIMIT,
                    "blind_candidates_per_stack": BLIND_CANDIDATE_LIMIT,
                    "tournament_pool": FINAL_TOURNAMENT_POOL_LIMIT,
                },
            },
            "deterministic": True,
        }

    @staticmethod
    def _expected_reentries(*, players: int, max_reentries_per_player: int) -> tuple[int, str]:
        maximum = players * max_reentries_per_player
        if maximum == 0:
            return 0, "Re-entry запрещены правилами турнира, поэтому прогноз длительности их не учитывает."
        percentage = min(50, 25 + 10 * min(max_reentries_per_player, 3))
        expected = min(maximum, (players * percentage + 99) // 100)
        return (
            expected,
            f"Для прогноза длительности взято {expected} re-entry ({percentage}% от числа игроков), "
            f"а не теоретический максимум {maximum}.",
        )

    @classmethod
    def _candidate_stack_values(
        cls,
        *,
        quantities: tuple[tuple[int, int], ...],
        players: int,
        max_reentries_per_player: int,
    ) -> list[int]:
        total_value = sum(value * quantity for value, quantity in quantities)
        initial_capacity = total_value // players
        if initial_capacity <= 0:
            return []
        denomination_gcd = reduce(gcd, (value for value, _ in quantities))
        friendly: set[int] = set()
        for power in range(STACK_VALUE_POWER_LIMIT + 1):
            scale = 10**power
            for numerator, denominator in STACK_VALUE_MANTISSAS:
                raw = numerator * scale
                if raw % denominator:
                    continue
                value = raw // denominator
                if value <= initial_capacity and value % denomination_gcd == 0:
                    friendly.add(value)
        for denomination, _ in quantities:
            for chip_count in STACK_CHIP_COUNT_ANCHORS:
                value = denomination * chip_count
                if value <= initial_capacity and value % denomination_gcd == 0:
                    friendly.add(value)
        if not friendly:
            fallback = initial_capacity - initial_capacity % denomination_gcd
            return [fallback] if fallback > 0 else []

        ordered = sorted(friendly)
        full_capacity = total_value // (players * (1 + max_reentries_per_player))
        anchors = (
            max(denomination_gcd, full_capacity),
            max(denomination_gcd, initial_capacity // 2),
            max(denomination_gcd, initial_capacity * 3 // 4),
            initial_capacity,
        )
        selected: set[int] = set()
        for anchor in anchors:
            nearest = sorted(
                ordered,
                key=lambda value: (abs(log(value / max(1, anchor))), value),
            )[:2]
            selected.update(nearest)
        ideal = max(denomination_gcd, full_capacity)
        for value in sorted(ordered, key=lambda item: (abs(log(item / ideal)), item)):
            selected.add(value)
            if len(selected) >= STACK_CANDIDATE_LIMIT:
                break
        return sorted(selected, key=lambda value: (abs(log(value / ideal)), value))[
            :STACK_CANDIDATE_LIMIT
        ]

    @staticmethod
    def _preliminary_rank_key(option: dict[str, Any]) -> tuple[Any, ...]:
        candidate = option["candidate"]
        return (
            -round(candidate["coverage_ratio"], 6),
            -round(candidate["overall_score"], 4),
            abs(candidate["chips_per_player"] - 28),
            option["starting_stack"],
        )

    @staticmethod
    def _plan_denominations(candidate: dict[str, Any]) -> list[int]:
        return sorted(
            {
                item["value"]
                for item in candidate["initial_distribution"] + candidate["reentry_pack"]
                if item["quantity"] > 0
            }
        )

    @staticmethod
    def _initial_stack_pays_first_level(
        candidate: dict[str, Any], first_blinds: dict[str, Any]
    ) -> bool:
        values = tuple(item["value"] for item in candidate["initial_distribution"])
        plan = tuple(item["quantity"] for item in candidate["initial_distribution"])
        return all(
            StackOptimizerService._minimum_payment_chips(plan, values, amount) is not None
            for amount in (first_blinds["small_blind"], first_blinds["big_blind"])
        )

    @staticmethod
    def _level_duration_candidates(target_minutes: int) -> tuple[int, ...]:
        if target_minutes <= 180:
            return (10, 12, 15)
        if target_minutes <= 360:
            return (12, 15, 20)
        if target_minutes <= 480:
            return (15, 20, 25)
        return (20, 25, 30)

    @staticmethod
    def _break_schedule(*, target_minutes: int, level_minutes: int) -> tuple[int, int]:
        if target_minutes < 120:
            return 0, 0
        if target_minutes < 210:
            estimated_levels = max(4, round(target_minutes / level_minutes))
            return max(4, estimated_levels // 2 + estimated_levels % 2), 10
        cadence = max(3, min(6, round(75 / level_minutes)))
        return cadence, 15 if target_minutes >= 420 else 10

    @classmethod
    def _tournament_plan(
        cls,
        *,
        chip_set_ids: list[Any],
        inventory: dict[str, Any],
        players: int,
        reentry_limit: int,
        target_minutes: int,
        ante_mode: str,
        starting_stack: int,
        first_blinds: dict[str, Any],
        level_minutes: int,
        break_every: int,
        break_minutes: int,
        expected_reentries: int,
        expected_explanation: str,
        stack_candidate: dict[str, Any],
        structure: dict[str, Any],
    ) -> dict[str, Any]:
        score_components = cls._score_tournament(
            target_minutes=target_minutes,
            level_minutes=level_minutes,
            break_every=break_every,
            inventory=inventory,
            stack_candidate=stack_candidate,
            structure=structure,
        )
        diagnostics = [dict(item) for item in structure["diagnostics"]]
        if stack_candidate["coverage_status"] == "partial":
            diagnostics.insert(
                0,
                {
                    "code": "partial_reentry_coverage",
                    "severity": "warning",
                    "message": stack_candidate["coverage_message"],
                },
            )
        diagnostics.extend(
            {"code": "stack_plan_note", "severity": "info", "message": message}
            for message in stack_candidate["warnings"]
        )
        if expected_reentries < min(
            players * reentry_limit,
            cls._expected_reentries(
                players=players, max_reentries_per_player=reentry_limit
            )[0],
        ):
            diagnostics.append(
                {
                    "code": "expected_reentries_capped_by_inventory",
                    "severity": "info",
                    "message": "Duration forecast ограничен физически обеспеченным re-entry reserve.",
                }
            )
        summary = structure["summary"]
        return {
            "recommended": False,
            "variant": "candidate",
            "label": "Вариант",
            "selected_chip_sets": inventory["chip_sets"],
            "combined_inventory": inventory,
            "players": players,
            "max_reentries_per_player": reentry_limit,
            "starting_stack": starting_stack,
            "stack_distribution_per_player": stack_candidate["initial_distribution"],
            "chips_per_player": stack_candidate["chips_per_player"],
            "reentry_pack": stack_candidate["reentry_pack"],
            "structure_denominations": summary["chip_denominations"],
            "reentry_coverage": {
                "covered": stack_candidate["covered_reentries"],
                "maximum": stack_candidate["max_allowed_reentries"],
                "status": stack_candidate["coverage_status"],
                "ratio": round(stack_candidate["coverage_ratio"], 4),
            },
            "chip_plan": {
                "chip_set_ids": chip_set_ids,
                "excluded_denominations": [],
                "initial_distribution": stack_candidate["initial_distribution"],
            },
            "first_small_blind": first_blinds["small_blind"],
            "first_big_blind": first_blinds["big_blind"],
            "starting_depth_bb": summary["starting_depth_bb"],
            "level_duration_minutes": level_minutes,
            "target_duration_minutes": target_minutes,
            "expected_reentries": expected_reentries,
            "expected_reentries_explanation": expected_explanation,
            "ante_mode": ante_mode,
            "ante_start_level": summary["ante_first_level"],
            "break_schedule": {
                "every_levels": break_every,
                "duration_minutes": break_minutes,
                "before_target": summary["breaks_before_target"],
                "total": summary["breaks_total"],
            },
            "levels": structure["levels"],
            "finish_window": summary["finish_window"],
            "extension_levels": summary["extension_levels"],
            "estimated_duration_is_guaranteed": False,
            "overall_score": score_components["total"],
            "score_components": score_components,
            "stack_optimizer_score": stack_candidate["overall_score"],
            "structure_generator_score": structure["score"],
            "diagnostics": diagnostics,
            "structure_summary": summary,
        }

    @staticmethod
    def _score_tournament(
        *,
        target_minutes: int,
        level_minutes: int,
        break_every: int,
        inventory: dict[str, Any],
        stack_candidate: dict[str, Any],
        structure: dict[str, Any],
    ) -> dict[str, float]:
        summary = structure["summary"]
        depth = summary["starting_depth_bb"]
        finish = summary["finish_window"]
        finish_midpoint_minutes = (finish["from_seconds"] + finish["to_seconds"]) / 120
        preferred_level_minutes = 12 if target_minutes <= 180 else 15 if target_minutes <= 360 else 20
        reserved_chips = sum(item["quantity"] for item in stack_candidate["reserved_quantities"])
        inventory_chips = max(1, inventory["total_chips"])
        blind_awkwardness = max(0.0, 24.0 - stack_candidate["blind_playability_score"])
        expected_breaks = 0 if target_minutes < 120 else max(1, round(target_minutes / 90) - 1)
        actual_breaks = summary["breaks_before_target"]
        components = {
            "stack_quality": -stack_candidate["overall_score"] * SCORE_STACK_QUALITY_WEIGHT,
            "structure_quality": structure["score"]["total"] * SCORE_STRUCTURE_QUALITY_WEIGHT,
            "coverage_shortfall": (1 - stack_candidate["coverage_ratio"])
            * SCORE_COVERAGE_SHORTFALL_WEIGHT,
            "starting_depth": abs(log(depth / 100)) * SCORE_DEPTH_DISTANCE_WEIGHT,
            "level_duration": abs(level_minutes - preferred_level_minutes)
            * SCORE_LEVEL_DURATION_DISTANCE_WEIGHT,
            "duration_window": abs(finish_midpoint_minutes - target_minutes)
            * SCORE_DURATION_WINDOW_DISTANCE_WEIGHT,
            "first_blind_awkwardness": blind_awkwardness * SCORE_FIRST_BLIND_AWKWARD_WEIGHT,
            "inventory_usage": (reserved_chips / inventory_chips) * SCORE_INVENTORY_USAGE_WEIGHT,
            "break_schedule": abs(actual_breaks - expected_breaks) * SCORE_BREAK_SCHEDULE_WEIGHT
            + (SCORE_BREAK_SCHEDULE_WEIGHT if target_minutes >= 240 and not break_every else 0),
        }
        return {
            "total": round(sum(components.values()), 4),
            **{key: round(value, 4) for key, value in components.items()},
        }

    @staticmethod
    def _tournament_rank_key(plan: dict[str, Any]) -> tuple[Any, ...]:
        return (
            plan["overall_score"],
            -plan["reentry_coverage"]["covered"],
            abs(plan["starting_depth_bb"] - 100),
            plan["starting_stack"],
            plan["first_big_blind"],
            plan["level_duration_minutes"],
        )

    @classmethod
    def _select_variants(cls, pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
        recommended = pool[0]
        selected = [recommended]
        for candidate in pool[1:]:
            if candidate["overall_score"] > recommended["overall_score"] + ALTERNATIVE_SCORE_MARGIN:
                continue
            if not all(cls._meaningfully_different(candidate, existing) for existing in selected):
                continue
            selected.append(candidate)
            if len(selected) == 3:
                break
        return selected

    @staticmethod
    def _meaningfully_different(left: dict[str, Any], right: dict[str, Any]) -> bool:
        stack_ratio = max(left["starting_stack"], right["starting_stack"]) / min(
            left["starting_stack"], right["starting_stack"]
        )
        return (
            stack_ratio >= 1.2
            or abs(left["starting_depth_bb"] - right["starting_depth_bb"]) >= 25
            or abs(left["level_duration_minutes"] - right["level_duration_minutes"]) >= 5
        )

    @staticmethod
    def _alternative_label(plan: dict[str, Any], recommended: dict[str, Any]) -> tuple[str, str]:
        if plan["starting_depth_bb"] >= recommended["starting_depth_bb"] * 1.15:
            return "deep", "Глубокий"
        if (
            plan["starting_depth_bb"] <= recommended["starting_depth_bb"] * 0.85
            or plan["level_duration_minutes"] < recommended["level_duration_minutes"]
        ):
            return "compact", "Компактный / быстрый"
        return "alternative", "Альтернативный"

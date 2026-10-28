"""Детерминированный подбор физических стартовых стеков и re-entry packs."""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from math import gcd
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.chip_inventory import ChipSet
from app.services.errors import DomainError


MODE_TARGETS = {
    "comfortable": (35, 30, 42),
    "balanced": (27, 22, 32),
    "compact": (19, 14, 24),
}
MODE_LABELS = {
    "comfortable": "Comfortable",
    "balanced": "Balanced",
    "compact": "Compact",
}
MODE_COVERAGE_WEIGHTS = {"comfortable": 54.0, "balanced": 68.0, "compact": 60.0}
OVERALL_COVERAGE_WEIGHT = 120.0
OVERALL_CHIP_TARGET = 28
OVERALL_REASONABLE_CHIP_RANGE = (14, 42)
DOMINANCE_PLAYABILITY_MARGIN = 12.0
DOMINANCE_REENTRY_TOLERANCE = 4.0
DIRECT_DENOMINATION_PROFILES = {
    "small_blind": (-24.0, -12.0, -6.0, -2.0, 4.0, 7.0, 9.0, 10.0, 11.0),
    "big_blind": (-16.0, -8.0, -4.0, -1.0, 3.0, 5.0, 7.0, 8.0, 9.0),
    "ante": (-14.0, -7.0, -3.0, 0.0, 3.0, 5.0, 6.0, 7.0),
}
PAYMENT_CHIP_SCORES = {1: 8.0, 2: 3.0, 3: -2.0}
UNREPRESENTABLE_BLIND_PENALTY = -20.0
EXTRA_PAYMENT_CHIP_PENALTY = 2.0
REENTRY_EARLY_DENOMINATION_WEIGHTS = {"small_blind": 5.0, "big_blind": 3.0, "ante": 2.0}
INITIAL_SEARCH_LIMIT = 280
INITIAL_EVALUATION_LIMIT = 48
REENTRY_SEARCH_LIMIT = 220
LARGE_REENTRY_CHIP_RATIO = 0.7


@dataclass(frozen=True)
class CombinedInventory:
    chip_sets: tuple[dict[str, Any], ...]
    quantities: tuple[tuple[int, int], ...]

    @property
    def total_chips(self) -> int:
        return sum(quantity for _, quantity in self.quantities)

    @property
    def total_value(self) -> int:
        return sum(value * quantity for value, quantity in self.quantities)

    def serialize(self) -> dict[str, Any]:
        return {
            "chip_sets": [dict(item) for item in self.chip_sets],
            "denominations": [
                {"value": value, "quantity": quantity} for value, quantity in self.quantities
            ],
            "total_chips": self.total_chips,
            "total_value": self.total_value,
        }


class StackOptimizerService:
    """Решает bounded integer-задачу без изменения исходного inventory."""

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
    def combine_inventory(
        cls,
        session: Session,
        chip_set_ids: Any,
        *,
        excluded_denominations: Iterable[Any] | None = None,
    ) -> CombinedInventory:
        if not isinstance(chip_set_ids, list) or not chip_set_ids:
            raise DomainError("invalid_selected_chip_sets", "Выберите хотя бы один набор фишек.")
        normalized_ids: list[int] = []
        for raw_id in chip_set_ids:
            chip_set_id = cls._integer(
                raw_id,
                code="invalid_selected_chip_sets",
                message="Проверьте выбранные наборы фишек.",
                minimum=1,
            )
            if chip_set_id not in normalized_ids:
                normalized_ids.append(chip_set_id)

        excluded: set[int] = set()
        for raw_value in excluded_denominations or []:
            excluded.add(
                cls._integer(
                    raw_value,
                    code="invalid_excluded_denomination",
                    message="Проверьте исключённые номиналы.",
                    minimum=1,
                )
            )

        selected = list(
            session.scalars(
                select(ChipSet)
                .options(selectinload(ChipSet.denominations))
                .where(ChipSet.id.in_(normalized_ids))
            )
        )
        by_id = {chip_set.id: chip_set for chip_set in selected}
        missing = [chip_set_id for chip_set_id in normalized_ids if chip_set_id not in by_id]
        if missing:
            raise DomainError(
                "invalid_selected_chip_sets",
                "Один или несколько выбранных наборов больше не существуют.",
            )

        quantities: dict[int, int] = {}
        snapshots: list[dict[str, Any]] = []
        for chip_set_id in normalized_ids:
            chip_set = by_id[chip_set_id]
            denominations = [
                {"value": item.value, "quantity": item.quantity}
                for item in sorted(chip_set.denominations, key=lambda item: item.value)
            ]
            snapshots.append({"id": chip_set.id, "name": chip_set.name, "denominations": denominations})
            for denomination in chip_set.denominations:
                if denomination.value not in excluded:
                    quantities[denomination.value] = quantities.get(denomination.value, 0) + denomination.quantity
        return CombinedInventory(
            chip_sets=tuple(snapshots),
            quantities=tuple(sorted(quantities.items())),
        )

    @classmethod
    def solve(
        cls,
        session: Session,
        *,
        chip_set_ids: Any,
        players: Any,
        starting_stack: Any,
        max_reentries_per_player: Any,
        first_small_blind: Any = None,
        first_big_blind: Any = None,
        first_ante: Any = None,
        excluded_denominations: Iterable[Any] | None = None,
    ) -> dict[str, Any]:
        player_count = cls._integer(
            players, code="invalid_players", message="Количество игроков должно быть больше нуля.", minimum=1
        )
        stack_value = cls._integer(
            starting_stack,
            code="invalid_starting_stack",
            message="Стартовый стек должен быть больше нуля.",
            minimum=1,
        )
        reentry_limit = cls._integer(
            max_reentries_per_player,
            code="invalid_reentry_limit",
            message="Укажите неотрицательный лимит re-entry на одного игрока.",
            minimum=0,
        )
        sb = cls._optional_nonnegative(first_small_blind, "invalid_first_blinds")
        bb = cls._optional_nonnegative(first_big_blind, "invalid_first_blinds")
        ante = cls._optional_nonnegative(first_ante, "invalid_first_blinds")
        if (sb is None) != (bb is None) or (sb is not None and (sb <= 0 or bb < sb)):
            raise DomainError("invalid_first_blinds", "Проверьте SB и BB первого уровня.")

        inventory = cls.combine_inventory(
            session, chip_set_ids, excluded_denominations=excluded_denominations
        )
        max_allowed_reentries = player_count * reentry_limit
        required_initial_value = player_count * stack_value
        required_full_value = player_count * (1 + reentry_limit) * stack_value
        diagnostics = {
            "required_initial_value": required_initial_value,
            "required_full_coverage_value": required_full_value,
            "available_value": inventory.total_value,
            "initial_value_shortage": max(0, required_initial_value - inventory.total_value),
            "full_coverage_value_shortage": max(0, required_full_value - inventory.total_value),
            "full_coverage_possible_by_value": inventory.total_value >= required_full_value,
        }
        base_result = {
            "feasible": False,
            "players": player_count,
            "starting_stack": stack_value,
            "max_reentries_per_player": reentry_limit,
            "max_total_reentries": max_allowed_reentries,
            "max_total_entries": player_count * (1 + reentry_limit),
            "first_blinds": {"small_blind": sb, "big_blind": bb, "ante": ante},
            "combined_inventory": inventory.serialize(),
            "diagnostics": diagnostics,
            "candidates": [],
        }
        if inventory.total_value < required_initial_value:
            diagnostics["reason"] = "insufficient_total_value"
            diagnostics["message"] = "Общей стоимости фишек недостаточно для стартовой посадки."
            return base_result

        positive = [(value, quantity) for value, quantity in inventory.quantities if quantity > 0]
        if not positive:
            diagnostics["reason"] = "empty_inventory"
            diagnostics["message"] = "В выбранных наборах нет доступных фишек."
            return base_result
        denomination_gcd = reduce(gcd, (value for value, _ in positive))
        diagnostics["denomination_gcd"] = denomination_gcd
        if stack_value % denomination_gcd:
            diagnostics["reason"] = "stack_unrepresentable"
            diagnostics["message"] = "Стартовый стек нельзя точно собрать из выбранных номиналов."
            return base_result

        values = tuple(value for value, _ in positive)
        quantities = tuple(quantity for _, quantity in positive)
        per_player_limits = tuple(quantity // player_count for quantity in quantities)
        all_initials: set[tuple[int, ...]] = set()
        mode_initials: dict[str, list[tuple[int, ...]]] = {}
        for mode, (target, low, high) in MODE_TARGETS.items():
            combinations = cls._exact_combinations(
                values,
                per_player_limits,
                stack_value,
                target_chips=target,
                min_chips=low,
                max_chips=high,
                limit=INITIAL_SEARCH_LIMIT,
            )
            if not combinations:
                combinations = cls._exact_combinations(
                    values,
                    per_player_limits,
                    stack_value,
                    target_chips=target,
                    min_chips=1,
                    max_chips=sum(per_player_limits),
                    limit=INITIAL_SEARCH_LIMIT,
                )
            mode_initials[mode] = combinations
            all_initials.update(combinations)

        if not all_initials:
            diagnostics["reason"] = "denomination_quantities_insufficient"
            diagnostics["message"] = "Номиналов или их количества недостаточно для точных стартовых стеков."
            return base_result

        evaluated: dict[tuple[int, ...], dict[str, Any]] = {}
        for mode in MODE_TARGETS:
            target = MODE_TARGETS[mode][0]
            ranked_initials = sorted(
                mode_initials[mode],
                key=lambda plan: cls._initial_pref_key(
                    plan, values, quantities, player_count, target, sb, bb, ante
                ),
            )[:INITIAL_EVALUATION_LIMIT]
            for initial in ranked_initials:
                if initial not in evaluated:
                    evaluated[initial] = cls._evaluate_initial(
                        initial,
                        values=values,
                        quantities=quantities,
                        players=player_count,
                        stack_value=stack_value,
                        max_allowed_reentries=max_allowed_reentries,
                        max_reentries_per_player=reentry_limit,
                        small_blind=sb,
                        big_blind=bb,
                        ante=ante,
                    )

        candidate_pool: list[dict[str, Any]] = []
        for candidate_data in evaluated.values():
            candidate = dict(candidate_data)
            mode = cls._classify_mode(candidate["chips_per_player"])
            candidate["mode"] = mode
            candidate["label"] = MODE_LABELS[mode]
            candidate["mode_score"] = round(
                cls._candidate_score(candidate, mode, quantities, player_count), 4
            )
            candidate["overall_score"] = round(
                cls._overall_score(candidate, quantities, player_count), 4
            )
            candidate["score"] = candidate["mode_score"]
            candidate["quality_highlights"] = cls._quality_highlights(candidate, sb, bb)
            candidate_pool.append(candidate)

        selected_by_mode: dict[str, dict[str, Any]] = {}
        for candidate in candidate_pool:
            current = selected_by_mode.get(candidate["mode"])
            if current is None or cls._mode_rank_key(candidate) < cls._mode_rank_key(current):
                selected_by_mode[candidate["mode"]] = candidate

        nondominated = [
            candidate
            for candidate in candidate_pool
            if not any(
                other is not candidate and cls._dominates(other, candidate)
                for other in candidate_pool
            )
        ]
        recommended = min(nondominated, key=cls._overall_rank_key)
        selected_by_mode[recommended["mode"]] = recommended

        deduplicated: list[dict[str, Any]] = []
        seen_distributions: set[tuple[tuple[int, int], ...]] = set()
        for mode in ("comfortable", "balanced", "compact"):
            candidate = selected_by_mode.get(mode)
            if candidate is None:
                continue
            key = tuple((item["value"], item["quantity"]) for item in candidate["initial_distribution"])
            if key in seen_distributions:
                continue
            seen_distributions.add(key)
            deduplicated.append(candidate)
        if not deduplicated:
            diagnostics["reason"] = "denomination_quantities_insufficient"
            diagnostics["message"] = "Не удалось построить практический точный стек."
            return base_result

        for candidate in deduplicated:
            candidate["recommended"] = candidate is recommended
        deduplicated.sort(
            key=lambda item: (
                not item["recommended"],
                ("comfortable", "balanced", "compact").index(item["mode"]),
            )
        )
        max_supported = max(item["covered_reentries"] for item in deduplicated)
        diagnostics["reason"] = None
        diagnostics["message"] = "Стартовые стеки обеспечены полностью."
        diagnostics["max_physically_supported_reentries"] = max_supported
        diagnostics["full_coverage"] = max_supported == max_allowed_reentries
        if max_supported < max_allowed_reentries:
            diagnostics["coverage_warning"] = (
                f"Правила допускают до {max_allowed_reentries} re-entry; "
                f"лучший найденный план обеспечивает {max_supported}."
            )
        return {**base_result, "feasible": True, "candidates": deduplicated}

    @classmethod
    def evaluate_selection(
        cls,
        session: Session,
        *,
        chip_set_ids: Any,
        players: Any,
        starting_stack: Any,
        max_reentries_per_player: Any,
        initial_distribution: Any,
        first_small_blind: Any = None,
        first_big_blind: Any = None,
        first_ante: Any = None,
        excluded_denominations: Iterable[Any] | None = None,
    ) -> dict[str, Any]:
        """Revalidate an explicitly selected exact plan without re-ranking it.

        Manual blind edits may change soft score, but they must not silently
        replace a user's physical stack.  This method reuses the existing
        inventory constraints and candidate evaluator while treating the
        selected initial distribution as an input hard constraint.
        """

        player_count = cls._integer(
            players,
            code="invalid_players",
            message="Количество игроков должно быть больше нуля.",
            minimum=1,
        )
        stack_value = cls._integer(
            starting_stack,
            code="invalid_starting_stack",
            message="Стартовый стек должен быть больше нуля.",
            minimum=1,
        )
        reentry_limit = cls._integer(
            max_reentries_per_player,
            code="invalid_reentry_limit",
            message="Укажите неотрицательный лимит re-entry на одного игрока.",
            minimum=0,
        )
        small_blind = cls._optional_nonnegative(first_small_blind, "invalid_first_blinds")
        big_blind = cls._optional_nonnegative(first_big_blind, "invalid_first_blinds")
        ante = cls._optional_nonnegative(first_ante, "invalid_first_blinds")
        if (small_blind is None) != (big_blind is None) or (
            small_blind is not None and (small_blind <= 0 or big_blind < small_blind)
        ):
            raise DomainError("invalid_first_blinds", "Проверьте SB и BB первого уровня.")
        if not isinstance(initial_distribution, list) or not initial_distribution:
            raise DomainError("invalid_chip_plan", "Проверьте выбранный план фишек.")

        inventory = cls.combine_inventory(
            session,
            chip_set_ids,
            excluded_denominations=excluded_denominations,
        )
        positive = [(value, quantity) for value, quantity in inventory.quantities if quantity > 0]
        values = tuple(value for value, _ in positive)
        quantities = tuple(quantity for _, quantity in positive)
        requested: dict[int, int] = {}
        for raw in initial_distribution:
            if not isinstance(raw, dict):
                raise DomainError("invalid_chip_plan", "Проверьте выбранный план фишек.")
            value = cls._integer(
                raw.get("value"),
                code="invalid_chip_plan",
                message="Проверьте выбранный план фишек.",
                minimum=1,
            )
            quantity = cls._integer(
                raw.get("quantity"),
                code="invalid_chip_plan",
                message="Проверьте выбранный план фишек.",
                minimum=0,
            )
            if value in requested:
                raise DomainError("invalid_chip_plan", "В плане фишек повторяется номинал.")
            requested[value] = quantity
        if any(value not in values and quantity > 0 for value, quantity in requested.items()):
            raise DomainError(
                "chip_plan_no_longer_feasible",
                "Набор изменился или выбранный вариант устарел. Рассчитайте план повторно.",
            )
        initial = tuple(requested.get(value, 0) for value in values)
        if sum(value * quantity for value, quantity in zip(values, initial)) != stack_value or any(
            player_count * count > available for count, available in zip(initial, quantities)
        ):
            raise DomainError(
                "chip_plan_no_longer_feasible",
                "Набор изменился или выбранный вариант устарел. Рассчитайте план повторно.",
            )

        candidate = cls._evaluate_initial(
            initial,
            values=values,
            quantities=quantities,
            players=player_count,
            stack_value=stack_value,
            max_allowed_reentries=player_count * reentry_limit,
            max_reentries_per_player=reentry_limit,
            small_blind=small_blind,
            big_blind=big_blind,
            ante=ante,
        )
        mode = cls._classify_mode(candidate["chips_per_player"])
        candidate["mode"] = mode
        candidate["label"] = MODE_LABELS[mode]
        candidate["mode_score"] = round(
            cls._candidate_score(candidate, mode, quantities, player_count), 4
        )
        candidate["overall_score"] = round(
            cls._overall_score(candidate, quantities, player_count), 4
        )
        candidate["score"] = candidate["mode_score"]
        candidate["quality_highlights"] = cls._quality_highlights(
            candidate, small_blind, big_blind
        )
        candidate["recommended"] = True
        return {
            "players": player_count,
            "starting_stack": stack_value,
            "max_reentries_per_player": reentry_limit,
            "max_total_reentries": player_count * reentry_limit,
            "combined_inventory": inventory.serialize(),
            "candidate": candidate,
        }

    @staticmethod
    def _optional_nonnegative(raw: Any, code: str) -> int | None:
        if raw in (None, ""):
            return None
        if isinstance(raw, bool):
            raise DomainError(code, "Проверьте параметры первого уровня.")
        try:
            value = int(raw)
        except (TypeError, ValueError) as error:
            raise DomainError(code, "Проверьте параметры первого уровня.") from error
        if value < 0:
            raise DomainError(code, "Проверьте параметры первого уровня.")
        return value

    @classmethod
    def _evaluate_initial(
        cls,
        initial: tuple[int, ...],
        *,
        values: tuple[int, ...],
        quantities: tuple[int, ...],
        players: int,
        stack_value: int,
        max_allowed_reentries: int,
        max_reentries_per_player: int,
        small_blind: int | None,
        big_blind: int | None,
        ante: int | None,
    ) -> dict[str, Any]:
        after_initial = tuple(quantity - players * count for quantity, count in zip(quantities, initial))
        covered, reentry = cls._best_reentry_pack(
            values,
            after_initial,
            stack_value,
            max_allowed_reentries,
            small_blind=small_blind,
            big_blind=big_blind,
            ante=ante,
        )
        reserved = tuple(players * count + covered * pack for count, pack in zip(initial, reentry))
        remaining = tuple(quantity - used for quantity, used in zip(quantities, reserved))
        uniform = covered // players
        common_reserve = covered % players
        coverage_status = "full" if covered == max_allowed_reentries else "partial"
        warnings: list[str] = []
        if reentry and sum(reentry):
            threshold = big_blind * 5 if big_blind else stack_value // 5
            large_count = sum(count for value, count in zip(values, reentry) if value >= threshold)
            if large_count / sum(reentry) >= LARGE_REENTRY_CHIP_RATIO:
                warnings.append("Для re-entry может потребоваться размен за столом.")
        suggested_limit = min(max_reentries_per_player, uniform)
        if coverage_status == "full":
            coverage_message = f"Все {max_allowed_reentries} разрешённых re-entry обеспечены."
        else:
            coverage_message = (
                f"Правила допускают {max_allowed_reentries} re-entry; набор обеспечивает {covered}."
            )
        uniform_message = None
        if coverage_status == "partial" and uniform > 0:
            uniform_message = (
                f"Гарантированно каждому — {uniform}; дополнительный общий запас — {common_reserve}."
            )
        coverage_suggestion = None
        if coverage_status == "partial" and suggested_limit > 0:
            coverage_suggestion = (
                f"Полное покрытие возможно при лимите {suggested_limit} re-entry на игрока."
            )
        blind_playability_score = cls._blind_playability_score(
            initial, values, small_blind, big_blind, ante
        )
        reentry_quality_score = cls._reentry_quality_score(
            reentry, values, small_blind, big_blind, ante
        )
        return {
            "initial_distribution": cls._serialize_distribution(values, initial),
            "initial_total_distribution": cls._serialize_distribution(
                values, tuple(players * count for count in initial), include_zero=True
            ),
            "value": stack_value,
            "chips_per_player": sum(initial),
            "reentry_pack": cls._serialize_distribution(values, reentry),
            "reentry_chips": sum(reentry),
            "max_reentries_per_player": max_reentries_per_player,
            "max_allowed_reentries": max_allowed_reentries,
            "covered_reentries": covered,
            "coverage_status": coverage_status,
            "coverage_ratio": 1.0 if max_allowed_reentries == 0 else covered / max_allowed_reentries,
            "uniform_reentries_per_player": uniform,
            "additional_common_reserve": common_reserve,
            "coverage_message": coverage_message,
            "uniform_message": uniform_message,
            "coverage_suggestion": coverage_suggestion,
            "blind_playability_score": round(blind_playability_score, 4),
            "reentry_quality_score": round(reentry_quality_score, 4),
            "reserved_quantities": cls._serialize_distribution(values, reserved, include_zero=True),
            "remaining_inventory": cls._serialize_distribution(values, remaining, include_zero=True),
            "warnings": warnings,
        }

    @classmethod
    def _best_reentry_pack(
        cls,
        values: tuple[int, ...],
        remaining: tuple[int, ...],
        stack_value: int,
        max_allowed: int,
        *,
        small_blind: int | None,
        big_blind: int | None,
        ante: int | None,
    ) -> tuple[int, tuple[int, ...]]:
        empty = tuple(0 for _ in values)
        if max_allowed == 0:
            return 0, empty
        value_capacity = sum(value * quantity for value, quantity in zip(values, remaining)) // stack_value
        upper = min(max_allowed, value_capacity)
        for covered in range(upper, 0, -1):
            limits = tuple(quantity // covered for quantity in remaining)
            combinations = cls._exact_combinations(
                values,
                limits,
                stack_value,
                target_chips=10,
                min_chips=1,
                max_chips=sum(limits),
                limit=REENTRY_SEARCH_LIMIT,
            )
            if combinations:
                return covered, min(
                    combinations,
                    key=lambda plan: cls._reentry_pref_key(
                        plan,
                        values,
                        remaining,
                        covered,
                        small_blind,
                        big_blind,
                        ante,
                    ),
                )
        return 0, empty

    @staticmethod
    def _initial_pref_key(
        plan: tuple[int, ...],
        values: tuple[int, ...],
        quantities: tuple[int, ...],
        players: int,
        target: int,
        small_blind: int | None,
        big_blind: int | None,
        ante: int | None,
    ) -> tuple[Any, ...]:
        chips = sum(plan)
        blind_score = StackOptimizerService._blind_playability_score(
            plan, values, small_blind, big_blind, ante
        )
        depletion = sum((players * count) / quantity for count, quantity in zip(plan, quantities) if quantity)
        return (
            abs(chips - target),
            -blind_score,
            depletion,
            -sum(count > 0 for count in plan),
            tuple(reversed(plan)),
        )

    @staticmethod
    def _reentry_pref_key(
        plan: tuple[int, ...],
        values: tuple[int, ...],
        remaining: tuple[int, ...],
        covered: int,
        small_blind: int | None,
        big_blind: int | None,
        ante: int | None,
    ) -> tuple[Any, ...]:
        early_usage = StackOptimizerService._reentry_early_usage_penalty(
            plan, values, small_blind, big_blind, ante
        )
        scarcity = sum(
            (covered * count) / quantity for count, quantity in zip(plan, remaining) if quantity
        )
        large_concentration = sum(value * value * count for value, count in zip(values, plan))
        return (
            early_usage,
            sum(plan),
            scarcity,
            -large_concentration,
            -sum(count > 0 for count in plan),
            tuple(plan),
        )

    @classmethod
    def _candidate_score(
        cls,
        candidate: dict[str, Any],
        mode: str,
        quantities: tuple[int, ...],
        players: int,
    ) -> float:
        target, low, high = MODE_TARGETS[mode]
        chips = candidate["chips_per_player"]
        range_penalty = max(0, low - chips, chips - high)
        chip_score = 30.0 - abs(chips - target) * 1.1 - range_penalty * 1.8
        initial = tuple(item["quantity"] for item in candidate["initial_total_distribution"])
        per_player = tuple(count // players for count in initial)
        variety_score = min(10.0, sum(count > 0 for count in per_player) * 2.0)
        depletion = sum(used / total for used, total in zip(initial, quantities) if total)
        coverage_score = candidate["coverage_ratio"] * MODE_COVERAGE_WEIGHTS[mode]
        return (
            chip_score
            + candidate["blind_playability_score"]
            + variety_score
            + coverage_score
            + candidate["reentry_quality_score"] * 0.45
            - depletion * 2.0
        )

    @staticmethod
    def _overall_score(
        candidate: dict[str, Any], quantities: tuple[int, ...], players: int
    ) -> float:
        chips = candidate["chips_per_player"]
        low, high = OVERALL_REASONABLE_CHIP_RANGE
        range_penalty = max(0, low - chips, chips - high)
        chip_score = 20.0 - abs(chips - OVERALL_CHIP_TARGET) * 0.55 - range_penalty * 2.0
        initial = tuple(item["quantity"] for item in candidate["initial_total_distribution"])
        per_player = tuple(count // players for count in initial)
        variety_score = min(8.0, sum(count > 0 for count in per_player) * 1.5)
        depletion = sum(used / total for used, total in zip(initial, quantities) if total)
        return (
            candidate["coverage_ratio"] * OVERALL_COVERAGE_WEIGHT
            + candidate["blind_playability_score"]
            + candidate["reentry_quality_score"] * 0.7
            + chip_score
            + variety_score
            - depletion * 2.0
        )

    @staticmethod
    def _classify_mode(chips_per_player: int) -> str:
        mode_order = ("comfortable", "balanced", "compact")
        return min(
            mode_order,
            key=lambda mode: (
                abs(chips_per_player - MODE_TARGETS[mode][0]),
                mode_order.index(mode),
            ),
        )

    @classmethod
    def _mode_rank_key(cls, candidate: dict[str, Any]) -> tuple[Any, ...]:
        return (
            -candidate["mode_score"],
            -candidate["covered_reentries"],
            -candidate["blind_playability_score"],
            -candidate["reentry_quality_score"],
            candidate["chips_per_player"],
            cls._distribution_key(candidate),
        )

    @classmethod
    def _overall_rank_key(cls, candidate: dict[str, Any]) -> tuple[Any, ...]:
        return (
            -round(candidate["overall_score"], 3),
            -candidate["covered_reentries"],
            -candidate["blind_playability_score"],
            -candidate["reentry_quality_score"],
            candidate["chips_per_player"],
            cls._distribution_key(candidate),
        )

    @staticmethod
    def _dominates(candidate: dict[str, Any], other: dict[str, Any]) -> bool:
        low, high = OVERALL_REASONABLE_CHIP_RANGE
        return (
            candidate["covered_reentries"] >= other["covered_reentries"]
            and candidate["blind_playability_score"]
            >= other["blind_playability_score"] + DOMINANCE_PLAYABILITY_MARGIN
            and candidate["reentry_quality_score"]
            >= other["reentry_quality_score"] - DOMINANCE_REENTRY_TOLERANCE
            and low <= candidate["chips_per_player"] <= high
        )

    @staticmethod
    def _direct_denomination_score(count: int, profile: tuple[float, ...]) -> float:
        return profile[min(count, len(profile) - 1)]

    @staticmethod
    def _minimum_payment_chips(
        plan: tuple[int, ...], values: tuple[int, ...], amount: int
    ) -> int | None:
        if amount <= 0:
            return 0
        unreachable = amount + 1
        best = [unreachable] * (amount + 1)
        best[0] = 0
        for value, count in zip(values, plan):
            usable = min(count, amount // value)
            for _ in range(usable):
                for total in range(amount, value - 1, -1):
                    if best[total - value] != unreachable:
                        best[total] = min(best[total], best[total - value] + 1)
        return None if best[amount] == unreachable else best[amount]

    @classmethod
    def _blind_playability_score(
        cls,
        plan: tuple[int, ...],
        values: tuple[int, ...],
        small_blind: int | None,
        big_blind: int | None,
        ante: int | None,
    ) -> float:
        score = 0.0
        for role, amount in (
            ("small_blind", small_blind),
            ("big_blind", big_blind),
            ("ante", ante),
        ):
            if not amount:
                continue
            if amount in values:
                score += cls._direct_denomination_score(
                    plan[values.index(amount)], DIRECT_DENOMINATION_PROFILES[role]
                )
            payment_chips = cls._minimum_payment_chips(plan, values, amount)
            if payment_chips is None:
                score += UNREPRESENTABLE_BLIND_PENALTY
            elif payment_chips in PAYMENT_CHIP_SCORES:
                score += PAYMENT_CHIP_SCORES[payment_chips]
            elif payment_chips > 3:
                score += PAYMENT_CHIP_SCORES[3] - (
                    payment_chips - 3
                ) * EXTRA_PAYMENT_CHIP_PENALTY
        return score

    @staticmethod
    def _reentry_early_usage_penalty(
        plan: tuple[int, ...],
        values: tuple[int, ...],
        small_blind: int | None,
        big_blind: int | None,
        ante: int | None,
    ) -> float:
        weights: dict[int, float] = {}
        for role, amount in (
            ("small_blind", small_blind),
            ("big_blind", big_blind),
            ("ante", ante),
        ):
            if amount:
                weights[amount] = max(weights.get(amount, 0.0), REENTRY_EARLY_DENOMINATION_WEIGHTS[role])
        penalty = sum(count * weights.get(value, 0.0) for value, count in zip(values, plan))
        if big_blind:
            penalty += sum(
                count * 0.25
                for value, count in zip(values, plan)
                if value < big_blind and value not in weights
            )
        return penalty

    @classmethod
    def _reentry_quality_score(
        cls,
        plan: tuple[int, ...],
        values: tuple[int, ...],
        small_blind: int | None,
        big_blind: int | None,
        ante: int | None,
    ) -> float:
        if not any(plan):
            return 0.0
        early_penalty = cls._reentry_early_usage_penalty(
            plan, values, small_blind, big_blind, ante
        )
        chip_count = sum(plan)
        compact_bonus = max(-8.0, 8.0 - chip_count * 0.6)
        largest_value = max(value for value, count in zip(values, plan) if count)
        large_chip_bonus = sum(
            count for value, count in zip(values, plan) if value >= largest_value / 2
        ) * 0.5
        return compact_bonus + large_chip_bonus - early_penalty

    @staticmethod
    def _quality_highlights(
        candidate: dict[str, Any], small_blind: int | None, big_blind: int | None
    ) -> list[str]:
        if not small_blind or not big_blind:
            return []
        initial = {item["value"]: item["quantity"] for item in candidate["initial_distribution"]}
        reentry = {item["value"]: item["quantity"] for item in candidate["reentry_pack"]}
        highlights: list[str] = []
        if initial.get(small_blind, 0) >= 4 and initial.get(big_blind, 0) >= 4:
            highlights.append(f"Удобно для первого уровня {small_blind}/{big_blind}.")
        if reentry.get(small_blind, 0) == 0 and reentry.get(big_blind, 0) == 0:
            highlights.append("Номиналы ранних блайндов сохранены для стартовых стеков.")
        return highlights

    @staticmethod
    def _distribution_key(candidate: dict[str, Any]) -> tuple[tuple[int, int], ...]:
        return tuple((item["value"], item["quantity"]) for item in candidate["initial_distribution"])

    @staticmethod
    def _serialize_distribution(
        values: tuple[int, ...], counts: tuple[int, ...], *, include_zero: bool = False
    ) -> list[dict[str, int]]:
        return [
            {"value": value, "quantity": count}
            for value, count in zip(values, counts)
            if include_zero or count
        ]

    @staticmethod
    def _exact_combinations(
        values: tuple[int, ...],
        limits: tuple[int, ...],
        target_value: int,
        *,
        target_chips: int,
        min_chips: int,
        max_chips: int,
        limit: int,
    ) -> list[tuple[int, ...]]:
        """Bounded DFS: suffix value/GCD/chip bounds prune the search tree."""
        if not values or target_value <= 0 or max_chips <= 0:
            return []
        order = tuple(sorted(range(len(values)), key=lambda index: values[index], reverse=True))
        ordered_values = tuple(values[index] for index in order)
        ordered_limits = tuple(limits[index] for index in order)
        length = len(order)
        suffix_max = [0] * (length + 1)
        suffix_gcd = [0] * (length + 1)
        for index in range(length - 1, -1, -1):
            suffix_max[index] = suffix_max[index + 1] + ordered_values[index] * ordered_limits[index]
            suffix_gcd[index] = gcd(suffix_gcd[index + 1], ordered_values[index])
        found: list[tuple[int, ...]] = []
        current = [0] * length

        def visit(index: int, remaining_value: int, used_chips: int) -> None:
            if len(found) >= limit or remaining_value < 0:
                return
            if remaining_value > suffix_max[index]:
                return
            if index < length and suffix_gcd[index] and remaining_value % suffix_gcd[index]:
                return
            if index == length:
                if remaining_value == 0 and min_chips <= used_chips <= max_chips:
                    original = [0] * length
                    for ordered_index, original_index in enumerate(order):
                        original[original_index] = current[ordered_index]
                    found.append(tuple(original))
                return
            value = ordered_values[index]
            maximum = min(ordered_limits[index], remaining_value // value, max_chips - used_chips)
            if index == length - 1:
                if remaining_value % value:
                    return
                count = remaining_value // value
                if 0 <= count <= maximum and min_chips <= used_chips + count <= max_chips:
                    current[index] = count
                    visit(index + 1, 0, used_chips + count)
                return
            ideal = max(0, min(maximum, target_chips - used_chips))
            counts = sorted(range(maximum + 1), key=lambda count: (abs(count - ideal), count))
            for count in counts:
                next_value = remaining_value - count * value
                next_chips = used_chips + count
                if next_value and index + 1 < length:
                    max_remaining_denomination = ordered_values[index + 1]
                    min_needed = (next_value + max_remaining_denomination - 1) // max_remaining_denomination
                    min_remaining_denomination = ordered_values[-1]
                    max_needed = next_value // min_remaining_denomination
                    if next_chips + min_needed > max_chips or next_chips + max_needed < min_chips:
                        continue
                current[index] = count
                visit(index + 1, next_value, next_chips)

        visit(0, target_value, 0)
        return found

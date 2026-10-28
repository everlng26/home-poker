"""Deterministic blind-structure planning for editable Home Poker levels.

The generator is deliberately heuristic.  It estimates where a tournament may
reach late-game pressure; it does not predict the actual finish time.  Its
output is the same ``play``/``break`` payload already consumed by BlindLevel.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from heapq import heappop, heappush
from math import ceil, gcd, log
from typing import Any, Iterable

from app.services.errors import DomainError


# Late-game pressure heuristic: around the estimated finish point the chips in
# play are expected to total roughly twenty big blinds.  This represents a
# short-handed / heads-up pressure zone, not a mathematical finish condition.
TARGET_FINAL_TOTAL_CHIPS_IN_BB = 20

FINISH_WINDOW_RADIUS_LEVELS = 2
EXTENSION_LEVELS_AFTER_WINDOW = 4

# Auto BBA waits for at least two complete levels and for the nominal starting
# stack to fall to at most this many current big blinds.
AUTO_ANTE_START_DEPTH_BB = 50
MIN_AUTO_ANTE_START_LEVEL = 3

# Progression quality targets.  Values outside the soft band remain legal, but
# are penalised.  The hard warning threshold identifies visibly abrupt jumps.
MIN_PREFERRED_GROWTH = 1.25
MAX_PREFERRED_GROWTH = 1.50
MIN_MEANINGFUL_GROWTH = 1.15
MAX_REASONABLE_GROWTH = 1.65
AGGRESSIVE_GROWTH_WARNING = 1.70

SHALLOW_STARTING_DEPTH_BB = 20
DEEP_STARTING_DEPTH_BB = 200

# Named deterministic scoring weights.  Lower scores are better.
SCORE_TARGET_PRESSURE_WEIGHT = 90.0
SCORE_GROWTH_BAND_WEIGHT = 28.0
SCORE_GROWTH_VARIANCE_WEIGHT = 12.0
SCORE_TINY_STEP_WEIGHT = 80.0
SCORE_ABRUPT_JUMP_WEIGHT = 110.0
SCORE_PHYSICAL_PAYMENT_WEIGHT = 2.0
SCORE_STARTING_DEPTH_WEIGHT = 0.25
SCORE_DURATION_DISTANCE_WEIGHT = 0.01

# Candidate variants are intentionally small, keeping generation effectively
# instantaneous while still comparing slower/faster terminal approaches.
TERMINAL_CANDIDATE_FACTORS = (0.82, 0.92, 1.0, 1.08, 1.18)
CURVE_CANDIDATE_EXPONENTS = (0.9, 1.0, 1.1)

# Familiar poker values are represented as rational mantissas times powers of
# ten.  This includes 75/150, 600/1,200 and 800/1,600 style transitions.
NICE_VALUE_MANTISSAS = (
    (1, 1),
    (6, 5),
    (3, 2),
    (8, 5),
    (2, 1),
    (5, 2),
    (3, 1),
    (4, 1),
    (5, 1),
    (6, 1),
    (15, 2),
    (8, 1),
)
MAX_NICE_VALUE_POWER = 12
MAX_REPRESENTABILITY_RESIDUES = 20_000


@dataclass(frozen=True)
class BlindPair:
    small_blind: int
    big_blind: int


class _PaymentModel:
    """Exact unbounded denomination representability with stable diagnostics."""

    def __init__(self, denominations: Iterable[int] | None):
        values = sorted({int(value) for value in (denominations or []) if int(value) > 0})
        self.values = tuple(values)
        self.gcd = reduce(gcd, values) if values else 1
        self._normalized = tuple(value // self.gcd for value in values)
        self._minimum_by_residue: tuple[int, ...] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.values)

    def representable(self, amount: int) -> bool:
        if amount <= 0:
            return False
        if not self.enabled:
            return True
        if amount % self.gcd:
            return False
        normalized_amount = amount // self.gcd
        smallest = self._normalized[0]
        if smallest == 1:
            return True
        if smallest > MAX_REPRESENTABILITY_RESIDUES:
            # Exact bounded DP is safer than treating GCD as sufficient.  This
            # branch is only for highly unusual non-poker denominations.
            reachable = bytearray(normalized_amount + 1)
            reachable[0] = 1
            for current in range(normalized_amount + 1):
                if not reachable[current]:
                    continue
                for value in self._normalized:
                    if current + value <= normalized_amount:
                        reachable[current + value] = 1
            return bool(reachable[normalized_amount])
        if self._minimum_by_residue is None:
            distances = [10**30] * smallest
            distances[0] = 0
            queue: list[tuple[int, int]] = [(0, 0)]
            while queue:
                distance, residue = heappop(queue)
                if distance != distances[residue]:
                    continue
                for value in self._normalized:
                    candidate = distance + value
                    candidate_residue = candidate % smallest
                    if candidate < distances[candidate_residue]:
                        distances[candidate_residue] = candidate
                        heappush(queue, (candidate, candidate_residue))
            self._minimum_by_residue = tuple(distances)
        return self._minimum_by_residue[normalized_amount % smallest] <= normalized_amount

    def convenience_penalty(self, amount: int) -> float:
        if not self.enabled or amount in self.values:
            return 0.0
        return 1.0 if self.representable(amount) else 1000.0

    def practically_payable(self, amount: int, *, maximum_chips: int = 3) -> bool:
        """Whether an exact payment needs at most a few physical chips."""

        if not self.enabled or amount in self.values:
            return True
        reachable = {0}
        for _ in range(maximum_chips):
            reachable = {
                current + value
                for current in reachable
                for value in self.values
                if current + value <= amount
            }
            if amount in reachable:
                return True
        return False


class TournamentStructureGeneratorService:
    """Builds an editable BlindLevel-compatible structure from planner inputs."""

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
    def generate(
        cls,
        *,
        players: Any,
        starting_stack: Any,
        expected_reentries: Any = 0,
        max_reentries_per_player: Any = None,
        first_small_blind: Any,
        first_big_blind: Any,
        level_duration_minutes: Any,
        target_duration_minutes: Any,
        ante_mode: Any = "big_blind",
        ante_start_mode: Any = "auto",
        ante_start_level: Any = None,
        break_every_levels: Any = 4,
        break_duration_minutes: Any = 10,
        chip_denominations: Iterable[Any] | None = None,
    ) -> dict[str, Any]:
        player_count = cls._integer(
            players,
            code="invalid_players",
            message="Количество игроков должно быть больше нуля.",
            minimum=1,
        )
        stack = cls._integer(
            starting_stack,
            code="invalid_starting_stack",
            message="Стартовый стек должен быть больше нуля.",
            minimum=1,
        )
        expected = cls._integer(
            expected_reentries,
            code="invalid_expected_reentries",
            message="Ожидаемое число re-entry не может быть отрицательным.",
            minimum=0,
        )
        reentry_limit: int | None
        if max_reentries_per_player in (None, ""):
            reentry_limit = None
        else:
            reentry_limit = cls._integer(
                max_reentries_per_player,
                code="invalid_reentry_limit",
                message="Лимит re-entry на игрока не может быть отрицательным.",
                minimum=0,
            )
            maximum_expected = player_count * reentry_limit
            if expected > maximum_expected:
                raise DomainError(
                    "expected_reentries_exceed_limit",
                    f"Ожидаемых re-entry не может быть больше {maximum_expected} при текущем лимите.",
                )

        first_sb = cls._integer(
            first_small_blind,
            code="invalid_first_blinds",
            message="Проверьте SB и BB первого уровня.",
            minimum=1,
        )
        first_bb = cls._integer(
            first_big_blind,
            code="invalid_first_blinds",
            message="Проверьте SB и BB первого уровня.",
            minimum=1,
        )
        if first_sb >= first_bb:
            raise DomainError("invalid_first_blinds", "Малый блайнд должен быть меньше большого.")

        level_minutes = cls._integer(
            level_duration_minutes,
            code="invalid_level_duration",
            message="Длительность уровня должна быть больше нуля.",
            minimum=1,
        )
        target_minutes = cls._integer(
            target_duration_minutes,
            code="invalid_target_duration",
            message="Целевая продолжительность должна быть не меньше одного уровня.",
            minimum=1,
        )
        if target_minutes < level_minutes:
            raise DomainError(
                "invalid_target_duration",
                "Целевая продолжительность должна быть не меньше одного уровня.",
            )

        break_every = cls._integer(
            break_every_levels,
            code="invalid_break_schedule",
            message="Интервал перерывов не может быть отрицательным.",
            minimum=0,
        )
        if break_every:
            break_minutes = cls._integer(
                break_duration_minutes,
                code="invalid_break_schedule",
                message="Длительность перерыва должна быть больше нуля.",
                minimum=1,
            )
        else:
            break_minutes = 0

        normalized_ante_mode = str(ante_mode)
        if normalized_ante_mode not in {"none", "big_blind"}:
            raise DomainError("invalid_ante_mode", "Выберите режим без анте или BB Ante.")
        normalized_ante_start = str(ante_start_mode)
        if normalized_ante_start not in {"auto", "manual"}:
            raise DomainError("invalid_ante_start", "Выберите автоматический или ручной старт анте.")
        manual_ante_level: int | None = None
        if normalized_ante_mode == "big_blind" and normalized_ante_start == "manual":
            manual_ante_level = cls._integer(
                ante_start_level,
                code="invalid_ante_start",
                message="Номер старта BB Ante должен быть больше нуля.",
                minimum=1,
            )

        denominations = cls._normalize_denominations(chip_denominations)
        payment = _PaymentModel(denominations)
        if payment.enabled and (
            not payment.representable(first_sb) or not payment.representable(first_bb)
        ):
            raise DomainError(
                "starting_blinds_unrepresentable",
                "Стартовые блайнды нельзя точно оплатить выбранными турнирными фишками.",
            )

        planned_entries = player_count + expected
        planned_total_chips = planned_entries * stack
        starting_depth = stack / first_bb
        raw_terminal_bb = max(1, round(planned_total_chips / TARGET_FINAL_TOTAL_CHIPS_IN_BB))

        target_level = cls._target_play_level_count(
            target_minutes=target_minutes,
            level_minutes=level_minutes,
            break_every=break_every,
            break_minutes=break_minutes,
        )
        finish_low_level = max(1, target_level - FINISH_WINDOW_RADIUS_LEVELS)
        finish_high_level = target_level + FINISH_WINDOW_RADIUS_LEVELS
        total_play_levels = finish_high_level + EXTENSION_LEVELS_AFTER_WINDOW

        pairs = cls._candidate_pairs(
            first=BlindPair(first_sb, first_bb),
            payment=payment,
            terminal_bb=raw_terminal_bb,
            minimum_count=total_play_levels,
        )
        candidate_structures = cls._candidate_structures(
            pairs,
            target_level=target_level,
            total_play_levels=total_play_levels,
            target_terminal_bb=raw_terminal_bb,
        )
        if not candidate_structures:
            raise DomainError(
                "structure_generation_failed",
                "Не удалось построить возрастающую структуру для этих параметров.",
            )

        target_seconds = target_minutes * 60
        level_seconds = level_minutes * 60
        break_seconds = break_minutes * 60
        scored = [
            (
                cls._score_structure(
                    structure,
                    target_level=target_level,
                    target_terminal_bb=raw_terminal_bb,
                    starting_depth=starting_depth,
                    target_seconds=target_seconds,
                    level_seconds=level_seconds,
                    break_every=break_every,
                    break_seconds=break_seconds,
                    payment=payment,
                ),
                structure,
            )
            for structure in candidate_structures
        ]
        score_data, selected = min(
            scored,
            key=lambda item: (
                item[0]["total"],
                tuple(pair.big_blind for pair in item[1]),
            ),
        )

        break_positions = cls._break_positions(
            total_play_levels,
            break_every=break_every,
            target_level=target_level,
        )
        ante_first_level = cls._ante_first_level(
            selected,
            starting_stack=stack,
            ante_mode=normalized_ante_mode,
            ante_start_mode=normalized_ante_start,
            manual_level=manual_ante_level,
        )
        levels, play_end_seconds = cls._serialize_levels(
            selected,
            level_seconds=level_seconds,
            break_positions=break_positions,
            break_seconds=break_seconds,
            ante_mode=normalized_ante_mode,
            ante_first_level=ante_first_level,
        )

        warnings = cls._diagnostics(
            structure=selected,
            starting_depth=starting_depth,
            target_level=target_level,
            target_terminal_bb=raw_terminal_bb,
            level_minutes=level_minutes,
            break_every=break_every,
            break_minutes=break_minutes,
        )

        target_elapsed = play_end_seconds[target_level - 1]
        lower_elapsed = play_end_seconds[finish_low_level - 1]
        upper_elapsed = play_end_seconds[finish_high_level - 1]
        target_pair = selected[target_level - 1]
        actual_pressure = planned_total_chips / target_pair.big_blind

        return {
            "levels": levels,
            "summary": {
                "players": player_count,
                "starting_stack": stack,
                "expected_reentries": expected,
                "planned_entries": planned_entries,
                "planned_total_chips": planned_total_chips,
                "starting_depth_bb": round(starting_depth, 2),
                "target_duration_seconds": target_seconds,
                "target_level": target_level,
                "target_elapsed_seconds": target_elapsed,
                "blind_levels_to_target": target_level,
                "breaks_before_target": sum(position < target_level for position in break_positions),
                "breaks_total": len(break_positions),
                "break_duration_seconds": break_seconds,
                "finish_window": {
                    "from_level": finish_low_level,
                    "to_level": finish_high_level,
                    "from_seconds": lower_elapsed,
                    "to_seconds": upper_elapsed,
                },
                "extension_levels": EXTENSION_LEVELS_AFTER_WINDOW,
                "target_terminal_big_blind": raw_terminal_bb,
                "generated_target_big_blind": target_pair.big_blind,
                "estimated_total_chips_in_bb": round(actual_pressure, 2),
                "ante_first_level": ante_first_level,
                "chip_denominations": list(denominations),
            },
            "diagnostics": warnings,
            "score": score_data,
            "heuristic": {
                "target_final_total_chips_in_bb": TARGET_FINAL_TOTAL_CHIPS_IN_BB,
                "finish_window_radius_levels": FINISH_WINDOW_RADIUS_LEVELS,
                "actual_duration_is_guaranteed": False,
            },
        }

    @classmethod
    def starting_blind_candidates(
        cls,
        *,
        starting_stack: Any,
        chip_denominations: Iterable[Any],
        target_depths: Iterable[int] = (100, 125, 80, 150),
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Return a small deterministic set of physically payable first levels.

        Auto Tournament Builder owns the tournament-wide search.  This helper
        keeps denomination-aware blind construction inside the existing
        structure generator instead of duplicating its payment model.
        """

        stack = cls._integer(
            starting_stack,
            code="invalid_starting_stack",
            message="Стартовый стек должен быть больше нуля.",
            minimum=1,
        )
        denominations = cls._normalize_denominations(chip_denominations)
        if not denominations:
            raise DomainError(
                "invalid_chip_denominations",
                "Для автоматического выбора блайндов нужны физические номиналы.",
            )
        normalized_depths = tuple(
            cls._integer(
                value,
                code="invalid_starting_depth",
                message="Проверьте целевую стартовую глубину.",
                minimum=1,
            )
            for value in target_depths
        )
        payment = _PaymentModel(denominations)
        maximum_big_blind = max(2, stack // 20)
        pairs: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        for big_blind in cls.nice_blind_values(maximum_big_blind):
            if not payment.representable(big_blind):
                continue
            small_blind = cls._small_blind_for(big_blind, payment)
            if small_blind is None or not payment.representable(small_blind):
                continue
            depth = stack / big_blind
            if depth < 20 or depth > 300:
                continue
            depth_distance = min(abs(log(depth / target)) for target in normalized_depths)
            direct_count = int(small_blind in denominations) + int(big_blind in denominations)
            practical_penalty = payment.convenience_penalty(small_blind) + payment.convenience_penalty(
                big_blind
            )
            data = {
                "small_blind": small_blind,
                "big_blind": big_blind,
                "starting_depth_bb": round(depth, 2),
                "exactly_payable": True,
                "direct_denominations": direct_count,
            }
            pairs.append(
                (
                    (
                        round(depth_distance, 8),
                        practical_penalty,
                        -direct_count,
                        abs(depth - 100),
                        big_blind,
                    ),
                    data,
                )
            )
        if not pairs:
            raise DomainError(
                "starting_blinds_unrepresentable",
                "Не удалось подобрать физически оплачиваемый первый уровень для выбранных фишек.",
            )
        return [data for _, data in sorted(pairs, key=lambda item: item[0])[: max(1, limit)]]

    @classmethod
    def analyze_draft(
        cls,
        *,
        levels: Any,
        players: Any,
        starting_stack: Any,
        expected_reentries: Any = 0,
        target_duration_minutes: Any,
        chip_denominations: Iterable[Any] | None = None,
    ) -> dict[str, Any]:
        """Recalculate informational metrics without regenerating a draft.

        The input rows are inspected only.  The returned payload contains no
        replacement structure, so a caller cannot accidentally overwrite a
        user's manual edits with this endpoint.
        """

        player_count = cls._integer(
            players,
            code="invalid_players",
            message="Количество игроков должно быть больше нуля.",
            minimum=1,
        )
        stack = cls._integer(
            starting_stack,
            code="invalid_starting_stack",
            message="Стартовый стек должен быть больше нуля.",
            minimum=1,
        )
        expected = cls._integer(
            expected_reentries,
            code="invalid_expected_reentries",
            message="Ожидаемое число re-entry не может быть отрицательным.",
            minimum=0,
        )
        target_minutes = cls._integer(
            target_duration_minutes,
            code="invalid_target_duration",
            message="Целевая продолжительность должна быть больше нуля.",
            minimum=1,
        )
        if not isinstance(levels, list) or not levels:
            raise DomainError("empty_structure", "Добавьте хотя бы один уровень.")

        denominations = cls._normalize_denominations(chip_denominations)
        payment = _PaymentModel(denominations)
        diagnostics: list[dict[str, Any]] = []
        play_rows: list[dict[str, Any]] = []
        elapsed = 0
        for row_index, raw in enumerate(levels):
            if not isinstance(raw, dict):
                raise DomainError("invalid_structure", "Проверьте параметры структуры уровней.")
            kind = str(raw.get("kind", ""))
            duration = cls._integer(
                raw.get("duration_seconds"),
                code="invalid_structure",
                message="Длительность каждого элемента должна быть больше нуля.",
                minimum=1,
            )
            elapsed += duration
            if kind == "break":
                continue
            if kind != "play":
                raise DomainError("invalid_structure", "Проверьте типы строк структуры.")
            small_blind = cls._integer(
                raw.get("small_blind"),
                code="invalid_structure",
                message="Проверьте SB и BB игровых уровней.",
                minimum=1,
            )
            big_blind = cls._integer(
                raw.get("big_blind"),
                code="invalid_structure",
                message="Проверьте SB и BB игровых уровней.",
                minimum=1,
            )
            ante = cls._integer(
                raw.get("ante", 0),
                code="invalid_structure",
                message="Проверьте ante игровых уровней.",
                minimum=0,
            )
            if small_blind > big_blind:
                raise DomainError("invalid_structure", "Малый блайнд не может быть больше большого.")
            play_number = len(play_rows) + 1
            amounts = (("SB", small_blind), ("BB", big_blind), ("ante", ante))
            impossible = [label for label, amount in amounts if amount and not payment.representable(amount)]
            awkward = [
                label
                for label, amount in amounts
                if amount
                and payment.enabled
                and payment.representable(amount)
                and not payment.practically_payable(amount)
            ]
            if impossible:
                diagnostics.append(
                    {
                        "code": "unpayable_level",
                        "severity": "error",
                        "level": play_number,
                        "row_index": row_index,
                        "message": (
                            f"Уровень {play_number}: {', '.join(impossible)} невозможно точно оплатить "
                            "выбранными фишками."
                        ),
                    }
                )
            elif awkward:
                diagnostics.append(
                    {
                        "code": "awkward_level",
                        "severity": "warning",
                        "level": play_number,
                        "row_index": row_index,
                        "message": f"Уровень {play_number} потребует частого размена.",
                    }
                )
            play_rows.append(
                {
                    "number": play_number,
                    "big_blind": big_blind,
                    "end_seconds": elapsed,
                }
            )

        if not play_rows:
            raise DomainError("invalid_structure", "Добавьте хотя бы один игровой уровень.")
        planned_total_chips = (player_count + expected) * stack
        terminal_big_blind = max(1, round(planned_total_chips / TARGET_FINAL_TOTAL_CHIPS_IN_BB))
        target_index = min(
            range(len(play_rows)),
            key=lambda index: (
                abs(log(play_rows[index]["big_blind"] / terminal_big_blind)),
                index,
            ),
        )
        growths = [
            play_rows[index]["big_blind"] / play_rows[index - 1]["big_blind"]
            for index in range(1, len(play_rows))
        ]
        if max(growths, default=1.0) > AGGRESSIVE_GROWTH_WARNING:
            diagnostics.append(
                {
                    "code": "aggressive_growth",
                    "severity": "warning",
                    "message": "В ручной структуре есть очень резкий рост блайндов.",
                }
            )
        first_big_blind = play_rows[0]["big_blind"]
        starting_depth = stack / first_big_blind
        if starting_depth < SHALLOW_STARTING_DEPTH_BB:
            diagnostics.append(
                {
                    "code": "shallow_starting_depth",
                    "severity": "warning",
                    "message": "Стартовая глубина очень мала; турнир начнётся в коротких стеках.",
                }
            )
        lower_index = max(0, target_index - FINISH_WINDOW_RADIUS_LEVELS)
        upper_index = min(len(play_rows) - 1, target_index + FINISH_WINDOW_RADIUS_LEVELS)
        return {
            "summary": {
                "players": player_count,
                "starting_stack": stack,
                "expected_reentries": expected,
                "planned_total_chips": planned_total_chips,
                "starting_depth_bb": round(starting_depth, 2),
                "target_duration_seconds": target_minutes * 60,
                "structure_total_seconds": elapsed,
                "estimated_finish_level": play_rows[target_index]["number"],
                "finish_window": {
                    "from_level": play_rows[lower_index]["number"],
                    "to_level": play_rows[upper_index]["number"],
                    "from_seconds": play_rows[lower_index]["end_seconds"],
                    "to_seconds": play_rows[upper_index]["end_seconds"],
                },
                "target_terminal_big_blind": terminal_big_blind,
                "chip_denominations": list(denominations),
            },
            "diagnostics": diagnostics,
            "heuristic": {
                "target_final_total_chips_in_bb": TARGET_FINAL_TOTAL_CHIPS_IN_BB,
                "actual_duration_is_guaranteed": False,
                "structure_was_regenerated": False,
            },
        }

    @classmethod
    def _normalize_denominations(cls, raw_values: Iterable[Any] | None) -> tuple[int, ...]:
        if raw_values is None:
            return ()
        values: set[int] = set()
        try:
            iterator = iter(raw_values)
        except TypeError as error:
            raise DomainError(
                "invalid_chip_denominations", "Проверьте номиналы турнирных фишек."
            ) from error
        for raw in iterator:
            values.add(
                cls._integer(
                    raw,
                    code="invalid_chip_denominations",
                    message="Номиналы турнирных фишек должны быть больше нуля.",
                    minimum=1,
                )
            )
        return tuple(sorted(values))

    @staticmethod
    def _elapsed_minutes(
        play_levels: int, *, level_minutes: int, break_every: int, break_minutes: int
    ) -> int:
        breaks_before_end = (play_levels - 1) // break_every if break_every else 0
        return play_levels * level_minutes + breaks_before_end * break_minutes

    @classmethod
    def _target_play_level_count(
        cls, *, target_minutes: int, level_minutes: int, break_every: int, break_minutes: int
    ) -> int:
        rough_max = max(1, target_minutes // level_minutes + 2)
        candidates = range(1, rough_max + 1)
        return min(
            candidates,
            key=lambda count: (
                abs(
                    cls._elapsed_minutes(
                        count,
                        level_minutes=level_minutes,
                        break_every=break_every,
                        break_minutes=break_minutes,
                    )
                    - target_minutes
                ),
                count,
            ),
        )

    @staticmethod
    def nice_blind_values(maximum: int) -> tuple[int, ...]:
        """Returns the documented poker-friendly ladder up to ``maximum``."""
        values: set[int] = set()
        for power in range(MAX_NICE_VALUE_POWER + 1):
            scale = 10**power
            for numerator, denominator in NICE_VALUE_MANTISSAS:
                raw = numerator * scale
                if raw % denominator == 0:
                    value = raw // denominator
                    if 0 < value <= maximum:
                        values.add(value)
        return tuple(sorted(values))

    @classmethod
    def _small_blind_for(cls, big_blind: int, payment: _PaymentModel) -> int | None:
        target = big_blind / 2
        friendly = set(cls.nice_blind_values(big_blind - 1))
        if payment.enabled:
            # A physical denomination is meaningful even for a deliberately
            # non-canonical custom chip set. Arbitrary multiples are not: a
            # denomination of 1 must never turn 75 / 2 into a generated SB 37.
            friendly.update(value for value in payment.values if value < big_blind)
        candidates = [
            value
            for value in friendly
            if big_blind / 3 <= value <= big_blind * 2 / 3
            and (not payment.enabled or payment.representable(value))
        ]
        if candidates:
            return min(
                candidates,
                key=lambda value: (
                    cls._blind_ratio_rank(value, big_blind),
                    not payment.practically_payable(value),
                    payment.convenience_penalty(value),
                    abs(value - target),
                    value,
                ),
            )

        # Exact familiar ratios keep unusual physical sets usable without
        # falling back to rounded half-blinds such as 37 / 75.
        ratio_candidates = (
            big_blind // 2 if big_blind % 2 == 0 else None,
            big_blind * 2 // 5 if (big_blind * 2) % 5 == 0 else None,
            big_blind // 3 if big_blind % 3 == 0 else None,
        )
        for value in ratio_candidates:
            if value and (not payment.enabled or payment.representable(value)):
                return value
        return None

    @staticmethod
    def _blind_ratio_rank(small_blind: int, big_blind: int) -> int:
        """Prefer familiar 1/2, 2/5 and 1/3 blind pairs, in that order."""

        if small_blind * 2 == big_blind:
            return 0
        if small_blind * 5 == big_blind * 2:
            return 1
        if small_blind * 3 == big_blind:
            return 2
        return 3

    @classmethod
    def _candidate_pairs(
        cls,
        *,
        first: BlindPair,
        payment: _PaymentModel,
        terminal_bb: int,
        minimum_count: int,
    ) -> tuple[BlindPair, ...]:
        maximum = max(first.big_blind * 10, terminal_bb * 10)
        while True:
            values = cls.nice_blind_values(maximum)
            pairs = [first]
            for big_blind in values:
                if big_blind <= first.big_blind or not payment.representable(big_blind):
                    continue
                small_blind = cls._small_blind_for(big_blind, payment)
                if small_blind is None or not payment.representable(small_blind):
                    continue
                pairs.append(BlindPair(small_blind, big_blind))
            if len(pairs) >= minimum_count + 8:
                return tuple(pairs)
            maximum *= 10
            if maximum > 10**MAX_NICE_VALUE_POWER:
                return tuple(pairs)

    @classmethod
    def _candidate_structures(
        cls,
        pairs: tuple[BlindPair, ...],
        *,
        target_level: int,
        total_play_levels: int,
        target_terminal_bb: int,
    ) -> list[tuple[BlindPair, ...]]:
        if len(pairs) < total_play_levels:
            return []
        structures: set[tuple[BlindPair, ...]] = set()
        first_bb = pairs[0].big_blind
        target_steps = max(0, target_level - 1)
        for terminal_factor in TERMINAL_CANDIDATE_FACTORS:
            terminal = max(first_bb, target_terminal_bb * terminal_factor)
            for curve in CURVE_CANDIDATE_EXPONENTS:
                selected = [pairs[0]]
                previous_index = 0
                for step in range(1, target_steps + 1):
                    progress = (step / target_steps) ** curve if target_steps else 1.0
                    desired = first_bb * ((terminal / first_bb) ** progress)
                    remaining_target = target_steps - step
                    max_index = len(pairs) - 1 - remaining_target
                    choices = range(previous_index + 1, max_index + 1)
                    next_index = min(
                        choices,
                        key=lambda index: (
                            abs(log(pairs[index].big_blind / desired)),
                            pairs[index].big_blind,
                        ),
                    )
                    selected.append(pairs[next_index])
                    previous_index = next_index

                growths = [
                    selected[index].big_blind / selected[index - 1].big_blind
                    for index in range(1, len(selected))
                ]
                extension_growth = (
                    min(MAX_PREFERRED_GROWTH, max(MIN_PREFERRED_GROWTH, sum(growths) / len(growths)))
                    if growths
                    else 1.35
                )
                while len(selected) < total_play_levels:
                    desired = selected[-1].big_blind * extension_growth
                    choices = range(previous_index + 1, len(pairs))
                    if not choices:
                        break
                    next_index = min(
                        choices,
                        key=lambda index: (
                            abs(log(pairs[index].big_blind / desired)),
                            pairs[index].big_blind,
                        ),
                    )
                    selected.append(pairs[next_index])
                    previous_index = next_index
                if len(selected) == total_play_levels:
                    structures.add(tuple(selected))
        return sorted(structures, key=lambda structure: tuple(pair.big_blind for pair in structure))

    @classmethod
    def _score_structure(
        cls,
        structure: tuple[BlindPair, ...],
        *,
        target_level: int,
        target_terminal_bb: int,
        starting_depth: float,
        target_seconds: int,
        level_seconds: int,
        break_every: int,
        break_seconds: int,
        payment: _PaymentModel,
    ) -> dict[str, float]:
        target_bb = structure[target_level - 1].big_blind
        target_pressure = abs(log(target_bb / max(1, target_terminal_bb))) * SCORE_TARGET_PRESSURE_WEIGHT
        growths = [
            structure[index].big_blind / structure[index - 1].big_blind
            for index in range(1, len(structure))
        ]
        band = sum(
            (MIN_PREFERRED_GROWTH - growth) ** 2
            if growth < MIN_PREFERRED_GROWTH
            else (growth - MAX_PREFERRED_GROWTH) ** 2
            if growth > MAX_PREFERRED_GROWTH
            else 0.0
            for growth in growths
        ) * SCORE_GROWTH_BAND_WEIGHT
        tiny = sum(max(0.0, MIN_MEANINGFUL_GROWTH - growth) ** 2 for growth in growths) * SCORE_TINY_STEP_WEIGHT
        abrupt = sum(max(0.0, growth - MAX_REASONABLE_GROWTH) ** 2 for growth in growths) * SCORE_ABRUPT_JUMP_WEIGHT
        mean_growth = sum(growths) / len(growths) if growths else 1.0
        variance = (
            sum((growth - mean_growth) ** 2 for growth in growths) / len(growths)
            if growths
            else 0.0
        ) * SCORE_GROWTH_VARIANCE_WEIGHT
        physical = sum(
            payment.convenience_penalty(pair.small_blind)
            + payment.convenience_penalty(pair.big_blind)
            for pair in structure
        ) * SCORE_PHYSICAL_PAYMENT_WEIGHT
        depth = (
            max(0.0, SHALLOW_STARTING_DEPTH_BB - starting_depth)
            + max(0.0, starting_depth - DEEP_STARTING_DEPTH_BB) / 10
        ) * SCORE_STARTING_DEPTH_WEIGHT
        elapsed_seconds = cls._elapsed_minutes(
            target_level,
            level_minutes=level_seconds // 60,
            break_every=break_every,
            break_minutes=break_seconds // 60,
        ) * 60
        duration = abs(elapsed_seconds - target_seconds) * SCORE_DURATION_DISTANCE_WEIGHT
        components = {
            "target_pressure": target_pressure,
            "growth_band": band,
            "growth_variance": variance,
            "tiny_steps": tiny,
            "abrupt_jumps": abrupt,
            "physical_payment": physical,
            "starting_depth": depth,
            "duration_distance": duration,
        }
        return {
            "total": round(sum(components.values()), 4),
            **{key: round(value, 4) for key, value in components.items()},
        }

    @staticmethod
    def _break_positions(total_play_levels: int, *, break_every: int, target_level: int) -> tuple[int, ...]:
        if not break_every:
            return ()
        positions = set(range(break_every, total_play_levels, break_every))
        if target_level in positions:
            positions.remove(target_level)
            deferred = target_level + break_every
            if deferred < total_play_levels:
                positions.add(deferred)
        return tuple(sorted(positions))

    @staticmethod
    def _ante_first_level(
        structure: tuple[BlindPair, ...],
        *,
        starting_stack: int,
        ante_mode: str,
        ante_start_mode: str,
        manual_level: int | None,
    ) -> int | None:
        if ante_mode == "none":
            return None
        if ante_start_mode == "manual":
            if manual_level is None or manual_level > len(structure):
                raise DomainError(
                    "invalid_ante_start", "Уровень старта BB Ante отсутствует в сгенерированной структуре."
                )
            return manual_level
        for number, pair in enumerate(structure, start=1):
            if number >= MIN_AUTO_ANTE_START_LEVEL and starting_stack / pair.big_blind <= AUTO_ANTE_START_DEPTH_BB:
                return number
        return len(structure)

    @staticmethod
    def _serialize_levels(
        structure: tuple[BlindPair, ...],
        *,
        level_seconds: int,
        break_positions: tuple[int, ...],
        break_seconds: int,
        ante_mode: str,
        ante_first_level: int | None,
    ) -> tuple[list[dict[str, Any]], list[int]]:
        levels: list[dict[str, Any]] = []
        play_end_seconds: list[int] = []
        elapsed = 0
        for number, pair in enumerate(structure, start=1):
            ante_enabled = ante_mode == "big_blind" and ante_first_level is not None and number >= ante_first_level
            levels.append(
                {
                    "kind": "play",
                    "small_blind": pair.small_blind,
                    "big_blind": pair.big_blind,
                    "ante": pair.big_blind if ante_enabled else 0,
                    "duration_seconds": level_seconds,
                }
            )
            elapsed += level_seconds
            play_end_seconds.append(elapsed)
            if number in break_positions:
                levels.append(
                    {
                        "kind": "break",
                        "duration_seconds": break_seconds,
                        "title": "Перерыв",
                    }
                )
                elapsed += break_seconds
        return levels, play_end_seconds

    @classmethod
    def _diagnostics(
        cls,
        *,
        structure: tuple[BlindPair, ...],
        starting_depth: float,
        target_level: int,
        target_terminal_bb: int,
        level_minutes: int,
        break_every: int,
        break_minutes: int,
    ) -> list[dict[str, Any]]:
        diagnostics: list[dict[str, Any]] = []
        if starting_depth < SHALLOW_STARTING_DEPTH_BB:
            diagnostics.append(
                {
                    "code": "shallow_starting_depth",
                    "severity": "warning",
                    "message": "Стартовая глубина очень мала; турнир начнётся в коротких стеках.",
                }
            )
        elif starting_depth > DEEP_STARTING_DEPTH_BB:
            diagnostics.append(
                {
                    "code": "deep_starting_depth",
                    "severity": "info",
                    "message": "Стартовая глубина велика; ранняя стадия будет особенно глубокой.",
                }
            )

        growths = [
            structure[index].big_blind / structure[index - 1].big_blind
            for index in range(1, min(target_level, len(structure)))
        ]
        max_growth = max(growths, default=1.0)
        if max_growth > AGGRESSIVE_GROWTH_WARNING:
            required_transitions = (
                ceil(log(max(target_terminal_bb, structure[0].big_blind) / structure[0].big_blind, MAX_PREFERRED_GROWTH))
                if target_terminal_bb > structure[0].big_blind
                else 0
            )
            suggested_levels = required_transitions + 1
            suggested_minutes = cls._elapsed_minutes(
                suggested_levels,
                level_minutes=level_minutes,
                break_every=break_every,
                break_minutes=break_minutes,
            )
            diagnostics.append(
                {
                    "code": "aggressive_growth",
                    "severity": "warning",
                    "message": "Для выбранной продолжительности рост блайндов получается очень быстрым.",
                    "suggested_target_duration_minutes": suggested_minutes,
                }
            )
        mean_growth = sum(growths) / len(growths) if growths else 1.0
        if target_level > 2 and mean_growth < MIN_MEANINGFUL_GROWTH:
            diagnostics.append(
                {
                    "code": "slow_growth",
                    "severity": "warning",
                    "message": "Целевая продолжительность требует множества очень близких уровней. Попробуйте увеличить длительность уровня.",
                }
            )
        return diagnostics

from __future__ import annotations

from time import perf_counter

import pytest

from app.services.errors import DomainError
from app.services.structure_generator_service import (
    EXTENSION_LEVELS_AFTER_WINDOW,
    TournamentStructureGeneratorService,
    _PaymentModel,
)


def generate(**overrides):
    payload = {
        "players": 8,
        "starting_stack": 20_000,
        "expected_reentries": 0,
        "max_reentries_per_player": 2,
        "first_small_blind": 100,
        "first_big_blind": 200,
        "level_duration_minutes": 15,
        "target_duration_minutes": 300,
        "ante_mode": "big_blind",
        "ante_start_mode": "auto",
        "break_every_levels": 4,
        "break_duration_minutes": 10,
    }
    payload.update(overrides)
    return TournamentStructureGeneratorService.generate(**payload)


def play_levels(result):
    return [level for level in result["levels"] if level["kind"] == "play"]


def break_levels(result):
    return [level for level in result["levels"] if level["kind"] == "break"]


@pytest.mark.parametrize(
    ("overrides", "expected_target_minutes"),
    [
        ({}, 300),
        (
            {
                "players": 6,
                "starting_stack": 10_000,
                "target_duration_minutes": 120,
            },
            120,
        ),
        (
            {
                "players": 10,
                "starting_stack": 20_000,
                "level_duration_minutes": 20,
                "target_duration_minutes": 360,
            },
            360,
        ),
    ],
)
def test_standard_short_and_long_generation(overrides, expected_target_minutes) -> None:
    result = generate(**overrides)
    plays = play_levels(result)
    summary = result["summary"]

    assert plays
    assert summary["extension_levels"] == EXTENSION_LEVELS_AFTER_WINDOW
    assert len(plays) == summary["finish_window"]["to_level"] + EXTENSION_LEVELS_AFTER_WINDOW
    assert abs(summary["target_elapsed_seconds"] - expected_target_minutes * 60) <= max(
        level["duration_seconds"] for level in result["levels"]
    )


def test_generated_arithmetic_and_growth_invariants() -> None:
    result = generate(expected_reentries=2)
    plays = play_levels(result)
    big_blinds = [level["big_blind"] for level in plays]

    assert all(level["small_blind"] > 0 for level in plays)
    assert all(level["big_blind"] > level["small_blind"] for level in plays)
    assert all(level["ante"] >= 0 for level in plays)
    assert all(level["duration_seconds"] > 0 for level in result["levels"])
    assert big_blinds == sorted(set(big_blinds))
    normal_growths = [right / left for left, right in zip(big_blinds, big_blinds[1:])]
    assert max(normal_growths) <= 1.7
    assert min(normal_growths) >= 1.15
    target_index = result["summary"]["target_level"] - 1
    assert 12 <= result["summary"]["planned_total_chips"] / big_blinds[target_index] <= 32
    assert all(
        later > earlier
        for earlier, later in zip(
            big_blinds[target_index : target_index + EXTENSION_LEVELS_AFTER_WINDOW],
            big_blinds[target_index + 1 : target_index + EXTENSION_LEVELS_AFTER_WINDOW + 1],
        )
    )


def test_breaks_are_counted_and_duration_changes_level_count() -> None:
    with_breaks = generate(break_every_levels=4, break_duration_minutes=10)
    longer_breaks = generate(break_every_levels=4, break_duration_minutes=20)
    no_breaks = generate(break_every_levels=0, break_duration_minutes=0)
    longer_levels = generate(level_duration_minutes=20)

    assert break_levels(with_breaks)
    assert not break_levels(no_breaks)
    assert longer_breaks["summary"]["target_level"] < with_breaks["summary"]["target_level"]
    assert no_breaks["summary"]["target_level"] > with_breaks["summary"]["target_level"]
    assert longer_levels["summary"]["target_level"] < with_breaks["summary"]["target_level"]
    assert with_breaks["summary"]["finish_window"]["to_seconds"] < sum(
        level["duration_seconds"] for level in with_breaks["levels"]
    )


@pytest.mark.parametrize("every", [4, 6, 0])
def test_break_cadence_and_no_trailing_break_at_target(every) -> None:
    result = generate(break_every_levels=every, break_duration_minutes=7 if every else 0)
    assert all(level["duration_seconds"] == 420 for level in break_levels(result))
    target_level = result["summary"]["target_level"]
    play_number = 0
    for index, level in enumerate(result["levels"]):
        if level["kind"] == "play":
            play_number += 1
            if play_number == target_level and index + 1 < len(result["levels"]):
                assert result["levels"][index + 1]["kind"] != "break"


def test_expected_reentries_change_only_planning_volume_and_terminal_pressure() -> None:
    without = generate(expected_reentries=0)
    with_reentries = generate(expected_reentries=4)

    assert without["summary"]["planned_entries"] == 8
    assert with_reentries["summary"]["planned_entries"] == 12
    assert without["summary"]["planned_total_chips"] == 160_000
    assert with_reentries["summary"]["planned_total_chips"] == 240_000
    assert with_reentries["summary"]["target_terminal_big_blind"] > without["summary"]["target_terminal_big_blind"]
    assert with_reentries["summary"]["generated_target_big_blind"] >= without["summary"]["generated_target_big_blind"]
    assert with_reentries["summary"]["expected_reentries"] == 4


def test_expected_reentries_respect_existing_per_player_limit() -> None:
    with pytest.raises(DomainError) as error:
        generate(players=8, expected_reentries=17, max_reentries_per_player=2)
    assert error.value.code == "expected_reentries_exceed_limit"

    with pytest.raises(DomainError) as disabled:
        generate(expected_reentries=1, max_reentries_per_player=0)
    assert disabled.value.code == "expected_reentries_exceed_limit"


def test_physical_denominations_are_exactly_representable() -> None:
    result = generate(chip_denominations=[25, 100, 500, 1_000])
    plays = play_levels(result)

    assert result["summary"]["chip_denominations"] == [25, 100, 500, 1_000]
    assert all(level["small_blind"] % 25 == 0 for level in plays)
    assert all(level["big_blind"] % 25 == 0 for level in plays)

    coarse = generate(
        first_small_blind=100,
        first_big_blind=200,
        chip_denominations=[100, 500, 1_000],
    )
    assert all(level["small_blind"] % 100 == 0 for level in play_levels(coarse))
    assert all(level["big_blind"] % 100 == 0 for level in play_levels(coarse))


def test_small_blinds_use_friendly_ratios_instead_of_rounded_half_values() -> None:
    payment = _PaymentModel([1, 5, 10, 25, 50, 100, 500, 1_000])
    result = generate(chip_denominations=[1, 5, 10, 25, 50, 100, 500, 1_000])
    plays = play_levels(result)

    assert TournamentStructureGeneratorService._small_blind_for(75, payment) == 30
    assert all(level["small_blind"] != 37 for level in plays)
    assert all(
        TournamentStructureGeneratorService._blind_ratio_rank(
            level["small_blind"], level["big_blind"]
        )
        < 3
        for level in plays
    )


def test_impossible_starting_blinds_are_rejected_with_chip_plan() -> None:
    with pytest.raises(DomainError) as error:
        generate(first_small_blind=75, first_big_blind=150, chip_denominations=[100, 500])
    assert error.value.code == "starting_blinds_unrepresentable"


def test_no_ante_auto_and_manual_bba() -> None:
    no_ante = generate(ante_mode="none")
    automatic = generate(ante_mode="big_blind", ante_start_mode="auto")
    manual = generate(ante_mode="big_blind", ante_start_mode="manual", ante_start_level=5)

    assert all(level["ante"] == 0 for level in play_levels(no_ante))
    automatic_start = automatic["summary"]["ante_first_level"]
    assert automatic_start >= 3
    for number, level in enumerate(play_levels(automatic), start=1):
        assert level["ante"] == (level["big_blind"] if number >= automatic_start else 0)
    for number, level in enumerate(play_levels(manual), start=1):
        assert level["ante"] == (level["big_blind"] if number >= 5 else 0)


def test_deterministic_and_fast() -> None:
    started = perf_counter()
    first = generate(expected_reentries=2, chip_denominations=[25, 100, 500, 1_000])
    second = generate(expected_reentries=2, chip_denominations=[25, 100, 500, 1_000])
    elapsed = perf_counter() - started

    assert first == second
    assert elapsed < 1.0


def test_diagnostics_for_shallow_and_aggressive_configuration() -> None:
    shallow = generate(
        players=8,
        starting_stack=5_000,
        first_small_blind=1_000,
        first_big_blind=2_000,
        level_duration_minutes=10,
        target_duration_minutes=20,
        break_every_levels=0,
        break_duration_minutes=0,
    )
    aggressive = generate(
        starting_stack=20_000,
        first_small_blind=100,
        first_big_blind=200,
        level_duration_minutes=10,
        target_duration_minutes=20,
        break_every_levels=0,
        break_duration_minutes=0,
    )
    assert "shallow_starting_depth" in {item["code"] for item in shallow["diagnostics"]}
    assert "aggressive_growth" in {item["code"] for item in aggressive["diagnostics"]}


def test_draft_analysis_distinguishes_practical_and_awkward_exact_payments() -> None:
    result = TournamentStructureGeneratorService.analyze_draft(
        levels=[
            {
                "kind": "play",
                "small_blind": 25,
                "big_blind": 50,
                "ante": 0,
                "duration_seconds": 900,
            },
            {
                "kind": "play",
                "small_blind": 200,
                "big_blind": 400,
                "ante": 400,
                "duration_seconds": 900,
            },
        ],
        players=8,
        starting_stack=5_000,
        expected_reentries=2,
        target_duration_minutes=180,
        chip_denominations=[25, 100],
    )

    awkward = [item for item in result["diagnostics"] if item["code"] == "awkward_level"]
    assert [item["level"] for item in awkward] == [2]
    assert "levels" not in result


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"first_small_blind": 200, "first_big_blind": 200}, "invalid_first_blinds"),
        ({"starting_stack": 0}, "invalid_starting_stack"),
        ({"target_duration_minutes": 10, "level_duration_minutes": 15}, "invalid_target_duration"),
        ({"break_every_levels": -1}, "invalid_break_schedule"),
    ],
)
def test_invalid_inputs(overrides, code) -> None:
    with pytest.raises(DomainError) as error:
        generate(**overrides)
    assert error.value.code == code

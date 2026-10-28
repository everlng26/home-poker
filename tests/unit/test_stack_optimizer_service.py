import copy

import pytest

from app.services.chip_inventory_service import ChipInventoryService
from app.services.errors import DomainError
from app.services.stack_optimizer_service import StackOptimizerService


def create_set(session, name: str, denominations: list[tuple[int, int]], *, default: bool = False):
    return ChipInventoryService.create(
        session,
        name=name,
        denominations=[{"value": value, "quantity": quantity} for value, quantity in denominations],
        is_default=default,
    )


@pytest.mark.parametrize(
    ("players", "limit", "expected"),
    [(8, 2, 16), (5, 3, 15), (8, 0, 0), (1, 4, 4)],
)
def test_reentry_limit_is_per_player(session, players, limit, expected) -> None:
    chip_set = create_set(session, "Plenty", [(1_000, 1_000)])

    result = StackOptimizerService.solve(
        session,
        chip_set_ids=[chip_set["id"]],
        players=players,
        starting_stack=20_000,
        max_reentries_per_player=limit,
    )

    assert result["max_total_reentries"] == expected
    assert result["max_total_entries"] == players * (1 + limit)


def test_full_coverage_exact_invariants_and_rules_cap(session) -> None:
    chip_set = create_set(session, "Full", [(1_000, 600)])
    before = copy.deepcopy(ChipInventoryService.get(session, chip_set["id"]))

    result = StackOptimizerService.solve(
        session,
        chip_set_ids=[chip_set["id"]],
        players=8,
        starting_stack=20_000,
        max_reentries_per_player=2,
        first_small_blind=100,
        first_big_blind=200,
        first_ante=200,
    )

    assert result["feasible"] is True
    assert result["max_total_reentries"] == 16
    candidate = next(item for item in result["candidates"] if item["recommended"])
    assert candidate["coverage_status"] == "full"
    assert candidate["covered_reentries"] == 16
    assert sum(item["value"] * item["quantity"] for item in candidate["initial_distribution"]) == 20_000
    assert sum(item["value"] * item["quantity"] for item in candidate["reentry_pack"]) == 20_000
    for combined, used, remaining in zip(
        result["combined_inventory"]["denominations"],
        candidate["reserved_quantities"],
        candidate["remaining_inventory"],
    ):
        assert used["quantity"] + remaining["quantity"] == combined["quantity"]
    assert ChipInventoryService.get(session, chip_set["id"]) == before


def test_partial_coverage_is_not_solve_failure_and_uniform_guarantee(session) -> None:
    chip_set = create_set(session, "Partial", [(1_000, 380)])

    result = StackOptimizerService.solve(
        session,
        chip_set_ids=[chip_set["id"]],
        players=8,
        starting_stack=20_000,
        max_reentries_per_player=2,
    )

    candidate = next(item for item in result["candidates"] if item["recommended"])
    assert result["feasible"] is True
    assert candidate["coverage_status"] == "partial"
    assert candidate["covered_reentries"] == 11
    assert candidate["max_allowed_reentries"] == 16
    assert candidate["max_reentries_per_player"] == 2
    assert candidate["uniform_reentries_per_player"] == 1
    assert candidate["additional_common_reserve"] == 3


def test_inventory_capacity_never_exceeds_tournament_rules(session) -> None:
    chip_set = create_set(session, "Huge", [(1_000, 1_000)])

    result = StackOptimizerService.solve(
        session,
        chip_set_ids=[chip_set["id"]],
        players=8,
        starting_stack=20_000,
        max_reentries_per_player=1,
    )

    assert all(item["covered_reentries"] == 8 for item in result["candidates"])


def test_combines_multiple_sets_deduplicates_ids_and_supports_exclusions(session) -> None:
    first = create_set(session, "A", [(100, 80), (500, 60), (1_000, 40)])
    second = create_set(session, "B", [(100, 20), (500, 20), (5_000, 20)])

    combined = StackOptimizerService.combine_inventory(
        session, [first["id"], second["id"], first["id"]]
    )
    excluded = StackOptimizerService.combine_inventory(
        session, [first["id"], second["id"]], excluded_denominations=[500]
    )

    assert combined.quantities == ((100, 100), (500, 80), (1_000, 40), (5_000, 20))
    assert excluded.quantities == ((100, 100), (1_000, 40), (5_000, 20))
    assert len(combined.chip_sets) == 2


def test_reports_total_value_and_exact_representation_failures(session) -> None:
    too_small = create_set(session, "Small", [(1_000, 10)])
    result = StackOptimizerService.solve(
        session,
        chip_set_ids=[too_small["id"]],
        players=8,
        starting_stack=20_000,
        max_reentries_per_player=2,
    )
    assert result["feasible"] is False
    assert result["diagnostics"]["reason"] == "insufficient_total_value"
    assert result["diagnostics"]["initial_value_shortage"] == 150_000

    session.rollback()
    odd = create_set(session, "Odd", [(500, 1_000)])
    result = StackOptimizerService.solve(
        session,
        chip_set_ids=[odd["id"]],
        players=1,
        starting_stack=20_250,
        max_reentries_per_player=0,
    )
    assert result["diagnostics"]["reason"] == "stack_unrepresentable"


def test_solver_is_deterministic_deduplicated_and_blind_aware(session) -> None:
    chip_set = create_set(
        session,
        "Mixed",
        [(25, 160), (100, 160), (500, 120), (1_000, 120), (5_000, 80)],
    )
    payload = {
        "chip_set_ids": [chip_set["id"]],
        "players": 8,
        "starting_stack": 20_000,
        "max_reentries_per_player": 2,
        "first_small_blind": 100,
        "first_big_blind": 200,
        "first_ante": 200,
    }

    first = StackOptimizerService.solve(session, **payload)
    second = StackOptimizerService.solve(session, **payload)

    assert first == second
    distributions = [tuple((row["value"], row["quantity"]) for row in item["initial_distribution"]) for item in first["candidates"]]
    assert len(distributions) == len(set(distributions))
    assert 1 <= len(first["candidates"]) <= 3
    assert sum(item["recommended"] for item in first["candidates"]) == 1
    recommended = next(item for item in first["candidates"] if item["recommended"])
    assert any(row["value"] <= 200 for row in recommended["initial_distribution"])


def test_explicit_selection_is_revalidated_without_reranking_after_manual_blind_edit(
    session,
) -> None:
    chip_set = create_set(
        session,
        "Manual structure",
        [(1, 80), (5, 80), (10, 80), (25, 80), (50, 80), (100, 80), (500, 80), (1_000, 80)],
    )
    solved = StackOptimizerService.solve(
        session,
        chip_set_ids=[chip_set["id"]],
        players=8,
        starting_stack=5_000,
        max_reentries_per_player=2,
        first_small_blind=25,
        first_big_blind=50,
    )
    selected = next(item for item in solved["candidates"] if item["recommended"])

    evaluated = StackOptimizerService.evaluate_selection(
        session,
        chip_set_ids=[chip_set["id"]],
        players=8,
        starting_stack=5_000,
        max_reentries_per_player=2,
        initial_distribution=selected["initial_distribution"],
        first_small_blind=13,
        first_big_blind=26,
        first_ante=0,
    )

    assert evaluated["candidate"]["initial_distribution"] == selected["initial_distribution"]
    assert evaluated["candidate"]["max_allowed_reentries"] == 16


def test_real_25_50_case_recommends_playable_stack_without_changing_coverage(session) -> None:
    chip_set = create_set(
        session,
        "Real 500-chip set",
        [(1, 25), (5, 75), (10, 75), (25, 75), (50, 75), (100, 75), (500, 50), (1_000, 50)],
    )

    result = StackOptimizerService.solve(
        session,
        chip_set_ids=[chip_set["id"]],
        players=8,
        starting_stack=5_000,
        max_reentries_per_player=2,
        first_small_blind=25,
        first_big_blind=50,
    )

    assert result["feasible"] is True
    assert result["combined_inventory"]["total_value"] == 89_275
    assert result["max_total_reentries"] == 16
    assert {item["covered_reentries"] for item in result["candidates"]} == {9}
    recommended = next(item for item in result["candidates"] if item["recommended"])
    initial = {item["value"]: item["quantity"] for item in recommended["initial_distribution"]}
    reentry = {item["value"]: item["quantity"] for item in recommended["reentry_pack"]}
    assert recommended["mode"] == "comfortable"
    assert initial[25] >= 4
    assert initial[50] >= 4
    assert reentry.get(25, 0) == 0
    assert reentry.get(50, 0) == 0
    assert recommended["covered_reentries"] == 9
    by_mode = {item["mode"]: item for item in result["candidates"]}
    assert by_mode["comfortable"]["chips_per_player"] > by_mode["balanced"]["chips_per_player"]
    assert by_mode["balanced"]["chips_per_player"] > by_mode["compact"]["chips_per_player"]


def test_direct_small_blind_denomination_beats_same_chip_count_composition() -> None:
    values = (5, 10, 25, 50, 100)
    direct = (0, 0, 4, 8, 5)
    composed = (2, 4, 0, 3, 8)

    assert sum(direct) == sum(composed) == 17
    assert sum(value * count for value, count in zip(values, direct)) == 1_000
    assert sum(value * count for value, count in zip(values, composed)) == 1_000
    assert StackOptimizerService._minimum_payment_chips(direct, values, 25) == 1
    assert StackOptimizerService._minimum_payment_chips(composed, values, 25) == 3
    assert StackOptimizerService._blind_playability_score(
        direct, values, 25, 50, None
    ) > StackOptimizerService._blind_playability_score(composed, values, 25, 50, None)


def test_reentry_pack_prefers_large_chips_and_preserves_early_denominations() -> None:
    values = (25, 50, 500, 1_000)
    remaining = (100, 100, 100, 100)
    early_heavy = (4, 8, 1, 1)
    large = (0, 0, 2, 1)

    assert sum(value * count for value, count in zip(values, early_heavy)) == 2_000
    assert sum(value * count for value, count in zip(values, large)) == 2_000
    assert StackOptimizerService._reentry_pref_key(
        large, values, remaining, 1, 25, 50, None
    ) < StackOptimizerService._reentry_pref_key(
        early_heavy, values, remaining, 1, 25, 50, None
    )


def test_overall_score_keeps_large_coverage_advantage() -> None:
    common = {
        "initial_total_distribution": [
            {"value": 25, "quantity": 8},
            {"value": 50, "quantity": 8},
        ],
        "reentry_quality_score": 2.0,
        "chips_per_player": 24,
    }
    comfortable_but_partial = {
        **common,
        "coverage_ratio": 0.25,
        "blind_playability_score": 38.0,
    }
    playable_full_coverage = {
        **common,
        "coverage_ratio": 1.0,
        "blind_playability_score": 18.0,
        "chips_per_player": 27,
    }

    assert StackOptimizerService._overall_score(
        playable_full_coverage, (100, 100), 1
    ) > StackOptimizerService._overall_score(comfortable_but_partial, (100, 100), 1)


def test_rejects_missing_set_and_invalid_inputs(session) -> None:
    with pytest.raises(DomainError, match="набор"):
        StackOptimizerService.solve(
            session,
            chip_set_ids=[999],
            players=8,
            starting_stack=20_000,
            max_reentries_per_player=2,
        )
    with pytest.raises(DomainError, match="игрок"):
        StackOptimizerService.solve(
            session,
            chip_set_ids=[1],
            players=0,
            starting_stack=20_000,
            max_reentries_per_player=2,
        )

import copy
import inspect

from app.services.auto_tournament_builder_service import AutoTournamentBuilderService
from app.services.chip_inventory_service import ChipInventoryService
from app.services.structure_generator_service import TournamentStructureGeneratorService


def create_set(session, name: str, denominations: list[tuple[int, int]], *, default=False):
    return ChipInventoryService.create(
        session,
        name=name,
        denominations=[{"value": value, "quantity": quantity} for value, quantity in denominations],
        is_default=default,
    )


def standard_sets(session):
    primary = create_set(
        session,
        "Основной",
        [(25, 160), (50, 160), (100, 160), (500, 100), (1_000, 100)],
        default=True,
    )
    extra = create_set(
        session,
        "Дополнительный",
        [(25, 80), (50, 80), (500, 100), (1_000, 100), (5_000, 50)],
    )
    return primary, extra


def build(session, chip_set_ids, **overrides):
    payload = {
        "chip_set_ids": chip_set_ids,
        "players": 8,
        "max_reentries_per_player": 2,
        "target_duration_minutes": 300,
        "ante_mode": "big_blind",
    }
    payload.update(overrides)
    return AutoTournamentBuilderService.build(session, **payload)


def test_standard_auto_build_chooses_every_required_parameter(session) -> None:
    primary, extra = standard_sets(session)

    result = build(session, [primary["id"], extra["id"]])

    assert result["max_total_reentries"] == 16
    assert result["max_total_entries"] == 24
    assert 0 < result["expected_reentries"] < 16
    assert result["deterministic"] is True
    recommended = result["candidates"][0]
    assert recommended["recommended"] is True
    assert recommended["starting_stack"] > 0
    assert recommended["stack_distribution_per_player"]
    assert recommended["reentry_pack"]
    assert recommended["first_small_blind"] > 0
    assert recommended["first_big_blind"] > recommended["first_small_blind"]
    assert recommended["starting_depth_bb"] > 0
    assert recommended["level_duration_minutes"] in {12, 15, 20}
    assert recommended["levels"]
    assert recommended["finish_window"]["from_seconds"] > 0
    assert recommended["extension_levels"] == 4
    assert recommended["ante_start_level"] is not None
    assert recommended["chip_plan"]["initial_distribution"] == recommended[
        "stack_distribution_per_player"
    ]


def test_public_auto_builder_inputs_do_not_require_manual_stack_blinds_or_level_duration() -> None:
    parameters = inspect.signature(AutoTournamentBuilderService.build).parameters

    assert "starting_stack" not in parameters
    assert "first_small_blind" not in parameters
    assert "first_big_blind" not in parameters
    assert "level_duration_minutes" not in parameters


def test_combined_inventory_is_immutable_and_build_is_deterministic(session) -> None:
    primary, extra = standard_sets(session)
    before = {
        primary["id"]: copy.deepcopy(ChipInventoryService.get(session, primary["id"])),
        extra["id"]: copy.deepcopy(ChipInventoryService.get(session, extra["id"])),
    }

    first = build(session, [primary["id"], extra["id"]])
    second = build(session, [primary["id"], extra["id"]])

    combined = {
        item["value"]: item["quantity"]
        for item in first["combined_inventory"]["denominations"]
    }
    assert combined[25] == 240
    assert combined[1_000] == 200
    assert first == second
    assert ChipInventoryService.get(session, primary["id"]) == before[primary["id"]]
    assert ChipInventoryService.get(session, extra["id"]) == before[extra["id"]]


def test_target_duration_and_ante_change_generated_tournament(session) -> None:
    primary, extra = standard_sets(session)
    selected = [primary["id"], extra["id"]]

    fast = build(session, selected, target_duration_minutes=150, ante_mode="none")
    long = build(session, selected, target_duration_minutes=360, ante_mode="big_blind")

    fast_plan = fast["candidates"][0]
    long_plan = long["candidates"][0]
    assert fast_plan["levels"] != long_plan["levels"]
    assert fast_plan["level_duration_minutes"] != long_plan["level_duration_minutes"] or len(
        fast_plan["levels"]
    ) != len(long_plan["levels"])
    assert all(level.get("ante", 0) == 0 for level in fast_plan["levels"])
    assert long_plan["ante_start_level"] is not None
    assert any(level.get("ante", 0) > 0 for level in long_plan["levels"])


def test_different_physical_inventory_can_change_recommended_plan(session) -> None:
    primary, extra = standard_sets(session)
    low = create_set(
        session,
        "Низкий inventory",
        [(25, 80), (50, 80), (100, 80), (500, 60), (1_000, 80)],
    )

    plentiful = build(session, [primary["id"], extra["id"]])["candidates"][0]
    constrained = build(session, [low["id"]])["candidates"][0]

    assert (
        plentiful["starting_stack"],
        plentiful["first_small_blind"],
        plentiful["first_big_blind"],
        plentiful["stack_distribution_per_player"],
    ) != (
        constrained["starting_stack"],
        constrained["first_small_blind"],
        constrained["first_big_blind"],
        constrained["stack_distribution_per_player"],
    )
    assert constrained["reentry_coverage"]["maximum"] == 16


def test_low_inventory_returns_explicit_partial_coverage_when_initial_seating_is_feasible(
    session,
) -> None:
    low = create_set(
        session,
        "Partial only",
        [(25, 64), (50, 64), (100, 64), (1_000, 10)],
    )

    result = build(session, [low["id"]])
    recommended = result["candidates"][0]

    assert recommended["reentry_coverage"]["maximum"] == 16
    assert recommended["reentry_coverage"]["status"] == "partial"
    assert recommended["reentry_coverage"]["covered"] < 16
    assert any(
        item["code"] == "partial_reentry_coverage"
        for item in recommended["diagnostics"]
    )


def test_unused_one_chips_cannot_create_rounded_small_blinds(session) -> None:
    chip_set = create_set(
        session,
        "Домашний набор",
        [
            (1, 25),
            (5, 75),
            (10, 75),
            (25, 75),
            (50, 75),
            (100, 75),
            (500, 50),
            (1_000, 50),
        ],
    )

    recommended = build(session, [chip_set["id"]])["candidates"][0]
    used_values = {
        item["value"]
        for item in recommended["stack_distribution_per_player"] + recommended["reentry_pack"]
        if item["quantity"] > 0
    }
    plays = [level for level in recommended["levels"] if level["kind"] == "play"]

    assert 1 not in used_values
    assert recommended["structure_denominations"] == sorted(used_values)
    assert all(level["small_blind"] != 37 for level in plays)
    assert all(
        TournamentStructureGeneratorService._blind_ratio_rank(
            level["small_blind"], level["big_blind"]
        )
        < 3
        for level in plays
    )

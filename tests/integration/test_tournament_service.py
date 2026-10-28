import pytest

from app.models.enums import BlindLevelKind
from app.models.tournament import Tournament
from app.security import hash_pin
from app.services import DomainError, TournamentService
from app.services.setup_service import TournamentSetupService
from app.services.state_service import tournament_state
from app.services.structure_generator_service import TournamentStructureGeneratorService


def test_delete_tournament_requires_pin_and_removes_tournament(session) -> None:
    tournament = TournamentService.create_tournament(
        session,
        name="Удаляемый турнир",
        buy_in_amount=100,
        currency_label="₽",
        starting_stack=1_000,
        admin_pin_hash=hash_pin("1234"),
    )
    tournament_id = tournament.id

    with pytest.raises(DomainError, match="Неверный PIN"):
        TournamentService.delete_tournament(session, tournament_id, "0000")
    session.rollback()

    TournamentService.delete_tournament(session, tournament_id, "1234")

    assert session.get(Tournament, tournament_id) is None


def test_create_tournament_setup_creates_structure_and_players(session) -> None:
    tournament = TournamentSetupService.create(
        session,
        name="Полная настройка",
        buy_in_amount=500,
        currency_label="₽",
        starting_stack=20_000,
        admin_pin_hash=hash_pin("1234"),
        max_reentries_per_player=2,
        levels=[
            {"kind": "play", "duration_seconds": 1_200, "small_blind": 25, "big_blind": 50, "ante": 50},
            {"kind": "break", "duration_seconds": 600},
            {"kind": "play", "duration_seconds": 1_200, "small_blind": 50, "big_blind": 100, "ante": 100},
        ],
        player_names=["Анна", "Борис"],
        late_registration_end_level_number=1,
        payout_percentages=[50, 30, 20],
    )

    assert tournament.id is not None
    assert tournament.max_reentries_per_player == 2
    assert len(tournament.levels) == 3
    assert [entry.player.name for entry in tournament.players] == ["Анна", "Борис"]
    assert tournament.late_registration_end_level_index == 0
    assert [payout.percentage_basis_points for payout in tournament.payouts] == [5000, 3000, 2000]
    assert tournament_state(session, tournament.id)["public_latest_event"] is None


def test_create_tournament_setup_freeroll_zeros_buy_in(session) -> None:
    tournament = TournamentSetupService.create(
        session,
        name="Фриролл",
        buy_in_amount=1_000,
        currency_label="₽",
        starting_stack=10_000,
        admin_pin_hash=hash_pin("1234"),
        is_freeroll=True,
        payout_percentages=[100],
        levels=[{"kind": "play", "duration_seconds": 1_200, "small_blind": 25, "big_blind": 50}],
        late_registration_end_level_number=1,
    )

    assert tournament.buy_in_amount == 0
    assert tournament.payouts == []


def test_create_tournament_setup_can_disable_antes(session) -> None:
    tournament = TournamentSetupService.create(
        session,
        name="Без анте",
        buy_in_amount=1_000,
        currency_label="₽",
        starting_stack=10_000,
        admin_pin_hash=hash_pin("1234"),
        ante_enabled=False,
        levels=[
            {"kind": "play", "duration_seconds": 1_200, "small_blind": 25, "big_blind": 50, "ante": 50},
            {"kind": "play", "duration_seconds": 1_200, "small_blind": 50, "big_blind": 100, "ante": 100},
        ],
        late_registration_end_level_number=1,
    )

    assert tournament.ante_enabled is False
    assert [level.ante for level in tournament.levels] == [0, 0]
    state = tournament_state(session, tournament.id)
    assert state["ante_enabled"] is False
    assert state["current_level"]["ante"] is None


def test_create_tournament_setup_requires_late_registration_end(session) -> None:
    with pytest.raises(DomainError) as error:
        TournamentSetupService.create(
            session,
            name="Без дедлайна",
            buy_in_amount=1_000,
            currency_label="₽",
            starting_stack=10_000,
            admin_pin_hash=hash_pin("1234"),
            levels=[{"kind": "play", "duration_seconds": 1_200, "small_blind": 25, "big_blind": 50}],
        )

    assert error.value.code == "invalid_late_registration_end"
    assert "Укажите игровой уровень" in error.value.message


def test_generated_structure_remains_an_editable_snapshot_after_reload(session) -> None:
    generated = TournamentStructureGeneratorService.generate(
        players=8,
        starting_stack=20_000,
        expected_reentries=2,
        max_reentries_per_player=2,
        first_small_blind=100,
        first_big_blind=200,
        level_duration_minutes=15,
        target_duration_minutes=300,
        ante_mode="big_blind",
        ante_start_mode="auto",
        break_every_levels=4,
        break_duration_minutes=10,
    )
    edited = [dict(level) for level in generated["levels"]]

    # The same operations exposed by the existing editor remain ordinary list
    # edits: change, move a level, move a break, delete, and add.
    first_play = next(level for level in edited if level["kind"] == "play")
    first_play["duration_seconds"] = 1_200
    play_indexes = [index for index, level in enumerate(edited) if level["kind"] == "play"]
    edited[play_indexes[1]], edited[play_indexes[2]] = edited[play_indexes[2]], edited[play_indexes[1]]
    break_index = next(index for index, level in enumerate(edited) if level["kind"] == "break")
    moved_break = edited.pop(break_index)
    edited.insert(break_index + 2, moved_break)
    removable = next(index for index in range(len(edited) - 1, -1, -1) if edited[index]["kind"] == "play")
    edited.pop(removable)
    last_play = next(level for level in reversed(edited) if level["kind"] == "play")
    edited.append(
        {
            "kind": "play",
            "small_blind": last_play["big_blind"],
            "big_blind": last_play["big_blind"] * 2,
            "ante": last_play["big_blind"] * 2,
            "duration_seconds": 900,
        }
    )

    tournament = TournamentSetupService.create(
        session,
        name="Generated snapshot",
        buy_in_amount=1_000,
        currency_label="₽",
        starting_stack=20_000,
        max_reentries_per_player=2,
        admin_pin_hash=hash_pin("1234"),
        levels=edited,
        player_names=[f"Игрок {number}" for number in range(1, 9)],
        late_registration_end_level_number=4,
        payout_percentages=[50, 30, 20],
    )
    tournament_id = tournament.id
    expected_snapshot = [
        (
            BlindLevelKind(level["kind"]),
            level.get("small_blind"),
            level.get("big_blind"),
            level.get("ante") if level["kind"] == "play" else None,
            level["duration_seconds"],
        )
        for level in edited
    ]

    session.expunge_all()
    restored = session.get(Tournament, tournament_id)
    assert restored is not None
    assert [
        (level.kind, level.small_blind, level.big_blind, level.ante, level.duration_seconds)
        for level in restored.levels
    ] == expected_snapshot
    assert restored.starting_stack == 20_000
    assert not hasattr(restored, "generator_parameters")

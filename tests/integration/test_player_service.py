import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.security import hash_pin
from app.models.enums import TimerStatus, TournamentPlayerStatus, TournamentStatus
from app.models.tournament import Player, TournamentEvent, TournamentPlayer
from app.services import DomainError, EventService, PlayerService, TournamentService
from app.services.level_service import LevelService
from app.services.state_service import tournament_state


def create_tournament(session: Session, *, limit: int | None = None):
    tournament = TournamentService.create_tournament(
        session,
        name="Вечерний турнир",
        buy_in_amount=500,
        currency_label="₽",
        starting_stack=10_000,
        max_reentries_per_player=limit,
        admin_pin_hash="hash",
    )
    with session.begin():
        tournament.status = TournamentStatus.RUNNING
    return tournament


def test_registration_rejects_duplicate_player(session: Session) -> None:
    tournament = create_tournament(session)
    player = PlayerService.create_player(session, "Анна")

    entry = PlayerService.register_player(session, tournament.id, player.id, request_id="register-1")

    assert entry.status == TournamentPlayerStatus.ACTIVE
    tournament_id, player_id = tournament.id, player.id
    state = tournament_state(session, tournament.id)
    assert state["latest_event"]["type"] == "player_registered"
    assert state["latest_event"]["player_name"] == "Анна"
    session.rollback()
    with pytest.raises(DomainError, match="уже зарегистрирован"):
        PlayerService.register_player(session, tournament_id, player_id, request_id="register-2")


def test_elimination_reentry_and_undo(session: Session) -> None:
    tournament = create_tournament(session, limit=1)
    player = PlayerService.create_player(session, "Борис")
    entry = PlayerService.register_player(session, tournament.id, player.id)

    eliminated = PlayerService.eliminate_player(session, entry.id, request_id="eliminate-1")
    assert eliminated.status == TournamentPlayerStatus.ELIMINATED
    assert eliminated.elimination_place == 1
    assert eliminated.eliminated_at is not None

    reentered = PlayerService.add_reentry(session, entry.id, request_id="reentry-1")
    assert reentered.status == TournamentPlayerStatus.ACTIVE
    assert reentered.entries_count == 2

    EventService.undo_last(session, tournament.id, request_id="undo-reentry")
    assert entry.status == TournamentPlayerStatus.ELIMINATED
    assert entry.entries_count == 1

    out = PlayerService.mark_out(session, entry.id, request_id="out-1")
    assert out.status == TournamentPlayerStatus.OUT
    entry_id = entry.id
    with pytest.raises(DomainError, match="окончательный аут"):
        PlayerService.add_reentry(session, entry_id)
    restored = PlayerService.add_reentry(session, entry_id, allow_warnings=True)
    assert restored.status == TournamentPlayerStatus.ACTIVE


def test_late_registration_warning_happens_before_registering_or_reentry(session: Session) -> None:
    tournament = create_tournament(session)
    tournament_id = tournament.id
    LevelService.replace_levels(
        session,
        tournament_id,
        [
            {"kind": "play", "small_blind": 10, "big_blind": 20, "duration_seconds": 60},
            {"kind": "play", "small_blind": 20, "big_blind": 40, "duration_seconds": 60},
            {"kind": "break", "duration_seconds": 60},
            {"kind": "play", "small_blind": 40, "big_blind": 80, "duration_seconds": 60},
        ],
        late_registration_end_level_index=1,
    )

    session.rollback()
    with session.begin():
        session.get(type(tournament), tournament_id).current_level_index = 2

    entry = PlayerService.create_and_register_player(session, tournament_id, "Анна")
    entry_id = entry.id
    PlayerService.eliminate_player(session, entry_id)
    restored = PlayerService.add_reentry(session, entry_id)
    assert restored.entries_count == 2

    PlayerService.eliminate_player(session, entry_id)
    session.rollback()
    with session.begin():
        session.get(type(tournament), tournament_id).current_level_index = 3

    with pytest.raises(DomainError) as reentry_error:
        PlayerService.add_reentry(session, entry_id)
    assert reentry_error.value.code == "late_registration_warning"

    with pytest.raises(DomainError) as registration_error:
        PlayerService.create_and_register_player(session, tournament_id, "Борис")
    assert registration_error.value.code == "late_registration_warning"

    blocked_entry = session.get(TournamentPlayer, entry_id)
    assert blocked_entry.status == TournamentPlayerStatus.ELIMINATED
    assert blocked_entry.entries_count == 2
    assert session.scalar(select(func.count()).select_from(Player).where(Player.name == "Борис")) == 0
    session.rollback()

    reentered_after_confirmation = PlayerService.add_reentry(session, entry_id, allow_warnings=True)
    assert reentered_after_confirmation.status == TournamentPlayerStatus.ACTIVE
    assert reentered_after_confirmation.entries_count == 3


def test_public_event_feed_contains_latest_registration_elimination_or_reentry(session: Session) -> None:
    tournament = create_tournament(session)
    players = [PlayerService.create_player(session, name) for name in ("Анна", "Борис")]
    entries = [PlayerService.register_player(session, tournament.id, player.id) for player in players]
    tournament_id = tournament.id
    entry_id = entries[0].id

    state = tournament_state(session, tournament_id)
    assert state["public_latest_event"]["type"] == "player_registered"
    assert state["public_latest_event"]["player_name"] == "Борис"
    session.rollback()

    PlayerService.eliminate_player(session, entry_id)
    state = tournament_state(session, tournament_id)
    assert state["public_latest_event"]["type"] == "player_eliminated"
    assert state["public_latest_event"]["player_name"] == "Анна"

    session.rollback()
    PlayerService.add_reentry(session, entry_id)
    state = tournament_state(session, tournament_id)
    assert state["public_latest_event"]["type"] == "reentry_added"
    assert state["public_latest_event"]["player_name"] == "Анна"

    session.rollback()
    PlayerService.eliminate_player(session, entry_id)
    PlayerService.mark_out(session, entry_id)
    state = tournament_state(session, tournament_id)
    assert state["public_latest_event"]["type"] == "player_eliminated"
    assert state["public_latest_event"]["player_name"] == "Анна"


def test_public_event_feed_hides_players_registered_during_setup(session: Session) -> None:
    tournament = TournamentService.create_tournament(
        session,
        name="Подготовка",
        buy_in_amount=500,
        currency_label="₽",
        starting_stack=10_000,
        admin_pin_hash="hash",
    )
    player = PlayerService.create_player(session, "Анна")

    PlayerService.register_player(session, tournament.id, player.id)

    state = tournament_state(session, tournament.id)
    assert state["latest_event"]["type"] == "player_registered"
    assert state["public_latest_event"] is None


def test_public_stage_feed_tracks_three_players_heads_up_and_winner(session: Session) -> None:
    tournament = create_tournament(session)
    players = [PlayerService.create_player(session, name) for name in ("Анна", "Борис", "Вера", "Глеб")]
    entries = [PlayerService.register_player(session, tournament.id, player.id) for player in players]
    tournament_id = tournament.id
    entry_ids = [entry.id for entry in entries]

    assert tournament_state(session, tournament_id)["public_stage"] is None
    session.rollback()

    PlayerService.eliminate_player(session, entry_ids[0])
    PlayerService.mark_out(session, entry_ids[0])
    assert tournament_state(session, tournament_id)["public_stage"] == {"type": "three_players_left"}
    session.rollback()

    PlayerService.eliminate_player(session, entry_ids[1])
    PlayerService.mark_out(session, entry_ids[1])
    assert tournament_state(session, tournament_id)["public_stage"] == {"type": "heads_up"}
    session.rollback()

    PlayerService.eliminate_player(session, entry_ids[2])
    PlayerService.mark_out(session, entry_ids[2])
    assert tournament_state(session, tournament_id)["public_stage"] == {
        "type": "winner",
        "player_name": "Глеб",
    }


def test_elimination_can_be_undone(session: Session) -> None:
    tournament = create_tournament(session)
    player = PlayerService.create_player(session, "Олег")
    entry = PlayerService.register_player(session, tournament.id, player.id)

    PlayerService.eliminate_player(session, entry.id)

    EventService.undo_last(session, tournament.id)

    assert entry.status == TournamentPlayerStatus.ACTIVE
    assert entry.elimination_place is None
    assert entry.eliminated_at is None


def test_out_then_two_undos_restore_player_without_reentry(session: Session) -> None:
    tournament = create_tournament(session)
    players = [PlayerService.create_player(session, name) for name in ("Олег", "Анна", "Борис")]
    entries = [PlayerService.register_player(session, tournament.id, player.id) for player in players]
    entry = entries[0]

    PlayerService.eliminate_player(session, entry.id)
    eliminated_at = entry.eliminated_at
    PlayerService.mark_out(session, entry.id)
    out_event = session.scalar(select(TournamentEvent).where(TournamentEvent.event_type == "player_out"))
    assert out_event is not None and out_event.is_reversible
    # Старые турниры сохраняли этот тип события без флага обратимости.
    out_event.is_reversible = False
    session.commit()
    out_event_id = out_event.id
    tournament_id = tournament.id
    session.rollback()

    EventService.undo_last(session, tournament_id)
    assert entry.status == TournamentPlayerStatus.ELIMINATED
    assert entry.eliminated_at == eliminated_at
    assert session.get(TournamentEvent, out_event_id).reversed_at is not None
    session.rollback()

    EventService.undo_last(session, tournament_id)
    assert entry.status == TournamentPlayerStatus.ACTIVE
    assert entry.entries_count == 1
    assert entry.elimination_place is None
    assert entry.eliminated_at is None
    assert session.scalar(select(func.count()).select_from(TournamentEvent).where(
        TournamentEvent.tournament_id == tournament.id,
        TournamentEvent.event_type == "event_reversed",
    )) == 2


def test_undo_out_reopens_automatically_finished_tournament(session: Session) -> None:
    tournament = create_tournament(session)
    players = [PlayerService.create_player(session, name) for name in ("Олег", "Анна")]
    entries = [PlayerService.register_player(session, tournament.id, player.id) for player in players]
    eliminated, winner = entries

    PlayerService.eliminate_player(session, eliminated.id)
    PlayerService.mark_out(session, eliminated.id)
    assert tournament.status == TournamentStatus.FINISHED
    assert winner.elimination_place == 1

    EventService.undo_last(session, tournament.id)
    assert tournament.status == TournamentStatus.PAUSED
    assert tournament.timer_status == TimerStatus.PAUSED
    assert winner.elimination_place is None
    assert eliminated.status == TournamentPlayerStatus.ELIMINATED

    EventService.undo_last(session, tournament.id)
    assert eliminated.status == TournamentPlayerStatus.ACTIVE
    assert tournament_state(session, tournament.id)["metrics"]["active_players"] == 2


def test_reentry_limit_is_enforced(session: Session) -> None:
    tournament = create_tournament(session, limit=1)
    player = PlayerService.create_player(session, "Вера")
    entry = PlayerService.register_player(session, tournament.id, player.id)

    PlayerService.eliminate_player(session, entry.id)
    PlayerService.add_reentry(session, entry.id)
    PlayerService.eliminate_player(session, entry.id)
    entry_id = entry.id

    with pytest.raises(DomainError, match="все доступные re-entry"):
        PlayerService.add_reentry(session, entry_id)
    restored = PlayerService.add_reentry(session, entry_id, allow_warnings=True)
    assert restored.entries_count == 3


def test_only_active_player_can_be_eliminated(session: Session) -> None:
    tournament = create_tournament(session)
    player = PlayerService.create_player(session, "Глеб")
    entry = PlayerService.register_player(session, tournament.id, player.id)
    PlayerService.eliminate_player(session, entry.id)

    with pytest.raises(DomainError, match="только для игрока в игре"):
        PlayerService.eliminate_player(session, entry.id)


def test_elimination_after_entry_lookup_uses_a_clean_transaction(session: Session) -> None:
    tournament = create_tournament(session)
    player = PlayerService.create_player(session, "Лена")
    entry = PlayerService.register_player(session, tournament.id, player.id)

    looked_up = session.get(type(entry), entry.id)
    assert looked_up is not None
    session.rollback()

    eliminated = PlayerService.eliminate_player(session, looked_up.id)

    assert eliminated.status == TournamentPlayerStatus.ELIMINATED


def test_tournament_finishes_after_all_but_one_are_out(session: Session) -> None:
    tournament = TournamentService.create_tournament(
        session,
        name="Автоматическое завершение",
        buy_in_amount=500,
        currency_label="₽",
        starting_stack=10_000,
        admin_pin_hash=hash_pin("1234"),
    )
    with session.begin():
        tournament.status = TournamentStatus.RUNNING
    players = [PlayerService.create_player(session, name) for name in ("Анна", "Борис", "Вера")]
    entries = [PlayerService.register_player(session, tournament.id, player.id) for player in players]

    for entry in entries[:2]:
        PlayerService.eliminate_player(session, entry.id)
        PlayerService.mark_out(session, entry.id)

    finished = session.get(type(tournament), tournament.id)
    assert finished is not None
    assert finished.status == TournamentStatus.FINISHED
    assert finished.timer_status == TimerStatus.STOPPED
    assert finished.is_manually_finished is False
    assert entries[2].elimination_place == 1
    state = tournament_state(session, tournament.id)
    assert [(item["place"], item["reentries"]) for item in state["standings"]] == [(1, 0), (2, 0), (3, 0)]

    tournament_id = tournament.id
    winner_entry_id = entries[2].id
    session.rollback()
    TournamentService.finish_manually(session, tournament_id, "1234")

    locked = session.get(type(tournament), tournament_id)
    assert locked is not None
    assert locked.status == TournamentStatus.FINISHED
    assert locked.is_manually_finished is True

    session.rollback()
    with pytest.raises(DomainError, match="заблокирован для изменений"):
        PlayerService.eliminate_player(session, winner_entry_id)


def test_manual_finish_locks_tournament_changes(session: Session) -> None:
    tournament = TournamentService.create_tournament(
        session,
        name="Ручное завершение",
        buy_in_amount=500,
        currency_label="₽",
        starting_stack=10_000,
        admin_pin_hash=hash_pin("1234"),
    )
    player = PlayerService.create_player(session, "Мария")
    entry = PlayerService.register_player(session, tournament.id, player.id)

    with pytest.raises(DomainError, match="Неверный PIN"):
        TournamentService.finish_manually(session, tournament.id, "0000")
    tournament_id = tournament.id
    session.rollback()
    TournamentService.finish_manually(session, tournament_id, "1234")

    finished = session.get(type(tournament), tournament.id)
    assert finished is not None
    assert finished.status == TournamentStatus.FINISHED
    assert finished.timer_status == TimerStatus.STOPPED
    assert finished.is_manually_finished is True
    state = tournament_state(session, tournament.id)
    assert state["is_manually_finished"] is True
    entry_id = entry.id
    session.rollback()

    with pytest.raises(DomainError, match="заблокирован для изменений"):
        PlayerService.eliminate_player(session, entry_id)


def test_structure_and_late_registration_can_change_after_start(session: Session) -> None:
    tournament = create_tournament(session)
    LevelService.replace_levels(
        session,
        tournament.id,
        [
            {"kind": "play", "small_blind": 10, "big_blind": 20, "duration_seconds": 60},
            {"kind": "break", "duration_seconds": 60},
        ],
        late_registration_end_level_index=0,
    )
    LevelService.replace_levels(
        session,
        tournament.id,
        [
            {"kind": "play", "small_blind": 25, "big_blind": 50, "duration_seconds": 120},
            {"kind": "play", "small_blind": 50, "big_blind": 100, "duration_seconds": 120},
            {"kind": "break", "duration_seconds": 60},
        ],
        late_registration_end_level_index=1,
    )

    assert len(tournament.levels) == 3
    assert tournament.levels[0].big_blind == 50
    assert tournament.late_registration_end_level_index == 1

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.enums import TimerStatus, TournamentPlayerStatus, TournamentStatus
from app.services import PlayerService, TournamentService
from app.services.errors import DomainError
from app.services.level_service import LevelService
from app.services.setup_service import TournamentSetupService
from app.services.state_service import tournament_state
from app.services.timer_service import TimerService


def make_tournament_with_levels(session: Session):
    tournament = TournamentService.create_tournament(
        session,
        name="Тест таймера",
        buy_in_amount=100,
        currency_label="₽",
        starting_stack=1_000,
        admin_pin_hash="hash",
    )
    assert tournament.timer_status == TimerStatus.PAUSED
    LevelService.replace_levels(
        session,
        tournament.id,
        [
            {"kind": "play", "small_blind": 10, "big_blind": 20, "ante": 0, "duration_seconds": 60},
            {"kind": "play", "small_blind": 20, "big_blind": 40, "ante": 0, "duration_seconds": 60},
        ],
        late_registration_end_level_index=0,
    )
    return tournament


def test_not_started_tournament_shows_full_first_level(session: Session) -> None:
    tournament = TournamentSetupService.create(
        session,
        name="Ещё не начат",
        buy_in_amount=100,
        currency_label="₽",
        starting_stack=1_000,
        admin_pin_hash="hash",
        levels=[{"kind": "play", "small_blind": 10, "big_blind": 20, "ante": 0, "duration_seconds": 900}],
        late_registration_end_level_number=1,
    )
    assert tournament.paused_remaining_seconds is None

    state = tournament_state(session, tournament.id)

    assert state["status"] == TournamentStatus.DRAFT.value
    assert state["remaining_seconds"] == 900


def test_start_pause_resume_and_next_level(session: Session) -> None:
    tournament = make_tournament_with_levels(session)
    player = PlayerService.create_player(session, "Ирина")
    entry = PlayerService.register_player(session, tournament.id, player.id)
    now = datetime(2026, 8, 6, 18, 0, tzinfo=UTC)

    TimerService.command(session, tournament.id, "resume", now=now)
    assert tournament.timer_status == TimerStatus.RUNNING
    assert entry.status == TournamentPlayerStatus.ACTIVE

    TimerService.command(session, tournament.id, "pause", now=now + timedelta(seconds=20))
    assert tournament.timer_status == TimerStatus.PAUSED
    assert tournament.paused_remaining_seconds == 40

    TimerService.command(session, tournament.id, "resume", now=now + timedelta(seconds=40))
    TimerService.command(session, tournament.id, "next", now=now + timedelta(seconds=41))
    assert tournament.current_level_index == 1
    assert tournament.timer_status == TimerStatus.RUNNING


def test_auto_advance_after_large_time_jump(session: Session) -> None:
    tournament = make_tournament_with_levels(session)
    now = datetime(2026, 8, 6, 18, 0, tzinfo=UTC)
    TimerService.command(session, tournament.id, "resume", now=now)

    with session.begin():
        changed = TimerService.reconcile(session, tournament.id, now + timedelta(seconds=61))

    assert changed
    assert tournament.current_level_index == 1


def test_reconcile_handles_sqlite_naive_timestamp(session: Session) -> None:
    tournament = make_tournament_with_levels(session)
    now = datetime(2026, 8, 6, 18, 0, tzinfo=UTC)
    TimerService.command(session, tournament.id, "resume", now=now)

    session.expire_all()
    persisted_tournament = session.get(type(tournament), tournament.id)
    assert persisted_tournament is not None
    assert persisted_tournament.level_started_at is not None

    changed = TimerService.reconcile(session, tournament.id, now + timedelta(seconds=61))
    session.commit()

    assert changed
    assert persisted_tournament.current_level_index == 1


def test_level_defaults_ante_to_big_blind(session: Session) -> None:
    tournament = make_tournament_with_levels(session)
    levels = LevelService.replace_levels(
        session,
        tournament.id,
        [{"kind": "play", "small_blind": 100, "big_blind": 200, "duration_seconds": 1_500}],
        late_registration_end_level_index=0,
    )

    assert levels[0].ante == 200


def test_level_replacement_requires_play_level_for_late_registration_end(session: Session) -> None:
    tournament = make_tournament_with_levels(session)
    tournament_id = tournament.id
    levels = [
        {"kind": "play", "small_blind": 100, "big_blind": 200, "duration_seconds": 1_500},
        {"kind": "break", "duration_seconds": 600},
    ]

    with pytest.raises(DomainError, match="Укажите игровой уровень"):
        LevelService.replace_levels(session, tournament_id, levels)

    session.rollback()
    with pytest.raises(DomainError, match="после игрового уровня"):
        LevelService.replace_levels(session, tournament_id, levels, late_registration_end_level_index=1)


def test_state_numbers_only_play_levels_and_exposes_late_registration_number(session: Session) -> None:
    tournament = make_tournament_with_levels(session)
    LevelService.replace_levels(
        session,
        tournament.id,
        [
            {"kind": "play", "small_blind": 10, "big_blind": 20, "ante": 20, "duration_seconds": 60},
            {"kind": "play", "small_blind": 20, "big_blind": 40, "ante": 40, "duration_seconds": 60},
            {"kind": "break", "duration_seconds": 15, "title": "Летний hydration break"},
            {"kind": "play", "small_blind": 40, "big_blind": 80, "ante": 80, "duration_seconds": 60},
        ],
        late_registration_end_level_index=1,
    )

    state = tournament_state(session, tournament.id)

    assert [level["level_number"] for level in state["levels"]] == [1, 2, None, 3]
    assert state["levels"][2]["title"] == "Перерыв"
    assert state["late_registration_end_level_number"] == 2
    assert state["late_registration_phase"] == "next_level"
    assert state["late_registration_ended"] is False

    session.rollback()
    with session.begin():
        tournament.current_level_index = 1
    state = tournament_state(session, tournament.id)
    assert state["late_registration_phase"] == "closing"
    assert state["late_registration_ended"] is False

    session.rollback()
    with session.begin():
        tournament.current_level_index = 2
    state = tournament_state(session, tournament.id)
    assert state["late_registration_phase"] == "grace_break"
    assert state["late_registration_ended"] is False

    session.rollback()
    with session.begin():
        tournament.current_level_index = 3
    state = tournament_state(session, tournament.id)
    assert state["late_registration_phase"] == "closed"
    assert state["late_registration_ended"] is True


def test_late_registration_closes_on_next_level_without_break(session: Session) -> None:
    tournament = make_tournament_with_levels(session)
    LevelService.replace_levels(
        session,
        tournament.id,
        [
            {"kind": "play", "small_blind": 10, "big_blind": 20, "ante": 20, "duration_seconds": 60},
            {"kind": "play", "small_blind": 20, "big_blind": 40, "ante": 40, "duration_seconds": 60},
            {"kind": "play", "small_blind": 40, "big_blind": 80, "ante": 80, "duration_seconds": 60},
        ],
        late_registration_end_level_index=1,
    )

    session.rollback()
    with session.begin():
        tournament.current_level_index = 2

    state = tournament_state(session, tournament.id)
    assert state["late_registration_phase"] == "closed"
    assert state["late_registration_ended"] is True


def test_reset_and_previous_level(session: Session) -> None:
    tournament = make_tournament_with_levels(session)
    now = datetime(2026, 8, 6, 18, 0, tzinfo=UTC)
    TimerService.command(session, tournament.id, "resume", now=now)
    TimerService.command(session, tournament.id, "next", now=now + timedelta(seconds=1))
    TimerService.command(session, tournament.id, "previous", now=now + timedelta(seconds=2))
    TimerService.command(session, tournament.id, "reset", now=now + timedelta(seconds=3))

    assert tournament.current_level_index == 0
    assert tournament.level_started_at == now + timedelta(seconds=3)


def test_previous_level_reopens_tournament_after_structure_expires(session: Session) -> None:
    tournament = make_tournament_with_levels(session)
    now = datetime(2026, 8, 6, 18, 0, tzinfo=UTC)
    TimerService.command(session, tournament.id, "resume", now=now)

    with session.begin():
        TimerService.reconcile(session, tournament.id, now + timedelta(seconds=121))

    assert tournament.status == TournamentStatus.FINISHED
    assert tournament.current_level_index == 1

    TimerService.command(session, tournament.id, "previous", now=now + timedelta(seconds=122))

    assert tournament.status == TournamentStatus.PAUSED
    assert tournament.timer_status == TimerStatus.PAUSED
    assert tournament.current_level_index == 0
    assert tournament.paused_remaining_seconds == 60
    assert tournament_state(session, tournament.id)["remaining_seconds"] == 60


def test_add_time_reopens_last_level_after_structure_expires(session: Session) -> None:
    tournament = make_tournament_with_levels(session)
    now = datetime(2026, 8, 6, 18, 0, tzinfo=UTC)
    TimerService.command(session, tournament.id, "resume", now=now)

    with session.begin():
        TimerService.reconcile(session, tournament.id, now + timedelta(seconds=121))

    TimerService.command(session, tournament.id, "add_60", now=now + timedelta(seconds=122))

    assert tournament.status == TournamentStatus.PAUSED
    assert tournament.timer_status == TimerStatus.PAUSED
    assert tournament.current_level_index == 1
    assert tournament.paused_remaining_seconds == 60
    assert tournament_state(session, tournament.id)["remaining_seconds"] == 60


def test_previous_level_reopens_automatic_finish_with_winner(session: Session) -> None:
    tournament = make_tournament_with_levels(session)
    player = PlayerService.create_player(session, "Победитель")
    entry = PlayerService.register_player(session, tournament.id, player.id)

    with session.begin():
        tournament.current_level_index = 1
        tournament.status = TournamentStatus.FINISHED
        tournament.timer_status = TimerStatus.STOPPED
        tournament.paused_remaining_seconds = 0
        entry.elimination_place = 1

    TimerService.command(session, tournament.id, "previous")

    assert tournament.status == TournamentStatus.PAUSED
    assert tournament.timer_status == TimerStatus.PAUSED
    assert tournament.current_level_index == 0
    assert tournament.paused_remaining_seconds == 60
    assert entry.elimination_place is None
    state = tournament_state(session, tournament.id)
    assert state["status"] == "paused"
    assert all(item["place"] != 1 for item in state["standings"])


def test_previous_level_reopens_real_automatic_finish_and_hides_results(session: Session) -> None:
    tournament = make_tournament_with_levels(session)
    first = PlayerService.create_player(session, "Анна")
    second = PlayerService.create_player(session, "Борис")
    winner = PlayerService.register_player(session, tournament.id, first.id)
    eliminated = PlayerService.register_player(session, tournament.id, second.id)
    now = datetime(2026, 8, 6, 18, 0, tzinfo=UTC)

    TimerService.command(session, tournament.id, "resume", now=now)
    TimerService.command(session, tournament.id, "next", now=now + timedelta(seconds=1))
    PlayerService.eliminate_player(session, eliminated.id)
    PlayerService.mark_out(session, eliminated.id)

    tournament_id = tournament.id
    finished_state = tournament_state(session, tournament.id)
    assert finished_state["status"] == "finished"
    assert next(item for item in finished_state["standings"] if item["place"] == 1)["id"] == winner.id
    session.rollback()

    TimerService.command(session, tournament_id, "previous", now=now + timedelta(seconds=2))

    reopened_state = tournament_state(session, tournament_id)
    assert reopened_state["status"] == "paused"
    assert reopened_state["timer_status"] == "paused"
    assert reopened_state["current_level_index"] == 0
    assert reopened_state["remaining_seconds"] == 60
    assert all(item["place"] != 1 for item in reopened_state["standings"])


def test_timer_cannot_reopen_manually_finished_tournament(session: Session) -> None:
    tournament = make_tournament_with_levels(session)

    with session.begin():
        tournament.current_level_index = 1
        tournament.status = TournamentStatus.FINISHED
        tournament.timer_status = TimerStatus.STOPPED
        tournament.paused_remaining_seconds = 0
        tournament.is_manually_finished = True

    with pytest.raises(DomainError, match="заблокирован"):
        TimerService.command(session, tournament.id, "previous")

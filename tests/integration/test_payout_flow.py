import pytest
from sqlalchemy.orm import Session

from app.models.enums import TournamentPlayerStatus, TournamentStatus
from app.services import DomainError, EventService, PayoutService, PlayerService, TournamentService
from app.services.level_service import LevelService
from app.services.state_service import tournament_state
from app.services.timer_service import TimerService


def money_tournament(session: Session):
    tournament = TournamentService.create_tournament(
        session,
        name="Выплаты",
        buy_in_amount=1_000,
        currency_label="₽",
        starting_stack=20_000,
        admin_pin_hash="hash",
    )
    PayoutService.save_structure(session, tournament.id, [50, 30, 20])
    return tournament


def test_payouts_follow_existing_entry_and_prize_pool_counts(session: Session) -> None:
    tournament = money_tournament(session)
    players = [PlayerService.create_player(session, f"Игрок {index}") for index in range(8)]
    entries = [PlayerService.register_player(session, tournament.id, player.id) for player in players]

    first = PayoutService.calculate(
        sum(entry.entries_count for entry in entries) * tournament.buy_in_amount,
        list(tournament.payouts),
    )
    assert [line.amount for line in first] == [4_000, 2_400, 1_600]

    session.rollback()
    with session.begin():
        tournament.status = TournamentStatus.RUNNING
        entries[0].status = TournamentPlayerStatus.ACTIVE
    PlayerService.eliminate_player(session, entries[0].id)
    PlayerService.add_reentry(session, entries[0].id)

    second = PayoutService.calculate(
        sum(entry.entries_count for entry in entries) * tournament.buy_in_amount,
        list(tournament.payouts),
    )
    assert [line.amount for line in second] == [4_500, 2_700, 1_800]
    assert sum(line.amount for line in second) == 9_000


def test_freeroll_rejects_money_payout_structure(session: Session) -> None:
    tournament = TournamentService.create_tournament(
        session,
        name="Фриролл",
        buy_in_amount=0,
        currency_label="₽",
        starting_stack=20_000,
        admin_pin_hash="hash",
    )

    with pytest.raises(DomainError) as error:
        PayoutService.save_structure(session, tournament.id, [100])
    assert error.value.code == "freeroll_has_no_payouts"


def running_payout_tournament(session: Session, names: tuple[str, ...], percentages=(50, 30, 20)):
    tournament = money_tournament(session) if percentages == (50, 30, 20) else TournamentService.create_tournament(
        session,
        name="Выплаты",
        buy_in_amount=1_000,
        currency_label="₽",
        starting_stack=20_000,
        admin_pin_hash="hash",
    )
    if percentages != (50, 30, 20):
        PayoutService.save_structure(session, tournament.id, list(percentages))
    LevelService.replace_levels(
        session,
        tournament.id,
        [
            {"kind": "play", "small_blind": 10, "big_blind": 20, "duration_seconds": 60},
            {"kind": "play", "small_blind": 20, "big_blind": 40, "duration_seconds": 60},
        ],
        late_registration_end_level_index=0,
    )
    players = [PlayerService.create_player(session, name) for name in names]
    entries = [PlayerService.register_player(session, tournament.id, player.id) for player in players]
    TimerService.command(session, tournament.id, "resume")
    return tournament, entries


def close_registration(session: Session, tournament_id: int) -> dict:
    TimerService.command(session, tournament_id, "next")
    return tournament_state(session, tournament_id)


def test_bubble_and_itm_are_server_transitions_and_repeat_after_undo(session: Session) -> None:
    tournament, entries = running_payout_tournament(
        session,
        ("Анна", "Борис", "Вера", "Глеб", "Даша"),
    )
    tournament_id = tournament.id
    entry_ids = [entry.id for entry in entries]

    open_state = tournament_state(session, tournament_id)
    assert open_state["payouts"]["stage"] == "registration_open"
    assert open_state["payouts"]["status"] == "preliminary"
    session.rollback()

    closed_state = close_registration(session, tournament_id)
    assert closed_state["payouts"]["stage"] == "registration_closed"
    assert closed_state["payouts"]["status"] == "final"
    assert closed_state["payouts"]["finalized_at"] is not None
    session.rollback()

    PlayerService.eliminate_player(session, entry_ids[0])
    bubble = tournament_state(session, tournament_id)
    assert bubble["metrics"]["active_players"] == 4
    assert bubble["payouts"]["stage"] == "bubble"
    assert bubble["public_payout_event"]["type"] == "bubble_reached"
    bubble_event_id = bubble["public_payout_event"]["id"]
    session.rollback()

    PlayerService.eliminate_player(session, entry_ids[1])
    itm = tournament_state(session, tournament_id)
    assert itm["metrics"]["active_players"] == 3
    assert itm["payouts"]["stage"] == "itm"
    assert itm["public_payout_event"]["type"] == "itm_reached"
    first_itm_event_id = itm["public_payout_event"]["id"]
    session.rollback()

    EventService.undo_last(session, tournament_id)
    restored = tournament_state(session, tournament_id)
    assert restored["metrics"]["active_players"] == 4
    assert restored["payouts"]["stage"] == "bubble"
    assert restored["public_payout_event"]["type"] == "bubble_reached"
    assert restored["public_payout_event"]["id"] > bubble_event_id
    session.rollback()

    PlayerService.eliminate_player(session, entry_ids[1])
    repeated = tournament_state(session, tournament_id)
    assert repeated["payouts"]["stage"] == "itm"
    assert repeated["public_payout_event"]["type"] == "itm_reached"
    assert repeated["public_payout_event"]["id"] > first_itm_event_id


def test_post_close_reentry_changes_entries_and_payouts_not_unique_player_count(session: Session) -> None:
    tournament, entries = running_payout_tournament(
        session,
        ("Анна", "Борис", "Вера", "Глеб", "Даша"),
    )
    tournament_id = tournament.id
    first_entry_id = entries[0].id
    close_registration(session, tournament_id)
    session.rollback()
    PlayerService.eliminate_player(session, first_entry_id)
    session.rollback()

    with pytest.raises(DomainError) as warning:
        PlayerService.add_reentry(session, first_entry_id)
    assert warning.value.code == "late_registration_warning"
    session.rollback()

    PlayerService.add_reentry(session, first_entry_id, allow_warnings=True)
    state = tournament_state(session, tournament_id)
    assert state["metrics"]["active_players"] == 5
    assert state["metrics"]["registered_players"] == 5
    assert state["metrics"]["total_entries"] == 6
    assert state["metrics"]["prize_pool"] == 6_000
    assert [line["amount"] for line in state["payouts"]["lines"]] == [3_000, 1_800, 1_200]
    assert state["payouts"]["status"] == "final"


def test_winner_takes_all_skips_conflicting_itm_overlay_and_finishes_with_money_results(session: Session) -> None:
    tournament, entries = running_payout_tournament(session, ("Анна", "Борис"), percentages=(100,))
    tournament_id = tournament.id
    first_entry_id = entries[0].id
    bubble = close_registration(session, tournament_id)
    assert bubble["payouts"]["stage"] == "bubble"
    assert bubble["public_payout_event"]["type"] == "bubble_reached"
    bubble_event_id = bubble["public_payout_event"]["id"]
    session.rollback()

    PlayerService.eliminate_player(session, first_entry_id)
    itm = tournament_state(session, tournament_id)
    assert itm["payouts"]["stage"] == "itm"
    assert itm["public_payout_event"]["id"] == bubble_event_id
    session.rollback()

    PlayerService.mark_out(session, first_entry_id)
    finished = tournament_state(session, tournament_id)
    assert finished["payouts"]["stage"] == "tournament_finished"
    winner = next(item for item in finished["standings"] if item["place"] == 1)
    loser = next(item for item in finished["standings"] if item["place"] == 2)
    assert (winner["winnings"], winner["total_buy_ins"], winner["net_result"], winner["itm"]) == (
        2_000,
        1_000,
        1_000,
        True,
    )
    assert (loser["winnings"], loser["net_result"], loser["itm"]) == (0, -1_000, False)


def test_finalization_survives_state_reload_and_locks_structure(session: Session) -> None:
    tournament, _ = running_payout_tournament(
        session,
        ("Анна", "Борис", "Вера", "Глеб", "Даша"),
    )
    tournament_id = tournament.id
    close_registration(session, tournament_id)
    session.rollback()
    session.expire_all()

    restored = tournament_state(session, tournament_id)
    assert restored["payouts"]["status"] == "final"
    assert restored["late_registration_phase"] == "closed"
    session.rollback()

    TimerService.command(session, tournament_id, "previous")
    navigated_back = tournament_state(session, tournament_id)
    assert navigated_back["current_level_index"] == 0
    assert navigated_back["payouts"]["status"] == "final"
    assert navigated_back["late_registration_phase"] == "closed"
    session.rollback()

    with pytest.raises(DomainError) as error:
        PayoutService.save_structure(session, tournament_id, [60, 40])
    assert error.value.code == "payouts_finalized"


def test_paid_places_equal_to_multiple_registered_players_is_reported(session: Session) -> None:
    tournament, _ = running_payout_tournament(session, ("Анна", "Борис", "Вера"))
    state = close_registration(session, tournament.id)

    assert state["payouts"]["stage"] == "configuration_error"
    assert state["payouts"]["configuration_error"] is not None


def test_registration_can_be_explicitly_finalized_without_level_cutoff(session: Session) -> None:
    tournament = money_tournament(session)
    players = [PlayerService.create_player(session, f"Игрок {index}") for index in range(5)]
    entries = [PlayerService.register_player(session, tournament.id, player.id) for player in players]
    with session.begin():
        tournament.status = TournamentStatus.RUNNING
        for entry in entries:
            entry.status = TournamentPlayerStatus.ACTIVE

    PayoutService.finalize_registration(session, tournament.id)
    state = tournament_state(session, tournament.id)

    assert state["late_registration_phase"] == "closed"
    assert state["payouts"]["status"] == "final"
    assert state["payouts"]["stage"] == "registration_closed"


def test_explicit_finalization_rejects_too_many_paid_places(session: Session) -> None:
    tournament = money_tournament(session)
    for name in ("Анна", "Борис", "Вера"):
        player = PlayerService.create_player(session, name)
        PlayerService.register_player(session, tournament.id, player.id)

    with pytest.raises(DomainError) as error:
        PayoutService.finalize_registration(session, tournament.id)
    assert error.value.code == "invalid_paid_places"

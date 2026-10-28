import pytest
from sqlalchemy import func, select

from app.models.enums import TournamentPlayerStatus
from app.models.tournament import Tournament, TournamentEvent, TournamentPlayer
from app.security import hash_pin
from app.services import BountyService, DomainError, EventService, PlayerService, TournamentService
from app.services.setup_service import TournamentSetupService
from app.services.timer_service import TimerService
from app.services.state_service import tournament_state


def running_bounty_tournament(session, names=("EVERLONG", "ANDREY", "MAX")):
    tournament = TournamentSetupService.create(
        session,
        name="Fixed Bounty",
        buy_in_amount=1_000,
        bounty_mode="fixed",
        bounty_amount=300,
        currency_label="₽",
        starting_stack=20_000,
        admin_pin_hash=hash_pin("1234"),
        levels=[
            {"kind": "play", "duration_seconds": 1_200, "small_blind": 25, "big_blind": 50},
            {"kind": "play", "duration_seconds": 1_200, "small_blind": 50, "big_blind": 100},
        ],
        player_names=list(names),
        late_registration_end_level_number=1,
        payout_percentages=[100] if len(names) == 1 else [50, 30, 20],
    )
    entry_ids = [entry.id for entry in tournament.players]
    tournament_id = tournament.id
    session.rollback()
    TimerService.command(session, tournament_id, "resume")
    return tournament_id, entry_ids


def test_fixed_bounty_elimination_requires_valid_active_killer(session) -> None:
    tournament_id, entries = running_bounty_tournament(session)
    eliminated_id, killer_id, other_id = entries

    with pytest.raises(DomainError) as missing:
        PlayerService.eliminate_player(session, eliminated_id)
    assert missing.value.code == "killer_required"

    with pytest.raises(DomainError) as self_elimination:
        PlayerService.eliminate_player(session, eliminated_id, killer_tournament_player_id=eliminated_id)
    assert self_elimination.value.code == "self_elimination"

    session.rollback()
    with session.begin():
        session.get(TournamentPlayer, other_id).status = TournamentPlayerStatus.ELIMINATED
    with pytest.raises(DomainError) as inactive:
        PlayerService.eliminate_player(session, eliminated_id, killer_tournament_player_id=other_id)
    assert inactive.value.code == "killer_not_active"

    PlayerService.eliminate_player(session, eliminated_id, killer_tournament_player_id=killer_id)
    result = BountyService.results(session, tournament_id)[killer_id]
    assert result.ko_count == 1
    assert result.bounty_winnings == 300
    state = tournament_state(session, tournament_id)
    assert state["bounty_mode"] == "fixed"
    assert state["bounty_amount"] == 300
    assert state["metrics"]["prize_pool"] == 2_100
    assert state["metrics"]["bounty_pool"] == 900
    assert state["metrics"]["total_collected"] == 3_000
    assert state["public_latest_event"]["killer_name"] == "ANDREY"
    assert state["public_latest_event"]["bounty_amount_awarded"] == 300
    assert state["ko_leader"] == {"ko_count": 1, "names": ["ANDREY"], "tie": False}


def test_reentry_creates_another_bounty_and_each_bust_is_a_separate_ko(session) -> None:
    tournament_id, entries = running_bounty_tournament(session)
    eliminated_id, killer_id, _ = entries

    PlayerService.eliminate_player(session, eliminated_id, killer_tournament_player_id=killer_id)
    PlayerService.add_reentry(session, eliminated_id)
    PlayerService.eliminate_player(session, eliminated_id, killer_tournament_player_id=killer_id)

    result = BountyService.results(session, tournament_id)[killer_id]
    assert session.get(TournamentPlayer, eliminated_id).entries_count == 2
    assert result.ko_count == 2
    assert result.bounty_winnings == 600


def test_first_player_to_reach_tied_ko_count_stays_leader_and_undo_recalculates(session) -> None:
    tournament_id, entries = running_bounty_tournament(session, ("A", "B", "C", "D"))
    first_killer_id, second_killer_id, first_out_id, second_out_id = entries
    PlayerService.eliminate_player(session, first_out_id, killer_tournament_player_id=first_killer_id)
    PlayerService.eliminate_player(session, second_out_id, killer_tournament_player_id=second_killer_id)

    tournament = session.get(Tournament, tournament_id)
    assert BountyService.leader(session, tournament) == {
        "ko_count": 1,
        "names": ["A"],
        "tie": False,
    }

    session.rollback()
    EventService.undo_last(session, tournament_id)

    assert session.get(TournamentPlayer, second_out_id).status == TournamentPlayerStatus.ACTIVE
    assert BountyService.results(session, tournament_id).get(second_killer_id) is None
    assert BountyService.leader(session, session.get(Tournament, tournament_id)) == {
        "ko_count": 1,
        "names": ["A"],
        "tie": False,
    }


def test_champion_gets_one_surviving_bounty_without_an_extra_ko(session) -> None:
    tournament_id, entries = running_bounty_tournament(session)
    champion_id, second_id, third_id = entries
    PlayerService.eliminate_player(session, third_id, killer_tournament_player_id=champion_id)
    PlayerService.mark_out(session, third_id)
    PlayerService.eliminate_player(session, second_id, killer_tournament_player_id=champion_id)
    PlayerService.mark_out(session, second_id)

    results = BountyService.results(session, tournament_id)
    assert results[champion_id].ko_count == 2
    assert results[champion_id].bounty_winnings == 900
    assert sum(result.bounty_winnings for result in results.values()) == 900
    tournament = session.get(Tournament, tournament_id)
    assert BountyService.leader(session, tournament) == {
        "ko_count": 2,
        "names": ["EVERLONG"],
        "tie": False,
    }

    session.rollback()
    with session.begin():
        assert TournamentService.finish_if_ready(session, session.get(Tournament, tournament_id)) is False
    session.expire_all()
    restored = BountyService.results(session, tournament_id)
    assert restored[champion_id].bounty_winnings == 900
    awards = session.scalar(
        select(func.count()).select_from(TournamentEvent).where(
            TournamentEvent.tournament_id == tournament_id,
            TournamentEvent.event_type == "champion_bounty_awarded",
        )
    )
    assert awards == 1
    state = tournament_state(session, tournament_id)
    assert state["status"] == "finished"
    assert state["payouts"]["total_amount"] == state["metrics"]["prize_pool"] == 2_100
    assert sum(player["bounty_winnings"] for player in state["standings"]) == state["metrics"]["bounty_pool"] == 900
    assert state["metrics"]["prize_pool"] + state["metrics"]["bounty_pool"] == state["metrics"]["total_collected"]
    champion_result = next(player for player in state["standings"] if player["id"] == champion_id)
    assert champion_result["main_prize_winnings"] == 1_050
    assert champion_result["bounty_winnings"] == 900
    assert champion_result["winnings"] == 1_950
    assert champion_result["net_result"] == 950


def test_undo_final_out_revokes_champion_award_then_undo_elimination_revokes_ko(session) -> None:
    tournament_id, entries = running_bounty_tournament(session, ("A", "B"))
    winner_id, eliminated_id = entries
    PlayerService.eliminate_player(session, eliminated_id, killer_tournament_player_id=winner_id)
    PlayerService.mark_out(session, eliminated_id)
    assert BountyService.results(session, tournament_id)[winner_id].bounty_winnings == 600
    session.rollback()

    EventService.undo_last(session, tournament_id)
    assert session.get(Tournament, tournament_id).status.value == "paused"
    assert BountyService.results(session, tournament_id)[winner_id].bounty_winnings == 300
    session.rollback()

    EventService.undo_last(session, tournament_id)
    assert session.get(TournamentPlayer, eliminated_id).status == TournamentPlayerStatus.ACTIVE
    assert BountyService.results(session, tournament_id).get(winner_id) is None


def test_reentry_tournament_finishes_with_exact_main_and_bounty_accounting(session) -> None:
    tournament_id, entries = running_bounty_tournament(session, ("CHAMP", "A", "B", "C"))
    champion_id, first_id, second_id, third_id = entries

    PlayerService.eliminate_player(session, first_id, killer_tournament_player_id=second_id)
    PlayerService.add_reentry(session, first_id)
    PlayerService.eliminate_player(session, first_id, killer_tournament_player_id=third_id)
    PlayerService.mark_out(session, first_id)
    PlayerService.eliminate_player(session, third_id, killer_tournament_player_id=champion_id)
    PlayerService.mark_out(session, third_id)
    PlayerService.eliminate_player(session, second_id, killer_tournament_player_id=champion_id)
    PlayerService.mark_out(session, second_id)

    state = tournament_state(session, tournament_id)
    assert state["metrics"]["total_entries"] == 5
    assert state["metrics"]["prize_pool"] == 3_500
    assert state["metrics"]["bounty_pool"] == 1_500
    assert state["metrics"]["total_collected"] == 5_000
    assert state["payouts"]["total_amount"] == 3_500
    assert sum(player["bounty_winnings"] for player in state["standings"]) == 1_500
    assert sum(player["ko_count"] for player in state["standings"]) == 4
    champion = next(player for player in state["standings"] if player["id"] == champion_id)
    assert champion["ko_count"] == 2
    assert champion["bounty_winnings"] == 900


def test_single_player_manual_finish_awards_surviving_bounty_once(session) -> None:
    tournament_id, entries = running_bounty_tournament(session, ("SOLO",))
    champion_id = entries[0]

    TournamentService.finish_manually(session, tournament_id, "1234")

    state = tournament_state(session, tournament_id)
    champion = state["standings"][0]
    assert champion["id"] == champion_id
    assert champion["place"] == 1
    assert champion["ko_count"] == 0
    assert champion["main_prize_winnings"] == 700
    assert champion["bounty_winnings"] == 300
    assert champion["winnings"] == 1_000
    assert champion["net_result"] == 0

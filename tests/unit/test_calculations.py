from app.models.enums import BountyMode, BlindLevelKind, TournamentPlayerStatus
from app.models.tournament import BlindLevel, Tournament, TournamentPlayer
from app.services import CalculationService


def make_tournament() -> Tournament:
    return Tournament(name="Пятничный турнир", buy_in_amount=1000, currency_label="₽", starting_stack=20_000, admin_pin_hash="x")


def test_calculates_prize_pool_average_stack_and_bb() -> None:
    tournament = make_tournament()
    entries = [
        TournamentPlayer(status=TournamentPlayerStatus.ACTIVE, entries_count=2),
        TournamentPlayer(status=TournamentPlayerStatus.ACTIVE, entries_count=1),
        TournamentPlayer(status=TournamentPlayerStatus.ELIMINATED, entries_count=1),
    ]
    level = BlindLevel(
        order_index=0, kind=BlindLevelKind.PLAY, small_blind=100, big_blind=200, ante=0, duration_seconds=900
    )

    metrics = CalculationService.calculate(tournament, entries, level)

    assert metrics.active_players == 2
    assert metrics.registered_players == 3
    assert metrics.total_entries == 4
    assert metrics.total_reentries == 1
    assert metrics.prize_pool == 4_000
    assert metrics.bounty_pool == 0
    assert metrics.total_collected == 4_000
    assert metrics.total_chips_in_play == 80_000
    assert metrics.average_stack == 40_000
    assert metrics.average_stack_bb == 200


def test_fixed_bounty_splits_collected_money_without_a_parallel_entry_count() -> None:
    tournament = make_tournament()
    tournament.bounty_mode = BountyMode.FIXED
    tournament.bounty_amount = 300
    entries = [
        TournamentPlayer(status=TournamentPlayerStatus.ACTIVE, entries_count=2),
        TournamentPlayer(status=TournamentPlayerStatus.ACTIVE, entries_count=1),
    ]

    metrics = CalculationService.calculate(tournament, entries, None)

    assert metrics.total_entries == 3
    assert metrics.main_prize_contribution == 700
    assert metrics.prize_pool == 2_100
    assert metrics.bounty_pool == 900
    assert metrics.total_collected == 3_000
    assert metrics.prize_pool + metrics.bounty_pool == metrics.total_collected


def test_average_metrics_are_empty_without_active_players() -> None:
    tournament = make_tournament()
    entries = [TournamentPlayer(status=TournamentPlayerStatus.ELIMINATED, entries_count=1)]

    metrics = CalculationService.calculate(tournament, entries, None)

    assert metrics.average_stack is None
    assert metrics.average_stack_bb is None

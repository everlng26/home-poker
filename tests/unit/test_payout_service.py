import pytest

from app.models.tournament import TournamentPayout
from app.services import DomainError, PayoutService


def payout(place: int, percentage_basis_points: int) -> TournamentPayout:
    return TournamentPayout(place=place, percentage_basis_points=percentage_basis_points)


def test_payout_percentages_must_total_exactly_one_hundred_percent() -> None:
    assert PayoutService.normalize_percentages([50, 30, 20]) == [5000, 3000, 2000]
    assert PayoutService.normalize_percentages(["33.33", "33.33", "33.34"]) == [3333, 3333, 3334]

    with pytest.raises(DomainError) as error:
        PayoutService.normalize_percentages([50, 30, 19])
    assert error.value.code == "invalid_payout_total"

    with pytest.raises(DomainError) as precision_error:
        PayoutService.normalize_percentages(["33.333", "66.667"])
    assert precision_error.value.code == "invalid_payout_percentage"


def test_payout_rounding_residual_goes_to_first_place() -> None:
    lines = PayoutService.calculate(
        10_001,
        [payout(1, 3333), payout(2, 3333), payout(3, 3334)],
    )

    assert [line.amount for line in lines] == [3334, 3333, 3334]
    assert sum(line.amount for line in lines) == 10_001


def test_winner_takes_all_equals_entire_prize_pool() -> None:
    lines = PayoutService.calculate(7_003, [payout(1, 10_000)])

    assert [(line.place, line.amount) for line in lines] == [(1, 7_003)]

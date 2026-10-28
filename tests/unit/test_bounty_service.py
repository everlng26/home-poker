import pytest

from app.models.enums import BountyMode
from app.services.bounty_service import BountyService
from app.services.errors import DomainError


def test_none_mode_has_no_bounty() -> None:
    assert BountyService.validate_configuration("none", 300, 1_000) == (BountyMode.NONE, 0)


def test_fixed_mode_requires_positive_bounty_below_buy_in() -> None:
    assert BountyService.validate_configuration("fixed", 300, 1_000) == (BountyMode.FIXED, 300)
    for amount in (0, 1_000, 1_500):
        with pytest.raises(DomainError) as error:
            BountyService.validate_configuration("fixed", amount, 1_000)
        assert error.value.code == "invalid_bounty_amount"


def test_freeroll_cannot_be_fixed_bounty() -> None:
    with pytest.raises(DomainError) as error:
        BountyService.validate_configuration("fixed", 300, 0, is_freeroll=True)
    assert error.value.code == "freeroll_bounty_conflict"

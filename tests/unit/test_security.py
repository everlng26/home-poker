import pytest

from app.security import hash_pin, verify_pin


def test_pin_is_salted_and_verifiable() -> None:
    stored_hash = hash_pin("1234")

    assert stored_hash.startswith("scrypt$")
    assert verify_pin("1234", stored_hash)
    assert not verify_pin("4321", stored_hash)


def test_invalid_pin_is_rejected() -> None:
    with pytest.raises(ValueError):
        hash_pin("12")

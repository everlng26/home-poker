import base64

import pytest

from app.security import hash_pin, read_session, sign_session, verify_pin


def test_pin_is_salted_and_verifiable() -> None:
    stored_hash = hash_pin("1234")

    assert stored_hash.startswith("scrypt$")
    assert verify_pin("1234", stored_hash)
    assert not verify_pin("4321", stored_hash)


def test_invalid_pin_is_rejected() -> None:
    with pytest.raises(ValueError):
        hash_pin("12")

def test_session_round_trip_when_signature_contains_dot() -> None:
    secret = b"session-test-secret"
    raw = base64.urlsafe_b64decode(sign_session(3, secret))
    assert b"." in raw[-32:]

    assert read_session(sign_session(3, secret), secret) == 3


def test_session_round_trip_for_many_tournaments() -> None:
    secret = b"another-local-secret"
    assert all(read_session(sign_session(tournament_id, secret), secret) == tournament_id for tournament_id in range(1, 500))


def test_session_rejects_tampered_and_foreign_cookies() -> None:
    secret = b"session-test-secret"
    cookie = sign_session(3, secret)
    forged = base64.urlsafe_b64encode(base64.urlsafe_b64decode(cookie).replace(b'"tournament_id":3', b'"tournament_id":4')).decode()

    assert read_session(forged, secret) is None
    assert read_session(cookie, b"other-secret") is None
    assert read_session("not-base64", secret) is None
    assert read_session(None, secret) is None

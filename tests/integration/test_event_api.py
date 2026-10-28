from starlette.requests import Request

from app import main
from app.routers.api import events
from app.security import sign_session
from app.services import PlayerService, TournamentService
from app.models.enums import TournamentPlayerStatus, TournamentStatus


def test_event_feed_includes_player_name(session) -> None:
    tournament = TournamentService.create_tournament(
        session,
        name="Журнал",
        buy_in_amount=100,
        currency_label="₽",
        starting_stack=1_000,
        admin_pin_hash="hash",
    )
    player = PlayerService.create_player(session, "Анна")
    entry = PlayerService.register_player(session, tournament.id, player.id)
    with session.begin():
        tournament.status = TournamentStatus.RUNNING
        entry.status = TournamentPlayerStatus.ACTIVE
    PlayerService.eliminate_player(session, entry.id)
    PlayerService.add_reentry(session, entry.id)

    secret = b"event-test-secret"
    main.app.state.app_secret = secret
    cookie = f"poker_admin={sign_session(tournament.id, secret)}".encode()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/v1/tournaments/{tournament.id}/events",
            "headers": [(b"cookie", cookie)],
            "app": main.app,
        }
    )

    feed = events(tournament.id, request, session)

    assert any(item["type"] == "player_registered" and item["player_name"] == "Анна" for item in feed)
    assert any(item["type"] == "reentry_added" and item["player_name"] == "Анна" for item in feed)

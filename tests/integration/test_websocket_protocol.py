import asyncio

from app.services import TournamentService
from app.websocket.manager import TournamentConnectionManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)


def test_connection_receives_complete_state_snapshot(session, monkeypatch) -> None:
    tournament = TournamentService.create_tournament(
        session,
        name="WS",
        buy_in_amount=100,
        currency_label="₽",
        starting_stack=1_000,
        admin_pin_hash="hash",
    )
    monkeypatch.setattr("app.websocket.manager.SessionLocal", lambda: session)
    manager = TournamentConnectionManager()
    socket = FakeWebSocket()

    asyncio.run(manager.connect(tournament.id, socket))

    assert socket.accepted
    assert socket.messages[0]["protocol_version"] == 1
    assert socket.messages[0]["type"] == "state_snapshot"
    assert socket.messages[0]["payload"]["id"] == tournament.id
    assert socket.messages[0]["payload"]["payouts"]["configured"] is False
    assert "public_payout_event" in socket.messages[0]["payload"]

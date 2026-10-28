from datetime import UTC, datetime

from starlette.requests import Request

from app import main
from app.routers.api import admin_session
from app.security import sign_session
from app.services import PlayerService, TournamentService
from app.services.setup_service import TournamentSetupService
from app.services.timer_service import TimerService


def create(session, name: str, **options):
    return TournamentSetupService.create(
        session,
        name=name,
        buy_in_amount=options.pop("buy_in_amount", 2_000),
        currency_label="₽",
        starting_stack=20_000,
        admin_pin_hash="hash",
        levels=[
            {"kind": "play", "small_blind": 25, "big_blind": 50, "ante": 50, "duration_seconds": 900},
            {"kind": "break", "duration_seconds": 600},
            {"kind": "play", "small_blind": 50, "big_blind": 100, "ante": 100, "duration_seconds": 900},
        ],
        late_registration_end_level_number=1,
        **options,
    )


def test_tournament_summaries_describe_each_game(session) -> None:
    draft = create(session, "Подготовка", player_names=["Анна", "Борис", "Вера"])
    running = create(session, "Баунти", player_names=["Гоша", "Дина"], bounty_mode="fixed", bounty_amount=500)
    TimerService.command(session, running.id, "resume", now=datetime(2026, 10, 28, 19, 0, tzinfo=UTC))
    entries = {entry.player.name: entry.id for entry in running.players}
    session.rollback()
    PlayerService.eliminate_player(session, entries["Гоша"], killer_tournament_player_id=entries["Дина"])
    freeroll = create(session, "Фриролл", buy_in_amount=0, is_freeroll=True)

    summaries = {item["id"]: item for item in TournamentService.list_summaries(session)}

    assert [item["id"] for item in TournamentService.list_summaries(session)] == [freeroll.id, running.id, draft.id]
    assert summaries[draft.id] | {"created_at": None} == {
        "id": draft.id,
        "name": "Подготовка",
        "status": "draft",
        "timer_status": "paused",
        "buy_in_amount": 2_000,
        "currency_label": "₽",
        "is_freeroll": False,
        "bounty_mode": "none",
        "bounty_amount": 0,
        "registered_players": 3,
        "active_players": 0,
        "current_level_kind": "play",
        "current_level_number": 1,
        "created_at": None,
    }
    assert summaries[running.id]["status"] == "running"
    assert summaries[running.id]["bounty_mode"] == "fixed"
    assert summaries[running.id]["bounty_amount"] == 500
    assert summaries[running.id]["registered_players"] == 2
    assert summaries[running.id]["active_players"] == 1
    assert summaries[freeroll.id]["is_freeroll"] is True


def test_summary_numbers_play_levels_and_skips_breaks(session) -> None:
    tournament_id = create(session, "Перерыв").id
    started = datetime(2026, 10, 28, 19, 0, tzinfo=UTC)
    TimerService.command(session, tournament_id, "resume", now=started)
    TimerService.command(session, tournament_id, "next", now=started)

    summary = TournamentService.list_summaries(session)[0]
    session.rollback()
    assert summary["current_level_kind"] == "break"
    assert summary["current_level_number"] is None

    TimerService.command(session, tournament_id, "next", now=started)
    summary = TournamentService.list_summaries(session)[0]
    assert summary["current_level_kind"] == "play"
    assert summary["current_level_number"] == 2


def session_request(tournament_id: int, cookie_tournament_id: int | None, secret: bytes) -> Request:
    headers = []
    if cookie_tournament_id is not None:
        headers.append((b"cookie", f"poker_admin={sign_session(cookie_tournament_id, secret)}".encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/v1/tournaments/{tournament_id}/session",
            "headers": headers,
            "app": main.app,
        }
    )


def test_admin_session_reports_only_the_signed_tournament() -> None:
    secret = b"session-test-secret"
    main.app.state.app_secret = secret

    assert admin_session(3, session_request(3, 3, secret)) == {"authenticated": True}
    assert admin_session(3, session_request(3, 4, secret)) == {"authenticated": False}
    assert admin_session(3, session_request(3, None, secret)) == {"authenticated": False}

"""Сквозная проверка главного сценария в отдельной временной SQLite-базе."""

from datetime import UTC, datetime, timedelta

from app.models.enums import BlindLevelKind, TournamentPlayerStatus
from app.models.tournament import BlindLevel
from app.services import CalculationService, EventService, PlayerService, TournamentService
from app.services.level_service import LevelService
from app.services.timer_service import TimerService


def test_home_tournament_acceptance_flow(session) -> None:
    tournament = TournamentService.create_tournament(
        session,
        name="Приёмочный турнир",
        buy_in_amount=1_000,
        currency_label="₽",
        starting_stack=20_000,
        max_reentries_per_player=2,
        admin_pin_hash="test-hash",
    )
    LevelService.replace_levels(
        session,
        tournament.id,
        [
            {"kind": "play", "small_blind": 25, "big_blind": 50, "ante": 0, "duration_seconds": 900},
            {"kind": "play", "small_blind": 50, "big_blind": 100, "ante": 0, "duration_seconds": 900},
            {"kind": "play", "small_blind": 75, "big_blind": 150, "ante": 25, "duration_seconds": 900},
            {"kind": "break", "duration_seconds": 600, "title": "Перерыв"},
        ],
        late_registration_end_level_index=1,
    )
    players = [PlayerService.create_player(session, name) for name in ("Анна", "Борис")]
    entries = [PlayerService.register_player(session, tournament.id, player.id) for player in players]

    started_at = datetime(2026, 8, 6, 18, 0, tzinfo=UTC)
    TimerService.command(session, tournament.id, "resume", now=started_at)
    assert all(entry.status == TournamentPlayerStatus.ACTIVE for entry in entries)

    TimerService.command(session, tournament.id, "pause", now=started_at + timedelta(seconds=120))
    assert tournament.paused_remaining_seconds == 780
    TimerService.command(session, tournament.id, "resume", now=started_at + timedelta(seconds=180))
    TimerService.command(session, tournament.id, "next", now=started_at + timedelta(seconds=181))

    PlayerService.eliminate_player(session, entries[0].id, request_id="eliminate")
    PlayerService.add_reentry(session, entries[0].id, request_id="reentry")

    current_level = BlindLevel(
        order_index=1,
        kind=BlindLevelKind.PLAY,
        small_blind=50,
        big_blind=100,
        ante=0,
        duration_seconds=900,
    )
    metrics = CalculationService.calculate(tournament, entries, current_level)
    assert metrics.total_entries == 3
    assert metrics.prize_pool == 3_000
    assert metrics.total_chips_in_play == 60_000
    assert metrics.active_players == 2

    EventService.undo_last(session, tournament.id, request_id="undo-reentry")
    assert entries[0].status == TournamentPlayerStatus.ELIMINATED
    assert entries[0].entries_count == 1

    PlayerService.mark_out(session, entries[0].id, request_id="out")
    assert entries[0].status == TournamentPlayerStatus.OUT

    session.expunge_all()
    restored = session.get(type(tournament), tournament.id)
    restored_entry = session.get(type(entries[0]), entries[0].id)
    assert restored is not None and restored.current_level_index == 1
    assert restored_entry is not None and restored_entry.status == TournamentPlayerStatus.OUT

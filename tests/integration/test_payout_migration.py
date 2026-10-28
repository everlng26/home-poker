from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_upgrade_from_v1_preserves_tournament_players_and_events(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "home-poker-v1.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("POKER_DATABASE_URL", database_url)
    config = Config("alembic.ini")

    command.upgrade(config, "2026081001")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tournaments (
                    id, name, buy_in_amount, currency_label, starting_stack,
                    max_reentries_per_player, ante_enabled, status,
                    is_manually_finished, current_level_index,
                    late_registration_end_level_index, timer_status,
                    auto_advance_levels, admin_pin_hash, state_version,
                    created_at, updated_at
                ) VALUES (
                    7, 'Существующий турнир', 1000, '₽', 20000,
                    2, 1, 'paused', 0, 0, NULL, 'paused',
                    1, 'legacy-hash', 3,
                    '2026-08-12 18:00:00', '2026-08-12 18:00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO players (id, name, created_at, updated_at)
                VALUES (11, 'Анна', '2026-08-12 18:00:00', '2026-08-12 18:00:00')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO tournament_players (
                    id, tournament_id, player_id, status, entries_count, registered_at
                ) VALUES (13, 7, 11, 'active', 2, '2026-08-12 18:00:00')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO tournament_events (
                    id, tournament_id, event_type, payload_json, is_reversible, created_at
                ) VALUES (17, 7, 'reentry_added', '{}', 0, '2026-08-12 18:10:00')
                """
            )
        )

    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "tournament_payouts" in inspector.get_table_names()
    assert "payouts_finalized_at" in {column["name"] for column in inspector.get_columns("tournaments")}
    assert {"bounty_mode", "bounty_amount"}.issubset(
        {column["name"] for column in inspector.get_columns("tournaments")}
    )
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name FROM tournaments WHERE id = 7")).scalar_one() == "Существующий турнир"
        assert connection.execute(
            text("SELECT entries_count FROM tournament_players WHERE id = 13")
        ).scalar_one() == 2
        assert connection.execute(
            text("SELECT event_type FROM tournament_events WHERE id = 17")
        ).scalar_one() == "reentry_added"
        assert connection.execute(text("SELECT COUNT(*) FROM tournament_payouts")).scalar_one() == 0
        assert connection.execute(
            text("SELECT bounty_mode, bounty_amount FROM tournaments WHERE id = 7")
        ).one() == ("none", 0)

    command.downgrade(config, "2026081301")

    downgraded_inspector = inspect(engine)
    downgraded_columns = {
        column["name"] for column in downgraded_inspector.get_columns("tournaments")
    }
    assert "bounty_mode" not in downgraded_columns
    assert "bounty_amount" not in downgraded_columns
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT name FROM tournaments WHERE id = 7")
        ).scalar_one() == "Существующий турнир"
        assert connection.execute(
            text("SELECT entries_count FROM tournament_players WHERE id = 13")
        ).scalar_one() == 2

    command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT bounty_mode, bounty_amount FROM tournaments WHERE id = 7")
        ).one() == ("none", 0)
    engine.dispose()

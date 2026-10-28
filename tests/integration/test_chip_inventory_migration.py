from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_chip_inventory_migration_is_local_and_cascades(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "home-poker-before-chip-inventory.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("POKER_DATABASE_URL", database_url)
    config = Config("alembic.ini")

    command.upgrade(config, "2026081302")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tournaments (
                    id, name, buy_in_amount, bounty_mode, bounty_amount, currency_label,
                    starting_stack, ante_enabled, status, is_manually_finished,
                    current_level_index, timer_status, auto_advance_levels,
                    admin_pin_hash, state_version, created_at, updated_at
                ) VALUES (
                    1, 'Существующий турнир', 1000, 'none', 0, '₽',
                    20000, 1, 'paused', 0, 0, 'paused', 1,
                    'hash', 0, '2026-08-14 00:00:00', '2026-08-14 00:00:00'
                )
                """
            )
        )

    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert {"chip_sets", "chip_denominations"}.issubset(inspector.get_table_names())
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(
            text(
                "INSERT INTO chip_sets (id, name, created_at, updated_at) "
                "VALUES (10, 'Кейс', '2026-08-14 00:00:00', '2026-08-14 00:00:00')"
            )
        )
        connection.execute(
            text("INSERT INTO chip_denominations (chip_set_id, value, quantity) VALUES (10, 25, 100)")
        )
        connection.execute(text("DELETE FROM chip_sets WHERE id = 10"))
        assert connection.execute(text("SELECT COUNT(*) FROM chip_denominations")).scalar_one() == 0
        assert connection.execute(text("SELECT name FROM tournaments WHERE id = 1")).scalar_one() == "Существующий турнир"

    command.downgrade(config, "2026081302")
    downgraded = inspect(engine)
    assert "chip_sets" not in downgraded.get_table_names()
    assert "chip_denominations" not in downgraded.get_table_names()
    assert "tournaments" in downgraded.get_table_names()
    engine.dispose()

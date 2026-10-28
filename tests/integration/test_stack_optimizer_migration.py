import json

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_chip_plan_migration_preserves_snapshots_without_chip_set_foreign_key(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "home-poker-before-stack-optimizer.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("POKER_DATABASE_URL", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "2026081401")
    engine = create_engine(database_url)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tournaments (
                    id, name, buy_in_amount, bounty_mode, bounty_amount, currency_label,
                    starting_stack, max_reentries_per_player, ante_enabled, status,
                    is_manually_finished, current_level_index, timer_status,
                    auto_advance_levels, admin_pin_hash, state_version, created_at, updated_at
                ) VALUES (
                    1, 'План', 1000, 'none', 0, '₽', 20000, 2, 1, 'paused',
                    0, 0, 'paused', 1, 'hash', 0,
                    '2026-08-14 00:00:00', '2026-08-14 00:00:00'
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO chip_sets (id, name, created_at, updated_at) "
                "VALUES (10, 'Кейс', '2026-08-14 00:00:00', '2026-08-14 00:00:00')"
            )
        )
    command.upgrade(config, "head")

    assert "tournament_chip_plans" in inspect(engine).get_table_names()
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        payload = {
            "sets": json.dumps([{"id": 10, "name": "Кейс"}]),
            "inventory": json.dumps([{"value": 1000, "quantity": 480}]),
            "initial": json.dumps([{"value": 1000, "quantity": 20}]),
            "reentry": json.dumps([{"value": 1000, "quantity": 20}]),
            "reserved": json.dumps([{"value": 1000, "quantity": 480}]),
            "remaining": json.dumps([{"value": 1000, "quantity": 0}]),
        }
        connection.execute(
            text(
                """
                INSERT INTO tournament_chip_plans (
                    tournament_id, selected_chip_sets_json, combined_inventory_json,
                    planned_players, starting_stack, max_reentries_per_player,
                    max_total_reentries, covered_reentries, initial_distribution_json,
                    reentry_distribution_json, reserved_quantities_json,
                    remaining_inventory_json, created_at
                ) VALUES (
                    1, :sets, :inventory, 8, 20000, 2, 16, 16,
                    :initial, :reentry, :reserved, :remaining, '2026-08-14 00:00:00'
                )
                """
            ),
            payload,
        )
        connection.execute(text("DELETE FROM chip_sets WHERE id = 10"))
        assert connection.execute(text("SELECT covered_reentries FROM tournament_chip_plans")).scalar_one() == 16
        connection.execute(text("DELETE FROM tournaments WHERE id = 1"))
        assert connection.execute(text("SELECT COUNT(*) FROM tournament_chip_plans")).scalar_one() == 0

    command.downgrade(config, "2026081401")
    assert "tournament_chip_plans" not in inspect(engine).get_table_names()
    engine.dispose()

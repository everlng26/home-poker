"""add tournament chip plan snapshots

Revision ID: 2026081402
Revises: 2026081401
Create Date: 2026-08-14 04:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2026081402"
down_revision: Union[str, Sequence[str], None] = "2026081401"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tournament_chip_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("selected_chip_sets_json", sa.JSON(), nullable=False),
        sa.Column("combined_inventory_json", sa.JSON(), nullable=False),
        sa.Column("planned_players", sa.Integer(), nullable=False),
        sa.Column("starting_stack", sa.Integer(), nullable=False),
        sa.Column("max_reentries_per_player", sa.Integer(), nullable=False),
        sa.Column("max_total_reentries", sa.Integer(), nullable=False),
        sa.Column("covered_reentries", sa.Integer(), nullable=False),
        sa.Column("initial_distribution_json", sa.JSON(), nullable=False),
        sa.Column("reentry_distribution_json", sa.JSON(), nullable=False),
        sa.Column("reserved_quantities_json", sa.JSON(), nullable=False),
        sa.Column("remaining_inventory_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("planned_players > 0", name="ck_tournament_chip_plans_players_positive"),
        sa.CheckConstraint("starting_stack > 0", name="ck_tournament_chip_plans_stack_positive"),
        sa.CheckConstraint(
            "max_reentries_per_player >= 0",
            name="ck_tournament_chip_plans_reentry_limit_nonnegative",
        ),
        sa.CheckConstraint(
            "max_total_reentries = planned_players * max_reentries_per_player",
            name="ck_tournament_chip_plans_max_reentries_consistent",
        ),
        sa.CheckConstraint(
            "covered_reentries >= 0 AND covered_reentries <= max_total_reentries",
            name="ck_tournament_chip_plans_coverage_range",
        ),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tournament_id"),
    )
    op.create_index(
        op.f("ix_tournament_chip_plans_tournament_id"),
        "tournament_chip_plans",
        ["tournament_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tournament_chip_plans_tournament_id"), table_name="tournament_chip_plans")
    op.drop_table("tournament_chip_plans")

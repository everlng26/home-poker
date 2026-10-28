"""add payout structure and registration finalization

Revision ID: 2026081301
Revises: 2026081001
Create Date: 2026-08-13 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2026081301"
down_revision: Union[str, Sequence[str], None] = "2026081001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.add_column(sa.Column("payouts_finalized_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "tournament_payouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("place", sa.Integer(), nullable=False),
        sa.Column("percentage_basis_points", sa.Integer(), nullable=False),
        sa.CheckConstraint("place > 0", name="ck_tournament_payouts_place_positive"),
        sa.CheckConstraint(
            "percentage_basis_points > 0 AND percentage_basis_points <= 10000",
            name="ck_tournament_payouts_percentage_range",
        ),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tournament_id", "place", name="uq_tournament_payouts_tournament_place"),
    )
    op.create_index(
        op.f("ix_tournament_payouts_tournament_id"),
        "tournament_payouts",
        ["tournament_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tournament_payouts_tournament_id"), table_name="tournament_payouts")
    op.drop_table("tournament_payouts")
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_column("payouts_finalized_at")

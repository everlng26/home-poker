"""add late registration cutoff to tournaments

Revision ID: 2026080603
Revises: 2026080602
Create Date: 2026-08-06 23:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2026080603"
down_revision: Union[str, Sequence[str], None] = "2026080602"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.add_column(sa.Column("late_registration_end_level_index", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "ck_tournaments_late_registration_end_nonnegative",
            "late_registration_end_level_index IS NULL OR late_registration_end_level_index >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_constraint("ck_tournaments_late_registration_end_nonnegative", type_="check")
        batch_op.drop_column("late_registration_end_level_index")

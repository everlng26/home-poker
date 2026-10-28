"""add manual tournament finish lock

Revision ID: 2026081001
Revises: 2026080904
Create Date: 2026-08-10 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2026081001"
down_revision: Union[str, Sequence[str], None] = "2026080904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.add_column(
            sa.Column("is_manually_finished", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_column("is_manually_finished")

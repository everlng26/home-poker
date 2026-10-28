"""add fixed bounty configuration

Revision ID: 2026081302
Revises: 2026081301
Create Date: 2026-08-13 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2026081302"
down_revision: Union[str, Sequence[str], None] = "2026081301"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bounty_mode_enum = sa.Enum(
        "none",
        "fixed",
        name="bountymode",
        native_enum=False,
        create_constraint=True,
    )
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.add_column(
            sa.Column("bounty_mode", bounty_mode_enum, server_default="none", nullable=False)
        )
        batch_op.add_column(
            sa.Column("bounty_amount", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.create_check_constraint(
            "ck_tournaments_bounty_configuration",
            "(bounty_mode = 'none' AND bounty_amount = 0) OR "
            "(bounty_mode = 'fixed' AND bounty_amount > 0 AND bounty_amount < buy_in_amount)",
        )


def downgrade() -> None:
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.drop_constraint("ck_tournaments_bounty_configuration", type_="check")
        batch_op.drop_constraint("bountymode", type_="check")
        batch_op.drop_column("bounty_amount")
        batch_op.drop_column("bounty_mode")

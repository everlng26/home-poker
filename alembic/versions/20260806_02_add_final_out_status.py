"""add final out status to tournament players

Revision ID: 2026080602
Revises: 8f2f51ad671f
Create Date: 2026-08-06 21:40:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2026080602"
down_revision: Union[str, Sequence[str], None] = "8f2f51ad671f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    old_status = sa.Enum(
        "registered", "active", "eliminated", name="tournamentplayerstatus", native_enum=False, create_constraint=True
    )
    new_status = sa.Enum(
        "registered", "active", "eliminated", "out", name="tournamentplayerstatus", native_enum=False, create_constraint=True
    )
    with op.batch_alter_table("tournament_players", recreate="always") as batch_op:
        batch_op.alter_column("status", existing_type=old_status, type_=new_status, existing_nullable=False)
    op.execute("UPDATE tournament_events SET is_reversible = 0 WHERE event_type = 'player_eliminated'")


def downgrade() -> None:
    old_status = sa.Enum(
        "registered", "active", "eliminated", name="tournamentplayerstatus", native_enum=False, create_constraint=True
    )
    new_status = sa.Enum(
        "registered", "active", "eliminated", "out", name="tournamentplayerstatus", native_enum=False, create_constraint=True
    )
    with op.batch_alter_table("tournament_players", recreate="always") as batch_op:
        batch_op.alter_column("status", existing_type=new_status, type_=old_status, existing_nullable=False)

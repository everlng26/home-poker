"""add physical chip inventory

Revision ID: 2026081401
Revises: 2026081302
Create Date: 2026-08-14 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2026081401"
down_revision: Union[str, Sequence[str], None] = "2026081302"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chip_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "chip_denominations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chip_set_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity >= 0", name="ck_chip_denominations_quantity_nonnegative"),
        sa.CheckConstraint("value > 0", name="ck_chip_denominations_value_positive"),
        sa.ForeignKeyConstraint(["chip_set_id"], ["chip_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chip_set_id", "value", name="uq_chip_denominations_chip_set_value"),
    )
    op.create_index(
        op.f("ix_chip_denominations_chip_set_id"),
        "chip_denominations",
        ["chip_set_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chip_denominations_chip_set_id"), table_name="chip_denominations")
    op.drop_table("chip_denominations")
    op.drop_table("chip_sets")

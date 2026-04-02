"""observability: latency, tokens, observability_json

Revision ID: 002
Revises: 001
Create Date: 2026-04-01

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("total_input_tokens", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("total_output_tokens", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("observability_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "observability_json")
    op.drop_column("tasks", "total_output_tokens")
    op.drop_column("tasks", "total_input_tokens")
    op.drop_column("tasks", "latency_ms")

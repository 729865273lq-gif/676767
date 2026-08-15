"""Add lead association and attachment count to inbound messages.

Revision ID: 0026_inbox_lead
Revises: 0025_inbox_uidvalidity
Create Date: 2026-08-15 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_inbox_lead"
down_revision: str | None = "0025_inbox_uidvalidity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("inbound_messages") as batch_op:
        batch_op.add_column(sa.Column("lead_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column("attachments_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.create_index("ix_inbound_messages_lead_id", ["lead_id"])
        batch_op.create_foreign_key(
            "fk_inbound_messages_lead_id",
            "leads",
            ["lead_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("inbound_messages") as batch_op:
        batch_op.drop_constraint("fk_inbound_messages_lead_id", type_="foreignkey")
        batch_op.drop_index("ix_inbound_messages_lead_id")
        batch_op.drop_column("attachments_count")
        batch_op.drop_column("lead_id")

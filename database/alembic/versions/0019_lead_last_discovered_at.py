"""Track when a lead was most recently discovered.

Revision ID: 0019_lead_last_discovered_at
Revises: 0018_normalize_lead_status
Create Date: 2026-08-11 18:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_lead_last_discovered_at"
down_revision: str | None = "0018_normalize_lead_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("last_discovered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE leads SET last_discovered_at = created_at")
    with op.batch_alter_table("leads") as batch_op:
        batch_op.alter_column(
            "last_discovered_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
    op.create_index("ix_leads_last_discovered_at", "leads", ["last_discovered_at"])


def downgrade() -> None:
    op.drop_index("ix_leads_last_discovered_at", table_name="leads")
    with op.batch_alter_table("leads") as batch_op:
        batch_op.drop_column("last_discovered_at")

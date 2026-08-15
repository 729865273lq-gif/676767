"""Track IMAP UIDVALIDITY so a rebuilt mailbox triggers a full rescan.

Revision ID: 0025_inbox_uidvalidity
Revises: 0024_inbox
Create Date: 2026-08-15 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_inbox_uidvalidity"
down_revision: str | None = "0024_inbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mailbox_cursors", sa.Column("uidvalidity", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("mailbox_cursors", "uidvalidity")

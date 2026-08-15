"""Add IMAP mailbox cursors and inbound reply messages.

Revision ID: 0024_inbox
Revises: 0023_knowledge
Create Date: 2026-08-15 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_inbox"
down_revision: str | None = "0023_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mailbox_cursors",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("mailbox", sa.String(length=120), nullable=False),
        sa.Column("last_uid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id", "mailbox"),
    )

    op.create_table(
        "inbound_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("sender_email", sa.String(length=320), nullable=False, server_default=""),
        sa.Column("sender_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("subject", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("intent", sa.String(length=30), nullable=False, server_default="other"),
        sa.Column("intent_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("analysis_rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("suggested_reply", sa.Text(), nullable=False, server_default=""),
        sa.Column("follow_up_task_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["follow_up_task_id"], ["follow_up_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "provider_message_id", name="uq_inbound_message_provider"),
    )
    op.create_index(
        "ix_inbound_messages_organization_id", "inbound_messages", ["organization_id"]
    )
    op.create_index("ix_inbound_messages_intent", "inbound_messages", ["intent"])


def downgrade() -> None:
    op.drop_index("ix_inbound_messages_intent", table_name="inbound_messages")
    op.drop_index("ix_inbound_messages_organization_id", table_name="inbound_messages")
    op.drop_table("inbound_messages")
    op.drop_table("mailbox_cursors")

"""Add email sent state tracking.

Revision ID: 0009_email_sent_state
Revises: 0008_email_drafts
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_email_sent_state"
down_revision = "0008_email_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("email_drafts") as batch_op:
        batch_op.add_column(sa.Column("sent_by_user_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_email_drafts_sent_by_user_id", ["sent_by_user_id"])
        batch_op.create_foreign_key(
            "fk_email_drafts_sent_by_user_id_users",
            "users",
            ["sent_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("email_drafts") as batch_op:
        batch_op.drop_constraint("fk_email_drafts_sent_by_user_id_users", type_="foreignkey")
        batch_op.drop_index("ix_email_drafts_sent_by_user_id")
        batch_op.drop_column("sent_at")
        batch_op.drop_column("sent_by_user_id")

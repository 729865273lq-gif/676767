"""Add follow-up tasks for CRM execution.

Revision ID: 0012_follow_up_tasks
Revises: 0011_product_items
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_follow_up_tasks"
down_revision = "0011_product_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "follow_up_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("task_type", sa.String(length=50), nullable=False, server_default="follow_up"),
        sa.Column("quote_status", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_follow_up_tasks_actor_user_id", "follow_up_tasks", ["actor_user_id"])
    op.create_index("ix_follow_up_tasks_due_at", "follow_up_tasks", ["due_at"])
    op.create_index("ix_follow_up_tasks_lead_id", "follow_up_tasks", ["lead_id"])
    op.create_index("ix_follow_up_tasks_organization_id", "follow_up_tasks", ["organization_id"])
    op.create_index("ix_follow_up_tasks_status", "follow_up_tasks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_follow_up_tasks_status", table_name="follow_up_tasks")
    op.drop_index("ix_follow_up_tasks_organization_id", table_name="follow_up_tasks")
    op.drop_index("ix_follow_up_tasks_lead_id", table_name="follow_up_tasks")
    op.drop_index("ix_follow_up_tasks_due_at", table_name="follow_up_tasks")
    op.drop_index("ix_follow_up_tasks_actor_user_id", table_name="follow_up_tasks")
    op.drop_table("follow_up_tasks")

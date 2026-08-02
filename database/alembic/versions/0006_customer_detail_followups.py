"""Add customer detail fields and follow-up records.

Revision ID: 0006_customer_detail_followups
Revises: 0005_password_auth
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_customer_detail_followups"
down_revision = "0005_password_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("leads") as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(length=30), nullable=False, server_default="new"))
        batch_op.add_column(sa.Column("owner_user_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("notes", sa.String(length=4000), nullable=False, server_default=""))
        batch_op.create_index("ix_leads_owner_user_id", ["owner_user_id"])
        batch_op.create_foreign_key(
            "fk_leads_owner_user_id_users",
            "users",
            ["owner_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_table(
        "follow_up_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("activity_type", sa.String(length=50), nullable=False),
        sa.Column("content", sa.String(length=4000), nullable=False),
        sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_follow_up_records_actor_user_id", "follow_up_records", ["actor_user_id"])
    op.create_index("ix_follow_up_records_lead_id", "follow_up_records", ["lead_id"])
    op.create_index("ix_follow_up_records_organization_id", "follow_up_records", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_follow_up_records_organization_id", table_name="follow_up_records")
    op.drop_index("ix_follow_up_records_lead_id", table_name="follow_up_records")
    op.drop_index("ix_follow_up_records_actor_user_id", table_name="follow_up_records")
    op.drop_table("follow_up_records")
    with op.batch_alter_table("leads") as batch_op:
        batch_op.drop_constraint("fk_leads_owner_user_id_users", type_="foreignkey")
        batch_op.drop_index("ix_leads_owner_user_id")
        batch_op.drop_column("notes")
        batch_op.drop_column("owner_user_id")
        batch_op.drop_column("status")

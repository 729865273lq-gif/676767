"""Create durable workflow runs and steps.

Revision ID: 0002_workflow
Revises: 0001_platform
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_workflow"
down_revision = "0001_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    workflow_state = sa.Enum(
        "queued",
        "running",
        "waiting_for_human",
        "completed",
        "failed",
        name="workflowstate",
        native_enum=False,
        length=30,
    )
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=100), nullable=False),
        sa.Column("agent_version", sa.String(length=50), nullable=False),
        sa.Column("state", workflow_state, nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.String(length=500), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_workflow_run_idempotency"),
    )
    op.create_index("ix_workflow_runs_organization_id", "workflow_runs", ["organization_id"])
    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("agent_id", sa.String(length=100), nullable=False),
        sa.Column("agent_version", sa.String(length=50), nullable=False),
        sa.Column("state", workflow_state, nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_run_id", "sequence", name="uq_workflow_step_sequence"),
    )
    op.create_index("ix_workflow_steps_organization_id", "workflow_steps", ["organization_id"])
    op.create_index("ix_workflow_steps_workflow_run_id", "workflow_steps", ["workflow_run_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_steps_workflow_run_id", table_name="workflow_steps")
    op.drop_index("ix_workflow_steps_organization_id", table_name="workflow_steps")
    op.drop_table("workflow_steps")
    op.drop_index("ix_workflow_runs_organization_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")

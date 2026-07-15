"""Create evidence-backed discovery leads.

Revision ID: 0004_discovery_leads
Revises: 0003_product_lines
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_discovery_leads"
down_revision = "0003_product_lines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    lead_bucket = sa.Enum(
        "priority_recommendation",
        "needs_enrichment",
        "not_qualified",
        name="leadbucket",
        native_enum=False,
        length=30,
    )
    op.create_table(
        "leads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=False),
        sa.Column("product_line_id", sa.String(length=36), nullable=False),
        sa.Column("company_name", sa.String(length=300), nullable=False),
        sa.Column("website", sa.String(length=1000), nullable=False),
        sa.Column("canonical_domain", sa.String(length=253), nullable=False),
        sa.Column("target_market", sa.String(length=120), nullable=False),
        sa.Column("buyer_profile", sa.String(length=200), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("bucket", lead_bucket, nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("missing_signals", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_line_id"], ["product_lines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "canonical_domain", name="uq_lead_domain"),
    )
    op.create_index("ix_leads_organization_id", "leads", ["organization_id"])
    op.create_index("ix_leads_workflow_run_id", "leads", ["workflow_run_id"])
    op.create_index("ix_leads_product_line_id", "leads", ["product_line_id"])
    op.create_table(
        "lead_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("source_excerpt", sa.String(length=4000), nullable=False),
        sa.Column("signal_name", sa.String(length=100), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_evidence_lead_id", "lead_evidence", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_lead_evidence_lead_id", table_name="lead_evidence")
    op.drop_table("lead_evidence")
    op.drop_index("ix_leads_product_line_id", table_name="leads")
    op.drop_index("ix_leads_workflow_run_id", table_name="leads")
    op.drop_index("ix_leads_organization_id", table_name="leads")
    op.drop_table("leads")

"""Add local password authentication.

Revision ID: 0005_password_auth
Revises: 0004_discovery_leads
"""
from alembic import op
import sqlalchemy as sa
revision = "0005_password_auth"
down_revision = "0004_discovery_leads"
branch_labels = None
depends_on = None
def upgrade() -> None: op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
def downgrade() -> None: op.drop_column("users", "password_hash")

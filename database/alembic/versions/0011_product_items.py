"""Add product items for independent site content.

Revision ID: 0011_product_items
Revises: 0010_website_inquiries
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_product_items"
down_revision = "0010_website_inquiries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("product_line_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("sku", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("summary", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("specs", sa.JSON(), nullable=False),
        sa.Column("image_url", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_line_id"], ["product_lines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_line_id", "name", name="uq_product_item_name"),
    )
    op.create_index("ix_product_items_is_published", "product_items", ["is_published"])
    op.create_index("ix_product_items_organization_id", "product_items", ["organization_id"])
    op.create_index("ix_product_items_product_line_id", "product_items", ["product_line_id"])

    with op.batch_alter_table("website_inquiries") as batch_op:
        batch_op.add_column(sa.Column("product_item_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("product_item_name", sa.String(length=200), nullable=False, server_default=""))
        batch_op.create_index("ix_website_inquiries_product_item_id", ["product_item_id"])
        batch_op.create_foreign_key(
            "fk_website_inquiries_product_item_id_product_items",
            "product_items",
            ["product_item_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("website_inquiries") as batch_op:
        batch_op.drop_constraint("fk_website_inquiries_product_item_id_product_items", type_="foreignkey")
        batch_op.drop_index("ix_website_inquiries_product_item_id")
        batch_op.drop_column("product_item_name")
        batch_op.drop_column("product_item_id")

    op.drop_index("ix_product_items_product_line_id", table_name="product_items")
    op.drop_index("ix_product_items_organization_id", table_name="product_items")
    op.drop_index("ix_product_items_is_published", table_name="product_items")
    op.drop_table("product_items")

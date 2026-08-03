from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.platform.models import ProductItem, ProductLine, ProductSupplier
from app.platform.service import AuditService, OrganizationService


class ProductLineNotFound(LookupError):
    """Raised when a product line is unavailable in the selected organization."""


class ProductItemNotFound(LookupError):
    """Raised when a product item is unavailable in the selected organization."""


class ProductLineService:
    def __init__(self, session: Session):
        self.session = session

    def create_product_line(
        self,
        *,
        actor_user_id: str,
        organization_id: str,
        name: str,
        description: str,
        product_keywords: list[str],
        buyer_profiles: list[str],
        target_regions: list[str],
    ) -> ProductLine:
        OrganizationService(self.session).require_admin(actor_user_id, organization_id)
        product_line = ProductLine(
            organization_id=organization_id,
            name=name.strip(),
            description=description.strip(),
            product_keywords=_normalize_list(product_keywords),
            buyer_profiles=_normalize_list(buyer_profiles),
            target_regions=_normalize_list(target_regions),
        )
        self.session.add(product_line)
        self.session.flush()
        AuditService(self.session).record(
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            event_type="product_line.created",
            metadata={"product_line_id": product_line.id, "name": product_line.name},
        )
        return product_line

    def list_product_lines(self, organization_id: str) -> list[ProductLine]:
        return list(
            self.session.scalars(
                select(ProductLine)
                .where(ProductLine.organization_id == organization_id)
                .order_by(ProductLine.name)
            )
        )

    def get_product_line(self, product_line_id: str, organization_id: str) -> ProductLine:
        product_line = self.session.scalar(
            select(ProductLine).where(
                ProductLine.id == product_line_id,
                ProductLine.organization_id == organization_id,
            )
        )
        if product_line is None:
            raise ProductLineNotFound("product line not found")
        return product_line

    def add_supplier(
        self,
        *,
        actor_user_id: str,
        organization_id: str,
        product_line_id: str,
        name: str,
        website: str | None,
        notes: str,
    ) -> ProductSupplier:
        OrganizationService(self.session).require_admin(actor_user_id, organization_id)
        product_line = self.get_product_line(product_line_id, organization_id)
        supplier = ProductSupplier(
            organization_id=organization_id,
            product_line_id=product_line.id,
            name=name.strip(),
            website=website.strip() if website else None,
            notes=notes.strip(),
        )
        self.session.add(supplier)
        self.session.flush()
        AuditService(self.session).record(
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            event_type="product_supplier.created",
            metadata={"product_line_id": product_line.id, "supplier_id": supplier.id},
        )
        return supplier

    def create_product_item(
        self,
        *,
        actor_user_id: str,
        organization_id: str,
        product_line_id: str,
        name: str,
        sku: str,
        summary: str,
        specs: list[str],
        image_url: str,
        is_published: bool,
    ) -> ProductItem:
        OrganizationService(self.session).require_admin(actor_user_id, organization_id)
        product_line = self.get_product_line(product_line_id, organization_id)
        product_item = ProductItem(
            organization_id=organization_id,
            product_line_id=product_line.id,
            name=name.strip(),
            sku=sku.strip(),
            summary=summary.strip(),
            specs=_normalize_list(specs),
            image_url=image_url.strip(),
            is_published=is_published,
        )
        self.session.add(product_item)
        self.session.flush()
        AuditService(self.session).record(
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            event_type="product_item.created",
            metadata={
                "product_line_id": product_line.id,
                "product_item_id": product_item.id,
                "name": product_item.name,
            },
        )
        return product_item

    def list_product_items(self, organization_id: str, product_line_id: str | None = None) -> list[ProductItem]:
        statement = select(ProductItem).where(ProductItem.organization_id == organization_id)
        if product_line_id is not None:
            statement = statement.where(ProductItem.product_line_id == product_line_id)
        return list(self.session.scalars(statement.order_by(ProductItem.created_at.desc(), ProductItem.name)))

    def get_product_item(
        self,
        product_item_id: str,
        organization_id: str,
        product_line_id: str | None = None,
    ) -> ProductItem:
        statement = select(ProductItem).where(
            ProductItem.id == product_item_id,
            ProductItem.organization_id == organization_id,
        )
        if product_line_id is not None:
            statement = statement.where(ProductItem.product_line_id == product_line_id)
        product_item = self.session.scalar(statement)
        if product_item is None:
            raise ProductItemNotFound("product item not found")
        return product_item

    def delete_product_item(self, *, actor_user_id: str, organization_id: str, product_item_id: str) -> None:
        OrganizationService(self.session).require_admin(actor_user_id, organization_id)
        product_item = self.get_product_item(product_item_id, organization_id)
        self.session.execute(delete(ProductItem).where(ProductItem.id == product_item.id))
        AuditService(self.session).record(
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            event_type="product_item.deleted",
            metadata={"product_line_id": product_item.product_line_id, "product_item_id": product_item.id},
        )

    def supplier_names_by_product_line(self, organization_id: str) -> dict[str, list[str]]:
        rows = self.session.execute(
            select(ProductSupplier.product_line_id, ProductSupplier.name)
            .where(ProductSupplier.organization_id == organization_id)
            .order_by(ProductSupplier.name)
        )
        suppliers: dict[str, list[str]] = {}
        for product_line_id, name in rows:
            suppliers.setdefault(product_line_id, []).append(name)
        return suppliers

    def product_items_by_product_line(self, organization_id: str) -> dict[str, list[ProductItem]]:
        rows = self.session.scalars(
            select(ProductItem)
            .where(ProductItem.organization_id == organization_id)
            .order_by(ProductItem.created_at.desc(), ProductItem.name)
        )
        items: dict[str, list[ProductItem]] = {}
        for product_item in rows:
            items.setdefault(product_item.product_line_id, []).append(product_item)
        return items


def _normalize_list(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))

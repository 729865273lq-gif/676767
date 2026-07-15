from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.models import ProductLine, ProductSupplier
from app.platform.service import AuditService, OrganizationService


class ProductLineNotFound(LookupError):
    """Raised when a product line is unavailable in the selected organization."""


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


def _normalize_list(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))

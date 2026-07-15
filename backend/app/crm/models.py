from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.models import utcnow
from app.shared.db import Base


class LeadBucket(StrEnum):
    PRIORITY_RECOMMENDATION = "priority_recommendation"
    NEEDS_ENRICHMENT = "needs_enrichment"
    NOT_QUALIFIED = "not_qualified"


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("organization_id", "canonical_domain", name="uq_lead_domain"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_line_id: Mapped[str] = mapped_column(
        ForeignKey("product_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_name: Mapped[str] = mapped_column(String(300), nullable=False)
    website: Mapped[str] = mapped_column(String(1_000), nullable=False)
    canonical_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    target_market: Mapped[str] = mapped_column(String(120), nullable=False)
    buyer_profile: Mapped[str | None] = mapped_column(String(200), nullable=True)
    score: Mapped[int] = mapped_column(nullable=False)
    bucket: Mapped[LeadBucket] = mapped_column(
        Enum(LeadBucket, native_enum=False, length=30), nullable=False
    )
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    missing_signals: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class LeadEvidence(Base):
    __tablename__ = "lead_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    lead_id: Mapped[str] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_url: Mapped[str] = mapped_column(String(1_000), nullable=False)
    source_excerpt: Mapped[str] = mapped_column(String(4_000), nullable=False)
    signal_name: Mapped[str] = mapped_column(String(100), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

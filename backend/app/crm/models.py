from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.models import utcnow
from app.shared.db import Base


class LeadBucket(StrEnum):
    PRIORITY_RECOMMENDATION = "priority_recommendation"
    NEEDS_ENRICHMENT = "needs_enrichment"
    NOT_QUALIFIED = "not_qualified"


class LeadStatus(StrEnum):
    NEW = "new"
    TO_CONTACT = "to_contact"
    CONTACTED = "contacted"
    INTERESTED = "interested"
    QUOTING = "quoting"
    WON = "won"
    NOT_FIT = "not_fit"


class EmailDraftStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    READY_TO_SEND = "ready_to_send"
    SENT = "sent"
    REJECTED = "rejected"


class WebsiteInquiryStatus(StrEnum):
    NEW = "new"
    CONVERTED = "converted"
    DISMISSED = "dismissed"


class FollowUpTaskStatus(StrEnum):
    OPEN = "open"
    DONE = "done"


class QuoteDraftStatus(StrEnum):
    DRAFT = "draft"
    SENT = "sent"


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
    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, native_enum=False, length=30),
        default=LeadStatus.NEW,
        nullable=False,
    )
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    notes: Mapped[str] = mapped_column(String(4_000), default="", nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    missing_signals: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    contact_discovery_status: Mapped[str] = mapped_column(
        String(30), default="not_scanned", nullable=False, index=True
    )
    contact_discovery_message: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    contact_discovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    contact_email_count: Mapped[int] = mapped_column(default=0, nullable=False)
    contact_phone_count: Mapped[int] = mapped_column(default=0, nullable=False)
    contact_social_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
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


class FollowUpRecord(Base):
    __tablename__ = "follow_up_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[str] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    activity_type: Mapped[str] = mapped_column(String(50), default="note", nullable=False)
    content: Mapped[str] = mapped_column(String(4_000), nullable=False)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class FollowUpTask(Base):
    __tablename__ = "follow_up_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[str] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), default="follow_up", nullable=False)
    quote_status: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    status: Mapped[FollowUpTaskStatus] = mapped_column(
        Enum(FollowUpTaskStatus, native_enum=False, length=20),
        default=FollowUpTaskStatus.OPEN,
        nullable=False,
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class CRMContact(Base):
    __tablename__ = "crm_contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[str] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    linkedin_url: Mapped[str] = mapped_column(String(1_000), default="", nullable=False)
    whatsapp: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    social_profiles: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list, nullable=False)
    source_url: Mapped[str] = mapped_column(String(1_000), default="", nullable=False)
    email_verification_provider: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    email_verification_status: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    email_verification_sub_status: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class QuoteDraft(Base):
    __tablename__ = "quote_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[str] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_line_id: Mapped[str] = mapped_column(
        ForeignKey("product_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sent_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[QuoteDraftStatus] = mapped_column(
        Enum(QuoteDraftStatus, native_enum=False, length=20),
        default=QuoteDraftStatus.DRAFT,
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    incoterm: Mapped[str] = mapped_column(String(20), default="FOB", nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    line_items: Mapped[list[dict[str, str | float | int]]] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[str] = mapped_column(String(2_000), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailDraft(Base):
    __tablename__ = "email_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[str] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("crm_contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_line_id: Mapped[str] = mapped_column(
        ForeignKey("product_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sent_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[EmailDraftStatus] = mapped_column(
        Enum(EmailDraftStatus, native_enum=False, length=30),
        default=EmailDraftStatus.PENDING_APPROVAL,
        nullable=False,
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(String(8_000), nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    evidence_snapshot: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list, nullable=False)
    rejection_reason: Mapped[str] = mapped_column(String(1_000), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebsiteInquiry(Base):
    __tablename__ = "website_inquiries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_line_id: Mapped[str | None] = mapped_column(
        ForeignKey("product_lines.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("product_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lead_id: Mapped[str | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[WebsiteInquiryStatus] = mapped_column(
        Enum(WebsiteInquiryStatus, native_enum=False, length=30),
        default=WebsiteInquiryStatus.NEW,
        nullable=False,
        index=True,
    )
    company_name: Mapped[str] = mapped_column(String(300), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    website: Mapped[str] = mapped_column(String(1_000), default="", nullable=False)
    target_market: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    message: Mapped[str] = mapped_column(String(4_000), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1_000), default="", nullable=False)
    product_item_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MailboxCursor(Base):
    __tablename__ = "mailbox_cursors"

    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    mailbox: Mapped[str] = mapped_column(String(120), primary_key=True)
    last_uid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uidvalidity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class InboundMessage(Base):
    __tablename__ = "inbound_messages"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider_message_id", name="uq_inbound_message_provider"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    sender_email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    sender_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    subject: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    body_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    intent: Mapped[str] = mapped_column(String(30), default="other", nullable=False, index=True)
    intent_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    analysis_rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    suggested_reply: Mapped[str] = mapped_column(Text, default="", nullable=False)
    follow_up_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("follow_up_tasks.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

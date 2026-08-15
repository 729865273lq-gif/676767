from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.connectors.email.imap import ImapConfigurationError, ImapConnector, InboundEmailRecord
from app.crm.models import (
    CRMContact,
    FollowUpRecord,
    FollowUpTask,
    FollowUpTaskStatus,
    InboundMessage,
    Lead,
    MailboxCursor,
)
from app.crm.service import canonical_domain, website_from_email
from app.platform.models import ProductLine, utcnow

logger = logging.getLogger(__name__)

INBOX_MAILBOX = "INBOX"
FOLLOW_UP_DUE_DAYS = 3


class ReplyIntent(StrEnum):
    INTERESTED = "interested"
    QUESTION = "question"
    NOT_NOW = "not_now"
    NOT_INTERESTED = "not_interested"
    OUT_OF_OFFICE = "out_of_office"
    OTHER = "other"


FOLLOW_UP_INTENTS = {
    ReplyIntent.INTERESTED,
    ReplyIntent.QUESTION,
    ReplyIntent.NOT_NOW,
    ReplyIntent.OTHER,
}


@dataclass(frozen=True)
class ReplyClassification:
    intent: str
    confidence: float
    rationale: str
    suggested_reply: str


_OUT_OF_OFFICE_MARKERS = (
    "out of office",
    "out-of-office",
    "automatic reply",
    "auto reply",
    "autoreply",
    "on vacation",
    "vacation",
    "on leave",
    "away from",
    "out of the office",
    "will be back",
    "自动回复",
    "自动答复",
    "休假",
    "出差",
    "外出",
)

_NOT_INTERESTED_MARKERS = (
    "not interested",
    "no thanks",
    "no thank you",
    "not for us",
    "do not contact",
    "don't contact",
    "please remove",
    "remove me",
    "unsubscribe",
    "stop emailing",
    "stop contacting",
    "not a fit",
    "not relevant",
    "不感兴趣",
    "不需要",
    "请勿再联系",
    "不要再联系",
    "请移除",
    "别联系",
)

_NOT_NOW_MARKERS = (
    "not now",
    "not at this time",
    "at a later",
    "later date",
    "next quarter",
    "next month",
    "next year",
    "in the future",
    "currently not",
    "not ready yet",
    "maybe later",
    "revisit",
    "以后再",
    "稍后",
    "暂时",
    "以后再联系",
    "下次",
)

_QUESTION_LEAD_INS = (
    "what",
    "how",
    "when",
    "where",
    "why",
    "which",
    "who",
    "could you",
    "can you",
    "would you",
    "do you",
    "is there",
    "are there",
    "please confirm",
    "请问",
    "吗",
)

_INTERESTED_MARKERS = (
    "interested",
    "price list",
    "quotation",
    "quote",
    "catalog",
    "catalogue",
    "send me",
    "sample",
    "samples",
    "would like to",
    "want to order",
    "want to buy",
    "send details",
    "more information",
    "more details",
    "感兴趣",
    "报价",
    "价格",
    "目录",
    "样品",
    "下单",
)


def classify_reply(subject: str, body: str, product_line_name: str = "") -> ReplyClassification:
    """Deterministic rule-based reply classification (no LLM required)."""
    subject_lower = subject.strip().lower()
    body_lower = body.strip().lower()
    if any(marker in subject_lower for marker in _OUT_OF_OFFICE_MARKERS) or any(
        marker in body_lower for marker in _OUT_OF_OFFICE_MARKERS
    ):
        return ReplyClassification(
            intent=ReplyIntent.OUT_OF_OFFICE.value,
            confidence=0.95,
            rationale="Subject or body matches automatic out-of-office reply patterns.",
            suggested_reply=_suggested_reply(ReplyIntent.OUT_OF_OFFICE, product_line_name),
        )
    if any(marker in body_lower for marker in _NOT_INTERESTED_MARKERS):
        return ReplyClassification(
            intent=ReplyIntent.NOT_INTERESTED.value,
            confidence=0.9,
            rationale="Body contains an explicit decline or unsubscribe request.",
            suggested_reply=_suggested_reply(ReplyIntent.NOT_INTERESTED, product_line_name),
        )
    if any(marker in body_lower for marker in _NOT_NOW_MARKERS):
        return ReplyClassification(
            intent=ReplyIntent.NOT_NOW.value,
            confidence=0.75,
            rationale="Body indicates the prospect is deferring rather than declining.",
            suggested_reply=_suggested_reply(ReplyIntent.NOT_NOW, product_line_name),
        )
    if _looks_like_question(subject_lower, body_lower):
        return ReplyClassification(
            intent=ReplyIntent.QUESTION.value,
            confidence=0.7,
            rationale="Body asks a question or requests specific information.",
            suggested_reply=_suggested_reply(ReplyIntent.QUESTION, product_line_name),
        )
    if any(marker in body_lower for marker in _INTERESTED_MARKERS):
        return ReplyClassification(
            intent=ReplyIntent.INTERESTED.value,
            confidence=0.8,
            rationale="Body expresses buying interest or requests a quote/catalog.",
            suggested_reply=_suggested_reply(ReplyIntent.INTERESTED, product_line_name),
        )
    return ReplyClassification(
        intent=ReplyIntent.OTHER.value,
        confidence=0.5,
        rationale="No strong intent signal detected; treat as a general reply.",
        suggested_reply=_suggested_reply(ReplyIntent.OTHER, product_line_name),
    )


def _looks_like_question(subject_lower: str, body_lower: str) -> bool:
    text = f"{subject_lower} {body_lower}"
    return "?" in text or any(marker in text for marker in _QUESTION_LEAD_INS)


def _suggested_reply(intent: ReplyIntent, product_line_name: str) -> str:
    product = (product_line_name or "").strip() or "our products"
    templates = {
        ReplyIntent.INTERESTED: (
            f"Thank you for your interest in {product}. I'd be glad to share our latest "
            "catalog and a tailored quotation. Could you let me know your target quantity "
            "and destination port so I can prepare the best offer?"
        ),
        ReplyIntent.QUESTION: (
            f"Thank you for your question about {product}. Here are the details you asked "
            "for. Please let me know if you would like a formal quotation or samples."
        ),
        ReplyIntent.NOT_NOW: (
            f"Thank you for letting me know. I'll follow up about {product} at a better "
            "time. In the meantime, feel free to reach out with any questions."
        ),
        ReplyIntent.NOT_INTERESTED: (
            "Thank you for your reply. I'll respect your preference and stop reaching out. "
            "Wishing you all the best."
        ),
        ReplyIntent.OUT_OF_OFFICE: (
            f"Thank you for your automatic reply. I'll follow up about {product} after "
            "you return to the office."
        ),
        ReplyIntent.OTHER: (
            f"Thank you for your reply regarding {product}. Could you share a bit more "
            "detail so I can point you to the most relevant information?"
        ),
    }
    return templates[intent]


class InboxService:
    """Syncs inbound replies from IMAP and classifies them into follow-up actions."""

    def __init__(
        self,
        session: Session,
        imap_connector: ImapConnector | None = None,
        llm_connector: object | None = None,
    ) -> None:
        self.session = session
        self.imap_connector = imap_connector
        self.llm_connector = llm_connector

    def sync_organization_mailbox(
        self, organization_id: str, mailbox: str = INBOX_MAILBOX
    ) -> int:
        """Fetch, classify and persist new messages atomically; returns new message count."""
        if self.imap_connector is None:
            raise ImapConfigurationError("IMAP inbox is not configured")
        try:
            count = self._sync(organization_id, mailbox)
            self.session.commit()
            return count
        except Exception:
            self.session.rollback()
            raise

    def _sync(self, organization_id: str, mailbox: str) -> int:
        cursor = self.session.get(MailboxCursor, (organization_id, mailbox))
        last_uid = cursor.last_uid if cursor is not None else 0
        uidvalidity = self.imap_connector.uidvalidity(mailbox)
        if (
            uidvalidity is not None
            and cursor is not None
            and cursor.uidvalidity is not None
            and cursor.uidvalidity != uidvalidity
        ):
            # The mailbox was rebuilt and UIDs were reassigned; rescan everything.
            # Re-inserts are idempotent thanks to the UNIQUE provider-message-id key.
            last_uid = 0
        # Capture the high-water mark before fetching so a message delivered during the
        # fetch is simply re-read next poll (idempotent) rather than silently skipped.
        latest = self.imap_connector.latest_uid(mailbox)
        records = self.imap_connector.list_since_uid(mailbox, last_uid)
        single_tenant = _is_single_polled_org(self.session, organization_id)
        new_count = 0
        for record in records:
            try:
                with self.session.begin_nested():
                    inserted = self._upsert_message(organization_id, record, single_tenant)
            except IntegrityError:
                # A concurrent sync already inserted this provider_message_id; skip it.
                continue
            if inserted:
                new_count += 1
        if latest is not None:
            if cursor is None:
                cursor = MailboxCursor(
                    organization_id=organization_id,
                    mailbox=mailbox,
                    last_uid=latest,
                    uidvalidity=uidvalidity,
                )
                self.session.add(cursor)
            else:
                cursor.last_uid = latest
                if uidvalidity is not None:
                    cursor.uidvalidity = uidvalidity
        return new_count

    def _upsert_message(
        self, organization_id: str, record: InboundEmailRecord, single_tenant: bool
    ) -> bool:
        existing = self.session.scalar(
            select(InboundMessage).where(
                InboundMessage.organization_id == organization_id,
                InboundMessage.provider_message_id == record.provider_message_id,
            )
        )
        if existing is not None:
            self._backfill_association(organization_id, existing)
            return False
        lead = self._match_lead(organization_id, record.sender_email)
        if lead is None and not single_tenant:
            # Shared-mailbox multi-tenant pilot is unsupported: a message that belongs to
            # no lead in this org is skipped rather than leaked into the wrong org.
            logger.warning(
                "Skipping inbox message %s: no matched lead in organization %s",
                record.provider_message_id,
                organization_id,
            )
            return False
        product_line_name = self._product_line_name(lead)
        classification = self._classify(record.subject, record.body_text, product_line_name)
        message = InboundMessage(
            organization_id=organization_id,
            provider_message_id=record.provider_message_id,
            thread_id=record.thread_id,
            sender_email=record.sender_email,
            sender_name=record.sender_name,
            subject=record.subject,
            body_text=record.body_text,
            attachments_count=record.attachments_count,
            received_at=record.received_at,
            intent=classification.intent,
            intent_confidence=classification.confidence,
            analysis_rationale=classification.rationale,
            suggested_reply=classification.suggested_reply,
            lead_id=lead.id if lead is not None else None,
        )
        self.session.add(message)
        self.session.flush()
        if lead is not None:
            self._append_timeline(organization_id, lead, message)
            if ReplyIntent(classification.intent) in FOLLOW_UP_INTENTS:
                message.follow_up_task_id = self._create_follow_up_task(
                    organization_id, lead, record.sender_name or record.sender_email
                ).id
        return True

    def _backfill_association(self, organization_id: str, message: InboundMessage) -> None:
        """Link an already-stored message once a matching lead finally exists (sync path)."""
        if message.lead_id is not None:
            return
        lead = self._match_lead(organization_id, message.sender_email)
        if lead is None:
            return
        self._link_message(organization_id, lead, message)

    def backfill_for_lead(self, organization_id: str, lead: Lead) -> int:
        """Link stored unlinked messages that match a newly created or updated lead.

        Called from the CRM lead-creation path (not the sync path), so a reply that arrived
        before its lead existed is associated as soon as the lead is persisted. Runs within
        the caller's transaction and only flushes; the caller commits once.
        """
        has_unlinked = self.session.scalar(
            select(InboundMessage.id)
            .where(
                InboundMessage.organization_id == organization_id,
                InboundMessage.lead_id.is_(None),
            )
            .limit(1)
        )
        if has_unlinked is None:
            return 0
        contact_emails = {
            contact.email.strip().casefold()
            for contact in self.session.scalars(
                select(CRMContact).where(
                    CRMContact.organization_id == organization_id,
                    CRMContact.lead_id == lead.id,
                )
            )
            if contact.email.strip()
        }
        unlinked = list(
            self.session.scalars(
                select(InboundMessage).where(
                    InboundMessage.organization_id == organization_id,
                    InboundMessage.lead_id.is_(None),
                )
            )
        )
        matched = 0
        for message in unlinked:
            if not _lead_matches_sender(lead, contact_emails, message.sender_email):
                continue
            self._link_message(organization_id, lead, message)
            matched += 1
        if matched:
            self.session.flush()
        return matched

    def _link_message(self, organization_id: str, lead: Lead, message: InboundMessage) -> None:
        message.lead_id = lead.id
        if message.follow_up_task_id is None:
            self._append_timeline(organization_id, lead, message)
            if ReplyIntent(message.intent) in FOLLOW_UP_INTENTS:
                message.follow_up_task_id = self._create_follow_up_task(
                    organization_id, lead, message.sender_name or message.sender_email
                ).id

    def _match_lead(self, organization_id: str, sender_email: str) -> Lead | None:
        email = (sender_email or "").strip().lower()
        if email:
            contact = self.session.scalar(
                select(CRMContact)
                .where(
                    CRMContact.organization_id == organization_id,
                    func.lower(CRMContact.email) == email,
                )
                .order_by(CRMContact.is_primary.desc())
                .limit(1)
            )
            if contact is not None:
                return self.session.get(Lead, contact.lead_id)
        domain = _canonical_domain_for_email(email)
        if domain is None:
            return None
        return self.session.scalar(
            select(Lead).where(
                Lead.organization_id == organization_id,
                Lead.canonical_domain == domain,
            )
        )

    def _product_line_name(self, lead: Lead | None) -> str:
        if lead is None:
            return ""
        product_line = self.session.scalar(
            select(ProductLine).where(ProductLine.id == lead.product_line_id)
        )
        return product_line.name if product_line is not None else ""

    def _classify(self, subject: str, body: str, product_line_name: str) -> ReplyClassification:
        rule = classify_reply(subject, body, product_line_name)
        if self.llm_connector is None:
            return rule
        try:
            refined = self.llm_connector.classify_intent(subject, body)
        except Exception:
            return rule
        valid_intents = {intent.value for intent in ReplyIntent}
        if refined in valid_intents:
            refined_intent = ReplyIntent(refined)
            return ReplyClassification(
                intent=refined,
                confidence=rule.confidence,
                rationale=f"{rule.rationale} Refined via LLM.",
                suggested_reply=_suggested_reply(refined_intent, product_line_name),
            )
        return rule

    def _append_timeline(
        self, organization_id: str, lead: Lead, message: InboundMessage
    ) -> None:
        sender = message.sender_name or message.sender_email
        self.session.add(
            FollowUpRecord(
                organization_id=organization_id,
                lead_id=lead.id,
                actor_user_id=None,
                activity_type="reply_analyzed",
                content=(
                    f"Reply from {sender} analyzed as {message.intent} "
                    f"(confidence {message.intent_confidence:.2f}): {message.analysis_rationale}"
                ),
                next_follow_up_at=None,
            )
        )

    def _create_follow_up_task(
        self, organization_id: str, lead: Lead, sender_label: str
    ) -> FollowUpTask:
        task = FollowUpTask(
            organization_id=organization_id,
            lead_id=lead.id,
            actor_user_id=None,
            title=f"Follow up on reply from {sender_label}",
            task_type="reply_follow_up",
            quote_status="",
            due_at=utcnow() + timedelta(days=FOLLOW_UP_DUE_DAYS),
        )
        self.session.add(task)
        self.session.flush()
        return task

    def list_messages(
        self,
        organization_id: str,
        *,
        intent: str | None = None,
        has_follow_up: bool | None = None,
        due_from: object | None = None,
        due_before: object | None = None,
    ) -> list[InboundMessage]:
        statement = select(InboundMessage).where(InboundMessage.organization_id == organization_id)
        if intent is not None:
            statement = statement.where(InboundMessage.intent == intent)
        if has_follow_up is True:
            statement = statement.where(InboundMessage.follow_up_task_id.is_not(None))
        elif has_follow_up is False:
            statement = statement.where(InboundMessage.follow_up_task_id.is_(None))
        if due_from is not None or due_before is not None:
            statement = statement.join(FollowUpTask, FollowUpTask.id == InboundMessage.follow_up_task_id)
            if due_from is not None:
                statement = statement.where(FollowUpTask.due_at >= due_from)
            if due_before is not None:
                statement = statement.where(FollowUpTask.due_at < due_before)
        return list(
            self.session.scalars(
                statement.order_by(InboundMessage.received_at.desc(), InboundMessage.created_at.desc())
            )
        )

    def get_message(self, message_id: str, organization_id: str) -> InboundMessage:
        message = self.session.scalar(
            select(InboundMessage).where(
                InboundMessage.id == message_id,
                InboundMessage.organization_id == organization_id,
            )
        )
        if message is None:
            raise LookupError("inbound message not found")
        return message

    def linked_company_name(self, message: InboundMessage) -> str | None:
        lead: Lead | None = None
        if message.lead_id is not None:
            lead = self.session.get(Lead, message.lead_id)
        elif message.follow_up_task_id is not None:
            lead = self.session.scalar(
                select(Lead)
                .join(FollowUpTask, FollowUpTask.lead_id == Lead.id)
                .where(FollowUpTask.id == message.follow_up_task_id)
            )
        return lead.company_name if lead is not None else None

    def message_due_at(self, message: InboundMessage) -> datetime | None:
        if message.follow_up_task_id is None:
            return None
        task = self.session.get(FollowUpTask, message.follow_up_task_id)
        return task.due_at if task is not None else None

    def mark_follow_up_done(
        self, message_id: str, organization_id: str, actor_user_id: str
    ) -> FollowUpTask:
        message = self.get_message(message_id, organization_id)
        if message.follow_up_task_id is None:
            raise ValueError("message has no follow-up task")
        task = self.session.scalar(
            select(FollowUpTask).where(
                FollowUpTask.id == message.follow_up_task_id,
                FollowUpTask.organization_id == organization_id,
            )
        )
        if task is None:
            raise LookupError("follow-up task not found")
        task.status = FollowUpTaskStatus.DONE
        task.completed_at = utcnow()
        self.session.add(
            FollowUpRecord(
                organization_id=organization_id,
                lead_id=task.lead_id,
                actor_user_id=actor_user_id,
                activity_type="task_done",
                content=f"Completed task: {task.title}",
                next_follow_up_at=None,
            )
        )
        self.session.flush()
        return task


def _canonical_domain_for_email(email: str) -> str | None:
    if not email or "@" not in email:
        return None
    try:
        return canonical_domain(website_from_email(email))
    except ValueError:
        return None


def _lead_matches_sender(lead: Lead, contact_emails: set[str], sender_email: str) -> bool:
    email = (sender_email or "").strip().lower()
    if email and email in contact_emails:
        return True
    domain = _canonical_domain_for_email(email)
    return domain is not None and domain == lead.canonical_domain


def poll_organization_ids(session: Session) -> list[str]:
    """Organization ids that should be polled: any org with a lead or an inbox cursor."""
    return list(
        session.scalars(
            select(Lead.organization_id).union(select(MailboxCursor.organization_id))
        )
    )


def _is_single_polled_org(session: Session, organization_id: str) -> bool:
    """True when ``organization_id`` is the only org with a lead or mailbox cursor.

    The inbox reads one shared IMAP mailbox. Storing every message under every org would
    duplicate content and leak one org's replies into another. The supported V1 pilot is a
    single tenant, so unmatched messages are stored only on that sole org.

    In a multi-org setup an unmatched message is skipped and never stored, so it cannot be
    backfilled later when a matching lead appears. Recovering such a message requires a
    manual full re-sync (e.g. clearing the mailbox cursor row so the mailbox is read again).
    """
    polled = poll_organization_ids(session)
    return organization_id in polled and len(polled) == 1

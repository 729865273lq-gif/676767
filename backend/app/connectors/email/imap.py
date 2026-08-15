from __future__ import annotations

import html as html_module
import imaplib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.parser import BytesParser
from email.policy import default
from email.utils import parseaddr, parsedate_to_datetime

from app.shared.config import Settings


class ImapConfigurationError(ValueError):
    """Raised when inbound IMAP polling has not been configured."""


class ImapError(RuntimeError):
    """Raised when an IMAP mailbox cannot be read."""


@dataclass(frozen=True)
class InboundEmailRecord:
    """A normalized inbound reply extracted from an IMAP mailbox."""

    provider_message_id: str
    thread_id: str
    sender_email: str
    sender_name: str
    subject: str
    body_text: str
    received_at: datetime
    attachments_count: int


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_TAG_RE = re.compile(r"<br\s*/?>|</p\s*>|</div\s*>", re.IGNORECASE)


class ImapConnector:
    """Reads inbound replies from an IMAP mailbox using the stdlib imaplib."""

    connector_id = "imap"
    version = "v1"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        ssl: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.ssl = ssl

    @classmethod
    def from_settings(cls, settings: Settings) -> "ImapConnector":
        missing = [
            name
            for name, value in {
                "IMAP_HOST": settings.imap_host,
                "IMAP_USERNAME": settings.imap_username,
                "IMAP_PASSWORD": settings.imap_password,
            }.items()
            if not value
        ]
        if missing:
            raise ImapConfigurationError("IMAP inbox is not configured: " + ", ".join(missing))
        return cls(
            host=settings.imap_host or "",
            port=settings.imap_port,
            username=settings.imap_username or "",
            password=settings.imap_password or "",
            ssl=True,
        )

    def list_since_uid(self, mailbox: str = "INBOX", since_uid: int = 0) -> list[InboundEmailRecord]:
        """Return normalized messages whose IMAP UID is greater than ``since_uid``."""
        try:
            with self._connect() as imap:
                self._login(imap)
                self._select(imap, mailbox)
                uids = self._search_uids(imap, since_uid)
                records: list[InboundEmailRecord] = []
                for uid in uids:
                    record = self._fetch_record(imap, uid)
                    if record is not None:
                        records.append(record)
                return records
        except ImapError:
            raise
        except (OSError, imaplib.IMAP4.error) as error:
            raise ImapError("IMAP mailbox could not be read") from error

    def latest_uid(self, mailbox: str = "INBOX") -> int | None:
        """Return the highest IMAP UID currently present, or ``None`` when empty."""
        try:
            with self._connect() as imap:
                self._login(imap)
                self._select(imap, mailbox)
                uids = self._search_uids(imap, 0)
                return max(uids) if uids else None
        except ImapError:
            raise
        except (OSError, imaplib.IMAP4.error) as error:
            raise ImapError("IMAP mailbox could not be read") from error

    def uidvalidity(self, mailbox: str = "INBOX") -> int | None:
        """Return the mailbox UIDVALIDITY token, or ``None`` when unavailable."""
        try:
            with self._connect() as imap:
                self._login(imap)
                return self._select(imap, mailbox)
        except ImapError:
            raise
        except (OSError, imaplib.IMAP4.error) as error:
            raise ImapError("IMAP mailbox could not be read") from error

    def _connect(self) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
        if self.ssl:
            return imaplib.IMAP4_SSL(self.host, self.port, timeout=30)
        return imaplib.IMAP4(self.host, self.port, timeout=30)

    def _login(self, imap: imaplib.IMAP4) -> None:
        status, _ = imap.login(self.username, self.password)
        if status != "OK":
            raise ImapError("IMAP login failed")

    def _select(self, imap: imaplib.IMAP4, mailbox: str) -> int | None:
        status, _ = imap.select(mailbox, readonly=True)
        if status != "OK":
            raise ImapError(f"IMAP could not open mailbox: {mailbox}")
        return _parse_uidvalidity(imap)

    def _search_uids(self, imap: imaplib.IMAP4, since_uid: int) -> list[int]:
        criterion = f"UID {since_uid + 1}:*" if since_uid and since_uid > 0 else "ALL"
        status, data = imap.uid("search", None, criterion)
        if status != "OK":
            raise ImapError("IMAP could not search the mailbox")
        payload = data[0] if data and data[0] else b""
        return [int(part) for part in payload.split()]

    def _fetch_record(self, imap: imaplib.IMAP4, uid: int) -> InboundEmailRecord | None:
        status, data = imap.uid("fetch", str(uid), "(RFC822)")
        if status != "OK":
            return None
        raw = _first_message_bytes(data)
        if raw is None:
            return None
        try:
            message = BytesParser(policy=default).parsebytes(raw)
        except Exception:
            return None
        sender_name, sender_email = parseaddr(message.get("From") or "")
        provider_message_id = _header(message, "Message-ID")
        thread_id = _thread_id(message, provider_message_id)
        received_at = parsedate_to_datetime(message.get("Date") or "") or datetime.now(timezone.utc)
        return InboundEmailRecord(
            provider_message_id=provider_message_id,
            thread_id=thread_id,
            sender_email=sender_email.strip().lower(),
            sender_name=sender_name.strip(),
            subject=_decoded_header(message.get("Subject") or ""),
            body_text=_extract_body(message),
            received_at=received_at,
            attachments_count=_count_attachments(message),
        )


def _first_message_bytes(data: list[bytes | tuple[bytes, bytes]] | None) -> bytes | None:
    if not data:
        return None
    for response_part in data:
        if isinstance(response_part, tuple):
            return response_part[1]
    return None


def _header(message: Message, name: str) -> str:
    return str(message.get(name) or "").strip()


def _decoded_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _thread_id(message: Message, provider_message_id: str) -> str:
    references = _header(message, "References")
    in_reply_to = _header(message, "In-Reply-To")
    candidate = ""
    if references:
        candidate = references.split()[-1]
    elif in_reply_to:
        candidate = in_reply_to.split()[-1]
    candidate = candidate.strip().strip("<>")
    return candidate or provider_message_id


def _extract_body(message: Message) -> str:
    if message.is_multipart():
        plain_parts: list[Message] = []
        html_parts: list[Message] = []
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain":
                plain_parts.append(part)
            elif content_type == "text/html":
                html_parts.append(part)
        chosen = plain_parts or html_parts
        texts = [_decode_part(part, is_html=part.get_content_type() == "text/html") for part in chosen]
        return "\n".join(text for text in texts if text).strip()
    return _decode_part(message, is_html=message.get_content_type() == "text/html").strip()


def _decode_part(part: Message, *, is_html: bool) -> str:
    try:
        payload = part.get_payload(decode=True)
    except Exception:
        return ""
    if payload is None:
        return ""
    charset = (part.get_content_charset() or "").strip().lower()
    text = _decode_payload(payload, charset)
    return _html_to_text(text) if is_html else text


def _decode_payload(payload: bytes, charset: str) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if charset and charset not in {"utf-8", "utf8"}:
        try:
            return payload.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass
    return payload.decode("latin-1")


def _html_to_text(text: str) -> str:
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _HTML_TAG_RE.sub(" ", text)
    return html_module.unescape(text)


def _parse_uidvalidity(imap: imaplib.IMAP4) -> int | None:
    try:
        values = imap.response("UIDVALIDITY")
    except Exception:
        return None
    if not values:
        return None
    raw = values[-1]
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="ignore")
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def _count_attachments(message: Message) -> int:
    if not message.is_multipart():
        return 0
    return sum(1 for part in message.walk() if part.get_content_disposition() == "attachment")

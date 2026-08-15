from __future__ import annotations

import imaplib
import smtplib
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.agents.base.contracts import OutboundMessage
from app.shared.config import Settings


class EmailDeliveryConfigurationError(ValueError):
    """Raised when outbound email delivery has not been configured."""


class EmailDeliveryError(RuntimeError):
    """Raised when a configured email provider rejects delivery."""


class SmtpEmailConnector:
    connector_id = "smtp"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        from_name: str,
        use_tls: bool = True,
        imap_host: str = "",
        imap_port: int = 993,
        imap_sent_mailbox: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.from_name = from_name
        self.use_tls = use_tls
        self.imap_host = imap_host
        self.imap_port = imap_port
        self.imap_sent_mailbox = imap_sent_mailbox
        self.sent_copy_error = ""

    @classmethod
    def from_settings(cls, settings: Settings) -> "SmtpEmailConnector":
        missing = [
            name
            for name, value in {
                "SMTP_HOST": settings.smtp_host,
                "SMTP_USERNAME": settings.smtp_username,
                "SMTP_PASSWORD": settings.smtp_password,
                "SMTP_FROM_EMAIL": settings.smtp_from_email,
            }.items()
            if not value
        ]
        if missing:
            raise EmailDeliveryConfigurationError(
                "SMTP email delivery is not configured: " + ", ".join(missing)
            )
        return cls(
            host=settings.smtp_host or "",
            port=settings.smtp_port,
            username=settings.smtp_username or "",
            password=settings.smtp_password or "",
            from_email=settings.smtp_from_email or "",
            from_name=settings.smtp_from_name,
            use_tls=settings.smtp_use_tls,
            imap_host=settings.imap_host or _default_imap_host(settings.smtp_host or ""),
            imap_port=settings.imap_port,
            imap_sent_mailbox=settings.imap_sent_mailbox,
        )

    def send(self, message: OutboundMessage, idempotency_key: str) -> str:
        provider_message_id = make_msgid(domain=self.from_email.split("@")[-1])
        email = EmailMessage()
        email["From"] = formataddr((self.from_name, self.from_email))
        email["To"] = ", ".join(message.recipients)
        email["Subject"] = message.subject
        email["Message-ID"] = provider_message_id
        email["X-Trade-Axis-Idempotency-Key"] = idempotency_key
        email.set_content(message.body)

        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
                if self.use_tls:
                    smtp.starttls()
                smtp.login(self.username, self.password)
                smtp.send_message(email)
        except (OSError, smtplib.SMTPException) as error:
            raise EmailDeliveryError("SMTP email delivery failed") from error

        self.sent_copy_error = ""
        if self.imap_host:
            try:
                self._save_sent_copy(email)
            except (OSError, imaplib.IMAP4.error) as error:
                self.sent_copy_error = str(error) or type(error).__name__

        return provider_message_id

    def save_sent_copy(self, message: OutboundMessage, idempotency_key: str, message_id: str) -> None:
        email = self._build_message(message, idempotency_key, message_id)
        self._save_sent_copy(email)

    def _build_message(
        self,
        message: OutboundMessage,
        idempotency_key: str,
        message_id: str,
    ) -> EmailMessage:
        email = EmailMessage()
        email["From"] = formataddr((self.from_name, self.from_email))
        email["To"] = ", ".join(message.recipients)
        email["Subject"] = message.subject
        email["Message-ID"] = message_id
        email["X-Trade-Axis-Idempotency-Key"] = idempotency_key
        email.set_content(message.body)
        return email

    def _save_sent_copy(self, email: EmailMessage) -> None:
        with imaplib.IMAP4_SSL(self.imap_host, self.imap_port, timeout=30) as imap:
            imap.login(self.username, self.password)
            mailbox = self.imap_sent_mailbox or _find_sent_mailbox(imap)
            status, _ = imap.append(
                mailbox,
                "\\Seen",
                imaplib.Time2Internaldate(time.time()),
                email.as_bytes(),
            )
            if status != "OK":
                raise imaplib.IMAP4.error("IMAP could not save the sent copy")


def _default_imap_host(smtp_host: str) -> str:
    return "imap.qq.com" if smtp_host.lower() == "smtp.qq.com" else ""


def _find_sent_mailbox(imap: imaplib.IMAP4_SSL) -> str:
    status, mailboxes = imap.list()
    if status != "OK":
        raise imaplib.IMAP4.error("IMAP could not list mailboxes")
    for raw_mailbox in mailboxes or []:
        text = raw_mailbox.decode("utf-8", errors="replace")
        mailbox = text.rsplit(" ", 1)[-1].strip('"')
        lowered = mailbox.lower()
        if "sent" in lowered or "已发送" in mailbox:
            return mailbox
    raise imaplib.IMAP4.error("IMAP sent mailbox was not found")

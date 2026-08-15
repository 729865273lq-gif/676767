from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import httpx
import pytest

from app.connectors.email.imap import _normalize_received_at, _parse_uidvalidity, parse_rfc822
from app.connectors.llm.openai_compatible import (
    ChatProviderError,
    OpenAICompatibleChatConnector,
)


def _rfc822(headers: list[bytes], body: bytes) -> bytes:
    return b"\r\n".join([*headers, b"", body])


def test_multipart_prefers_plain_text() -> None:
    msg = EmailMessage()
    msg["From"] = "Alice <alice@example.com>"
    msg["Subject"] = "Hello"
    msg["Message-ID"] = "<m1@example.com>"
    msg["Date"] = "Mon, 02 Jan 2026 10:00:00 +0000"
    msg.set_content("plain body text")
    msg.add_alternative("<p>HTML body &amp; more</p>", subtype="html")

    record = parse_rfc822(msg.as_bytes())

    assert record is not None
    assert record.body_text == "plain body text"
    assert record.sender_email == "alice@example.com"
    assert record.sender_name == "Alice"


def test_html_only_body_unescapes_and_adds_newlines() -> None:
    raw = _rfc822(
        [
            b"From: a@x.com",
            b"Subject: hi",
            b"Message-ID: <h1@x.com>",
            b"Date: Mon, 02 Jan 2026 10:00:00 +0000",
            b"Content-Type: text/html; charset=utf-8",
        ],
        b"<p>Hello &amp; welcome<br>to our site</p>",
    )

    record = parse_rfc822(raw)

    assert record is not None
    assert "Hello & welcome" in record.body_text
    assert "\nto our site" in record.body_text


def test_gbk_quoted_printable_decode() -> None:
    raw = _rfc822(
        [
            b"From: sender@example.com",
            b"Subject: hello",
            b"Message-ID: <gbk-1@example.com>",
            b"Date: Mon, 02 Jan 2026 10:00:00 +0000",
            b"Content-Type: text/plain; charset=gbk",
            b"Content-Transfer-Encoding: quoted-printable",
        ],
        b"=C4=E3=BA=C3",
    )

    record = parse_rfc822(raw)

    assert record is not None
    assert record.body_text == "\u4f60\u597d"  # 你好


def test_missing_message_id_and_date_headers() -> None:
    raw = _rfc822([b"From: a@x.com", b"Subject: hello"], b"body text")

    record = parse_rfc822(raw)

    assert record is not None
    assert record.provider_message_id == ""
    assert record.received_at.tzinfo is not None


def test_thread_id_from_references_and_in_reply_to() -> None:
    refs = _rfc822(
        [
            b"From: a@x.com",
            b"Message-ID: <m1@x.com>",
            b"References: <a@x.com> <b@x.com>",
        ],
        b"body",
    )
    in_reply_to = _rfc822(
        [b"From: a@x.com", b"Message-ID: <m1@x.com>", b"In-Reply-To: <c@x.com>"],
        b"body",
    )

    assert parse_rfc822(refs).thread_id == "b@x.com"
    assert parse_rfc822(in_reply_to).thread_id == "c@x.com"


def test_attachments_count() -> None:
    msg = EmailMessage()
    msg["From"] = "a@x.com"
    msg["Subject"] = "hi"
    msg["Message-ID"] = "<att@x.com>"
    msg["Date"] = "Mon, 02 Jan 2026 10:00:00 +0000"
    msg.set_content("body")
    msg.add_attachment(b"data", maintype="application", subtype="octet-stream", filename="f.bin")

    record = parse_rfc822(msg.as_bytes())

    assert record is not None
    assert record.attachments_count == 1


class _FakeImap:
    def __init__(self, uidvalidity: int | None) -> None:
        self._uidvalidity = uidvalidity

    def response(self, code: str):
        if code == "UIDVALIDITY" and self._uidvalidity is not None:
            return [str(self._uidvalidity).encode()]
        return None


def test_parse_uidvalidity() -> None:
    assert _parse_uidvalidity(_FakeImap(12345)) == 12345
    assert _parse_uidvalidity(_FakeImap(None)) is None


def test_normalize_received_at_to_utc() -> None:
    naive = datetime(2026, 1, 2, 10, 0, 0)
    assert _normalize_received_at(naive).tzinfo == timezone.utc

    aware = datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    assert _normalize_received_at(aware).utcoffset() == timedelta(0)


def _chat_connector(handler) -> OpenAICompatibleChatConnector:
    connector = OpenAICompatibleChatConnector(
        base_url="https://example.com", api_key="k", model="m"
    )
    connector._client = httpx.Client(transport=httpx.MockTransport(handler))  # noqa: SLF001
    return connector


def test_chat_classify_intent_strips_punctuation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "interested."}}]})

    result = _chat_connector(handler).classify_intent("hi", "we like it")

    assert result == "interested"


def test_chat_classify_intent_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    with pytest.raises(ChatProviderError):
        _chat_connector(handler).classify_intent("hi", "body")

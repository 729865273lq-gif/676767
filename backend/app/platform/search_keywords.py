from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.shared.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class KeywordSource(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


class ProductLineSearchKeywords(Base):
    __tablename__ = "product_line_search_keywords"
    __table_args__ = (
        UniqueConstraint("product_line_id", "language", name="uq_product_line_search_keyword_language"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    product_line_id: Mapped[str] = mapped_column(
        ForeignKey("product_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source: Mapped[KeywordSource] = mapped_column(
        Enum(KeywordSource, native_enum=False, length=20), nullable=False
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class TranslationError(RuntimeError):
    """Raised when the LLM cannot produce a parseable keyword translation."""


class ChatTextProvider(Protocol):
    def chat_text(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class KeywordPlan:
    """Multilingual search keyword plan used by the customer query planner."""

    language: str
    localized: list[str]
    english: list[str]


COUNTRY_LANGUAGE: dict[str, str] = {
    "de": "de", "germany": "de", "德国": "de",
    "es": "es", "spain": "es", "西班牙": "es",
    "pt": "pt", "br": "pt", "brazil": "pt", "巴西": "pt", "portugal": "pt", "葡萄牙": "pt",
    "fr": "fr", "france": "fr", "法国": "fr",
    "it": "it", "italy": "it", "意大利": "it",
    "nl": "nl", "netherlands": "nl", "holland": "nl", "荷兰": "nl",
    "tr": "tr", "turkey": "tr", "土耳其": "tr",
    "ru": "ru", "russia": "ru", "俄罗斯": "ru",
    "pl": "pl", "poland": "pl", "波兰": "pl",
    "ar": "ar", "sa": "ar", "ae": "ar", "uae": "ar", "united arab emirates": "ar",
    "阿联酋": "ar", "阿拉伯联合酋长国": "ar", "saudi arabia": "ar", "沙特阿拉伯": "ar", "沙特": "ar",
    "vn": "vi", "vi": "vi", "vietnam": "vi", "越南": "vi",
    "th": "th", "thailand": "th", "泰国": "th",
    "id": "id", "indonesia": "id", "印度尼西亚": "id", "印尼": "id",
    "jp": "ja", "ja": "ja", "japan": "ja", "日本": "ja",
    "kr": "ko", "ko": "ko", "korea": "ko", "south korea": "ko", "韩国": "ko", "南韩": "ko",
    "in": "en", "india": "en", "印度": "en",
    "mx": "es", "mexico": "es", "墨西哥": "es",
    "us": "en", "usa": "en", "united states": "en", "america": "en", "美国": "en",
    "gb": "en", "uk": "en", "united kingdom": "en", "britain": "en", "英国": "en",
    "au": "en", "australia": "en", "澳大利亚": "en", "澳洲": "en",
    "ca": "en", "canada": "en", "加拿大": "en",
    "za": "en", "south africa": "en", "南非": "en",
    "hu": "hu", "hungary": "hu", "匈牙利": "hu",
}


def country_to_language(country_code: str) -> str:
    """Map an ISO-2 country code or common country name to a search language code."""
    normalized = " ".join(country_code.strip().casefold().split())
    return COUNTRY_LANGUAGE.get(normalized, "en")


def translate_keywords(
    llm: ChatTextProvider,
    name: str,
    keywords: list[str],
    language: str,
) -> list[str]:
    """Ask the LLM for localized B2B search keywords; retry once on malformed JSON."""
    content = llm.chat_text(_build_translation_prompt(name, keywords, language))
    parsed = _parse_keywords_json(content)
    if parsed is not None:
        return parsed
    retry_content = llm.chat_text(_retry_translation_prompt(name, keywords, language))
    parsed = _parse_keywords_json(retry_content)
    if parsed is None:
        raise TranslationError(f"翻译服务返回了无法解析的关键词 JSON（语言: {language}）")
    return parsed


def ensure_keywords_for_search(
    session: Session,
    llm: ChatTextProvider | None,
    product_line: object,
    language: str,
) -> ProductLineSearchKeywords | None:
    """Return the stored keywords row for (product_line, language), translating when missing."""
    normalized_language = _normalize_language(language)
    row = session.scalar(
        select(ProductLineSearchKeywords).where(
            ProductLineSearchKeywords.product_line_id == product_line.id,
            ProductLineSearchKeywords.language == normalized_language,
        )
    )
    if row is not None:
        return row
    if llm is None:
        return None
    translated = translate_keywords(
        llm, product_line.name, product_line.product_keywords, normalized_language
    )
    row = ProductLineSearchKeywords(
        product_line_id=product_line.id,
        organization_id=product_line.organization_id,
        language=normalized_language,
        keywords=translated,
        source=KeywordSource.AUTO,
        updated_by_user_id=None,
    )
    session.add(row)
    session.flush()
    return row


def set_keywords_override(
    session: Session,
    product_line: object,
    language: str,
    keywords: list[str],
    user_id: str,
) -> ProductLineSearchKeywords:
    """Persist a manual keyword override for one language."""
    normalized_language = _normalize_language(language)
    normalized_keywords = _normalize_keywords(keywords)
    row = session.scalar(
        select(ProductLineSearchKeywords).where(
            ProductLineSearchKeywords.product_line_id == product_line.id,
            ProductLineSearchKeywords.language == normalized_language,
        )
    )
    if row is None:
        row = ProductLineSearchKeywords(
            product_line_id=product_line.id,
            organization_id=product_line.organization_id,
            language=normalized_language,
            keywords=normalized_keywords,
            source=KeywordSource.MANUAL,
            updated_by_user_id=user_id,
        )
        session.add(row)
    else:
        row.keywords = normalized_keywords
        row.source = KeywordSource.MANUAL
        row.updated_by_user_id = user_id
    session.flush()
    return row


def list_search_keywords(session: Session, product_line: object) -> list[ProductLineSearchKeywords]:
    return list(
        session.scalars(
            select(ProductLineSearchKeywords)
            .where(ProductLineSearchKeywords.product_line_id == product_line.id)
            .order_by(ProductLineSearchKeywords.language)
        )
    )


def latin_keywords(keywords: list[str]) -> list[str]:
    """Keep only keywords that contain at least one Latin-script letter."""
    return [keyword for keyword in keywords if any(char.isascii() and char.isalpha() for char in keyword)]


def plan_search_keywords(
    session: Session,
    llm: ChatTextProvider | None,
    product_line: object,
    country_code: str,
) -> KeywordPlan | None:
    """Build a multilingual keyword plan for a resolved country, or ``None`` when unavailable."""
    normalized = (country_code or "").strip()
    if not normalized:
        return None
    language = country_to_language(normalized)
    localized_row = ensure_keywords_for_search(session, llm, product_line, language)
    if localized_row is None:
        return None
    return KeywordPlan(
        language=language,
        localized=localized_row.keywords,
        english=_english_search_keywords(session, llm, product_line),
    )


def build_search_keyword_provider(llm: ChatTextProvider | None):
    """Return a callable ``(session, product_line, country_code) -> KeywordPlan | None``."""

    def provider(session: Session, product_line: object, country_code: str) -> KeywordPlan | None:
        return plan_search_keywords(session, llm, product_line, country_code)

    return provider


def _english_search_keywords(
    session: Session,
    llm: ChatTextProvider | None,
    product_line: object,
) -> list[str]:
    english_row = ensure_keywords_for_search(session, llm, product_line, "en")
    if english_row is not None:
        return english_row.keywords
    return latin_keywords(product_line.product_keywords)


def _normalize_language(language: str) -> str:
    return language.strip().casefold()


def _normalize_keywords(keywords: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in keywords if value.strip()))


def _build_translation_prompt(name: str, keywords: list[str], language: str) -> str:
    keyword_list = "、".join(keywords) if keywords else name
    return (
        "你是一名外贸 B2B 关键词专家。请把下面产品的关键词翻译/改写为 "
        f"“{language}”语言的本地化搜索关键词，用于在海外地图和搜索引擎中查找潜在客户。\n"
        f"产品名称：{name}\n"
        f"中文关键词：{keyword_list}\n"
        "要求：\n"
        "1. 最多输出 8 个最相关的 B2B 搜索关键词；\n"
        "2. 包含当地分销商/经销商/批发商/进口商等采购方常用术语；\n"
        "3. 只输出严格 JSON，不要输出任何解释、代码块或多余文字。\n"
        '输出格式：{"keywords": ["关键词1", "关键词2", ...]}'
    )


def _retry_translation_prompt(name: str, keywords: list[str], language: str) -> str:
    return (
        _build_translation_prompt(name, keywords, language)
        + "\n\n上次回复无法解析为 JSON。请严格只输出一个 JSON 对象，"
        '格式必须为 {"keywords": ["...", "..."]}，不要使用 Markdown 代码块。'
    )


def _parse_keywords_json(content: str) -> list[str] | None:
    text = _extract_json_text(content)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict):
        keywords = data.get("keywords")
    elif isinstance(data, list):
        keywords = data
    else:
        return None
    if not isinstance(keywords, list):
        return None
    values = [str(item).strip() for item in keywords if str(item).strip()]
    return values[:8] if values else None


def _extract_json_text(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    start = text.find("{")
    if start == -1:
        start = text.find("[")
    end = max(text.rfind("}"), text.rfind("]"))
    if start == -1 or end == -1 or end < start:
        return text
    return text[start : end + 1]

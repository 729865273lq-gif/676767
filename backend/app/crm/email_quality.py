from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class QualityIssue:
    code: str
    message: str
    suggestion: str


@dataclass(frozen=True)
class QualityReport:
    passed: bool
    issues: list[QualityIssue]
    product_evidence: list[str]
    customer_evidence: list[str]


class QualityGateFailedError(ValueError):
    """Raised when a draft fails the pre-review quality gate."""

    def __init__(self, report: QualityReport):
        self.report = report
        super().__init__(", ".join(issue.code for issue in report.issues))


DEFAULT_MIN_LENGTH = 30
DEFAULT_MAX_LENGTH = 8_000

# Weak fallback only: a small set of common product nouns. A draft whose product
# line is outside this list must instead cite its own product line via the
# ``product_context`` argument or a product evidence signal — never this list alone.
_GENERIC_PRODUCT_SIGNAL_RE = re.compile(
    r"\b(led|leds|driver|drivers|bearing|bearings|lighting|machinery|hardware"
    r"|fixture|fixtures|dimmable|component|components|module|modules|sensor|sensors"
    r"|valve|valves|motor|motors|pump|pumps|inverter|inverters|generator|generators"
    r"|battery|batteries|connector|connectors)\b",
    re.IGNORECASE,
)

_GREETING_PERSONALIZATION_RE = re.compile(
    r"\b(dear|hello|hi)\s+[A-Za-z][A-Za-z0-9'&\-]*(?:\s+[A-Za-z][A-Za-z0-9'&\-]*){0,4}",
    re.IGNORECASE,
)

_YOUR_REFERENCE_RE = re.compile(r"\byour\s+[A-Za-z][A-Za-z0-9'\-]*", re.IGNORECASE)
_YOUR_REFERENCE_STOPWORDS = {
    "next", "recent", "kind", "attention", "reply", "response", "time",
    "payment", "order", "email", "message", "request", "inquiry", "interest",
    "feedback", "opinion", "thoughts", "consideration", "reference",
}

_CTA_IMPERATIVE_RE = re.compile(
    r"\b(please\s+reply|please\s+let\s+me\s+know|let\s+me\s+know|reply|respond"
    r"|contact\s+us|get\s+in\s+touch|schedule\s+a\s+call|book\s+a\s+call"
    r"|reach\s+out|sign\s+up|let\s+us\s+know|confirm)\b",
    re.IGNORECASE,
)

_UNSUPPORTED_CLAIM_RE = re.compile(
    r"\bbest\s+in\s+the\s+world\b|\bworld'?s\s+best\b|\bworld-class\b"
    r"|\bnumber\s+one\b|\bno\.?\s*1\b|\b#1\b|\bcheapest\b|\bthe\s+best\b"
    r"|\bworld'?s\s+leading\b|\bindustry\s+leading\b|\bperfect\b|\bbest-in-class\b",
    re.IGNORECASE,
)

_PRICING_PROMISE_RE = re.compile(
    r"\bfree\s+shipping\b|\bfree\s+delivery\b|\blowest\s+price\b|\bbest\s+price\b"
    r"|\bdiscount\b|\d+\s*%\s+off\b|\b\d+%\s+discount\b|\bguaranteed\s+delivery\b"
    r"|\bdelivery\s+within\s+\d+\s+days?\b|\bwithin\s+\d+\s+days?\b"
    r"|\bmoney\s*back\b|\bhalf\s+price\b",
    re.IGNORECASE,
)

_SPAM_PHRASE_RE = re.compile(
    r"\bbuy\s+now\b|\bact\s+now\b|\bclick\s+here\b|\blimited\s+time\b"
    r"|\bspecial\s+offer\b|\bfree\s+money\b|\border\s+now\b|\b100%\s+free\b"
    r"|\burgent\b|\blimited\s+offer\b|!{2,}|\bhurry\b|\bact\s+fast\b",
    re.IGNORECASE,
)

_GENERIC_SALUTATION_RE = re.compile(
    r"\b(dear\s+(?:sir|madam|sir\s*/\s*madam|sir\s+or\s+madam|valued\s+customer|customer)"
    r"|to\s+whom\s+it\s+may\s+concern|hi\s+there)\b",
    re.IGNORECASE,
)

# signal_name semantics: markers that identify an evidence item's kind when the
# signal name is informative. Uninformative source descriptors (search_result,
# manual_entry, public_website) fall back to the source_excerpt text.
_PRODUCT_SIGNAL_MARKERS = (
    "product", "supplier", "factory", "manufacturer", "catalog", "sku", "material",
)
_CUSTOMER_SIGNAL_MARKERS = ("customer", "company", "lead", "contact", "buyer", "account")

# Text markers used when a signal_name is uninformative or evidence is a bare string.
# Customer markers are checked first: lead evidence describes the customer, so
# "lighting importer" is customer context, not product context.
_CUSTOMER_TEXT_MARKERS = (
    "company", "customer", "client", "buyer", "distributor", "importer", "wholesaler",
    "retailer", "merchant", "trader", "founded", "established", "成立", "公司", "ltd",
    "gmbh", "inc", "corp", "group", "co.",
)
_PRODUCT_TEXT_MARKERS = (
    "supplier", "factory", "manufacturer", "manufacturing", "oem", "odm",
    "datasheet", "specification", "catalog", "sku", "component",
)

_TOKEN_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "with", "from", "our", "your", "their",
    "this", "that", "these", "those", "are", "was", "were", "is", "be", "to", "of",
    "in", "on", "at", "by", "as", "it", "we", "you", "they", "he", "she", "them",
    "us", "into", "per", "via", "supply", "supplies", "supplying", "products", "product",
}


def evaluate_draft(
    subject: str,
    body: str,
    evidence: Sequence[str | Mapping[str, str]] = (),
    *,
    requested_language: str = "en",
    product_context: str = "",
    contact_context: str = "",
    min_length: int = DEFAULT_MIN_LENGTH,
    max_length: int = DEFAULT_MAX_LENGTH,
) -> QualityReport:
    subject_text = (subject or "").strip()
    body_text = (body or "").strip()
    evidence_entries = _evidence_entries(evidence)
    product_evidence = [text for kind, text in evidence_entries if kind == "product"]
    customer_evidence = [text for kind, text in evidence_entries if kind == "customer"]

    issues: list[QualityIssue] = []

    # Language detection is limited to CJK vs non-CJK. Latin-script languages
    # (en/es/fr/de/...) are not distinguished, so a Latin-script body passes
    # regardless of the requested Latin language until script-aware detection is added.
    if _contains_cjk(body_text) and not _is_cjk_language(requested_language):
        issues.append(
            QualityIssue(
                code="language_mismatch",
                message="草稿语言与要求语言不一致。",
                suggestion="请使用英文撰写邮件主题和正文。",
            )
        )

    if len(body_text) < min_length:
        issues.append(
            QualityIssue(
                code="body_too_short",
                message=f"邮件正文过短（少于 {min_length} 个字符）。",
                suggestion="请补充产品价值点和明确的行动号召，丰富正文内容。",
            )
        )
    elif len(body_text) > max_length:
        issues.append(
            QualityIssue(
                code="body_too_long",
                message=f"邮件正文过长（超过 {max_length} 个字符）。",
                suggestion="请精简正文，保留最关键的产品价值和单一行动号召。",
            )
        )

    body_cites_product = (
        _matches_product_context(body_text, product_context)
        or bool(product_evidence)
        or _GENERIC_PRODUCT_SIGNAL_RE.search(body_text) is not None
        or "0-10v" in body_text.lower()
    )
    if not body_cites_product:
        issues.append(
            QualityIssue(
                code="missing_product_evidence",
                message="正文未引用可追溯的产品信息。",
                suggestion="请基于产品线或知识库，写出一句具体的产品卖点（如型号、规格或用途）。",
            )
        )

    body_personalizes = (
        _GREETING_PERSONALIZATION_RE.search(body_text) is not None
        or _your_reference(body_text)
        or _matches_contact_context(body_text, contact_context)
    )
    if not customer_evidence and not body_personalizes:
        issues.append(
            QualityIssue(
                code="missing_personalization",
                message="正文缺少针对客户的个性化信息。",
                suggestion="请引用客户公司或联系人的具体信息，避免群发式的通用措辞。",
            )
        )

    cta_count = _count_ctas(body_text)
    if cta_count == 0:
        issues.append(
            QualityIssue(
                code="missing_cta",
                message="正文缺少明确的行动号召。",
                suggestion="请添加一个明确的下一步请求，例如约一次电话或请对方回复需求。",
            )
        )
    elif cta_count > 1:
        issues.append(
            QualityIssue(
                code="multiple_ctas",
                message="正文包含多个行动号召。",
                suggestion="请只保留一个最明确的行动号召，避免分散收件人的注意力。",
            )
        )

    if _UNSUPPORTED_CLAIM_RE.search(subject_text + " " + body_text):
        issues.append(
            QualityIssue(
                code="unsupported_claim",
                message="正文包含缺乏依据的绝对化宣传语。",
                suggestion="请删除“全球最好”“世界第一”等无法验证的措辞，改用可证实的描述。",
            )
        )

    if _PRICING_PROMISE_RE.search(body_text):
        issues.append(
            QualityIssue(
                code="pricing_promise",
                message="正文包含未经证实的报价或交期承诺。",
                suggestion="请勿承诺具体价格、折扣或交期，改为邀请对方索取报价单。",
            )
        )

    if _SPAM_PHRASE_RE.search(body_text):
        issues.append(
            QualityIssue(
                code="spam_phrase",
                message="正文包含容易被判定为垃圾邮件的措辞。",
                suggestion="请删除“立即购买”“限时”“!!!”等促销式用语，保持专业语气。",
            )
        )

    if _generic_salutation(body_text):
        issues.append(
            QualityIssue(
                code="unverified_personalization",
                message="邮件称呼过于笼统，个性化可信度较低。",
                suggestion="请使用收件人姓名或具体公司名称作为称呼。",
            )
        )

    return QualityReport(
        passed=not issues,
        issues=issues,
        product_evidence=product_evidence,
        customer_evidence=customer_evidence,
    )


def quality_gate_error(report: QualityReport) -> QualityGateFailedError:
    return QualityGateFailedError(report)


def quality_issues_list(report: QualityReport) -> list[dict[str, str]]:
    return [
        {"code": issue.code, "message": issue.message, "suggestion": issue.suggestion}
        for issue in report.issues
    ]


def quality_report_dict(report: QualityReport) -> dict:
    return {
        "passed": report.passed,
        "issues": quality_issues_list(report),
        "product_evidence": report.product_evidence,
        "customer_evidence": report.customer_evidence,
    }


def _evidence_entries(evidence: Sequence[str | Mapping[str, str]]) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for item in evidence:
        if isinstance(item, str):
            entries.append(_classify_string_evidence(item))
        elif isinstance(item, Mapping):
            entries.append(_classify_mapping_evidence(item))
        else:
            entries.append(("neutral", str(item)))
    return [(kind, text) for kind, text in entries if text.strip()]


def _classify_string_evidence(text: str) -> tuple[str, str]:
    lowered = text.lower()
    if lowered.startswith("product:"):
        return ("product", text)
    if lowered.startswith(("company:", "customer:", "client:")):
        return ("customer", text)
    return (_text_kind(text), text)


def _classify_mapping_evidence(item: Mapping[str, str]) -> tuple[str, str]:
    signal_name = str(item.get("signal_name", "") or "").strip()
    source_excerpt = str(item.get("source_excerpt", "") or "").strip()
    source_url = str(item.get("source_url", "") or "").strip()
    display = source_excerpt or signal_name or source_url
    if not display:
        return ("neutral", "")

    kind = _signal_name_kind(signal_name)
    if kind != "neutral":
        return (kind, display)

    # Uninformative signal name: fall back to the excerpt text. Lead evidence
    # defaults to customer context when the text carries no explicit signal.
    kind = _text_kind(display)
    if kind == "neutral":
        return ("customer", display)
    return (kind, display)


def _signal_name_kind(signal_name: str) -> str:
    lowered = signal_name.lower()
    if any(marker in lowered for marker in _PRODUCT_SIGNAL_MARKERS):
        return "product"
    if any(marker in lowered for marker in _CUSTOMER_SIGNAL_MARKERS):
        return "customer"
    return "neutral"


def _text_kind(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in _CUSTOMER_TEXT_MARKERS):
        return "customer"
    product_signal = _GENERIC_PRODUCT_SIGNAL_RE.search(lowered) is not None
    if any(marker in lowered for marker in _PRODUCT_TEXT_MARKERS) or product_signal:
        return "product"
    return "neutral"


def _matches_product_context(body: str, product_context: str) -> bool:
    if not product_context:
        return False
    body_lower = body.lower()
    return any(token in body_lower for token in _significant_tokens(product_context))


def _matches_contact_context(body: str, contact_context: str) -> bool:
    if not contact_context:
        return False
    body_lower = body.lower()
    return any(token in body_lower for token in _significant_tokens(contact_context))


def _significant_tokens(text: str) -> list[str]:
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*|[\u3400-\u9fff]+", lowered)
    return [token for token in tokens if len(token) >= 2 and token not in _TOKEN_STOPWORDS]


def _contains_cjk(value: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in value)


def _is_cjk_language(language: str) -> bool:
    lowered = language.strip().lower()
    return lowered.startswith("zh") or lowered in {"cn", "chinese"}


def _your_reference(body: str) -> bool:
    for match in _YOUR_REFERENCE_RE.finditer(body):
        word = match.group(0).split(" ", 1)[1].lower()
        if word not in _YOUR_REFERENCE_STOPWORDS:
            return True
    return False


def _count_ctas(body: str) -> int:
    count = 0
    for sentence in _sentences(body):
        if sentence.rstrip().endswith("?"):
            count += 1
        elif _CTA_IMPERATIVE_RE.search(sentence):
            count += 1
    return count


def _sentences(body: str) -> list[str]:
    return [sentence for sentence in re.split(r"(?<=[.!?])\s+", body) if sentence.strip()]


def _generic_salutation(body: str) -> bool:
    if _GENERIC_SALUTATION_RE.search(body):
        return True
    lines = [line for line in body.splitlines() if line.strip()]
    first_line = lines[0].strip() if lines else ""
    return bool(re.fullmatch(r"\s*(hello|hi)\s*,?\s*", first_line, re.IGNORECASE))

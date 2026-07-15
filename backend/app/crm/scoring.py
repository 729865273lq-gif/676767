from __future__ import annotations

from dataclasses import dataclass

from app.crm.models import LeadBucket


@dataclass(frozen=True)
class LeadQualification:
    bucket: LeadBucket
    score: int
    reasons: list[str]
    missing_signals: list[str]


def qualify_lead(
    *,
    website: str | None,
    fit_evidence: list[str],
    contact_channels: list[str],
    decision_maker_attempted: bool,
) -> LeadQualification:
    reasons: list[str] = []
    missing_signals: list[str] = []
    business_fit = 25 if fit_evidence else 0
    reachability = 10 if website else 0
    if contact_channels:
        reachability += 15
    contact_quality = 10 if contact_channels else 0
    if decision_maker_attempted:
        contact_quality += 15
    evidence_confidence = 25 if fit_evidence else 0

    if website:
        reasons.append("public website verified")
    else:
        missing_signals.append("verified website")
    if fit_evidence:
        reasons.append("product or business fit evidence recorded")
    else:
        missing_signals.append("product or business fit evidence")
    if contact_channels:
        reasons.append("usable public contact channel recorded")
    else:
        missing_signals.append("usable contact channel")
    if decision_maker_attempted:
        reasons.append("decision-maker identification attempted")
    else:
        missing_signals.append("decision-maker identification attempt")

    score = business_fit + reachability + contact_quality + evidence_confidence
    if website and fit_evidence and contact_channels and decision_maker_attempted:
        bucket = LeadBucket.PRIORITY_RECOMMENDATION
    elif website and fit_evidence:
        bucket = LeadBucket.NEEDS_ENRICHMENT
    else:
        bucket = LeadBucket.NOT_QUALIFIED
    return LeadQualification(bucket, score, reasons, missing_signals)

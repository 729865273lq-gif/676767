from app.crm.models import CRMContact, Lead, LeadBucket, LeadEvidence
from app.crm.service import build_email_body, build_email_subject
from app.platform.models import ProductLine


def test_chinese_crm_fields_do_not_leak_into_english_outreach() -> None:
    lead = Lead(
        company_name="Alliance Bearings Bearings & Seals Specialist Malaysia",
        website="https://www.alliancebearings.net/",
        canonical_domain="alliancebearings.net",
        target_market="马来西亚",
        buyer_profile="轴承生产，轴承销售，轴承开发，轴承批发商",
        notes="内部备注：先确认采购需求",
        score=70,
        bucket=LeadBucket.NEEDS_ENRICHMENT,
    )
    contact = CRMContact(
        name="alliancebearings",
        title="Public website contact",
        email="alliancebearings@yahoo.com",
    )
    product_line = ProductLine(
        name="轴承",
        description="轴承和轴承座",
        product_keywords=["轴承", "轴承座"],
    )
    evidence = [
        LeadEvidence(
            source_excerpt="公开证据：公司成立于 1989 年",
            source_url="https://www.alliancebearings.net/",
            signal_name="public_website",
        )
    ]

    subject = build_email_subject(lead=lead, product_line=product_line)
    body = build_email_body(
        lead=lead,
        contact=contact,
        product_line=product_line,
        evidence=evidence,
    )

    assert subject == "Industrial bearings supply discussion with Alliance Bearings & Seals Specialist Malaysia"
    assert body.startswith("Hello Alliance Bearings & Seals Specialist Malaysia team,")
    assert "industrial bearings" in body
    assert "Public evidence used" not in body
    assert "Internal context" not in body
    assert not any("\u3400" <= character <= "\u9fff" for character in subject + body)


def test_named_contact_and_english_product_name_are_preserved() -> None:
    lead = Lead(
        company_name="Berlin Lighting GmbH",
        website="https://berlin-lighting.example",
        canonical_domain="berlin-lighting.example",
        target_market="Germany",
        buyer_profile="Distributor",
        score=80,
        bucket=LeadBucket.PRIORITY_RECOMMENDATION,
    )
    contact = CRMContact(
        name="Anna Weber",
        title="Purchasing Manager",
        email="anna@berlin-lighting.example",
    )
    product_line = ProductLine(name="Industrial Lighting")

    subject = build_email_subject(lead=lead, product_line=product_line)
    body = build_email_body(
        lead=lead,
        contact=contact,
        product_line=product_line,
        evidence=[],
    )

    assert subject == "Industrial Lighting supply discussion with Berlin Lighting GmbH"
    assert body.startswith("Dear Anna Weber,")
    assert "We supply Industrial Lighting" in body

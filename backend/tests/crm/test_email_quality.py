from app.crm.email_quality import evaluate_draft


def test_quality_gate_blocks_generic_draft_without_product_or_customer_evidence() -> None:
    report = evaluate_draft(
        subject="Hello",
        body="We offer good products. Please reply.",
        evidence=[],
    )

    assert report.passed is False
    assert {issue.code for issue in report.issues} >= {
        "missing_product_evidence",
        "missing_personalization",
    }


def test_quality_gate_accepts_one_value_proposition_and_one_cta_with_citations() -> None:
    report = evaluate_draft(
        subject="Dimmable LED drivers for your retail lighting range",
        body=(
            "Your LED retail fixtures match our 0-10V dimmable drivers. We can share tested "
            "specifications for your next range review. Would a 15-minute call next week be useful?"
        ),
        evidence=["product: 0-10V dimmable driver", "company: LED retail fixtures"],
    )

    assert report.passed is True
    assert report.issues == []


def test_quality_gate_flags_unsupported_claim() -> None:
    report = evaluate_draft(
        subject="Dimmable LED drivers for your retail lighting range",
        body=(
            "Your LED retail fixtures match our 0-10V dimmable drivers, the best in the world. "
            "Would a 15-minute call next week be useful?"
        ),
        evidence=["product: 0-10V dimmable driver", "company: LED retail fixtures"],
    )

    assert report.passed is False
    assert {issue.code for issue in report.issues} == {"unsupported_claim"}


def test_quality_gate_flags_unverified_pricing_promise() -> None:
    report = evaluate_draft(
        subject="Dimmable LED drivers for your retail lighting range",
        body=(
            "Your LED retail fixtures match our 0-10V dimmable drivers with free shipping. "
            "Would a 15-minute call next week be useful?"
        ),
        evidence=["product: 0-10V dimmable driver", "company: LED retail fixtures"],
    )

    assert "pricing_promise" in {issue.code for issue in report.issues}


def test_quality_gate_flags_spam_like_phrase() -> None:
    report = evaluate_draft(
        subject="Dimmable LED drivers for your retail lighting range",
        body=(
            "Your LED retail fixtures match our 0-10V dimmable drivers. BUY NOW!!! "
            "Would a 15-minute call next week be useful?"
        ),
        evidence=["product: 0-10V dimmable driver", "company: LED retail fixtures"],
    )

    assert "spam_phrase" in {issue.code for issue in report.issues}


def test_quality_gate_requires_exactly_one_cta() -> None:
    two_ctas = evaluate_draft(
        subject="Dimmable LED drivers for your retail lighting range",
        body=(
            "Your LED retail fixtures match our 0-10V dimmable drivers. Could you share your "
            "requirements? Would a 15-minute call next week be useful?"
        ),
        evidence=["product: 0-10V dimmable driver", "company: LED retail fixtures"],
    )
    no_cta = evaluate_draft(
        subject="Dimmable LED drivers for your retail lighting range",
        body=(
            "Your LED retail fixtures match our 0-10V dimmable drivers. We can share tested "
            "specifications for your next range review."
        ),
        evidence=["product: 0-10V dimmable driver", "company: LED retail fixtures"],
    )

    assert "multiple_ctas" in {issue.code for issue in two_ctas.issues}
    assert "missing_cta" in {issue.code for issue in no_cta.issues}


def test_quality_gate_flags_requested_language_mismatch() -> None:
    report = evaluate_draft(
        subject="您好",
        body="我们的产品很好，请回复。",
        evidence=["product: 0-10V dimmable driver", "company: LED retail fixtures"],
    )

    assert "language_mismatch" in {issue.code for issue in report.issues}


def test_quality_gate_flags_configured_length() -> None:
    short = evaluate_draft(
        subject="Hello",
        body="Hi.",
        evidence=["product: driver", "company: fixtures"],
    )
    long = evaluate_draft(
        subject="Hello",
        body="x" * 8001,
        evidence=["product: driver", "company: fixtures"],
    )

    assert "body_too_short" in {issue.code for issue in short.issues}
    assert "body_too_long" in {issue.code for issue in long.issues}


def test_quality_gate_flags_unverified_contact_personalization() -> None:
    report = evaluate_draft(
        subject="Dimmable LED drivers for your retail lighting range",
        body=(
            "Dear Sir/Madam, your LED retail fixtures match our 0-10V dimmable drivers. "
            "Would a 15-minute call next week be useful?"
        ),
        evidence=["product: 0-10V dimmable driver", "company: LED retail fixtures"],
    )

    assert "unverified_personalization" in {issue.code for issue in report.issues}


def test_real_evidence_snapshot_classifies_lead_evidence_as_customer() -> None:
    evidence = [
        {
            "signal_name": "search_result",
            "source_excerpt": "Industrial lighting importer and distributor based in Berlin.",
            "source_url": "https://maps.google.com/?cid=abc",
        },
        {
            "signal_name": "manual_entry",
            "source_excerpt": "公开证据：公司成立于 1989 年，主营轴承批发。",
            "source_url": "https://example.com",
        },
    ]
    report = evaluate_draft(
        subject="Dimmable LED drivers for your retail lighting range",
        body=(
            "Your LED retail fixtures match our 0-10V dimmable drivers. "
            "Would a 15-minute call next week be useful?"
        ),
        evidence=evidence,
    )

    assert report.customer_evidence == [
        "Industrial lighting importer and distributor based in Berlin.",
        "公开证据：公司成立于 1989 年，主营轴承批发。",
    ]
    assert report.product_evidence == []


def test_product_excerpt_classifies_as_product_evidence() -> None:
    evidence = [
        {
            "signal_name": "search_result",
            "source_excerpt": "0-10V dimmable LED driver datasheet",
            "source_url": "https://catalog.example/driver",
        },
    ]
    report = evaluate_draft(
        subject="Dimmable LED drivers for your retail lighting range",
        body=(
            "Your LED retail fixtures match our 0-10V dimmable drivers. "
            "Would a 15-minute call next week be useful?"
        ),
        evidence=evidence,
    )

    assert report.product_evidence == ["0-10V dimmable LED driver datasheet"]
    assert report.customer_evidence == []


def test_unmarked_lead_excerpt_defaults_to_customer_evidence() -> None:
    evidence = [
        {
            "signal_name": "manual_entry",
            "source_excerpt": "Anna Weber, Purchasing Manager at Berlin Lighting.",
            "source_url": "https://linkedin.com/in/anna-weber",
        },
    ]
    report = evaluate_draft(
        subject="Dimmable LED drivers for your retail lighting range",
        body=(
            "Dear Anna Weber, your LED retail fixtures match our 0-10V dimmable drivers. "
            "Would a 15-minute call next week be useful?"
        ),
        evidence=evidence,
    )

    assert report.customer_evidence == ["Anna Weber, Purchasing Manager at Berlin Lighting."]
    assert report.product_evidence == []


def test_word_boundaries_prevent_abbreviation_overmatch() -> None:
    evidence = [
        {
            "signal_name": "search_result",
            "source_excerpt": "Incentive catalog for corporate LED drivers.",
            "source_url": "https://example.com",
        },
    ]
    report = evaluate_draft(
        subject="Dimmable LED drivers for your retail lighting range",
        body=(
            "Your LED retail fixtures match our 0-10V dimmable drivers. "
            "Would a 15-minute call next week be useful?"
        ),
        evidence=evidence,
    )

    # "inc"/"corp" must not match inside "incentive"/"corporate"; "catalog" wins.
    assert report.product_evidence == ["Incentive catalog for corporate LED drivers."]
    assert report.customer_evidence == []


def test_product_context_satisfies_citation_outside_generic_noun_list() -> None:
    report = evaluate_draft(
        subject="Solar panel supply discussion",
        body=(
            "We supply monocrystalline solar panels for rooftop installers. "
            "Would a 15-minute call next week be useful?"
        ),
        evidence=["company: Rooftop Solar Installers"],
        product_context="Solar Panels monocrystalline photovoltaic",
    )

    assert report.passed is True


def test_product_line_outside_generic_nouns_requires_product_context() -> None:
    report = evaluate_draft(
        subject="Solar panel supply discussion",
        body=(
            "We supply monocrystalline solar panels for rooftop installers. "
            "Would a 15-minute call next week be useful?"
        ),
        evidence=["company: Rooftop Solar Installers"],
    )

    assert "missing_product_evidence" in {issue.code for issue in report.issues}


def test_cjk_requested_language_accepts_cjk_body() -> None:
    report = evaluate_draft(
        subject="轴承供应",
        body="我们供应工业轴承和轴承座，可根据您的采购需求提供规格书和报价。您下周方便安排一次电话沟通吗？",
        evidence=["product: 轴承", "company: 某客户"],
        requested_language="zh",
    )

    assert "language_mismatch" not in {issue.code for issue in report.issues}


def test_generic_your_references_do_not_count_as_personalization() -> None:
    report = evaluate_draft(
        subject="Supply discussion",
        body=(
            "Thank you for your attention. We await your payment confirmation. "
            "Would a 15-minute call next week be useful?"
        ),
        evidence=["product: 0-10V dimmable driver"],
    )

    assert "missing_personalization" in {issue.code for issue in report.issues}

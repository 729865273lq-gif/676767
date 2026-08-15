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

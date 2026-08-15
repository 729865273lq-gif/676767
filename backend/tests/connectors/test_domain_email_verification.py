from app.connectors.email_verification import domain
from app.connectors.email_verification.domain import DomainEmailVerificationConnector


def test_domain_check_marks_resolvable_domain_without_claiming_mailbox_valid(monkeypatch) -> None:
    monkeypatch.setattr(domain.socket, "getaddrinfo", lambda *_args: [(2, 1, 6, "", ("1.1.1.1", 443))])

    result = DomainEmailVerificationConnector().verify("Buyer@Example.com")

    assert result.email == "buyer@example.com"
    assert result.status == "domain_reachable"
    assert result.sub_status == "mailbox_not_verified"
    assert result.deliverable is False


def test_domain_check_marks_unresolvable_domain(monkeypatch) -> None:
    def fail(*_args):
        raise domain.socket.gaierror

    monkeypatch.setattr(domain.socket, "getaddrinfo", fail)

    result = DomainEmailVerificationConnector().verify("buyer@missing.example")

    assert result.status == "domain_unreachable"
    assert result.deliverable is False

import pytest

from app.connectors.contact_discovery import website
from app.connectors.contact_discovery.website import (
    FetchedPage,
    WebsiteContactDiscoveryConnector,
    WebsiteContactDiscoveryError,
)


def test_website_contact_discovery_scans_homepage_and_contact_page() -> None:
    calls: list[str] = []
    pages = {
        "https://buyer.example": FetchedPage(
            url="https://buyer.example",
            content_type="text/html; charset=utf-8",
            body="""
                <a href="mailto:info@buyer.example">Email</a>
                <a href="tel:+49 30 123456">Call</a>
                <a href="https://www.linkedin.com/company/buyer">LinkedIn</a>
                <a href="https://instagram.com/buyer">Instagram</a>
                <a href="https://wa.me/49171123456">WhatsApp</a>
                <a href="/contact">Contact</a>
            """,
        ),
        "https://buyer.example/contact": FetchedPage(
            url="https://buyer.example/contact",
            content_type="text/html",
            body="""
                <p>Export team: export@buyer.example</p>
                <p>Monitoring: 605a7baede844d278b89dc95ae0a9123@sentry-next.wixpress.com</p>
                <p>Errors: 8c4075d5481d476e945486754f783364@sentry.io</p>
                <a href="mailto:no-reply@buyer.example">Automated notifications</a>
            """,
        ),
    }

    def fetcher(url: str) -> FetchedPage:
        calls.append(url)
        return pages[url]

    contacts = WebsiteContactDiscoveryConnector(fetcher).discover("buyer.example", 10)

    assert calls == ["https://buyer.example", "https://buyer.example/contact"]
    assert [contact.email for contact in contacts] == [
        "info@buyer.example",
        "export@buyer.example",
    ]
    assert contacts[0].phone == "+49 30 123456"
    assert contacts[0].whatsapp == "https://wa.me/49171123456"
    assert contacts[0].linkedin_url == "https://www.linkedin.com/company/buyer"
    assert contacts[0].social_profiles == [
        {"platform": "Instagram", "url": "https://instagram.com/buyer"}
    ]
    assert contacts[0].source_url == "https://buyer.example"


def test_website_contact_discovery_keeps_social_only_contact() -> None:
    connector = WebsiteContactDiscoveryConnector(
        lambda url: FetchedPage(
            url=url,
            content_type="text/html",
            body='<a href="https://facebook.com/buyer">Facebook</a>',
        )
    )

    contacts = connector.discover("https://buyer.example", 5)

    assert len(contacts) == 1
    assert contacts[0].email == ""
    assert contacts[0].social_profiles == [
        {"platform": "Facebook", "url": "https://facebook.com/buyer"}
    ]


def test_website_contact_discovery_extracts_obfuscated_email_and_text_phone() -> None:
    connector = WebsiteContactDiscoveryConnector(
        lambda url: FetchedPage(
            url=url,
            content_type="text/html",
            body="Sales: export [at] buyer [dot] example, phone +60 3 1234 5678",
        )
    )

    contacts = connector.discover("https://buyer.example", 5)

    assert contacts[0].email == "export@buyer.example"
    assert contacts[0].phone == "+60 3 1234 5678"


def test_website_contact_discovery_rejects_private_hosts() -> None:
    with pytest.raises(WebsiteContactDiscoveryError, match="non-public"):
        WebsiteContactDiscoveryConnector().discover("http://127.0.0.1", 5)


def test_public_host_allows_proxy_fake_ip_when_local_proxy_is_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        website.socket,
        "getaddrinfo",
        lambda *_args: [(website.socket.AF_INET, website.socket.SOCK_STREAM, 6, "", ("198.18.0.89", 443))],
    )
    monkeypatch.setattr(website, "getproxies", lambda: {"https": "http://127.0.0.1:7897"})

    website._assert_public_host("https://buyer.example")


def test_proxy_fake_ip_is_rejected_without_local_proxy(monkeypatch) -> None:
    monkeypatch.setattr(
        website.socket,
        "getaddrinfo",
        lambda *_args: [(website.socket.AF_INET, website.socket.SOCK_STREAM, 6, "", ("198.18.0.89", 443))],
    )
    monkeypatch.setattr(website, "getproxies", lambda: {})

    with pytest.raises(WebsiteContactDiscoveryError, match="non-public"):
        website._assert_public_host("https://buyer.example")


def test_literal_proxy_fake_ip_is_always_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        website.socket,
        "getaddrinfo",
        lambda *_args: [(website.socket.AF_INET, website.socket.SOCK_STREAM, 6, "", ("198.18.0.89", 443))],
    )
    monkeypatch.setattr(website, "getproxies", lambda: {"https": "http://127.0.0.1:7897"})

    with pytest.raises(WebsiteContactDiscoveryError, match="non-public"):
        website._assert_public_host("https://198.18.0.89")

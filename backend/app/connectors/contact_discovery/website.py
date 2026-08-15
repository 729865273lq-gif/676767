from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, getproxies

from app.connectors.contact_discovery.contracts import DiscoveredContact

MAX_PAGE_BYTES = 1_000_000
MAX_CONTACT_PAGES = 4
WEBSITE_USER_AGENT = "TradeAxis/0.1 (public business contact discovery)"
PROXY_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")

EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
OBFUSCATED_EMAIL_PATTERN = re.compile(
    r"([A-Z0-9._%+-]+)\s*(?:\[at\]|\(at\)|\sat\s)\s*"
    r"([A-Z0-9.-]+)\s*(?:\[dot\]|\(dot\)|\sdot\s)\s*([A-Z]{2,})",
    re.IGNORECASE,
)
PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+\d{1,3}[\s().-]*)?(?:\d[\s().-]*){7,15}(?!\w)")
IGNORED_EMAIL_DOMAIN_SUFFIXES = ("sentry.io", "wixpress.com")
IGNORED_EMAIL_LOCAL_PARTS = {"noreply", "no-reply", "donotreply", "do-not-reply"}
CONTACT_PAGE_TERMS = (
    "contact",
    "about",
    "impressum",
    "kontakt",
    "legal",
    "support",
    "team",
    "staff",
    "sales",
)
SOCIAL_HOSTS = {
    "facebook.com": "Facebook",
    "instagram.com": "Instagram",
    "linkedin.com": "LinkedIn",
    "tiktok.com": "TikTok",
    "twitter.com": "X / Twitter",
    "x.com": "X / Twitter",
    "youtube.com": "YouTube",
}
WHATSAPP_HOSTS = {"wa.me", "whatsapp.com", "api.whatsapp.com"}


@dataclass(frozen=True)
class FetchedPage:
    url: str
    content_type: str
    body: str


PageFetcher = Callable[[str], FetchedPage]


class WebsiteContactDiscoveryError(RuntimeError):
    """Raised when a public company website cannot be safely scanned."""


class WebsiteContactDiscoveryConnector:
    connector_id = "public_website"

    def __init__(self, page_fetcher: PageFetcher | None = None) -> None:
        self._page_fetcher = page_fetcher or _fetch_public_page

    def discover(self, website: str, limit: int) -> list[DiscoveredContact]:
        start_url = _normalize_public_url(website)
        bounded_limit = max(1, min(limit, 25))
        pages = [self._page_fetcher(start_url)]
        homepage_parser = _parse_page(pages[0])

        contact_urls = homepage_parser.contact_pages[:MAX_CONTACT_PAGES]
        if contact_urls:
            with ThreadPoolExecutor(max_workers=len(contact_urls)) as executor:
                future_urls = {
                    executor.submit(self._page_fetcher, contact_url): contact_url
                    for contact_url in contact_urls
                }
                fetched_by_url: dict[str, FetchedPage] = {}
                for future in as_completed(future_urls):
                    try:
                        fetched_by_url[future_urls[future]] = future.result()
                    except WebsiteContactDiscoveryError:
                        continue
                pages.extend(
                    fetched_by_url[url] for url in contact_urls if url in fetched_by_url
                )

        aggregate = _ContactAggregate()
        for page in pages:
            aggregate.add(_parse_page(page), page.url)

        return aggregate.to_contacts(urlparse(start_url).netloc, bounded_limit)


@dataclass
class _ContactAggregate:
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    whatsapp: list[str] = field(default_factory=list)
    social_profiles: list[dict[str, str]] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)

    def add(self, parsed: _PublicContactParser, source_url: str) -> None:
        _extend_unique(self.emails, parsed.emails)
        _extend_unique(self.phones, parsed.phones)
        _extend_unique(self.whatsapp, parsed.whatsapp)
        existing_profiles = {
            (item["platform"].lower(), item["url"].lower().rstrip("/"))
            for item in self.social_profiles
        }
        for profile in parsed.social_profiles:
            key = (profile["platform"].lower(), profile["url"].lower().rstrip("/"))
            if key not in existing_profiles:
                existing_profiles.add(key)
                self.social_profiles.append(profile)
        if any([parsed.emails, parsed.phones, parsed.whatsapp, parsed.social_profiles]):
            _extend_unique(self.source_urls, [source_url])

    def to_contacts(self, host: str, limit: int) -> list[DiscoveredContact]:
        if not any([self.emails, self.phones, self.whatsapp, self.social_profiles]):
            return []
        emails = self.emails[:limit] or [""]
        contacts: list[DiscoveredContact] = []
        for index, email in enumerate(emails):
            contacts.append(
                DiscoveredContact(
                    name=email.split("@", 1)[0] if email else host,
                    title="Public website contact",
                    email=email,
                    phone=self.phones[0] if index == 0 and self.phones else "",
                    linkedin_url=_profile_url(self.social_profiles, "LinkedIn") if index == 0 else "",
                    whatsapp=self.whatsapp[0] if index == 0 and self.whatsapp else "",
                    social_profiles=(
                        [item for item in self.social_profiles if item["platform"] != "LinkedIn"]
                        if index == 0
                        else []
                    ),
                    source_url=self.source_urls[0] if self.source_urls else "",
                    source="Public website",
                )
            )
        return contacts


class _PublicContactParser(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.emails: list[str] = []
        self.phones: list[str] = []
        self.whatsapp: list[str] = []
        self.social_profiles: list[dict[str, str]] = []
        self.contact_pages: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = next((value for name, value in attrs if name.lower() == "href" and value), "")
        if not href:
            return
        absolute = urljoin(self.page_url, href.strip())
        lowered = absolute.lower()
        if lowered.startswith("mailto:"):
            email = unquote(absolute[7:]).split("?", 1)[0].strip()
            if EMAIL_PATTERN.fullmatch(email) and _is_business_contact_email(email):
                _extend_unique(self.emails, [email])
            return
        if lowered.startswith("tel:"):
            phone = unquote(absolute[4:]).split("?", 1)[0].strip()
            if phone:
                _extend_unique(self.phones, [phone])
            return

        parsed = urlparse(absolute)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if host in WHATSAPP_HOSTS or any(host.endswith(f".{item}") for item in WHATSAPP_HOSTS):
            _extend_unique(self.whatsapp, [absolute])
            return
        platform = next(
            (
                label
                for social_host, label in SOCIAL_HOSTS.items()
                if host == social_host or host.endswith(f".{social_host}")
            ),
            "",
        )
        if platform:
            self.social_profiles.append({"platform": platform, "url": absolute})
            return
        if _same_origin(self.page_url, absolute) and any(term in lowered for term in CONTACT_PAGE_TERMS):
            _extend_unique(self.contact_pages, [absolute.split("#", 1)[0]])

    def handle_data(self, data: str) -> None:
        for email in EMAIL_PATTERN.findall(data):
            if _is_business_contact_email(email):
                _extend_unique(self.emails, [email])
        for match in OBFUSCATED_EMAIL_PATTERN.finditer(data):
            email = f"{match.group(1)}@{match.group(2)}.{match.group(3)}"
            if _is_business_contact_email(email):
                _extend_unique(self.emails, [email])
        for phone in PHONE_PATTERN.findall(data):
            normalized = " ".join(phone.split()).strip(" .-")
            digits = re.sub(r"\D", "", normalized)
            if 7 <= len(digits) <= 15:
                _extend_unique(self.phones, [normalized])


def _parse_page(page: FetchedPage) -> _PublicContactParser:
    if "html" not in page.content_type.lower():
        raise WebsiteContactDiscoveryError("website did not return HTML")
    parser = _PublicContactParser(page.url)
    parser.feed(page.body)
    return parser


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def _fetch_public_page(url: str) -> FetchedPage:
    current_url = url
    opener = build_opener(_NoRedirect)
    for _ in range(4):
        _assert_public_host(current_url)
        request = Request(
            current_url,
            headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": WEBSITE_USER_AGENT},
            method="GET",
        )
        try:
            response = opener.open(request, timeout=20)
        except HTTPError as error:
            if error.code in {301, 302, 303, 307, 308}:
                location = error.headers.get("Location", "")
                if not location:
                    raise WebsiteContactDiscoveryError("website redirect is missing a location") from error
                current_url = urljoin(current_url, location)
                continue
            raise WebsiteContactDiscoveryError(
                f"website contact scan failed with HTTP {error.code}"
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise WebsiteContactDiscoveryError("website contact scan could not reach the site") from error

        with response:
            final_url = response.geturl()
            _assert_public_host(final_url)
            content_type = response.headers.get("Content-Type", "")
            body = response.read(MAX_PAGE_BYTES + 1)
        if len(body) > MAX_PAGE_BYTES:
            raise WebsiteContactDiscoveryError("website page is too large to scan")
        charset = response.headers.get_content_charset() or "utf-8"
        return FetchedPage(final_url, content_type, body.decode(charset, errors="replace"))
    raise WebsiteContactDiscoveryError("website redirected too many times")


def _normalize_public_url(value: str) -> str:
    url = value.strip()
    if not url:
        raise ValueError("website is required")
    if "://" not in url:
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("website must be a public HTTP or HTTPS URL")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("website must use port 80 or 443")
    return url


def _assert_public_host(url: str) -> None:
    parsed = urlparse(_normalize_public_url(url))
    host = parsed.hostname or ""
    if host.lower() == "localhost" or host.lower().endswith(".local"):
        raise WebsiteContactDiscoveryError("website host is not public")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)}
    except socket.gaierror as error:
        raise WebsiteContactDiscoveryError("website host could not be resolved") from error
    if not addresses:
        raise WebsiteContactDiscoveryError("website host could not be resolved")
    host_is_ip = _is_ip_literal(host)
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            not host_is_ip
            and ip in PROXY_FAKE_IP_NETWORK
            and _uses_local_system_proxy(parsed.scheme)
        ):
            continue
        if not ip.is_global:
            raise WebsiteContactDiscoveryError("website host resolves to a non-public address")


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _uses_local_system_proxy(scheme: str) -> bool:
    proxy_url = getproxies().get(scheme, "")
    if not proxy_url:
        return False
    parsed = urlparse(proxy_url if "://" in proxy_url else f"http://{proxy_url}")
    proxy_host = parsed.hostname or ""
    if proxy_host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(proxy_host).is_loopback
    except ValueError:
        return False


def _same_origin(left: str, right: str) -> bool:
    return urlparse(left).hostname == urlparse(right).hostname


def _is_business_contact_email(email: str) -> bool:
    local_part, domain = email.lower().rsplit("@", 1)
    if local_part in IGNORED_EMAIL_LOCAL_PARTS:
        return False
    return not any(
        domain == suffix or domain.endswith(f".{suffix}")
        for suffix in IGNORED_EMAIL_DOMAIN_SUFFIXES
    )


def _profile_url(profiles: list[dict[str, str]], platform: str) -> str:
    return next((item["url"] for item in profiles if item["platform"] == platform), "")


def _extend_unique(target: list[str], values: list[str]) -> None:
    seen = {item.lower().rstrip("/") for item in target}
    for value in values:
        normalized = value.strip()
        key = normalized.lower().rstrip("/")
        if normalized and key not in seen:
            seen.add(key)
            target.append(normalized)

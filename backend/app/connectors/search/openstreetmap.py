from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.agents.base.contracts import SearchResult

OPENSTREETMAP_SEARCH_ENDPOINT = "https://nominatim.openstreetmap.org/search"
OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
OVERPASS_ENDPOINTS = (
    OVERPASS_ENDPOINT,
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
OPENSTREETMAP_USER_AGENT = "TradeAxis/0.1 (user-triggered customer discovery)"

TARGET_MARKET_ALIASES = {
    "越南": "Vietnam",
    "胡志明市": "Ho Chi Minh City, Vietnam",
    "河内": "Hanoi, Vietnam",
    "泰国": "Thailand",
    "马来西亚": "Malaysia",
    "印度尼西亚": "Indonesia",
    "菲律宾": "Philippines",
    "新加坡": "Singapore",
    "印度": "India",
    "美国": "United States",
    "加拿大": "Canada",
    "英国": "United Kingdom",
    "德国": "Germany",
    "法国": "France",
    "意大利": "Italy",
    "西班牙": "Spain",
    "荷兰": "Netherlands",
    "波兰": "Poland",
    "匈牙利": "Hungary",
    "土耳其": "Turkey",
    "阿联酋": "United Arab Emirates",
    "沙特阿拉伯": "Saudi Arabia",
    "俄罗斯": "Russia",
    "日本": "Japan",
    "韩国": "South Korea",
    "澳大利亚": "Australia",
    "墨西哥": "Mexico",
    "巴西": "Brazil",
    "南非": "South Africa",
}

_NOMINATIM_LOCK = threading.Lock()
_NOMINATIM_LAST_REQUEST_AT = 0.0

RequestSender = Callable[[str, dict[str, str | int]], list[dict[str, Any]]]
AreaResolver = Callable[[str], int | None]
OverpassSender = Callable[[str, str], dict[str, Any]]

BUSINESS_CATEGORIES = {
    "amenity",
    "building",
    "craft",
    "industrial",
    "office",
    "shop",
    "tourism",
}


class OpenStreetMapSearchError(RuntimeError):
    """Raised when OpenStreetMap search cannot return normalized results."""


class OpenStreetMapSearchConnector:
    connector_id = "openstreetmap"
    version = "v1"

    def __init__(
        self,
        request_sender: RequestSender | None = None,
        *,
        target_market: str = "",
        area_resolver: AreaResolver | None = None,
        overpass_sender: OverpassSender | None = None,
    ) -> None:
        self._request_sender = request_sender or _get_json
        self._target_market = target_market.strip()
        self._area_resolver = area_resolver or _resolve_area_id
        self._overpass_sender = overpass_sender or _post_overpass

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("search query is required")
        if self._target_market:
            resolved_market = TARGET_MARKET_ALIASES.get(self._target_market, self._target_market)
            area_id = await asyncio.to_thread(self._area_resolver, resolved_market)
            if area_id is None:
                return []
            count = min(max(limit, 1), 40)
            overpass_query = _build_overpass_query(
                area_id,
                query=query.strip(),
                target_market=resolved_market,
                limit=count,
            )
            errors: list[str] = []
            for endpoint in OVERPASS_ENDPOINTS:
                try:
                    response = await asyncio.to_thread(
                        self._overpass_sender,
                        endpoint,
                        overpass_query,
                    )
                except OpenStreetMapSearchError as error:
                    errors.append(f"{endpoint}: {error}")
                    continue
                return _normalize_overpass_results(response)
            raise OpenStreetMapSearchError(
                "All public Overpass endpoints failed: " + "; ".join(errors)
            )
        params: dict[str, str | int] = {
            "q": query.strip(),
            "format": "jsonv2",
            "addressdetails": 1,
            "extratags": 1,
            "namedetails": 1,
            "dedupe": 1,
            "limit": min(max(limit, 1), 40),
        }
        response = await asyncio.to_thread(self._request_sender, OPENSTREETMAP_SEARCH_ENDPOINT, params)
        return _normalize_results(response)


def _get_json(endpoint: str, params: dict[str, str | int]) -> list[dict[str, Any]]:
    _wait_for_nominatim_slot()
    request = Request(
        f"{endpoint}?{urlencode(params)}",
        headers={"Accept": "application/json", "User-Agent": OPENSTREETMAP_USER_AGENT},
        method="GET",
    )
    try:
        with urlopen(request, timeout=25) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise OpenStreetMapSearchError(
            f"OpenStreetMap search failed with HTTP {error.code}"
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise OpenStreetMapSearchError("OpenStreetMap search could not reach the provider") from error

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise OpenStreetMapSearchError("OpenStreetMap search returned invalid JSON") from error
    if not isinstance(decoded, list):
        raise OpenStreetMapSearchError("OpenStreetMap search returned an invalid response")
    return [item for item in decoded if isinstance(item, dict)]


def _wait_for_nominatim_slot() -> None:
    global _NOMINATIM_LAST_REQUEST_AT
    with _NOMINATIM_LOCK:
        elapsed = time.monotonic() - _NOMINATIM_LAST_REQUEST_AT
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        _NOMINATIM_LAST_REQUEST_AT = time.monotonic()


@lru_cache(maxsize=256)
def _resolve_area_id(target_market: str) -> int | None:
    rows = _get_json(
        OPENSTREETMAP_SEARCH_ENDPOINT,
        {
            "q": target_market,
            "format": "jsonv2",
            "addressdetails": 1,
            "dedupe": 1,
            "limit": 5,
        },
    )
    for row in rows:
        osm_type = _string(row.get("osm_type")).lower()
        osm_id = row.get("osm_id")
        if not isinstance(osm_id, int):
            continue
        if osm_type == "relation":
            return 3_600_000_000 + osm_id
        if osm_type == "way":
            return 2_400_000_000 + osm_id
    return None


def _post_overpass(endpoint: str, query: str) -> dict[str, Any]:
    request = Request(
        f"{endpoint}?{urlencode({'data': query})}",
        headers={
            "Accept": "application/json",
            "User-Agent": OPENSTREETMAP_USER_AGENT,
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise OpenStreetMapSearchError(f"Overpass search failed with HTTP {error.code}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise OpenStreetMapSearchError("Overpass search could not reach the provider") from error
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise OpenStreetMapSearchError("Overpass search returned invalid JSON") from error
    if not isinstance(decoded, dict) or not isinstance(decoded.get("elements"), list):
        raise OpenStreetMapSearchError("Overpass search returned an invalid response")
    return decoded


def _build_overpass_query(area_id: int, *, query: str, target_market: str, limit: int) -> str:
    terms = _query_terms(query, target_market)
    name_pattern = "|".join(re.escape(term) for term in terms) or "wholesale|distributor"
    shop_pattern = _shop_tag_pattern(terms)
    if shop_pattern:
        statements = [f'nwr["shop"~"{shop_pattern}",i](area.searchArea);']
    else:
        statements = [
            f'nwr["shop"]["name"~"{name_pattern}",i](area.searchArea);',
            f'nwr["office"]["name"~"{name_pattern}",i](area.searchArea);',
        ]
    body = "\n  ".join(statements)
    return (
        f"[out:json][timeout:15];\n"
        f"area({area_id})->.searchArea;\n"
        f"(\n  {body}\n);\n"
        f"out tags center {limit};"
    )


def _query_terms(query: str, target_market: str) -> list[str]:
    target_words = {word.lower() for word in re.findall(r"[A-Za-z0-9]+", target_market)}
    stop_words = {"buyer", "buyers", "company", "companies", "the", "and", "for"}
    terms: list[str] = []
    for word in re.findall(r"[A-Za-z0-9]+", query):
        lowered = word.lower()
        if len(lowered) < 3 or lowered in target_words or lowered in stop_words:
            continue
        if lowered not in terms:
            terms.append(lowered)
    return terms[:8]


def _shop_tag_pattern(terms: list[str]) -> str:
    aliases: set[str] = set()
    product_alias_groups = {
        "lighting": {"led", "light", "lighting", "lamp", "floodlight", "electrical"},
        "electrical": {"led", "light", "lighting", "lamp", "floodlight", "electrical"},
        "furniture": {"furniture", "chair", "table", "sofa"},
        "clothes": {"clothing", "clothes", "apparel", "garment", "textile"},
        "fabric": {"fabric", "textile"},
        "hardware": {"hardware", "tools", "fastener"},
    }
    for tag_value, keywords in product_alias_groups.items():
        if keywords.intersection(terms):
            aliases.add(tag_value)
    if aliases:
        return "|".join(sorted(aliases))
    role_alias_groups = {
        "trade": {"trading", "importer", "exporter"},
        "wholesale": {"distributor", "wholesale", "wholesaler", "importer"},
    }
    for tag_value, keywords in role_alias_groups.items():
        if keywords.intersection(terms):
            aliases.add(tag_value)
    return "|".join(sorted(aliases))


def _normalize_overpass_results(response: dict[str, Any]) -> list[SearchResult]:
    elements = response.get("elements", [])
    if not isinstance(elements, list):
        raise OpenStreetMapSearchError("Overpass response has invalid elements")
    results: list[SearchResult] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags")
        if not isinstance(tags, dict):
            continue
        osm_type = _string(element.get("type")).lower()
        osm_id = str(element.get("id", "")).strip()
        title = _first_tag(tags, "name", "name:en", "operator", "brand")
        if osm_type not in {"node", "way", "relation"} or not osm_id or not title:
            continue
        source_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
        website = _first_tag(tags, "contact:website", "website", "url")
        email = _first_tag(tags, "contact:email", "email")
        phone = _first_tag(tags, "contact:phone", "phone", "contact:mobile", "mobile")
        whatsapp = _first_tag(tags, "contact:whatsapp", "whatsapp")
        social_profiles = _social_profiles(tags)
        address = ", ".join(
            value
            for value in [
                _first_tag(tags, "addr:street"),
                _first_tag(tags, "addr:city"),
                _first_tag(tags, "addr:country"),
            ]
            if value
        )
        category = next(
            (f"{key}={_string(tags.get(key))}" for key in BUSINESS_CATEGORIES if tags.get(key)),
            "OpenStreetMap business",
        )
        results.append(
            SearchResult(
                url=_website_url(website) or source_url,
                title=title,
                snippet=" | ".join(part for part in [address, phone, category] if part),
                canonical_key="" if website else f"osm:{osm_type}:{osm_id}",
                email=email,
                phone=phone,
                whatsapp=whatsapp,
                social_profiles=social_profiles,
                source_url=source_url,
            )
        )
    return results


def _normalize_results(items: list[dict[str, Any]]) -> list[SearchResult]:
    results: list[SearchResult] = []
    for item in items:
        extra = item.get("extratags")
        tags = extra if isinstance(extra, dict) else {}
        category = _string(item.get("category")) or _string(item.get("class"))
        website = _first_tag(tags, "contact:website", "website", "url")
        email = _first_tag(tags, "contact:email", "email")
        phone = _first_tag(tags, "contact:phone", "phone", "contact:mobile", "mobile")
        whatsapp = _first_tag(tags, "contact:whatsapp", "whatsapp")
        social_profiles = _social_profiles(tags)
        if category not in BUSINESS_CATEGORIES and not any(
            [website, email, phone, whatsapp, social_profiles]
        ):
            continue

        osm_type = _string(item.get("osm_type")).lower()
        osm_id = str(item.get("osm_id", "")).strip()
        if osm_type not in {"node", "way", "relation"} or not osm_id:
            continue
        source_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
        title = _display_name(item)
        if not title:
            continue
        result_url = _website_url(website) or source_url
        display_name = _string(item.get("display_name"))
        place_type = _string(item.get("type"))
        snippet_parts = [display_name, f"OSM {category}/{place_type}".rstrip("/")]
        results.append(
            SearchResult(
                url=result_url,
                title=title,
                snippet=" | ".join(part for part in snippet_parts if part),
                canonical_key="" if website else f"osm:{osm_type}:{osm_id}",
                email=email,
                phone=phone,
                whatsapp=whatsapp,
                social_profiles=social_profiles,
                source_url=source_url,
            )
        )
    return results


def _display_name(item: dict[str, Any]) -> str:
    namedetails = item.get("namedetails")
    if isinstance(namedetails, dict):
        name = _first_tag(namedetails, "name", "name:en")
        if name:
            return name
    name = _string(item.get("name"))
    if name:
        return name
    return _string(item.get("display_name")).split(",", 1)[0].strip()


def _social_profiles(tags: dict[str, Any]) -> list[dict[str, str]]:
    profiles: list[dict[str, str]] = []
    for platform, keys in {
        "Facebook": ("contact:facebook", "facebook"),
        "Instagram": ("contact:instagram", "instagram"),
        "LinkedIn": ("contact:linkedin", "linkedin"),
        "TikTok": ("contact:tiktok", "tiktok"),
    }.items():
        value = _first_tag(tags, *keys)
        if value:
            profiles.append({"platform": platform, "url": value})
    return profiles


def _first_tag(tags: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _string(tags.get(key))
        if value:
            return value
    return ""


def _website_url(value: str) -> str:
    if not value:
        return ""
    return value if "://" in value else f"https://{value}"


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""

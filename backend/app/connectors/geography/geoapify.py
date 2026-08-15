from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import truststore

GEOAPIFY_GEOCODING_ENDPOINT = "https://api.geoapify.com/v1/geocode/search"
GEOAPIFY_REVERSE_ENDPOINT = "https://api.geoapify.com/v1/geocode/reverse"
GEOAPIFY_SUBDIVISIONS_ENDPOINT = "https://api.geoapify.com/v1/boundaries/consists-of"
NOMINATIM_SEARCH_ENDPOINT = "https://nominatim.openstreetmap.org/search"

ObjectSender = Callable[[str, dict[str, str]], dict[str, Any]]
ListSender = Callable[[str, dict[str, str]], list[dict[str, Any]]]


class GeoapifyAdministrativeAreaError(RuntimeError):
    """Raised when an administrative location cannot be resolved."""


@dataclass(frozen=True)
class AdministrativeArea:
    scope_id: str
    name: str
    formatted: str
    search_label: str
    country_code: str = ""
    level: str = "administrative"


class GeoapifyAdministrativeAreaConnector:
    connector_id = "geoapify-administrative-areas"

    def __init__(
        self,
        api_key: str,
        object_sender: ObjectSender | None = None,
        list_sender: ListSender | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Geoapify API key is required")
        self._api_key = api_key.strip()
        self._object_sender = object_sender or _get_json_object
        self._list_sender = list_sender or _get_json_list

    async def resolve(self, query: str) -> AdministrativeArea:
        normalized_query = " ".join(query.split())
        if not normalized_query:
            raise ValueError("location query is required")
        rows = await self._geocode(normalized_query)
        if not rows:
            translated_query, country_code, latitude, longitude = await asyncio.to_thread(
                self._resolve_with_nominatim,
                normalized_query,
            )
            if translated_query and translated_query.casefold() != normalized_query.casefold():
                rows = await self._geocode(translated_query, country_code=country_code)
            if not rows and latitude and longitude:
                rows = await self._reverse_geocode(latitude, longitude)
        if not rows:
            raise GeoapifyAdministrativeAreaError("无法识别这个地点，请尝试输入国家、州、省或城市全名")
        return _normalize_area(rows[0], fallback_name=normalized_query)

    async def subdivisions(self, area: AdministrativeArea) -> list[AdministrativeArea]:
        response = await asyncio.to_thread(
            self._object_sender,
            GEOAPIFY_SUBDIVISIONS_ENDPOINT,
            {
                "id": area.scope_id,
                "boundary": "administrative",
                "sublevel": "1",
                "geometry": "point",
                "lang": "zh",
                "apiKey": self._api_key,
            },
        )
        rows = _feature_rows(response)
        children: list[AdministrativeArea] = []
        seen: set[str] = set()
        for row in rows:
            child = _normalize_area(row)
            if not child.scope_id or child.scope_id == area.scope_id or child.scope_id in seen:
                continue
            seen.add(child.scope_id)
            parent_terms = [area.name]
            country = _string(row.get("country"))
            if country and country.casefold() not in {term.casefold() for term in parent_terms}:
                parent_terms.append(country)
            search_label = ", ".join([child.name, *parent_terms])
            children.append(
                AdministrativeArea(
                    scope_id=child.scope_id,
                    name=child.name,
                    formatted=child.formatted,
                    search_label=search_label,
                    country_code=child.country_code or area.country_code,
                    level=child.level,
                )
            )
        return sorted(children, key=lambda child: child.name.casefold())

    async def _geocode(
        self,
        query: str,
        *,
        country_code: str = "",
    ) -> list[dict[str, Any]]:
        parameters = {
            "text": query,
            "format": "json",
            "lang": "zh",
            "limit": "5",
            "apiKey": self._api_key,
        }
        if country_code:
            parameters["filter"] = f"countrycode:{country_code.lower()}"
        response = await asyncio.to_thread(
            self._object_sender,
            GEOAPIFY_GEOCODING_ENDPOINT,
            parameters,
        )
        rows = response.get("results", [])
        if not isinstance(rows, list):
            raise GeoapifyAdministrativeAreaError("地点解析服务返回了无效结果")
        candidates = [row for row in rows if isinstance(row, dict) and _string(row.get("place_id"))]
        candidates.sort(key=_area_priority)
        return candidates

    async def _reverse_geocode(self, latitude: str, longitude: str) -> list[dict[str, Any]]:
        response = await asyncio.to_thread(
            self._object_sender,
            GEOAPIFY_REVERSE_ENDPOINT,
            {
                "lat": latitude,
                "lon": longitude,
                "format": "json",
                "lang": "zh",
                "limit": "5",
                "apiKey": self._api_key,
            },
        )
        rows = response.get("results", [])
        if not isinstance(rows, list):
            raise GeoapifyAdministrativeAreaError("地点反向解析服务返回了无效结果")
        candidates = [row for row in rows if isinstance(row, dict) and _string(row.get("place_id"))]
        candidates.sort(key=_area_priority)
        return candidates

    def _resolve_with_nominatim(self, query: str) -> tuple[str, str, str, str]:
        rows = self._list_sender(
            NOMINATIM_SEARCH_ENDPOINT,
            {
                "q": query,
                "format": "jsonv2",
                "addressdetails": "1",
                "namedetails": "1",
                "limit": "1",
            },
        )
        if not rows:
            return "", "", "", ""
        row = rows[0]
        names = row.get("namedetails") if isinstance(row.get("namedetails"), dict) else {}
        address = row.get("address") if isinstance(row.get("address"), dict) else {}
        translated = _first_string(names, "name:en", "official_name:en", "name")
        country_code = _string(address.get("country_code"))
        return translated, country_code, _string(row.get("lat")), _string(row.get("lon"))


def _area_priority(row: dict[str, Any]) -> tuple[int, int]:
    result_type = _string(row.get("result_type"))
    priorities = {
        "country": 0,
        "state": 1,
        "county": 2,
        "city": 3,
        "district": 4,
        "suburb": 5,
    }
    rank = row.get("rank", {}).get("importance", 0) if isinstance(row.get("rank"), dict) else 0
    return priorities.get(result_type, 9), -int(float(rank or 0) * 1_000)


def _normalize_area(row: dict[str, Any], *, fallback_name: str = "") -> AdministrativeArea:
    name = _first_string(row, "name", "city", "state", "country") or fallback_name
    formatted = _first_string(row, "formatted", "address_line1") or name
    if not name or not _string(row.get("place_id")):
        raise GeoapifyAdministrativeAreaError("地点解析结果缺少行政区信息")
    return AdministrativeArea(
        scope_id=_string(row.get("place_id")),
        name=name,
        formatted=formatted,
        search_label=formatted,
        country_code=_string(row.get("country_code")).upper(),
        level=_string(row.get("result_type")) or "administrative",
    )


def _feature_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    features = response.get("features", [])
    if not isinstance(features, list):
        raise GeoapifyAdministrativeAreaError("行政区服务返回了无效结果")
    rows: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        if isinstance(properties, dict):
            rows.append(properties)
    return rows


def _get_json_object(endpoint: str, parameters: dict[str, str]) -> dict[str, Any]:
    decoded = _request_json(endpoint, parameters)
    if not isinstance(decoded, dict):
        raise GeoapifyAdministrativeAreaError("地点服务返回了无效数据")
    return decoded


def _get_json_list(endpoint: str, parameters: dict[str, str]) -> list[dict[str, Any]]:
    decoded = _request_json(endpoint, parameters)
    if not isinstance(decoded, list):
        raise GeoapifyAdministrativeAreaError("地点翻译服务返回了无效数据")
    return [row for row in decoded if isinstance(row, dict)]


def _request_json(endpoint: str, parameters: dict[str, str]) -> object:
    request = Request(
        f"{endpoint}?{urlencode(parameters)}",
        headers={
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh,en",
            "User-Agent": "TradeAxis/1.0",
        },
    )
    try:
        ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with urlopen(request, timeout=30, context=ssl_context) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise GeoapifyAdministrativeAreaError(f"地点服务请求失败（HTTP {error.code}）") from error
    except (URLError, TimeoutError, OSError) as error:
        raise GeoapifyAdministrativeAreaError("无法连接地点解析服务") from error
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise GeoapifyAdministrativeAreaError("地点服务返回了无效 JSON") from error


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first_string(values: dict[str, Any], *keys: str) -> str:
    return next((_string(values.get(key)) for key in keys if _string(values.get(key))), "")

import asyncio

from app.connectors.geography import GeoapifyAdministrativeAreaConnector


def test_resolve_translates_chinese_location_and_returns_direct_subdivisions() -> None:
    object_requests: list[tuple[str, dict[str, str]]] = []

    def object_sender(endpoint: str, parameters: dict[str, str]) -> dict[str, object]:
        object_requests.append((endpoint, parameters))
        if endpoint.endswith("/geocode/search") and parameters["text"] == "北京":
            return {"results": []}
        if endpoint.endswith("/geocode/search"):
            return {
                "results": [
                    {
                        "place_id": "beijing-place",
                        "name": "北京市",
                        "formatted": "北京市, 中国",
                        "country_code": "cn",
                        "result_type": "city",
                    }
                ]
            }
        return {
            "features": [
                {
                    "properties": {
                        "place_id": "chaoyang-place",
                        "name": "朝阳区",
                        "formatted": "朝阳区, 中国",
                        "country": "中国",
                    }
                },
                {
                    "properties": {
                        "place_id": "fengtai-place",
                        "name": "丰台区",
                        "formatted": "丰台区, 中国",
                        "country": "中国",
                    }
                },
            ]
        }

    connector = GeoapifyAdministrativeAreaConnector(
        "test-key",
        object_sender=object_sender,
        list_sender=lambda _endpoint, _parameters: [
            {
                "namedetails": {"name:en": "Beijing"},
                "address": {"country_code": "cn"},
            }
        ],
    )

    area = asyncio.run(connector.resolve("北京"))
    subdivisions = asyncio.run(connector.subdivisions(area))

    assert area.scope_id == "beijing-place"
    assert area.name == "北京市"
    assert [child.name for child in subdivisions] == ["丰台区", "朝阳区"]
    assert subdivisions[0].search_label == "丰台区, 北京市, 中国"
    assert object_requests[1][1]["filter"] == "countrycode:cn"


def test_resolve_uses_coordinates_when_no_english_location_name_exists() -> None:
    def object_sender(endpoint: str, parameters: dict[str, str]) -> dict[str, object]:
        if endpoint.endswith("/geocode/reverse"):
            assert parameters["lat"] == "39.9"
            assert parameters["lon"] == "116.4"
            return {
                "results": [
                    {
                        "place_id": "beijing-place",
                        "name": "北京市",
                        "formatted": "北京市, 中国",
                        "country_code": "cn",
                        "result_type": "city",
                    }
                ]
            }
        return {"results": []}

    connector = GeoapifyAdministrativeAreaConnector(
        "test-key",
        object_sender=object_sender,
        list_sender=lambda _endpoint, _parameters: [
            {
                "namedetails": {"name": "北京"},
                "address": {"country_code": "cn"},
                "lat": "39.9",
                "lon": "116.4",
            }
        ],
    )

    area = asyncio.run(connector.resolve("北京"))

    assert area.scope_id == "beijing-place"
    assert area.name == "北京市"

import asyncio
import hashlib
import json

from app.connectors.tradesparq import (
    TradesparqClient,
    build_get_signature,
    build_post_signature,
)


def test_get_signature_uses_secret_and_full_url() -> None:
    full_url = "https://openapi.tradesparq.com/example?kw=bearing&max=10"

    signature = build_get_signature("local-secret", full_url)

    assert signature == hashlib.md5(f"local-secret{full_url}".encode()).hexdigest()


def test_post_signature_sorts_keys_and_json_encodes_values() -> None:
    payload = {"product": "bearing", "countries": ["VN", "MY"], "page": 1}
    sorted_values = '["VN","MY"]1"bearing"'

    signature = build_post_signature("local-secret", payload)

    assert signature == hashlib.md5(f"local-secret{sorted_values}".encode()).hexdigest()


def test_client_sends_api_headers_without_exposing_secret() -> None:
    requests = []

    def sender(request):
        requests.append(request)
        return {"code": 200, "data": []}

    client = TradesparqClient("local-id", "local-secret", request_sender=sender)

    result = asyncio.run(client.get("https://openapi.tradesparq.com/example", {"kw": "bearing"}))

    assert result["code"] == 200
    request = requests[0]
    assert request.get_header("X-api-uid") == "local-id"
    assert request.get_header("X-api-request-sign")
    assert "local-secret" not in request.full_url
    assert "local-secret" not in json.dumps(dict(request.header_items()))

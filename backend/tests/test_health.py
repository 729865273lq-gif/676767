from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_service_name() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {"service": "foreign-trade-api", "status": "ok"}

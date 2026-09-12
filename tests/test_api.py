from fastapi.testclient import TestClient

from app.api.main import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_query_endpoint_returns_answer():
    response = client.post(
        "/query",
        json={"question": "How do I fix AUTH-401 after a gateway upgrade?", "top_k": 3},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "answer" in payload
    assert "citations" in payload
    assert len(payload["citations"]) >= 0

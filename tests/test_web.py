from fastapi.testclient import TestClient

import cairn
import cairn.web as web_module
from cairn.web import app


def test_healthz():
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "version": cairn.__version__,
    }


def test_healthz_degraded_when_database_unreachable(monkeypatch):
    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(web_module, "get_engine", lambda: _BrokenEngine())
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"

from fastapi.testclient import TestClient

import cairn
from cairn.web import app


def test_healthz():
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": cairn.__version__}

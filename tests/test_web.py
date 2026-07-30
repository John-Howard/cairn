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


def test_js_enabled_marks_govuk_frontend_supported():
    """The shipped govuk-frontend CSS gates conditional-reveal hiding on
    .govuk-frontend-supported — if the marker snippet drops it, every dependent
    intake question renders permanently expanded."""
    client = TestClient(app)
    script = client.get("/static/js-enabled.js")
    assert script.status_code == 200
    assert "govuk-frontend-supported" in script.text

    css = client.get("/static/govuk/govuk-frontend-6.3.0.min.css")
    assert ".govuk-frontend-supported .govuk-radios__conditional--hidden" in css.text


def test_cairn_stylesheet_is_served_and_linked():
    import pathlib

    client = TestClient(app)
    css = client.get("/static/cairn.css")
    assert css.status_code == 200
    assert ".cairn-inline-form" in css.text
    assert ".cairn-preserve-lines" in css.text

    # Assert the link against the template source rather than a rendered page:
    # every page needing a session hits the database, which this test has no
    # fixture for — it would pass only where a dev database happens to exist.
    base = pathlib.Path(__file__).resolve().parent.parent / "src" / "cairn" / "templates"
    assert '/static/cairn.css' in (base / "base.html").read_text()


def test_no_template_uses_an_inline_style_attribute():
    """The CSP (default-src 'self', no style-src 'unsafe-inline') drops inline
    style attributes, so one is always dead markup — it looks like styling but
    computes to nothing. Anything needing styling belongs in cairn.css."""
    import pathlib

    templates = pathlib.Path(__file__).resolve().parent.parent / "src" / "cairn" / "templates"
    offenders = [
        f"{path.relative_to(templates)}:{n}"
        for path in sorted(templates.rglob("*.html"))
        for n, line in enumerate(path.read_text().splitlines(), start=1)
        if 'style="' in line
    ]
    assert offenders == []

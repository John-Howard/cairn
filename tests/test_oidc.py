import pytest
from sqlalchemy import select

import cairn.oidc as oidc_module
from cairn.models import AuditEvent, Role, User
from cairn.oidc import OIDCDenied, resolve_oidc_user
from cairn.settings import get_settings
from cairn.web import create_app

ENTRA_SUB = "entra-sub-0001"


@pytest.fixture
def oidc_env(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-not-dev")
    monkeypatch.setenv("OIDC_ISSUER", "https://login.microsoftonline.com/tenant/v2.0")
    monkeypatch.setenv("OIDC_CLIENT_ID", "client-id")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "client-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def dpo(session):
    user = User(
        display_name="Dana DPO", email="dana@example.org", role=Role.APPROVER_DPO
    )
    session.add(user)
    session.flush()
    return user


def test_resolve_binds_subject_on_first_login_by_email(session, dpo):
    claims = {"sub": ENTRA_SUB, "email": "Dana@Example.org"}
    user = resolve_oidc_user(session, claims)
    assert user.id == dpo.id
    assert user.oidc_subject == ENTRA_SUB
    event = session.scalars(
        select(AuditEvent).where(AuditEvent.event == "oidc_subject_bound")
    ).one()
    assert event.entity_id == dpo.id

    # Second login matches by subject even if the email changes at the IdP
    user = resolve_oidc_user(session, {"sub": ENTRA_SUB, "email": "renamed@example.org"})
    assert user.id == dpo.id


def test_resolve_uses_preferred_username_claim(session, dpo):
    user = resolve_oidc_user(
        session, {"sub": ENTRA_SUB, "preferred_username": "dana@example.org"}
    )
    assert user.id == dpo.id


def test_resolve_denies_unknown_and_inactive(session, dpo):
    with pytest.raises(OIDCDenied):
        resolve_oidc_user(session, {"sub": "other", "email": "nobody@example.org"})
    with pytest.raises(OIDCDenied):
        resolve_oidc_user(session, {"sub": "other"})

    session.info["actor_id"] = dpo.id
    dpo.is_active = False
    session.flush()
    with pytest.raises(OIDCDenied):
        resolve_oidc_user(session, {"sub": "fresh-sub", "email": "dana@example.org"})


def test_resolve_does_not_rebind_taken_email(session, dpo):
    resolve_oidc_user(session, {"sub": ENTRA_SUB, "email": "dana@example.org"})
    # A different subject presenting the same email must not steal the account
    with pytest.raises(OIDCDenied):
        resolve_oidc_user(session, {"sub": "attacker-sub", "email": "dana@example.org"})


def test_oidc_mode_requires_client_config(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-not-dev")
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="OIDC_ISSUER"):
            create_app()
    finally:
        get_settings.cache_clear()


def test_unknown_auth_mode_rejected(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "saml")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="Unknown AUTH_MODE"):
            create_app()
    finally:
        get_settings.cache_clear()


@pytest.fixture
def oidc_client(oidc_env, seeded_web_engine, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from conftest import _wire_app

    with Session(seeded_web_engine) as db:
        ada = db.scalars(select(User).where(User.display_name == "Ada Approver")).one()
        db.info["actor_id"] = ada.id
        ada.email = "ada@example.org"
        db.commit()
    # https base URL — in oidc mode the session cookie is Secure and would be
    # dropped by the client over plain http.
    return TestClient(
        _wire_app(seeded_web_engine),
        follow_redirects=False,
        base_url="https://testserver",
    )


def test_login_page_shows_sso_button_and_dev_login_disabled(oidc_client):
    page = oidc_client.get("/login")
    assert page.status_code == 200
    assert "/auth/oidc/login" in page.text
    assert "Select a user" not in page.text
    # Dev login POST is not available outside dev mode
    assert oidc_client.post("/login", data={"user_id": "x", "csrf_token": "y"}).status_code == 404


def test_login_page_shows_denied_error(oidc_client):
    page = oidc_client.get("/login?error=denied")
    assert "Contact the IG team" in page.text


class _FakeIdp:
    def __init__(self, token):
        self._token = token

    async def authorize_access_token(self, request):
        return self._token


def test_callback_signs_in_known_user(oidc_client, seeded_web_engine, monkeypatch):
    monkeypatch.setattr(
        oidc_module,
        "_client",
        lambda: _FakeIdp({"userinfo": {"sub": ENTRA_SUB, "email": "ada@example.org"}}),
    )
    response = oidc_client.get("/auth/oidc/callback?code=x&state=y")
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    home = oidc_client.get("/")
    assert home.status_code == 200
    assert "Ada Approver" in home.text

    from sqlalchemy.orm import Session

    with Session(seeded_web_engine) as db:
        ada = db.scalars(select(User).where(User.display_name == "Ada Approver")).one()
        assert ada.oidc_subject == ENTRA_SUB
        assert (
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.event == "login_succeeded",
                    AuditEvent.entity_id == ada.id,
                )
            ).one()
            is not None
        )


def test_callback_denies_unknown_user(oidc_client, monkeypatch):
    monkeypatch.setattr(
        oidc_module,
        "_client",
        lambda: _FakeIdp({"userinfo": {"sub": "ghost", "email": "ghost@example.org"}}),
    )
    response = oidc_client.get("/auth/oidc/callback?code=x&state=y")
    assert response.status_code == 302
    assert response.headers["location"] == "/login?error=denied"
    assert oidc_client.get("/").status_code == 302  # still logged out


def test_oidc_routes_404_in_dev_mode(seeded_client):
    assert seeded_client.get("/auth/oidc/login").status_code == 404
    assert seeded_client.get("/auth/oidc/callback").status_code == 404

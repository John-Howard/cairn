from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.auth import require_role
from cairn.models import Role, User


def _extract_csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]


def _user_id(engine, display_name: str) -> str:
    with Session(engine) as db:
        return db.scalars(select(User).where(User.display_name == display_name)).one().id


def test_anonymous_get_redirects_to_login(seeded_client):
    response = seeded_client.get("/")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_healthz_needs_no_auth(seeded_client):
    response = seeded_client.get("/healthz")
    assert response.status_code == 200


def test_login_then_home_then_logout(seeded_client, seeded_web_engine):
    login_page = seeded_client.get("/login")
    assert login_page.status_code == 200
    token = _extract_csrf(login_page.text)
    approver_id = _user_id(seeded_web_engine, "Ada Approver")

    login_response = seeded_client.post(
        "/login", data={"user_id": approver_id, "csrf_token": token}
    )
    assert login_response.status_code == 302
    assert login_response.headers["location"] == "/"

    home = seeded_client.get("/")
    assert home.status_code == 200
    assert "Ada Approver" in home.text

    logout_page = seeded_client.get("/")
    logout_token = _extract_csrf(logout_page.text)
    logout_response = seeded_client.post("/logout", data={"csrf_token": logout_token})
    assert logout_response.status_code == 302
    assert logout_response.headers["location"] == "/login"

    after_logout = seeded_client.get("/")
    assert after_logout.status_code == 302


def test_viewer_cannot_reach_setup_once_it_exists(seeded_client, seeded_web_engine):
    login_page = seeded_client.get("/login")
    token = _extract_csrf(login_page.text)
    viewer_id = _user_id(seeded_web_engine, "Vic Viewer")
    seeded_client.post("/login", data={"user_id": viewer_id, "csrf_token": token})

    response = seeded_client.post("/setup", data={})
    assert response.status_code == 404


def test_inactive_user_excluded_from_login_and_rejected(seeded_client, seeded_web_engine):
    viewer_id = _user_id(seeded_web_engine, "Vic Viewer")
    with Session(seeded_web_engine) as db:
        db.info["actor_id"] = _user_id(seeded_web_engine, "Ada Approver")
        target = db.get(User, viewer_id)
        target.is_active = False
        db.commit()

    login_page = seeded_client.get("/login")
    assert "Vic Viewer" not in login_page.text
    token = _extract_csrf(login_page.text)

    response = seeded_client.post(
        "/login", data={"user_id": viewer_id, "csrf_token": token}
    )
    assert response.status_code == 400


class _StubURL:
    path = "/stub"


class _StubRequest:
    url = _StubURL()


def test_require_role_allows_matching_role(session):
    dependency = require_role(Role.APPROVER_DPO)
    approver = User(display_name="Ada", role=Role.APPROVER_DPO)
    assert dependency(_StubRequest(), user=approver, session=session) is approver


def test_require_role_denies_other_roles(session):
    dependency = require_role(Role.APPROVER_DPO)
    viewer = User(display_name="Vic", role=Role.VIEWER)
    session.add(viewer)
    session.flush()
    try:
        dependency(_StubRequest(), user=viewer, session=session)
        raised = False
    except Exception as exc:
        raised = True
        assert getattr(exc, "status_code", None) == 403
    assert raised


def _login_seeded(client, engine, display_name="Ada Approver"):
    token = _extract_csrf(client.get("/login").text)
    response = client.post(
        "/login", data={"user_id": _user_id(engine, display_name), "csrf_token": token}
    )
    assert response.status_code == 302
    return response


def test_session_cookie_carries_idle_max_age(seeded_client, seeded_web_engine):
    response = _login_seeded(seeded_client, seeded_web_engine)
    set_cookie = response.headers["set-cookie"]
    assert "cairn_session" in set_cookie
    assert "Max-Age=3600" in set_cookie


def test_session_expires_after_absolute_lifetime(
    seeded_client, seeded_web_engine, monkeypatch
):
    import cairn.auth as auth_module

    _login_seeded(seeded_client, seeded_web_engine)
    assert seeded_client.get("/").status_code == 200

    real_now = auth_module._now()
    monkeypatch.setattr(auth_module, "_now", lambda: real_now + 12 * 3600 + 60)
    response = seeded_client.get("/")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_session_without_auth_stamp_is_rejected(session):
    import pytest as _pytest

    from cairn.auth import LoginRequired, current_user

    class _StubRequest:
        def __init__(self):
            self.session = {"user_id": "someone"}

    with _pytest.raises(LoginRequired):
        current_user(_StubRequest(), session)

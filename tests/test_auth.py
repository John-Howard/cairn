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


def test_require_role_allows_matching_role():
    dependency = require_role(Role.APPROVER_DPO)
    approver = User(display_name="Ada", role=Role.APPROVER_DPO)
    assert dependency(user=approver) is approver


def test_require_role_denies_other_roles():
    dependency = require_role(Role.APPROVER_DPO)
    viewer = User(display_name="Vic", role=Role.VIEWER)
    try:
        dependency(user=viewer)
        raised = False
    except Exception as exc:
        raised = True
        assert getattr(exc, "status_code", None) == 403
    assert raised

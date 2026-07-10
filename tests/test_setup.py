from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cairn.models import (
    AuditEvent,
    BusinessFunction,
    LawfulBasisGeneral,
    OrganisationProfile,
    Role,
    User,
)


def test_anonymous_home_redirects_to_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_setup_form_renders(client):
    response = client.get("/setup")
    assert response.status_code == 200
    assert "Set up Cairn" in response.text


def test_setup_creates_profile_seeds_and_bootstrap_user(client, web_engine):
    get_response = client.get("/setup")
    token = _extract_csrf(get_response.text)

    response = client.post(
        "/setup",
        data={
            "csrf_token": token,
            "org_name": "Example Fire & Rescue Service",
            "org_type": "public_authority",
            "legal_entity_topology": "single",
            "applicable_regimes": ["general", "law_enforcement"],
            "active_modules": ["dpia"],
            "public_authority_guards": "true",
            "display_name": "Dana Dpo",
        },
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/"

    with Session(web_engine) as db:
        profile = db.scalars(select(OrganisationProfile)).one()
        assert profile.org_name == "Example Fire & Rescue Service"
        assert set(profile.applicable_regimes) == {"general", "law_enforcement"}
        assert "complaints" in profile.active_modules
        assert "dpia" in profile.active_modules

        art6_count = db.scalar(select(func.count()).select_from(LawfulBasisGeneral))
        assert art6_count == 7

        function_count = db.scalar(select(func.count()).select_from(BusinessFunction))
        assert function_count == 16

        bootstrap = db.scalars(select(User).where(User.display_name == "Dana Dpo")).one()
        assert bootstrap.role == Role.APPROVER_DPO

        event_query = select(AuditEvent).where(AuditEvent.event == "organisation_setup")
        events = db.scalars(event_query).all()
        assert len(events) == 1
        assert events[0].actor_id == bootstrap.id

    home = client.get("/")
    assert home.status_code == 200


def test_setup_404s_once_profile_exists(seeded_client):
    get_response = seeded_client.get("/setup")
    assert get_response.status_code == 404

    post_response = seeded_client.post("/setup", data={})
    assert post_response.status_code == 404


def _extract_csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]

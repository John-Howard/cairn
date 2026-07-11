from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import AuditEvent
from test_activities import _login


def _audit_events(engine, event: str = "register_exported") -> list[AuditEvent]:
    with Session(engine) as db:
        return db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "organisation_profile",
                AuditEvent.event == event,
            )
        ).all()


def test_download_art30_1_csv(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/register/export/art30_1")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    expected_filename = f"art30-1-{date.today().isoformat()}.csv"
    assert expected_filename in response.headers["content-disposition"]


def test_download_records_exactly_one_audit_event(activities_client, activities_web_engine):
    vic_id = _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/register/export/art30_1")
    assert response.status_code == 200

    events = _audit_events(activities_web_engine)
    assert len(events) == 1
    event = events[0]
    assert event.entity_type == "organisation_profile"
    assert event.event == "register_exported"
    assert event.actor_id == vic_id
    assert event.new_value["view"] == "art30_1"
    assert isinstance(event.new_value["rows"], int)


def test_download_with_no_matching_activities_returns_header_only(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/register/export/art30_1")
    assert response.status_code == 200
    lines = [line for line in response.text.splitlines() if line]
    assert len(lines) == 1

    events = _audit_events(activities_web_engine)
    assert events[0].new_value["rows"] == 0


def test_unknown_view_key_returns_404(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/register/export/not-a-real-view")
    assert response.status_code == 404


def test_s61_404_when_profile_lacks_law_enforcement(seeded_client, seeded_web_engine):
    _login(seeded_client, seeded_web_engine, "Vic Viewer")
    response = seeded_client.get("/register/export/s61")
    assert response.status_code == 404


def test_s61_200_when_profile_has_law_enforcement(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/register/export/s61")
    assert response.status_code == 200


def test_unauthenticated_download_redirects_to_login(activities_client):
    response = activities_client.get("/register/export/art30_1")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_register_page_shows_download_buttons(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/register")
    assert response.status_code == 200
    assert "/register/export/art30_1" in response.text
    assert "/register/export/art30_2" in response.text
    assert "/register/export/s61" in response.text
    assert "/register/export/combined" in response.text


def test_register_page_hides_s61_button_for_general_only_profile(seeded_client, seeded_web_engine):
    _login(seeded_client, seeded_web_engine, "Vic Viewer")
    response = seeded_client.get("/register")
    assert response.status_code == 200
    assert "/register/export/s61" not in response.text
    assert "/register/export/art30_1" in response.text

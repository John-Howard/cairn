import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.logs import JSONFormatter, security_event
from cairn.models import AuditEvent, User
from test_activities import _login


def _format(record: logging.LogRecord) -> dict:
    return json.loads(JSONFormatter().format(record))


def test_json_formatter_core_fields():
    record = logging.LogRecord(
        name="cairn.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )
    payload = _format(record)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "cairn.test"
    assert payload["message"] == "hello world"
    assert payload["time"].endswith("+00:00")


def test_json_formatter_includes_extra_fields():
    record = logging.LogRecord(
        name="cairn.security", level=logging.INFO, pathname=__file__, lineno=1,
        msg="authorisation_denied", args=(), exc_info=None,
    )
    record.path = "/users"
    record.required_roles = ["approver_dpo"]
    payload = _format(record)
    assert payload["path"] == "/users"
    assert payload["required_roles"] == ["approver_dpo"]


def test_security_event_emits_structured_record(caplog):
    with caplog.at_level(logging.INFO, logger="cairn.security"):
        security_event("test_event", path="/x", subject="abc")
    record = caplog.records[-1]
    assert record.event == "test_event"
    assert record.path == "/x"
    assert record.subject == "abc"


def test_rbac_denial_is_audited_and_logged(
    activities_client, activities_web_engine, caplog
):
    _login(activities_client, activities_web_engine, "Vic Viewer")
    with caplog.at_level(logging.INFO, logger="cairn.security"):
        response = activities_client.get("/intake")
    assert response.status_code == 403

    with Session(activities_web_engine) as db:
        vic = db.scalars(select(User).where(User.display_name == "Vic Viewer")).one()
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.event == "authorisation_denied",
                AuditEvent.entity_id == vic.id,
            )
        ).all()
        assert len(events) == 1
        assert events[0].new_value["path"] == "/intake"
        assert events[0].new_value["actual_role"] == "viewer"
        assert "contributor" in events[0].new_value["required_roles"]

    denial_logs = [r for r in caplog.records if getattr(r, "event", "") == "authorisation_denied"]
    assert denial_logs and denial_logs[-1].path == "/intake"


def test_logout_is_audited(activities_client, activities_web_engine):
    from test_activities import _extract_csrf

    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _extract_csrf(activities_client.get("/activities/new").text)
    response = activities_client.post("/logout", data={"csrf_token": token})
    assert response.status_code == 302

    with Session(activities_web_engine) as db:
        cara = db.scalars(select(User).where(User.display_name == "Cara Curator")).one()
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.event == "logout", AuditEvent.entity_id == cara.id
            )
        ).all()
        assert len(events) == 1
        assert events[0].actor_id == cara.id

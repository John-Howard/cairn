from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import AuditEvent, Role, User
from test_activities import _business_function_id, _extract_csrf, _login, _user_id


def _token(client, path="/users") -> str:
    page = client.get(path)
    return _extract_csrf(page.text)


def test_approver_can_list_users(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    response = activities_client.get("/users")
    assert response.status_code == 200
    assert "Cody Contributor" in response.text


def test_approver_creates_viewer(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    token = _token(activities_client, "/users/new")
    response = activities_client.post(
        "/users",
        data={
            "csrf_token": token,
            "display_name": "New Viewer",
            "role": "viewer",
            "business_function_id": "",
        },
    )
    assert response.status_code == 302, response.text
    with Session(activities_web_engine) as db:
        created = db.scalars(select(User).where(User.display_name == "New Viewer")).one()
        assert created.role == Role.VIEWER
        assert created.business_function_id is None
        assert created.is_active is True


def test_contributor_role_requires_business_function(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    token = _token(activities_client, "/users/new")
    response = activities_client.post(
        "/users",
        data={
            "csrf_token": token,
            "display_name": "New Contributor",
            "role": "contributor",
            "business_function_id": "",
        },
    )
    assert response.status_code == 422
    assert "Select a business function" in response.text


def test_contributor_role_with_business_function_ok(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    token = _token(activities_client, "/users/new")
    response = activities_client.post(
        "/users",
        data={
            "csrf_token": token,
            "display_name": "New Contributor",
            "role": "contributor",
            "business_function_id": prevention_id,
        },
    )
    assert response.status_code == 302, response.text
    with Session(activities_web_engine) as db:
        created = db.scalars(
            select(User).where(User.display_name == "New Contributor")
        ).one()
        assert created.business_function_id == prevention_id


def test_non_contributor_role_clears_business_function(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    token = _token(activities_client, "/users/new")
    response = activities_client.post(
        "/users",
        data={
            "csrf_token": token,
            "display_name": "New Curator",
            "role": "curator",
            "business_function_id": prevention_id,
        },
    )
    assert response.status_code == 302, response.text
    with Session(activities_web_engine) as db:
        created = db.scalars(select(User).where(User.display_name == "New Curator")).one()
        assert created.business_function_id is None


def test_edit_user_role_change_records_audit_event(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    cara_id = _user_id(activities_web_engine, "Cara Curator")
    token = _token(activities_client, f"/users/{cara_id}/edit")
    response = activities_client.post(
        f"/users/{cara_id}",
        data={
            "csrf_token": token,
            "display_name": "Cara Curator",
            "role": "approver_dpo",
            "business_function_id": "",
        },
    )
    assert response.status_code == 302, response.text
    with Session(activities_web_engine) as db:
        updated = db.get(User, cara_id)
        assert updated.role == Role.APPROVER_DPO
        event = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "user",
                AuditEvent.entity_id == cara_id,
                AuditEvent.event == "user_role_change",
            )
        ).one()
        assert event.old_value == {"role": "curator"}
        assert event.new_value == {"role": "approver_dpo"}


def test_deactivate_and_reactivate_user(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    cody_id = _user_id(activities_web_engine, "Cody Contributor")
    token = _token(activities_client)
    response = activities_client.post(
        f"/users/{cody_id}/deactivate", data={"csrf_token": token}
    )
    assert response.status_code == 302, response.text
    with Session(activities_web_engine) as db:
        target = db.get(User, cody_id)
        assert target.is_active is False
        event = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "user",
                AuditEvent.entity_id == cody_id,
                AuditEvent.event == "user_deactivated",
            )
        ).one()
        assert event is not None

    token = _token(activities_client)
    response = activities_client.post(
        f"/users/{cody_id}/reactivate", data={"csrf_token": token}
    )
    assert response.status_code == 302, response.text
    with Session(activities_web_engine) as db:
        target = db.get(User, cody_id)
        assert target.is_active is True
        event = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "user",
                AuditEvent.entity_id == cody_id,
                AuditEvent.event == "user_reactivated",
            )
        ).one()
        assert event is not None


def test_self_deactivation_forbidden(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    ada_id = _user_id(activities_web_engine, "Ada Approver")
    token = _token(activities_client)
    response = activities_client.post(
        f"/users/{ada_id}/deactivate", data={"csrf_token": token}
    )
    assert response.status_code == 422


def test_deactivating_already_deactivated_user_fails(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    cody_id = _user_id(activities_web_engine, "Cody Contributor")
    token = _token(activities_client)
    activities_client.post(f"/users/{cody_id}/deactivate", data={"csrf_token": token})
    token = _token(activities_client)
    response = activities_client.post(
        f"/users/{cody_id}/deactivate", data={"csrf_token": token}
    )
    assert response.status_code == 422


def test_reactivating_active_user_fails(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    cody_id = _user_id(activities_web_engine, "Cody Contributor")
    token = _token(activities_client)
    response = activities_client.post(
        f"/users/{cody_id}/reactivate", data={"csrf_token": token}
    )
    assert response.status_code == 422


def test_non_approver_roles_forbidden(activities_client, activities_web_engine):
    for role_name in ("Cara Curator", "Cody Contributor", "Vic Viewer"):
        _login(activities_client, activities_web_engine, role_name)
        assert activities_client.get("/users").status_code == 403
        assert activities_client.get("/users/new").status_code == 403
        target_id = _user_id(activities_web_engine, "Cody Contributor")
        assert activities_client.get(f"/users/{target_id}/edit").status_code == 403
        assert (
            activities_client.post(
                "/users", data={"csrf_token": "no-token"}
            ).status_code
            == 403
        )
        assert (
            activities_client.post(
                f"/users/{target_id}", data={"csrf_token": "no-token"}
            ).status_code
            == 403
        )
        assert (
            activities_client.post(
                f"/users/{target_id}/deactivate", data={"csrf_token": "no-token"}
            ).status_code
            == 403
        )
        assert (
            activities_client.post(
                f"/users/{target_id}/reactivate", data={"csrf_token": "no-token"}
            ).status_code
            == 403
        )


def test_deactivated_user_absent_from_login_and_owner_picker(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Ada Approver")
    cody_id = _user_id(activities_web_engine, "Cody Contributor")
    token = _token(activities_client)
    activities_client.post(f"/users/{cody_id}/deactivate", data={"csrf_token": token})

    login_page = activities_client.get("/login")
    assert "Cody Contributor" not in login_page.text
    login_token = _extract_csrf(login_page.text)
    response = activities_client.post(
        "/login", data={"user_id": cody_id, "csrf_token": login_token}
    )
    assert response.status_code == 400

    new_activity_page = activities_client.get("/activities/new")
    assert "Cody Contributor" not in new_activity_page.text


def test_deactivated_user_still_active_session_redirected_to_login(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Cody Contributor")
    ada_id = _user_id(activities_web_engine, "Ada Approver")
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = ada_id
        target = db.scalars(
            select(User).where(User.display_name == "Cody Contributor")
        ).one()
        target.is_active = False
        db.commit()

    response = activities_client.get("/")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_deactivated_user_still_renders_by_name_where_already_owner(
    activities_client, activities_web_engine
):
    from test_activities import _create_activity

    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cody Contributor"
    )
    _login(activities_client, activities_web_engine, "Ada Approver")
    token = _token(activities_client)
    cody_id = _user_id(activities_web_engine, "Cody Contributor")
    activities_client.post(f"/users/{cody_id}/deactivate", data={"csrf_token": token})

    detail_page = activities_client.get(f"/activities/{activity_id}")
    assert "Cody Contributor" in detail_page.text

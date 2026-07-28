from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import (
    ActivitySecurity,
    AuditEvent,
    EntryStatus,
    InformationAsset,
    RecordVersion,
    SecurityMeasure,
    SecurityMeasureCategory,
)
from test_activities import _create_activity, _extract_csrf, _login, _user_id


def _asset_token(client) -> str:
    return _extract_csrf(client.get("/assets/new").text)


def _minimal_asset_data(csrf_token: str, **overrides) -> dict:
    data = {
        "csrf_token": csrf_token,
        "label": "Test Asset",
        "asset_type": "system",
        "description": "",
        "iao_user_id": "",
        "custodian": "",
        "business_function_id": "",
        "classification": "not_classified",
        "status": "in_use",
        "next_review_date": "",
        "supplier_entity_id": "",
        "owner": "",
        "location": "",
        "hosting_country": "",
        "default_retention_id": "",
        "notes": "",
    }
    data.update(overrides)
    return data


def _create_asset(client, engine, *, login_as: str, **overrides) -> str:
    _login(client, engine, login_as)
    token = _asset_token(client)
    data = _minimal_asset_data(token, **overrides)
    response = client.post("/assets", data=data)
    assert response.status_code == 302, response.text
    return response.headers["location"].removeprefix("/assets/")


def test_register_list_renders(activities_client, activities_web_engine):
    _create_asset(
        activities_client, activities_web_engine, login_as="Cara Curator", label="System A"
    )
    response = activities_client.get("/assets")
    assert response.status_code == 200
    assert "System A" in response.text


def test_register_filters_by_type_personal_data_overdue_and_mine(
    activities_client, activities_web_engine
):
    curator_id = _user_id(activities_web_engine, "Cara Curator")
    _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        label="Case Management System",
        asset_type="system",
        contains_personal_data="true",
        iao_user_id=curator_id,
        next_review_date="2020-01-01",
    )
    _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        label="Paper Files",
        asset_type="paper",
    )

    only_system = activities_client.get("/assets", params={"asset_type": "system"})
    assert "Case Management System" in only_system.text
    assert "Paper Files" not in only_system.text

    only_personal = activities_client.get("/assets", params={"contains_personal_data": "true"})
    assert "Case Management System" in only_personal.text
    assert "Paper Files" not in only_personal.text

    overdue = activities_client.get("/assets", params={"review_overdue": "true"})
    assert "Case Management System" in overdue.text
    assert "Paper Files" not in overdue.text

    mine = activities_client.get("/assets", params={"mine": "true"})
    assert "Case Management System" in mine.text
    assert "Paper Files" not in mine.text


def test_curator_create_is_approved(activities_client, activities_web_engine):
    asset_id = _create_asset(
        activities_client, activities_web_engine, login_as="Cara Curator", label="Curator Asset"
    )
    with Session(activities_web_engine) as db:
        asset = db.get(InformationAsset, asset_id)
        assert asset.entry_status == EntryStatus.APPROVED


def test_contributor_create_is_proposed(activities_client, activities_web_engine):
    asset_id = _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cody Contributor",
        label="Contributor Asset",
    )
    with Session(activities_web_engine) as db:
        asset = db.get(InformationAsset, asset_id)
        assert asset.entry_status == EntryStatus.PROPOSED


def test_dpo_approves_proposal_and_records_audit_event(activities_client, activities_web_engine):
    asset_id = _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cody Contributor",
        label="Proposed Asset",
    )
    _login(activities_client, activities_web_engine, "Ada Approver")
    token = _extract_csrf(activities_client.get("/assets").text)
    response = activities_client.post(
        f"/assets/{asset_id}/approve", data={"csrf_token": token}
    )
    assert response.status_code == 302

    with Session(activities_web_engine) as db:
        asset = db.get(InformationAsset, asset_id)
        assert asset.entry_status == EntryStatus.APPROVED
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == asset_id, AuditEvent.event == "asset_approved"
            )
        ).all()
        assert len(events) == 1


def test_dpo_rejects_proposal_and_records_audit_event(activities_client, activities_web_engine):
    asset_id = _create_asset(
        activities_client, activities_web_engine, login_as="Cody Contributor", label="Reject Me"
    )
    _login(activities_client, activities_web_engine, "Ada Approver")
    token = _extract_csrf(activities_client.get("/assets").text)
    response = activities_client.post(
        f"/assets/{asset_id}/reject", data={"csrf_token": token, "reason": "Not needed"}
    )
    assert response.status_code == 302

    with Session(activities_web_engine) as db:
        asset = db.get(InformationAsset, asset_id)
        assert asset.entry_status == EntryStatus.REJECTED
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == asset_id, AuditEvent.event == "asset_rejected"
            )
        ).all()
        assert len(events) == 1
        assert events[0].reason == "Not needed"


def test_contributor_cannot_approve(activities_client, activities_web_engine):
    asset_id = _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cody Contributor",
        label="Cannot Approve",
    )
    token = _extract_csrf(activities_client.get("/assets").text)
    response = activities_client.post(
        f"/assets/{asset_id}/approve", data={"csrf_token": token}
    )
    assert response.status_code == 403


def test_edit_updates_fields_bumps_version_and_records_audit_event(
    activities_client, activities_web_engine
):
    asset_id = _create_asset(
        activities_client, activities_web_engine, login_as="Cara Curator", label="Original Label"
    )
    with Session(activities_web_engine) as db:
        version_before = db.get(InformationAsset, asset_id).version

    edit_page = activities_client.get(f"/assets/{asset_id}/edit")
    assert edit_page.status_code == 200
    token = _extract_csrf(edit_page.text)
    data = _minimal_asset_data(token, label="Updated Label", change_note="renamed")
    response = activities_client.post(f"/assets/{asset_id}", data=data)
    assert response.status_code == 302

    with Session(activities_web_engine) as db:
        asset = db.get(InformationAsset, asset_id)
        assert asset.label == "Updated Label"
        assert asset.version == version_before + 1
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == asset_id, AuditEvent.event == "asset_updated"
            )
        ).all()
        assert len(events) == 1
        versions = db.scalars(
            select(RecordVersion).where(RecordVersion.entity_id == asset_id)
        ).all()
        assert len(versions) == 1


def test_detail_shows_linked_activity_and_gap_flags(activities_client, activities_web_engine):
    curator_id = _user_id(activities_web_engine, "Cara Curator")
    linked_asset_id = _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        label="Linked Personal Data Asset",
        contains_personal_data="true",
        iao_user_id=curator_id,
    )
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    link_token = _extract_csrf(activities_client.get(f"/activities/{activity_id}").text)
    activities_client.post(
        f"/activities/{activity_id}/assets",
        data={"csrf_token": link_token, "item_id": linked_asset_id},
    )

    linked_detail = activities_client.get(f"/assets/{linked_asset_id}")
    assert linked_detail.status_code == 200
    assert "Test Activity" in linked_detail.text
    assert "undocumented processing" not in linked_detail.text
    assert "No Information Asset Owner" not in linked_detail.text

    orphan_asset_id = _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        label="Orphan Personal Data Asset",
        contains_personal_data="true",
        next_review_date=(date.today() - timedelta(days=10)).isoformat(),
    )
    orphan_detail = activities_client.get(f"/assets/{orphan_asset_id}")
    assert "No Information Asset Owner is set" in orphan_detail.text
    assert "undocumented processing" in orphan_detail.text
    assert "overdue" in orphan_detail.text


def test_security_measure_junction_syncs_into_linked_activities(
    activities_client, activities_web_engine
):
    asset_id = _create_asset(
        activities_client, activities_web_engine, login_as="Cara Curator", label="Synced Asset"
    )
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    link_token = _extract_csrf(activities_client.get(f"/activities/{activity_id}").text)
    activities_client.post(
        f"/activities/{activity_id}/assets",
        data={"csrf_token": link_token, "item_id": asset_id},
    )

    with Session(activities_web_engine) as db:
        measure = SecurityMeasure(
            label="disk encryption", category=SecurityMeasureCategory.TECHNICAL
        )
        db.add(measure)
        db.commit()
        measure_id = measure.id

    add_token = _extract_csrf(activities_client.get(f"/assets/{asset_id}").text)
    add_response = activities_client.post(
        f"/assets/{asset_id}/security-measures",
        data={"csrf_token": add_token, "item_id": measure_id},
    )
    assert add_response.status_code == 302

    activity_detail = activities_client.get(f"/activities/{activity_id}")
    assert "disk encryption" in activity_detail.text
    assert "Inherited from assets" in activity_detail.text

    with Session(activities_web_engine) as db:
        link = db.scalars(
            select(ActivitySecurity).where(
                ActivitySecurity.activity_id == activity_id,
                ActivitySecurity.security_measure_id == measure_id,
            )
        ).one()
        assert link.inherited_from_system is True

    remove_token = _extract_csrf(activities_client.get(f"/assets/{asset_id}").text)
    remove_response = activities_client.post(
        f"/assets/{asset_id}/security-measures/{measure_id}/remove",
        data={"csrf_token": remove_token},
    )
    assert remove_response.status_code == 302

    after_remove = activities_client.get(f"/activities/{activity_id}")
    assert "Inherited from assets" not in after_remove.text
    with Session(activities_web_engine) as db:
        remaining = db.scalars(
            select(ActivitySecurity).where(
                ActivitySecurity.activity_id == activity_id,
                ActivitySecurity.security_measure_id == measure_id,
            )
        ).all()
        assert remaining == []

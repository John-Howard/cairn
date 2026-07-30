from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import (
    ActivitySecurity,
    AuditEvent,
    EntryStatus,
    InformationAsset,
    ProcessingActivity,
    RecordVersion,
    SecurityMeasure,
    SecurityMeasureCategory,
)
from test_activities import (
    _business_function_id,
    _create_activity,
    _extract_csrf,
    _login,
    _user_id,
)


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
        "business_functions": [],
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


def test_register_filter_by_business_function_is_any_match(
    activities_client, activities_web_engine
):
    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    protection_id = _business_function_id(
        activities_web_engine, "Protection (Fire Safety Regulation & Enforcement)"
    )
    hr_id = _business_function_id(activities_web_engine, "HR")
    _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        label="Dual Function Asset",
        business_functions=[prevention_id, protection_id],
    )
    _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        label="HR Only Asset",
        business_functions=[hr_id],
    )

    under_prevention = activities_client.get(
        "/assets", params={"business_function_id": prevention_id}
    )
    assert "Dual Function Asset" in under_prevention.text
    assert "HR Only Asset" not in under_prevention.text

    under_protection = activities_client.get(
        "/assets", params={"business_function_id": protection_id}
    )
    assert "Dual Function Asset" in under_protection.text
    assert "HR Only Asset" not in under_protection.text

    under_hr = activities_client.get("/assets", params={"business_function_id": hr_id})
    assert "HR Only Asset" in under_hr.text
    assert "Dual Function Asset" not in under_hr.text


def test_detail_and_export_show_joined_business_function_labels(
    activities_client, activities_web_engine
):
    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    protection_id = _business_function_id(
        activities_web_engine, "Protection (Fire Safety Regulation & Enforcement)"
    )
    asset_id = _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        label="Joined Label Asset",
        business_functions=[prevention_id, protection_id],
    )

    detail = activities_client.get(f"/assets/{asset_id}")
    assert (
        "Prevention &amp; Community Safety; Protection (Fire Safety Regulation &amp; Enforcement)"
        in detail.text
    )

    export = activities_client.get("/assets/export.csv")
    assert "Business functions" in export.text
    assert (
        "Prevention & Community Safety; Protection (Fire Safety Regulation & Enforcement)"
        in export.text
    )


def test_curator_create_is_approved(activities_client, activities_web_engine):
    asset_id = _create_asset(
        activities_client, activities_web_engine, login_as="Cara Curator", label="Curator Asset"
    )
    with Session(activities_web_engine) as db:
        asset = db.get(InformationAsset, asset_id)
        assert asset.entry_status == EntryStatus.APPROVED


def _checkbox_is_checked(html: str, name: str, value: str) -> bool:
    marker = f'id="{name}-{value}"'
    start = html.index(marker)
    end = html.index(">", start)
    return "checked" in html[start:end]


def test_create_with_two_business_functions_via_form(activities_client, activities_web_engine):
    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    protection_id = _business_function_id(
        activities_web_engine, "Protection (Fire Safety Regulation & Enforcement)"
    )
    asset_id = _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        label="Multi-Function Asset",
        business_functions=[prevention_id, protection_id],
    )
    with Session(activities_web_engine) as db:
        asset = db.get(InformationAsset, asset_id)
        assert {bf.id for bf in asset.business_functions} == {prevention_id, protection_id}

    edit_page = activities_client.get(f"/assets/{asset_id}/edit")
    assert _checkbox_is_checked(edit_page.text, "business_functions", prevention_id)
    assert _checkbox_is_checked(edit_page.text, "business_functions", protection_id)


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


def test_document_processing_creates_linked_draft_with_inherited_security(
    activities_client, activities_web_engine
):
    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    asset_id = _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        label="Case System",
        business_functions=[prevention_id],
    )
    with Session(activities_web_engine) as db:
        measure = SecurityMeasure(
            label="disk encryption", category=SecurityMeasureCategory.TECHNICAL
        )
        db.add(measure)
        db.commit()
        measure_id = measure.id
    add_token = _extract_csrf(activities_client.get(f"/assets/{asset_id}").text)
    activities_client.post(
        f"/assets/{asset_id}/security-measures",
        data={"csrf_token": add_token, "item_id": measure_id},
    )

    token = _extract_csrf(activities_client.get(f"/assets/{asset_id}").text)
    response = activities_client.post(
        f"/assets/{asset_id}/document-processing", data={"csrf_token": token}
    )
    assert response.status_code == 302
    activity_id = response.headers["location"].removeprefix("/activities/")

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.record_status.value == "draft"
        assert asset_id in {a.id for a in activity.assets}
        link = db.scalars(
            select(ActivitySecurity).where(
                ActivitySecurity.activity_id == activity_id,
                ActivitySecurity.security_measure_id == measure_id,
            )
        ).one()
        assert link.inherited_from_system is True

        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == activity_id,
                AuditEvent.event == "activity_created_from_asset",
            )
        ).all()
        assert len(events) == 1


def test_document_processing_copies_business_function_from_asset(
    activities_client, activities_web_engine
):
    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    asset_id = _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        label="Functional Asset",
        business_functions=[prevention_id],
    )
    token = _extract_csrf(activities_client.get(f"/assets/{asset_id}").text)
    response = activities_client.post(
        f"/assets/{asset_id}/document-processing", data={"csrf_token": token}
    )
    assert response.status_code == 302
    activity_id = response.headers["location"].removeprefix("/activities/")

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.business_function_id == prevention_id


def test_document_processing_falls_back_to_users_function_when_asset_has_several(
    activities_client, activities_web_engine
):
    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    protection_id = _business_function_id(
        activities_web_engine, "Protection (Fire Safety Regulation & Enforcement)"
    )
    asset_id = _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        label="Multi Function Asset",
        business_functions=[prevention_id, protection_id],
    )
    _login(activities_client, activities_web_engine, "Cody Contributor")
    token = _extract_csrf(activities_client.get(f"/assets/{asset_id}").text)
    response = activities_client.post(
        f"/assets/{asset_id}/document-processing", data={"csrf_token": token}
    )
    assert response.status_code == 302
    activity_id = response.headers["location"].removeprefix("/activities/")

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.business_function_id == prevention_id


def test_document_processing_422_when_asset_and_user_have_no_function(
    activities_client, activities_web_engine
):
    asset_id = _create_asset(
        activities_client, activities_web_engine, login_as="Cara Curator", label="No Function Asset"
    )
    token = _extract_csrf(activities_client.get(f"/assets/{asset_id}").text)
    response = activities_client.post(
        f"/assets/{asset_id}/document-processing", data={"csrf_token": token}
    )
    assert response.status_code == 422


def test_document_processing_422_for_proposed_asset(activities_client, activities_web_engine):
    asset_id = _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cody Contributor",
        label="Still Proposed",
    )
    token = _extract_csrf(activities_client.get(f"/assets/{asset_id}").text)
    response = activities_client.post(
        f"/assets/{asset_id}/document-processing", data={"csrf_token": token}
    )
    assert response.status_code == 422


def test_document_processing_403_for_viewer(activities_client, activities_web_engine):
    asset_id = _create_asset(
        activities_client, activities_web_engine, login_as="Cara Curator", label="Viewer Blocked"
    )
    _login(activities_client, activities_web_engine, "Vic Viewer")
    token = _extract_csrf(activities_client.get(f"/assets/{asset_id}").text)
    response = activities_client.post(
        f"/assets/{asset_id}/document-processing", data={"csrf_token": token}
    )
    assert response.status_code == 403


def test_document_processing_403_for_contributor_wrong_function(
    activities_client, activities_web_engine
):
    protection_id = _business_function_id(
        activities_web_engine, "Protection (Fire Safety Regulation & Enforcement)"
    )
    asset_id = _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        label="Protection Asset",
        business_functions=[protection_id],
    )
    _login(activities_client, activities_web_engine, "Cody Contributor")
    token = _extract_csrf(activities_client.get(f"/assets/{asset_id}").text)
    response = activities_client.post(
        f"/assets/{asset_id}/document-processing", data={"csrf_token": token}
    )
    assert response.status_code == 403


def test_export_csv_content_filters_and_audit_event(activities_client, activities_web_engine):
    _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        label="Exportable System",
        asset_type="system",
    )
    _create_asset(
        activities_client,
        activities_web_engine,
        login_as="Cara Curator",
        label="Exportable Paper",
        asset_type="paper",
    )

    all_export = activities_client.get("/assets/export.csv")
    assert all_export.status_code == 200
    assert "text/csv" in all_export.headers["content-type"]
    assert "Exportable System" in all_export.text
    assert "Exportable Paper" in all_export.text

    filtered_export = activities_client.get("/assets/export.csv", params={"asset_type": "system"})
    assert "Exportable System" in filtered_export.text
    assert "Exportable Paper" not in filtered_export.text

    with Session(activities_web_engine) as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.event == "iar_exported")
        ).all()
        assert len(events) == 2


def test_asset_notes_preserve_stored_line_breaks(activities_client, activities_web_engine):
    """Intake writes multi-line notes; without the class they render as one
    run-on paragraph (the CSP rules out doing this with an inline style)."""
    from cairn.models import AssetType, InformationAsset

    with Session(activities_web_engine) as db:
        asset = InformationAsset(
            label="Multi-line notes asset",
            asset_type=AssetType.SYSTEM,
            notes="First line\nSecond line",
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    _login(activities_client, activities_web_engine, "Cara Curator")
    response = activities_client.get(f"/assets/{asset_id}")
    assert response.status_code == 200
    assert "cairn-preserve-lines" in response.text
    marker = "cairn-preserve-lines\">First line"
    assert marker in response.text

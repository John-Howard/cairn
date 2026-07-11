from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import (
    ActivityDataCategory,
    ActivityDomain,
    AuditEvent,
    DataSubjectCategory,
    EntryStatus,
    LawfulBasisRecord,
    LifecycleStage,
    PersonalDataCategory,
    ProcessingActivity,
    Recipient,
    RecipientType,
    RecordStatus,
    RecordVersion,
    Regime,
    RegimeScope,
    User,
)
from cairn.regime import set_regime_policy
from conftest import art6, business_function


def _extract_csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]


def _user_id(engine, display_name: str) -> str:
    with Session(engine) as db:
        return db.scalars(select(User).where(User.display_name == display_name)).one().id


def _login(client, engine, display_name: str) -> str:
    login_page = client.get("/login")
    token = _extract_csrf(login_page.text)
    user_id = _user_id(engine, display_name)
    response = client.post("/login", data={"user_id": user_id, "csrf_token": token})
    assert response.status_code == 302
    return user_id


def _token(client) -> str:
    page = client.get("/activities/new")
    return _extract_csrf(page.text)


def _business_function_id(engine, label: str) -> str:
    with Session(engine) as db:
        return business_function(db, label).id


def _minimal_create_data(
    csrf_token: str, business_function_id: str, owner_id: str, **overrides
) -> dict:
    data = {
        "csrf_token": csrf_token,
        "name": "Test Activity",
        "reference": "",
        "business_function_id": business_function_id,
        "description": "",
        "activity_type": "operational",
        "activity_domain": "",
        "controller_or_processor": "controller",
        "lifecycle_stage": "live",
        "trial_start": "",
        "trial_end": "",
        "purpose": "A purpose",
        "categories_of_processing": "",
        "personal_data_source": ["from_data_subject"],
        "external_data_use_mode": "none",
        "lineage_granularity": "activity",
        "owner_id": owner_id,
        "last_reviewed_at": "",
        "next_review_at": "2026-12-01",
    }
    data.update(overrides)
    return data


def _create_activity(client, engine, *, login_as: str, **overrides) -> str:
    _login(client, engine, login_as)
    token = _token(client)
    prevention_id = _business_function_id(engine, "Prevention & Community Safety")
    owner_id = _user_id(engine, login_as)
    data = _minimal_create_data(token, prevention_id, owner_id, **overrides)
    response = client.post("/activities", data=data)
    assert response.status_code == 302, response.text
    return response.headers["location"].removeprefix("/activities/")


def test_list_renders_and_filters(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    protection_id = _business_function_id(
        activities_web_engine, "Protection (Fire Safety Regulation & Enforcement)"
    )
    approver_id = _user_id(activities_web_engine, "Ada Approver")
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = approver_id
        db.add_all(
            [
                ProcessingActivity(
                    name="Alpha Activity",
                    business_function_id=prevention_id,
                    purpose="Purpose A",
                    personal_data_source=["from_data_subject"],
                    owner_id=approver_id,
                    next_review_at=date(2026, 12, 1),
                    record_status=RecordStatus.DRAFT,
                ),
                ProcessingActivity(
                    name="Beta Activity",
                    business_function_id=protection_id,
                    purpose="Purpose B",
                    personal_data_source=["from_data_subject"],
                    owner_id=approver_id,
                    next_review_at=date(2026, 12, 1),
                    record_status=RecordStatus.ACTIVE,
                ),
            ]
        )
        db.commit()

    response = activities_client.get("/activities")
    assert response.status_code == 200
    assert "Alpha Activity" in response.text
    assert "Beta Activity" in response.text

    filtered = activities_client.get(f"/activities?business_function={prevention_id}")
    assert "Alpha Activity" in filtered.text
    assert "Beta Activity" not in filtered.text

    by_status = activities_client.get("/activities?record_status=active")
    assert "Beta Activity" in by_status.text
    assert "Alpha Activity" not in by_status.text


def test_create_contributor_own_function_ok(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cody Contributor")
    token = _token(activities_client)
    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    owner_id = _user_id(activities_web_engine, "Cody Contributor")
    data = _minimal_create_data(token, prevention_id, owner_id)
    response = activities_client.post("/activities", data=data)
    assert response.status_code == 302
    activity_id = response.headers["location"].removeprefix("/activities/")

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.record_status == RecordStatus.DRAFT
        assert activity.regime == Regime.GENERAL
        assert activity.regime_source.value == "policy"


def test_create_contributor_other_function_forbidden(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cody Contributor")
    token = _token(activities_client)
    protection_id = _business_function_id(
        activities_web_engine, "Protection (Fire Safety Regulation & Enforcement)"
    )
    owner_id = _user_id(activities_web_engine, "Cody Contributor")
    data = _minimal_create_data(token, protection_id, owner_id)
    response = activities_client.post("/activities", data=data)
    assert response.status_code == 403


def test_create_viewer_forbidden(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/activities/new")
    assert response.status_code == 403

    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    owner_id = _user_id(activities_web_engine, "Vic Viewer")
    data = _minimal_create_data("no-token", prevention_id, owner_id)
    response = activities_client.post("/activities", data=data)
    assert response.status_code == 403


def test_processor_requires_categories_of_processing(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _token(activities_client)
    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    owner_id = _user_id(activities_web_engine, "Cara Curator")
    data = _minimal_create_data(
        token, prevention_id, owner_id, controller_or_processor="processor"
    )
    response = activities_client.post("/activities", data=data)
    assert response.status_code == 422
    assert "categories of processing" in response.text.lower()


def test_edit_round_trip_preserves_fields_and_versions(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )

    edit_page = activities_client.get(f"/activities/{activity_id}/edit")
    assert edit_page.status_code == 200
    token = _extract_csrf(edit_page.text)
    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    owner_id = _user_id(activities_web_engine, "Cara Curator")
    data = _minimal_create_data(
        token,
        prevention_id,
        owner_id,
        name="Renamed Activity",
        description="Updated description",
        change_note="Renamed and clarified description",
    )
    response = activities_client.post(f"/activities/{activity_id}", data=data)
    assert response.status_code == 302

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.name == "Renamed Activity"
        assert activity.description == "Updated description"
        version = db.scalars(
            select(RecordVersion).where(
                RecordVersion.entity_type == "processing_activity",
                RecordVersion.entity_id == activity_id,
            )
        ).one()
        assert version.version_change_note == "Renamed and clarified description"


def test_version_timeline_shows_after_edit(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    edit_page = activities_client.get(f"/activities/{activity_id}/edit")
    token = _extract_csrf(edit_page.text)
    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    owner_id = _user_id(activities_web_engine, "Cara Curator")
    data = _minimal_create_data(
        token, prevention_id, owner_id, change_note="Version timeline check"
    )
    activities_client.post(f"/activities/{activity_id}", data=data)

    detail = activities_client.get(f"/activities/{activity_id}")
    assert detail.status_code == 200
    assert "Version timeline check" in detail.text


def test_le_fields_render_for_law_enforcement_absent_for_general(
    activities_client, activities_web_engine
):
    approver_id = _user_id(activities_web_engine, "Ada Approver")
    with Session(activities_web_engine) as db:
        approver = db.get(User, approver_id)
        db.info["actor_id"] = approver_id
        set_regime_policy(
            db,
            domain=ActivityDomain.FIRE_SAFETY_ENFORCEMENT,
            regime=Regime.LAW_ENFORCEMENT,
            reason="Fire-safety enforcement treated as competent-authority processing",
            actor=approver,
        )
        db.commit()

    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _token(activities_client)
    protection_id = _business_function_id(
        activities_web_engine, "Protection (Fire Safety Regulation & Enforcement)"
    )
    owner_id = _user_id(activities_web_engine, "Cara Curator")
    le_data = _minimal_create_data(
        token, protection_id, owner_id, activity_domain="fire_safety_enforcement"
    )
    le_response = activities_client.post("/activities", data=le_data)
    assert le_response.status_code == 302
    le_activity_id = le_response.headers["location"].removeprefix("/activities/")

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, le_activity_id)
        assert activity.regime == Regime.LAW_ENFORCEMENT

    le_edit = activities_client.get(f"/activities/{le_activity_id}/edit")
    assert 'name="le_data_subject_classification"' in le_edit.text

    general_id = _create_activity(activities_client, activities_web_engine, login_as="Cara Curator")
    general_edit = activities_client.get(f"/activities/{general_id}/edit")
    assert 'name="le_data_subject_classification"' not in general_edit.text


def test_junction_add_remove_round_trip_with_data_category_scope(
    activities_client, activities_web_engine
):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    token = _token(activities_client)

    with Session(activities_web_engine) as db:
        subject = db.scalars(
            select(DataSubjectCategory).where(
                DataSubjectCategory.label == "members of the public"
            )
        ).one()
        category = db.scalars(
            select(PersonalDataCategory).where(
                PersonalDataCategory.label == "contact details"
            )
        ).one()
        subject_id, category_id = subject.id, category.id

    add_subject = activities_client.post(
        f"/activities/{activity_id}/data-subjects",
        data={"csrf_token": token, "item_id": subject_id},
    )
    assert add_subject.status_code == 302

    add_category = activities_client.post(
        f"/activities/{activity_id}/data-categories",
        data={
            "csrf_token": token,
            "category_id": category_id,
            "data_subject_scope_id": subject_id,
        },
    )
    assert add_category.status_code == 302

    detail = activities_client.get(f"/activities/{activity_id}")
    assert "members of the public" in detail.text
    assert "contact details" in detail.text

    with Session(activities_web_engine) as db:
        link = db.scalars(
            select(ActivityDataCategory).where(
                ActivityDataCategory.activity_id == activity_id,
                ActivityDataCategory.category_id == category_id,
            )
        ).one()
        assert link.data_subject_scope_id == subject_id
        link_id = link.id

    hx_add = activities_client.post(
        f"/activities/{activity_id}/data-categories/{link_id}/remove",
        data={"csrf_token": token},
        headers={"HX-Request": "true"},
    )
    assert hx_add.status_code == 200
    assert 'id="findings-panel"' in hx_add.text

    remove_subject = activities_client.post(
        f"/activities/{activity_id}/data-subjects/{subject_id}/remove",
        data={"csrf_token": token},
    )
    assert remove_subject.status_code == 302

    with Session(activities_web_engine) as db:
        remaining_links = db.scalars(
            select(ActivityDataCategory).where(ActivityDataCategory.activity_id == activity_id)
        ).all()
        assert remaining_links == []
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.data_subjects == []


def test_activation_gate(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    token = _token(activities_client)

    to_review = activities_client.post(
        f"/activities/{activity_id}/status",
        data={"csrf_token": token, "target_status": "in_review"},
    )
    assert to_review.status_code == 302

    _login(activities_client, activities_web_engine, "Ada Approver")
    approver_token = _token(activities_client)
    blocked = activities_client.post(
        f"/activities/{activity_id}/status",
        data={"csrf_token": approver_token, "target_status": "active"},
    )
    assert blocked.status_code == 422
    assert "blocking findings" in blocked.text.lower()

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.record_status == RecordStatus.IN_REVIEW

    _login(activities_client, activities_web_engine, "Cara Curator")
    curator_token = _token(activities_client)
    curator_attempt = activities_client.post(
        f"/activities/{activity_id}/status",
        data={"csrf_token": curator_token, "target_status": "active"},
    )
    assert curator_attempt.status_code == 403

    approver_id = _user_id(activities_web_engine, "Ada Approver")
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = approver_id
        db.add(
            LawfulBasisRecord(
                activity_id=activity_id,
                regime_scope=RegimeScope.PART2,
                art6_basis=art6(db, "e"),
                art6_justification="Statutory community fire safety function.",
            )
        )
        db.commit()

    _login(activities_client, activities_web_engine, "Ada Approver")
    approver_token = _token(activities_client)
    activated = activities_client.post(
        f"/activities/{activity_id}/status",
        data={"csrf_token": approver_token, "target_status": "active"},
    )
    assert activated.status_code == 302

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.record_status == RecordStatus.ACTIVE
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "processing_activity",
                AuditEvent.entity_id == activity_id,
                AuditEvent.event == "status_change",
            )
        ).all()
        assert any(e.new_value.get("record_status") == "active" for e in events)


def test_regime_override(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )

    _login(activities_client, activities_web_engine, "Ada Approver")
    approver_token = _token(activities_client)
    no_reason = activities_client.post(
        f"/activities/{activity_id}/regime-override",
        data={"csrf_token": approver_token, "target_regime": "law_enforcement", "reason": ""},
    )
    assert no_reason.status_code == 422

    with_reason = activities_client.post(
        f"/activities/{activity_id}/regime-override",
        data={
            "csrf_token": approver_token,
            "target_regime": "law_enforcement",
            "reason": "Enforcement case reclassified",
        },
    )
    assert with_reason.status_code == 302

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.regime == Regime.LAW_ENFORCEMENT
        assert activity.regime_source.value == "manual_override"
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "processing_activity",
                AuditEvent.entity_id == activity_id,
                AuditEvent.event == "regime_change",
            )
        ).all()
        assert len(events) == 1

    _login(activities_client, activities_web_engine, "Cara Curator")
    curator_token = _token(activities_client)
    curator_attempt = activities_client.post(
        f"/activities/{activity_id}/regime-override",
        data={
            "csrf_token": curator_token,
            "target_regime": "general",
            "reason": "Should be blocked",
        },
    )
    assert curator_attempt.status_code == 403


def test_picker_options_show_proposed_and_exclude_rejected(
    activities_client, activities_web_engine
):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    with Session(activities_web_engine) as db:
        db.add_all(
            [
                Recipient(
                    label="Proposed Picker Recipient",
                    type=RecipientType.PUBLIC_BODY,
                    entry_status=EntryStatus.PROPOSED,
                ),
                Recipient(
                    label="Rejected Picker Recipient",
                    type=RecipientType.PUBLIC_BODY,
                    entry_status=EntryStatus.REJECTED,
                ),
            ]
        )
        db.commit()

    detail = activities_client.get(f"/activities/{activity_id}")
    assert "Proposed Picker Recipient (proposed)" in detail.text
    assert "Rejected Picker Recipient" not in detail.text


def test_add_recipient_rejects_rejected_entry(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    with Session(activities_web_engine) as db:
        rejected = Recipient(
            label="Rejected Add Recipient",
            type=RecipientType.PUBLIC_BODY,
            entry_status=EntryStatus.REJECTED,
        )
        db.add(rejected)
        db.commit()
        rejected_id = rejected.id

    token = _token(activities_client)
    response = activities_client.post(
        f"/activities/{activity_id}/recipients",
        data={"csrf_token": token, "item_id": rejected_id},
    )
    assert response.status_code == 422


def test_activation_gate_blocks_on_unapproved_reference(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    token = _token(activities_client)

    with Session(activities_web_engine) as db:
        proposed = Recipient(
            label="Gate Recipient",
            type=RecipientType.PUBLIC_BODY,
            entry_status=EntryStatus.PROPOSED,
        )
        db.add(proposed)
        db.commit()
        proposed_id = proposed.id

    add_recipient = activities_client.post(
        f"/activities/{activity_id}/recipients",
        data={"csrf_token": token, "item_id": proposed_id},
    )
    assert add_recipient.status_code == 302

    to_review = activities_client.post(
        f"/activities/{activity_id}/status",
        data={"csrf_token": token, "target_status": "in_review"},
    )
    assert to_review.status_code == 302

    approver_id = _user_id(activities_web_engine, "Ada Approver")
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = approver_id
        db.add(
            LawfulBasisRecord(
                activity_id=activity_id,
                regime_scope=RegimeScope.PART2,
                art6_basis=art6(db, "e"),
                art6_justification="Statutory community fire safety function.",
            )
        )
        db.commit()

    _login(activities_client, activities_web_engine, "Ada Approver")
    approver_token = _token(activities_client)
    blocked = activities_client.post(
        f"/activities/{activity_id}/status",
        data={"csrf_token": approver_token, "target_status": "active"},
    )
    assert blocked.status_code == 422
    assert "not approved" in blocked.text.lower()

    with Session(activities_web_engine) as db:
        db.info["actor_id"] = approver_id
        recipient = db.get(Recipient, proposed_id)
        recipient.entry_status = EntryStatus.APPROVED
        db.commit()

    activated = activities_client.post(
        f"/activities/{activity_id}/status",
        data={"csrf_token": approver_token, "target_status": "active"},
    )
    assert activated.status_code == 302

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.record_status == RecordStatus.ACTIVE


def test_trial_to_live_contributor_forbidden_approver_allowed(
    activities_client, activities_web_engine
):
    activity_id = _create_activity(
        activities_client,
        activities_web_engine,
        login_as="Cody Contributor",
        lifecycle_stage="trial",
        trial_start="2026-01-01",
        trial_end="2026-12-31",
    )

    edit_page = activities_client.get(f"/activities/{activity_id}/edit")
    token = _extract_csrf(edit_page.text)
    prevention_id = _business_function_id(
        activities_web_engine, "Prevention & Community Safety"
    )
    owner_id = _user_id(activities_web_engine, "Cody Contributor")
    data = _minimal_create_data(
        token, prevention_id, owner_id, lifecycle_stage="live"
    )
    response = activities_client.post(f"/activities/{activity_id}", data=data)
    assert response.status_code == 403

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.lifecycle_stage == LifecycleStage.TRIAL

    _login(activities_client, activities_web_engine, "Ada Approver")
    edit_page = activities_client.get(f"/activities/{activity_id}/edit")
    token = _extract_csrf(edit_page.text)
    data = _minimal_create_data(
        token, prevention_id, owner_id, lifecycle_stage="live"
    )
    response = activities_client.post(f"/activities/{activity_id}", data=data)
    assert response.status_code == 302

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.lifecycle_stage == LifecycleStage.LIVE


def test_mark_reviewed_happy_path(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    token = _token(activities_client)
    future = (date.today() + timedelta(days=90)).isoformat()
    response = activities_client.post(
        f"/activities/{activity_id}/mark-reviewed",
        data={"csrf_token": token, "next_review_at": future},
    )
    assert response.status_code == 302

    with Session(activities_web_engine) as db:
        activity = db.get(ProcessingActivity, activity_id)
        assert activity.last_reviewed_at == date.today()
        assert activity.next_review_at.isoformat() == future
        assert activity.version == 2
        event = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "processing_activity",
                AuditEvent.entity_id == activity_id,
                AuditEvent.event == "review_completed",
            )
        ).one()
        assert event.new_value["next_review_at"] == future


def test_mark_reviewed_past_date_rejected(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    token = _token(activities_client)
    past = (date.today() - timedelta(days=1)).isoformat()
    response = activities_client.post(
        f"/activities/{activity_id}/mark-reviewed",
        data={"csrf_token": token, "next_review_at": past},
    )
    assert response.status_code == 422
    assert "future next review date" in response.text.lower()


def test_mark_reviewed_today_rejected(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    token = _token(activities_client)
    response = activities_client.post(
        f"/activities/{activity_id}/mark-reviewed",
        data={"csrf_token": token, "next_review_at": date.today().isoformat()},
    )
    assert response.status_code == 422


def test_mark_reviewed_missing_or_invalid_date_rejected(
    activities_client, activities_web_engine
):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    token = _token(activities_client)
    missing = activities_client.post(
        f"/activities/{activity_id}/mark-reviewed",
        data={"csrf_token": token, "next_review_at": ""},
    )
    assert missing.status_code == 422

    token = _token(activities_client)
    invalid = activities_client.post(
        f"/activities/{activity_id}/mark-reviewed",
        data={"csrf_token": token, "next_review_at": "not-a-date"},
    )
    assert invalid.status_code == 422


def test_mark_reviewed_viewer_forbidden(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cara Curator"
    )
    _login(activities_client, activities_web_engine, "Vic Viewer")
    future = (date.today() + timedelta(days=90)).isoformat()
    response = activities_client.post(
        f"/activities/{activity_id}/mark-reviewed",
        data={"csrf_token": "no-token", "next_review_at": future},
    )
    assert response.status_code == 403


def test_mark_reviewed_contributor_other_function_forbidden(
    activities_client, activities_web_engine
):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cody Contributor"
    )
    _login(activities_client, activities_web_engine, "Ollie OtherFunction")
    future = (date.today() + timedelta(days=90)).isoformat()
    response = activities_client.post(
        f"/activities/{activity_id}/mark-reviewed",
        data={"csrf_token": "no-token", "next_review_at": future},
    )
    assert response.status_code == 403


def test_mark_reviewed_curator_ok(activities_client, activities_web_engine):
    activity_id = _create_activity(
        activities_client, activities_web_engine, login_as="Cody Contributor"
    )
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _token(activities_client)
    future = (date.today() + timedelta(days=90)).isoformat()
    response = activities_client.post(
        f"/activities/{activity_id}/mark-reviewed",
        data={"csrf_token": token, "next_review_at": future},
    )
    assert response.status_code == 302

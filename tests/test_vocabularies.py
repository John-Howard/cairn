from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import (
    BusinessFunction,
    LawfulBasisGeneral,
    LegalEntity,
    PersonalDataCategory,
    Recipient,
    RecordVersion,
    SecurityMeasure,
    SecurityMeasureCategory,
)
from test_activities import _extract_csrf, _login


def _vocab_token(client) -> str:
    return _extract_csrf(client.get("/vocabularies").text)


def _index_row(html: str, key: str) -> str:
    for chunk in html.split("<tr"):
        if f'href="/vocabularies/{key}"' in chunk:
            return chunk
    raise AssertionError(f"no index row for {key}")


def test_index_lists_vocabularies_with_counts(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Vic Viewer")
    response = activities_client.get("/vocabularies")
    assert response.status_code == 200

    with Session(activities_web_engine) as db:
        function_count = len(db.scalars(select(BusinessFunction)).all())
        basis_count = len(db.scalars(select(LawfulBasisGeneral)).all())

    for key in (
        "business-functions",
        "data-subject-categories",
        "personal-data-categories",
        "recipients",
        "security-measures",
        "systems",
        "retention-rules",
        "legal-entities",
        "external-data-sources",
        "third-countries",
        "transfer-mechanisms",
        "lawful-bases-general",
        "schedule8-conditions",
    ):
        assert f'href="/vocabularies/{key}"' in response.text

    assert f">{function_count}<" in _index_row(response.text, "business-functions")
    assert f">{basis_count}<" in _index_row(response.text, "lawful-bases-general")
    assert "Read-only" in _index_row(response.text, "lawful-bases-general")


def test_curator_creates_and_edits_entry(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    new_page = activities_client.get("/vocabularies/business-functions/new")
    assert new_page.status_code == 200
    token = _extract_csrf(new_page.text)

    created = activities_client.post(
        "/vocabularies/business-functions",
        data={"csrf_token": token, "label": "Water Rescue"},
    )
    assert created.status_code == 302

    with Session(activities_web_engine) as db:
        entry = db.scalars(
            select(BusinessFunction).where(BusinessFunction.label == "Water Rescue")
        ).one()
        entry_id = entry.id

    edit_page = activities_client.get(f"/vocabularies/business-functions/{entry_id}/edit")
    assert edit_page.status_code == 200
    token = _extract_csrf(edit_page.text)
    updated = activities_client.post(
        f"/vocabularies/business-functions/{entry_id}",
        data={
            "csrf_token": token,
            "label": "Water & Flood Rescue",
            "change_note": "Broadened to flooding",
        },
    )
    assert updated.status_code == 302

    with Session(activities_web_engine) as db:
        entry = db.get(BusinessFunction, entry_id)
        assert entry.label == "Water & Flood Rescue"
        version = db.scalars(
            select(RecordVersion).where(
                RecordVersion.entity_type == "business_function",
                RecordVersion.entity_id == entry_id,
            )
        ).one()
        assert version.version_change_note == "Broadened to flooding"


def test_create_requires_label(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _vocab_token(activities_client)
    response = activities_client.post(
        "/vocabularies/business-functions", data={"csrf_token": token, "label": ""}
    )
    assert response.status_code == 422
    assert "Enter label" in response.text


def test_contributor_and_viewer_cannot_edit(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cody Contributor")
    token = _vocab_token(activities_client)
    assert activities_client.get("/vocabularies/business-functions").status_code == 200
    assert activities_client.get("/vocabularies/business-functions/new").status_code == 403
    response = activities_client.post(
        "/vocabularies/business-functions", data={"csrf_token": token, "label": "Nope"}
    )
    assert response.status_code == 403

    _login(activities_client, activities_web_engine, "Vic Viewer")
    token = _vocab_token(activities_client)
    assert activities_client.get("/vocabularies/business-functions").status_code == 200
    assert activities_client.get("/vocabularies/business-functions/new").status_code == 403
    response = activities_client.post(
        "/vocabularies/business-functions", data={"csrf_token": token, "label": "Nope"}
    )
    assert response.status_code == 403


def test_legal_vocabularies_are_read_only(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Ada Approver")
    token = _vocab_token(activities_client)

    listing = activities_client.get("/vocabularies/lawful-bases-general")
    assert listing.status_code == 200
    assert "Read-only" in listing.text
    assert "/vocabularies/lawful-bases-general/new" not in listing.text

    with Session(activities_web_engine) as db:
        basis_id = db.scalars(select(LawfulBasisGeneral)).first().id

    for key in (
        "lawful-bases-general",
        "lawful-bases-le",
        "special-category-conditions",
        "schedule1-conditions",
        "schedule8-conditions",
    ):
        assert activities_client.get(f"/vocabularies/{key}/new").status_code == 404
        assert (
            activities_client.post(
                f"/vocabularies/{key}", data={"csrf_token": token, "label": "Nope"}
            ).status_code
            == 404
        )
    assert (
        activities_client.get(f"/vocabularies/lawful-bases-general/{basis_id}/edit").status_code
        == 404
    )


def test_bool_field_round_trip(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _vocab_token(activities_client)
    created = activities_client.post(
        "/vocabularies/personal-data-categories",
        data={"csrf_token": token, "label": "test bool category", "is_special_category": "true"},
    )
    assert created.status_code == 302

    with Session(activities_web_engine) as db:
        entry = db.scalars(
            select(PersonalDataCategory).where(
                PersonalDataCategory.label == "test bool category"
            )
        ).one()
        assert entry.is_special_category is True
        assert entry.is_criminal_offence is False
        entry_id = entry.id

    updated = activities_client.post(
        f"/vocabularies/personal-data-categories/{entry_id}",
        data={"csrf_token": token, "label": "test bool category", "is_criminal_offence": "true"},
    )
    assert updated.status_code == 302

    with Session(activities_web_engine) as db:
        entry = db.get(PersonalDataCategory, entry_id)
        assert entry.is_special_category is False
        assert entry.is_criminal_offence is True


def test_enum_field_round_trip(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _vocab_token(activities_client)
    created = activities_client.post(
        "/vocabularies/security-measures",
        data={"csrf_token": token, "label": "test measure", "category": "technical"},
    )
    assert created.status_code == 302

    with Session(activities_web_engine) as db:
        entry = db.scalars(
            select(SecurityMeasure).where(SecurityMeasure.label == "test measure")
        ).one()
        assert entry.category == SecurityMeasureCategory.TECHNICAL
        entry_id = entry.id

    updated = activities_client.post(
        f"/vocabularies/security-measures/{entry_id}",
        data={"csrf_token": token, "label": "test measure", "category": "organisational"},
    )
    assert updated.status_code == 302

    with Session(activities_web_engine) as db:
        entry = db.get(SecurityMeasure, entry_id)
        assert entry.category == SecurityMeasureCategory.ORGANISATIONAL

    invalid = activities_client.post(
        f"/vocabularies/security-measures/{entry_id}",
        data={"csrf_token": token, "label": "test measure", "category": "bogus"},
    )
    assert invalid.status_code == 422


def test_fk_field_round_trip(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _vocab_token(activities_client)
    created_entity = activities_client.post(
        "/vocabularies/legal-entities",
        data={"csrf_token": token, "label": "Partner Council", "role_type": "partner_agency"},
    )
    assert created_entity.status_code == 302

    with Session(activities_web_engine) as db:
        entity_id = db.scalars(
            select(LegalEntity).where(LegalEntity.label == "Partner Council")
        ).one().id

    created = activities_client.post(
        "/vocabularies/recipients",
        data={
            "csrf_token": token,
            "label": "test recipient",
            "type": "public_body",
            "legal_entity_id": entity_id,
        },
    )
    assert created.status_code == 302

    with Session(activities_web_engine) as db:
        entry = db.scalars(select(Recipient).where(Recipient.label == "test recipient")).one()
        assert entry.legal_entity_id == entity_id
        entry_id = entry.id

    edit_page = activities_client.get(f"/vocabularies/recipients/{entry_id}/edit")
    assert "Partner Council" in edit_page.text

    cleared = activities_client.post(
        f"/vocabularies/recipients/{entry_id}",
        data={
            "csrf_token": token,
            "label": "test recipient",
            "type": "public_body",
            "legal_entity_id": "",
        },
    )
    assert cleared.status_code == 302

    with Session(activities_web_engine) as db:
        entry = db.get(Recipient, entry_id)
        assert entry.legal_entity_id is None

    invalid = activities_client.post(
        f"/vocabularies/recipients/{entry_id}",
        data={
            "csrf_token": token,
            "label": "test recipient",
            "type": "public_body",
            "legal_entity_id": "not-a-real-id",
        },
    )
    assert invalid.status_code == 422

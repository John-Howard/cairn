import csv
import io
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import (
    AssetType,
    AuditEvent,
    EntryStatus,
    ImportBatch,
    ImportBatchStatus,
    InformationAsset,
    ProcessingActivity,
    Recipient,
    RecipientType,
    RecordStatus,
    SecurityMeasure,
    SecurityMeasureCategory,
)
from test_activities import _extract_csrf, _login, _user_id

PREVENTION = "Prevention & Community Safety"

CSV_HEADERS = [
    "name",
    "business_function",
    "purpose",
    "description",
    "activity_domain",
    "personal_data_source",
    "data_subjects",
    "data_categories",
    "recipients",
    "systems",
    "next_review_at",
]


def _csv_bytes(rows: list[dict], headers: list[str] = CSV_HEADERS) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow({h: row.get(h, "") for h in headers})
    return buf.getvalue().encode("utf-8")


def _page_csrf(client, url: str) -> str:
    return _extract_csrf(client.get(url).text)


def _upload(client, csrf_token: str, rows: list[dict], filename="q.csv", headers=CSV_HEADERS):
    return client.post(
        "/imports",
        files={"file": (filename, _csv_bytes(rows, headers), "text/csv")},
        data={"csrf_token": csrf_token},
    )


def _confirm(client, batch_id: str, csrf_token: str):
    return client.post(f"/imports/{batch_id}/confirm", data={"csrf_token": csrf_token})


def test_happy_path_confirm_creates_activities(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports")

    upload = _upload(
        activities_client,
        token,
        [
            {
                "name": "Activity One",
                "business_function": PREVENTION,
                "purpose": "Purpose one",
                "personal_data_source": "from_data_subject",
                "recipients": "police",
            },
            {
                "name": "Activity Two",
                "business_function": PREVENTION,
                "purpose": "Purpose two",
                "personal_data_source": "from_data_subject",
                "recipients": "New Recipient Co",
            },
        ],
    )
    assert upload.status_code == 302
    batch_id = upload.headers["location"].removeprefix("/imports/")

    preview = activities_client.get(f"/imports/{batch_id}")
    assert preview.status_code == 200
    assert "New Recipient Co" in preview.text

    confirm_token = _extract_csrf(preview.text)
    confirm = _confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 302
    assert confirm.headers["location"] == "/activities"

    with Session(activities_web_engine) as db:
        activities = db.scalars(select(ProcessingActivity)).all()
        assert len(activities) == 2
        cara_id = _user_id(activities_web_engine, "Cara Curator")
        for activity in activities:
            assert activity.owner_id == cara_id
            assert activity.created_by == cara_id
            assert activity.record_status == RecordStatus.DRAFT

        new_recipient = db.scalars(
            select(Recipient).where(Recipient.label == "New Recipient Co")
        ).one()
        assert new_recipient.entry_status == EntryStatus.PROPOSED
        assert new_recipient.type == RecipientType.OTHER

        activity_two = next(a for a in activities if a.name == "Activity Two")
        assert new_recipient in activity_two.recipients

        police = db.scalars(select(Recipient).where(Recipient.label == "police")).one()
        activity_one = next(a for a in activities if a.name == "Activity One")
        assert police in activity_one.recipients

        batch = db.get(ImportBatch, batch_id)
        assert batch.status == ImportBatchStatus.CONFIRMED

        events = db.scalars(
            select(AuditEvent).where(AuditEvent.event == "import_confirmed")
        ).all()
        assert len(events) == 1
        assert set(events[0].new_value["activities"]) == {a.id for a in activities}


def test_unmatched_system_column_creates_proposed_information_asset(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports")

    upload = _upload(
        activities_client,
        token,
        [
            {
                "name": "Activity With System",
                "business_function": PREVENTION,
                "purpose": "Purpose",
                "personal_data_source": "from_data_subject",
                "systems": "Case Management System",
            },
        ],
    )
    assert upload.status_code == 302
    batch_id = upload.headers["location"].removeprefix("/imports/")
    preview = activities_client.get(f"/imports/{batch_id}")
    confirm_token = _extract_csrf(preview.text)
    confirm = _confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 302

    with Session(activities_web_engine) as db:
        asset = db.scalars(
            select(InformationAsset).where(InformationAsset.label == "Case Management System")
        ).one()
        assert asset.entry_status == EntryStatus.PROPOSED
        assert asset.asset_type == AssetType.SYSTEM
        assert asset.contains_personal_data is True

        activity = db.scalars(
            select(ProcessingActivity).where(ProcessingActivity.name == "Activity With System")
        ).one()
        assert asset in activity.assets


def test_preview_creates_nothing(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports")

    upload = _upload(
        activities_client,
        token,
        [
            {
                "name": "Preview Only",
                "business_function": PREVENTION,
                "purpose": "P",
                "recipients": "Some New Co",
            }
        ],
    )
    batch_id = upload.headers["location"].removeprefix("/imports/")

    for _ in range(2):
        preview = activities_client.get(f"/imports/{batch_id}")
        assert preview.status_code == 200

    with Session(activities_web_engine) as db:
        assert db.scalars(select(ProcessingActivity)).all() == []
        assert db.scalars(select(Recipient).where(Recipient.label == "Some New Co")).all() == []


def test_unmatched_business_function_row_error(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports")

    upload = _upload(
        activities_client,
        token,
        [{"name": "X", "business_function": "Nonexistent Function", "purpose": "P"}],
    )
    batch_id = upload.headers["location"].removeprefix("/imports/")

    preview = activities_client.get(f"/imports/{batch_id}")
    assert "Unknown business function" in preview.text

    confirm_token = _extract_csrf(preview.text)
    confirm = _confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 422

    with Session(activities_web_engine) as db:
        assert db.scalars(select(ProcessingActivity)).all() == []


def test_personal_data_source_invalid_token_and_empty_warning(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports")

    bad_upload = _upload(
        activities_client,
        token,
        [
            {
                "name": "Bad PDS",
                "business_function": PREVENTION,
                "purpose": "P",
                "personal_data_source": "not_a_real_value",
            }
        ],
    )
    bad_batch_id = bad_upload.headers["location"].removeprefix("/imports/")
    bad_preview = activities_client.get(f"/imports/{bad_batch_id}")
    assert "Unknown personal data source" in bad_preview.text

    empty_upload = _upload(
        activities_client,
        token,
        [
            {
                "name": "Empty PDS Activity",
                "business_function": PREVENTION,
                "purpose": "P",
                "personal_data_source": "",
            }
        ],
        filename="q2.csv",
    )
    empty_batch_id = empty_upload.headers["location"].removeprefix("/imports/")
    empty_preview = activities_client.get(f"/imports/{empty_batch_id}")
    assert "Warning" in empty_preview.text

    confirm_token = _extract_csrf(empty_preview.text)
    confirm = _confirm(activities_client, empty_batch_id, confirm_token)
    assert confirm.status_code == 302

    with Session(activities_web_engine) as db:
        activity = db.scalars(
            select(ProcessingActivity).where(ProcessingActivity.name == "Empty PDS Activity")
        ).one()
        assert activity.personal_data_source == []


def test_duplicate_unmatched_name_deduped_case_insensitive(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports")

    upload = _upload(
        activities_client,
        token,
        [
            {
                "name": "Row A",
                "business_function": PREVENTION,
                "purpose": "P",
                "recipients": "acme corp",
            },
            {
                "name": "Row B",
                "business_function": PREVENTION,
                "purpose": "P",
                "recipients": "ACME CORP",
            },
        ],
    )
    batch_id = upload.headers["location"].removeprefix("/imports/")
    preview = activities_client.get(f"/imports/{batch_id}")
    confirm_token = _extract_csrf(preview.text)
    confirm = _confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 302

    with Session(activities_web_engine) as db:
        recipients = db.scalars(
            select(Recipient).where(Recipient.label == "acme corp")
        ).all()
        assert len(recipients) == 1
        activities = db.scalars(select(ProcessingActivity)).all()
        assert len(activities) == 2
        for activity in activities:
            assert recipients[0] in activity.recipients


def test_matching_rejected_recipient_is_row_error(activities_client, activities_web_engine):
    curator_id = _user_id(activities_web_engine, "Cara Curator")
    with Session(activities_web_engine) as db:
        db.info["actor_id"] = curator_id
        police = db.scalars(select(Recipient).where(Recipient.label == "police")).one()
        police.entry_status = EntryStatus.REJECTED
        db.commit()

    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports")

    upload = _upload(
        activities_client,
        token,
        [{"name": "X", "business_function": PREVENTION, "purpose": "P", "recipients": "police"}],
    )
    batch_id = upload.headers["location"].removeprefix("/imports/")
    preview = activities_client.get(f"/imports/{batch_id}")
    assert "previously rejected" in preview.text


def test_missing_header_and_empty_csv_rejected_at_upload(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports")

    missing_header = activities_client.post(
        "/imports",
        files={"file": ("bad.csv", b"name,purpose\nX,P\n", "text/csv")},
        data={"csrf_token": token},
    )
    assert missing_header.status_code == 422
    assert "Missing required column" in missing_header.text

    empty_csv = activities_client.post(
        "/imports",
        files={"file": ("empty.csv", b"name,business_function,purpose\n", "text/csv")},
        data={"csrf_token": token},
    )
    assert empty_csv.status_code == 422
    assert "no data rows" in empty_csv.text


def test_permissions(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cody Contributor")
    token = _page_csrf(activities_client, "/activities")
    csv_bytes = _csv_bytes([{"name": "X", "business_function": PREVENTION, "purpose": "P"}])

    assert activities_client.get("/imports").status_code == 403
    assert (
        activities_client.post(
            "/imports",
            files={"file": ("q.csv", csv_bytes, "text/csv")},
            data={"csrf_token": token},
        ).status_code
        == 403
    )
    assert (
        activities_client.post(
            "/imports/nonexistent/confirm", data={"csrf_token": token}
        ).status_code
        == 403
    )
    assert (
        activities_client.post(
            "/imports/nonexistent/cancel", data={"csrf_token": token}
        ).status_code
        == 403
    )

    _login(activities_client, activities_web_engine, "Vic Viewer")
    token = _page_csrf(activities_client, "/activities")
    assert activities_client.get("/imports").status_code == 403
    assert (
        activities_client.post(
            "/imports",
            files={"file": ("q.csv", csv_bytes, "text/csv")},
            data={"csrf_token": token},
        ).status_code
        == 403
    )

    _login(activities_client, activities_web_engine, "Ada Approver")
    assert activities_client.get("/imports").status_code == 200


def test_confirm_already_processed_and_cancel(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports")

    upload = _upload(
        activities_client,
        token,
        [
            {
                "name": "X",
                "business_function": PREVENTION,
                "purpose": "P",
                "personal_data_source": "from_data_subject",
            }
        ],
    )
    batch_id = upload.headers["location"].removeprefix("/imports/")
    preview = activities_client.get(f"/imports/{batch_id}")
    confirm_token = _extract_csrf(preview.text)
    confirm = _confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 302

    again = _confirm(activities_client, batch_id, confirm_token)
    assert again.status_code == 422

    upload2 = _upload(
        activities_client,
        token,
        [{"name": "Y", "business_function": PREVENTION, "purpose": "P"}],
        filename="q2.csv",
    )
    batch_id2 = upload2.headers["location"].removeprefix("/imports/")
    preview2 = activities_client.get(f"/imports/{batch_id2}")
    cancel_token = _extract_csrf(preview2.text)
    cancel = activities_client.post(
        f"/imports/{batch_id2}/cancel", data={"csrf_token": cancel_token}
    )
    assert cancel.status_code == 302
    assert cancel.headers["location"] == "/imports"

    with Session(activities_web_engine) as db:
        batch2 = db.get(ImportBatch, batch_id2)
        assert batch2.status == ImportBatchStatus.CANCELLED
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_id == batch_id2, AuditEvent.event == "import_cancelled"
            )
        ).all()
        assert len(events) == 1


def test_import_proposal_blocks_rule18_until_approved(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports")

    upload = _upload(
        activities_client,
        token,
        [
            {
                "name": "Needs Approval",
                "business_function": PREVENTION,
                "purpose": "P",
                "personal_data_source": "from_data_subject",
                "recipients": "Brand New Recipient",
            }
        ],
    )
    batch_id = upload.headers["location"].removeprefix("/imports/")
    preview = activities_client.get(f"/imports/{batch_id}")
    confirm_token = _extract_csrf(preview.text)
    confirm = _confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 302

    with Session(activities_web_engine) as db:
        activity = db.scalars(
            select(ProcessingActivity).where(ProcessingActivity.name == "Needs Approval")
        ).one()
        activity_id = activity.id
        recipient = db.scalars(
            select(Recipient).where(Recipient.label == "Brand New Recipient")
        ).one()
        recipient_id = recipient.id

    detail = activities_client.get(f"/activities/{activity_id}")
    assert "Rule 18" in detail.text
    assert "not approved" in detail.text

    approve_token = _extract_csrf(detail.text)
    approve = activities_client.post(
        f"/vocabularies/recipients/{recipient_id}/approve", data={"csrf_token": approve_token}
    )
    assert approve.status_code == 302

    detail2 = activities_client.get(f"/activities/{activity_id}")
    assert "Rule 18" not in detail2.text


def test_bom_handling(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports")

    content = "﻿".encode() + _csv_bytes(
        [{"name": "BOM Activity", "business_function": PREVENTION, "purpose": "P"}]
    )
    upload = activities_client.post(
        "/imports",
        files={"file": ("bom.csv", content, "text/csv")},
        data={"csrf_token": token},
    )
    assert upload.status_code == 302
    batch_id = upload.headers["location"].removeprefix("/imports/")
    preview = activities_client.get(f"/imports/{batch_id}")
    assert "BOM Activity" in preview.text
    assert "Unknown business function" not in preview.text


ASSET_CSV_HEADERS = [
    "label",
    "asset_type",
    "description",
    "iao_email",
    "custodian",
    "business_function",
    "classification",
    "contains_personal_data",
    "status",
    "next_review_date",
    "supplier",
    "location",
    "hosting_country",
    "retention_rule",
    "security_measures",
]


def _asset_upload(client, csrf_token: str, rows: list[dict], filename="assets.csv"):
    return client.post(
        "/imports/assets",
        files={"file": (filename, _csv_bytes(rows, ASSET_CSV_HEADERS), "text/csv")},
        data={"csrf_token": csrf_token},
    )


def _asset_confirm(client, batch_id: str, csrf_token: str):
    return client.post(f"/imports/assets/{batch_id}/confirm", data={"csrf_token": csrf_token})


def _asset_cancel(client, batch_id: str, csrf_token: str):
    return client.post(f"/imports/assets/{batch_id}/cancel", data={"csrf_token": csrf_token})


def test_asset_happy_path_confirm_creates_assets(activities_client, activities_web_engine):
    with Session(activities_web_engine) as db:
        db.add(
            SecurityMeasure(label="encryption at rest", category=SecurityMeasureCategory.TECHNICAL)
        )
        db.commit()

    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports/assets/new")

    upload = _asset_upload(
        activities_client,
        token,
        [
            {
                "label": "Case Management System",
                "asset_type": "system",
                "description": "Holds incident and casualty records",
                "business_function": PREVENTION,
                "classification": "official",
                "contains_personal_data": "yes",
                "status": "in_use",
                "security_measures": "encryption at rest",
            },
        ],
    )
    assert upload.status_code == 302
    batch_id = upload.headers["location"].removeprefix("/imports/assets/")

    preview = activities_client.get(f"/imports/assets/{batch_id}")
    assert preview.status_code == 200
    assert "Case Management System" in preview.text

    confirm_token = _extract_csrf(preview.text)
    confirm = _asset_confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 302
    assert confirm.headers["location"] == "/assets"

    with Session(activities_web_engine) as db:
        asset = db.scalars(
            select(InformationAsset).where(InformationAsset.label == "Case Management System")
        ).one()
        assert asset.entry_status == EntryStatus.APPROVED
        assert asset.asset_type.value == "system"
        assert asset.classification.value == "official"
        assert asset.contains_personal_data is True
        assert {m.label for m in asset.security_measures} == {"encryption at rest"}

        batch = db.get(ImportBatch, batch_id)
        assert batch.status == ImportBatchStatus.CONFIRMED

        events = db.scalars(
            select(AuditEvent).where(AuditEvent.event == "asset_import_confirmed")
        ).all()
        assert len(events) == 1
        assert events[0].new_value["assets"] == [asset.id]


def test_asset_unmatched_iao_function_supplier_retention_warnings(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports/assets/new")

    upload = _asset_upload(
        activities_client,
        token,
        [
            {
                "label": "Unmatched Refs Asset",
                "asset_type": "system",
                "iao_email": "unknown@example.test",
                "business_function": "Not A Real Function",
                "supplier": "Not A Real Supplier",
                "retention_rule": "Not A Real Rule",
            },
        ],
    )
    batch_id = upload.headers["location"].removeprefix("/imports/assets/")
    preview = activities_client.get(f"/imports/assets/{batch_id}")
    assert "Unknown IAO email" in preview.text
    assert "Unknown business function" in preview.text
    assert "Unknown supplier" in preview.text
    assert "Unknown retention rule" in preview.text

    confirm_token = _extract_csrf(preview.text)
    confirm = _asset_confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 302

    with Session(activities_web_engine) as db:
        asset = db.scalars(
            select(InformationAsset).where(InformationAsset.label == "Unmatched Refs Asset")
        ).one()
        assert asset.iao_user_id is None
        assert asset.business_functions == []
        assert asset.supplier_entity_id is None
        assert asset.default_retention_id is None


def test_asset_multiple_business_functions_matched_and_unmatched(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports/assets/new")

    upload = _asset_upload(
        activities_client,
        token,
        [
            {
                "label": "Dual Function Asset",
                "asset_type": "system",
                "business_function": f"{PREVENTION}; Not A Real Function",
            },
        ],
    )
    batch_id = upload.headers["location"].removeprefix("/imports/assets/")
    preview = activities_client.get(f"/imports/assets/{batch_id}")
    assert "Unknown business function: &#39;Not A Real Function&#39;" in preview.text

    confirm_token = _extract_csrf(preview.text)
    confirm = _asset_confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 302

    with Session(activities_web_engine) as db:
        asset = db.scalars(
            select(InformationAsset).where(InformationAsset.label == "Dual Function Asset")
        ).one()
        assert {bf.label for bf in asset.business_functions} == {PREVENTION}


def test_asset_duplicate_label_skipped(activities_client, activities_web_engine):
    with Session(activities_web_engine) as db:
        db.add(InformationAsset(label="Existing System"))
        db.commit()

    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports/assets/new")

    upload = _asset_upload(
        activities_client,
        token,
        [
            {"label": "existing system", "asset_type": "system"},
            {"label": "Brand New System", "asset_type": "system"},
        ],
    )
    batch_id = upload.headers["location"].removeprefix("/imports/assets/")
    preview = activities_client.get(f"/imports/assets/{batch_id}")
    assert "already exists" in preview.text
    assert "Duplicate" in preview.text

    confirm_token = _extract_csrf(preview.text)
    confirm = _asset_confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 302

    with Session(activities_web_engine) as db:
        matches = db.scalars(
            select(InformationAsset).where(InformationAsset.label == "Existing System")
        ).all()
        assert len(matches) == 1
        new_asset = db.scalars(
            select(InformationAsset).where(InformationAsset.label == "Brand New System")
        ).one()
        assert new_asset.entry_status.value == "approved"


def test_asset_invalid_asset_type_error_row(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports/assets/new")

    upload = _asset_upload(
        activities_client,
        token,
        [{"label": "Bad Type Asset", "asset_type": "spaceship"}],
    )
    batch_id = upload.headers["location"].removeprefix("/imports/assets/")
    preview = activities_client.get(f"/imports/assets/{batch_id}")
    assert "Unknown asset type" in preview.text

    confirm_token = _extract_csrf(preview.text)
    confirm = _asset_confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 422

    with Session(activities_web_engine) as db:
        matches = db.scalars(
            select(InformationAsset).where(InformationAsset.label == "Bad Type Asset")
        ).all()
        assert matches == []


def test_asset_next_review_date_accepts_uk_format(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports/assets/new")

    upload = _asset_upload(
        activities_client,
        token,
        [
            {
                "label": "UK Date Asset",
                "asset_type": "system",
                "next_review_date": "01/04/2027",
            },
        ],
    )
    batch_id = upload.headers["location"].removeprefix("/imports/assets/")
    preview = activities_client.get(f"/imports/assets/{batch_id}")
    assert "Invalid next review date" not in preview.text

    confirm_token = _extract_csrf(preview.text)
    confirm = _asset_confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 302

    with Session(activities_web_engine) as db:
        asset = db.scalars(
            select(InformationAsset).where(InformationAsset.label == "UK Date Asset")
        ).one()
        assert asset.next_review_date == date(2027, 4, 1)


def test_asset_next_review_date_accepts_iso_format(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports/assets/new")

    upload = _asset_upload(
        activities_client,
        token,
        [
            {
                "label": "ISO Date Asset",
                "asset_type": "system",
                "next_review_date": "2027-04-01",
            },
        ],
    )
    batch_id = upload.headers["location"].removeprefix("/imports/assets/")
    preview = activities_client.get(f"/imports/assets/{batch_id}")
    assert "Invalid next review date" not in preview.text

    confirm_token = _extract_csrf(preview.text)
    confirm = _asset_confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 302

    with Session(activities_web_engine) as db:
        asset = db.scalars(
            select(InformationAsset).where(InformationAsset.label == "ISO Date Asset")
        ).one()
        assert asset.next_review_date == date(2027, 4, 1)


def test_asset_next_review_date_garbage_still_errors(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports/assets/new")

    upload = _asset_upload(
        activities_client,
        token,
        [
            {
                "label": "Bad Date Asset",
                "asset_type": "system",
                "next_review_date": "not-a-date",
            },
        ],
    )
    batch_id = upload.headers["location"].removeprefix("/imports/assets/")
    preview = activities_client.get(f"/imports/assets/{batch_id}")
    assert "Invalid next review date" in preview.text
    assert "not-a-date" in preview.text

    confirm_token = _extract_csrf(preview.text)
    confirm = _asset_confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 422

    with Session(activities_web_engine) as db:
        matches = db.scalars(
            select(InformationAsset).where(InformationAsset.label == "Bad Date Asset")
        ).all()
        assert matches == []


def test_asset_security_measures_unmatched_become_proposals(
    activities_client, activities_web_engine
):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports/assets/new")

    upload = _asset_upload(
        activities_client,
        token,
        [
            {
                "label": "Proposal Source Asset",
                "asset_type": "system",
                "security_measures": "brand new control",
            },
        ],
    )
    batch_id = upload.headers["location"].removeprefix("/imports/assets/")
    preview = activities_client.get(f"/imports/assets/{batch_id}")
    assert "brand new control" in preview.text

    confirm_token = _extract_csrf(preview.text)
    confirm = _asset_confirm(activities_client, batch_id, confirm_token)
    assert confirm.status_code == 302

    with Session(activities_web_engine) as db:
        measure = db.scalars(
            select(SecurityMeasure).where(SecurityMeasure.label == "brand new control")
        ).one()
        assert measure.entry_status == EntryStatus.PROPOSED
        asset = db.scalars(
            select(InformationAsset).where(InformationAsset.label == "Proposal Source Asset")
        ).one()
        assert measure in asset.security_measures


def test_asset_import_permissions(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cody Contributor")
    assert activities_client.get("/imports/assets/new").status_code == 403
    assert activities_client.post("/imports/assets").status_code == 403


def test_asset_upload_form_links_csv_template(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    response = activities_client.get("/imports/assets/new")
    assert response.status_code == 200
    assert 'href="/static/iar-import-template.csv"' in response.text


def test_asset_import_cancel(activities_client, activities_web_engine):
    _login(activities_client, activities_web_engine, "Cara Curator")
    token = _page_csrf(activities_client, "/imports/assets/new")
    upload = _asset_upload(
        activities_client, token, [{"label": "Cancel Me Asset", "asset_type": "system"}]
    )
    batch_id = upload.headers["location"].removeprefix("/imports/assets/")
    preview = activities_client.get(f"/imports/assets/{batch_id}")
    cancel_token = _extract_csrf(preview.text)
    cancel = _asset_cancel(activities_client, batch_id, cancel_token)
    assert cancel.status_code == 302
    assert cancel.headers["location"] == "/imports/assets/new"

    with Session(activities_web_engine) as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.status == ImportBatchStatus.CANCELLED
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.event == "asset_import_cancelled")
        ).all()
        assert len(events) == 1
        matches = db.scalars(
            select(InformationAsset).where(InformationAsset.label == "Cancel Me Asset")
        ).all()
        assert matches == []

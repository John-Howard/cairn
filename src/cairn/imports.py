import csv
import io
from dataclasses import dataclass, field
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.audit import record_event
from cairn.auth import get_csrf_token, require_role, verify_csrf
from cairn.db import get_session
from cairn.inheritance import sync_inherited_security
from cairn.models import (
    ActivityDomain,
    AssetType,
    BusinessFunction,
    DataSubjectCategory,
    EntryStatus,
    ImportBatch,
    ImportBatchStatus,
    InformationAsset,
    PersonalDataCategory,
    PersonalDataSource,
    ProcessingActivity,
    Recipient,
    RecipientType,
    RecordStatus,
    RegimeSource,
    Role,
    User,
)
from cairn.regime import resolve_regime
from cairn.templating import templates

router = APIRouter()

require_curator_or_approver = require_role(Role.CURATOR, Role.APPROVER_DPO)

REQUIRED_HEADERS = ("name", "business_function", "purpose")


@dataclass(frozen=True)
class VocabColumn:
    column: str
    model: type
    attr: str
    label_attr: str = "label"


VOCAB_COLUMNS: list[VocabColumn] = [
    VocabColumn("data_subjects", DataSubjectCategory, "data_subjects"),
    VocabColumn("data_categories", PersonalDataCategory, "data_categories"),
    VocabColumn("recipients", Recipient, "recipients"),
    VocabColumn("systems", InformationAsset, "assets"),
]

COLUMN_LABELS = {
    "data_subjects": "Data subjects",
    "data_categories": "Data categories",
    "recipients": "Recipients",
    "systems": "Systems",
}


@dataclass
class RowReport:
    index: int
    values: dict
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    matches: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    proposals: dict[str, list[str]] = field(default_factory=dict)


def _split_names(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def _vocab_maps(session: Session, model: type) -> tuple[dict[str, object], set[str]]:
    active: dict[str, object] = {}
    rejected: set[str] = set()
    for entry in session.scalars(select(model)).all():
        key = entry.label.lower()
        if entry.entry_status == EntryStatus.REJECTED:
            rejected.add(key)
        else:
            active[key] = entry
    return active, rejected


def analyse_rows(session: Session, rows: list[dict]) -> list[RowReport]:
    business_functions = {
        bf.label.lower(): bf for bf in session.scalars(select(BusinessFunction)).all()
    }
    vocab_maps = {col.column: _vocab_maps(session, col.model) for col in VOCAB_COLUMNS}
    proposal_registry: dict[str, dict[str, str]] = {col.column: {} for col in VOCAB_COLUMNS}
    reports = []
    for index, row in enumerate(rows, start=1):
        errors: list[str] = []
        warnings: list[str] = []
        matches: dict[str, list[tuple[str, str]]] = {}
        proposals: dict[str, list[str]] = {}
        values: dict = {}

        name = (row.get("name") or "").strip()
        values["name"] = name
        if not name:
            errors.append("Enter a name")

        bf_raw = (row.get("business_function") or "").strip()
        bf = business_functions.get(bf_raw.lower())
        values["business_function_id"] = bf.id if bf else None
        values["business_function_label"] = bf.label if bf else bf_raw
        if bf is None:
            errors.append(
                f"Unknown business function: '{bf_raw}'" if bf_raw else "Enter a business function"
            )

        purpose = (row.get("purpose") or "").strip()
        values["purpose"] = purpose
        if not purpose:
            errors.append("Enter a purpose")

        values["description"] = (row.get("description") or "").strip()

        domain_raw = (row.get("activity_domain") or "").strip()
        if not domain_raw:
            values["activity_domain"] = ActivityDomain.OTHER
        else:
            try:
                values["activity_domain"] = ActivityDomain(domain_raw.lower())
            except ValueError:
                values["activity_domain"] = None
                errors.append(f"Unknown activity domain: '{domain_raw}'")

        pds_raw = (row.get("personal_data_source") or "").strip()
        if not pds_raw:
            values["personal_data_source"] = []
            warnings.append(
                "No personal data source given — the author must set this before review"
            )
        else:
            pds_values = []
            for token in _split_names(pds_raw):
                try:
                    pds_values.append(PersonalDataSource(token.lower()))
                except ValueError:
                    errors.append(f"Unknown personal data source: '{token}'")
            values["personal_data_source"] = [p.value for p in pds_values]

        for col in VOCAB_COLUMNS:
            raw = (row.get(col.column) or "").strip()
            active_map, rejected_names = vocab_maps[col.column]
            col_matches: list[tuple[str, str]] = []
            col_proposals: list[str] = []
            for token_name in _split_names(raw):
                key = token_name.lower()
                entry = active_map.get(key)
                if entry is not None:
                    col_matches.append((entry.id, getattr(entry, col.label_attr)))
                    continue
                if key in rejected_names:
                    errors.append(f"'{token_name}' was previously rejected")
                    continue
                canonical = proposal_registry[col.column].setdefault(key, token_name)
                if canonical not in col_proposals:
                    col_proposals.append(canonical)
            if col_matches:
                matches[col.column] = col_matches
            if col_proposals:
                proposals[col.column] = col_proposals

        next_review_raw = (row.get("next_review_at") or "").strip()
        if not next_review_raw:
            values["next_review_at"] = date.today() + timedelta(days=365)
        else:
            try:
                values["next_review_at"] = date.fromisoformat(next_review_raw)
            except ValueError:
                values["next_review_at"] = None
                errors.append(f"Invalid next review date: '{next_review_raw}'")

        reports.append(
            RowReport(
                index=index,
                values=values,
                errors=errors,
                warnings=warnings,
                matches=matches,
                proposals=proposals,
            )
        )
    return reports


def apply_batch(
    session: Session, batch: ImportBatch, reports: list[RowReport], actor: User
) -> tuple[list[ProcessingActivity], dict[str, list[str]]]:
    proposal_entities: dict[str, dict[str, object]] = {col.column: {} for col in VOCAB_COLUMNS}
    for col in VOCAB_COLUMNS:
        names: dict[str, str] = {}
        for report in reports:
            for name in report.proposals.get(col.column, []):
                names.setdefault(name.lower(), name)
        for key, name in names.items():
            kwargs = {col.label_attr: name, "entry_status": EntryStatus.PROPOSED}
            if col.model is Recipient:
                kwargs["type"] = RecipientType.OTHER
            if col.model is InformationAsset:
                kwargs["asset_type"] = AssetType.SYSTEM
                kwargs["contains_personal_data"] = True
            entry = col.model(**kwargs)
            session.add(entry)
            proposal_entities[col.column][key] = entry
    session.flush()
    proposal_ids = {
        col.column: [entry.id for entry in proposal_entities[col.column].values()]
        for col in VOCAB_COLUMNS
        if proposal_entities[col.column]
    }

    activities = []
    for report in reports:
        values = report.values
        activity = ProcessingActivity(record_status=RecordStatus.DRAFT)
        activity.name = values["name"]
        activity.business_function_id = values["business_function_id"]
        activity.purpose = values["purpose"]
        activity.description = values["description"] or None
        activity.activity_domain = values["activity_domain"]
        activity.personal_data_source = values["personal_data_source"]
        activity.owner_id = actor.id
        activity.next_review_at = values["next_review_at"]
        activity.regime = resolve_regime(session, activity)
        activity.regime_source = RegimeSource.POLICY
        session.add(activity)
        session.flush()

        linked_asset = False
        for col in VOCAB_COLUMNS:
            collection = getattr(activity, col.attr)
            for entry_id, _label in report.matches.get(col.column, []):
                entry = session.get(col.model, entry_id)
                collection.append(entry)
            for name in report.proposals.get(col.column, []):
                entry = proposal_entities[col.column][name.lower()]
                collection.append(entry)
            if col.column == "systems" and (
                report.matches.get("systems") or report.proposals.get("systems")
            ):
                linked_asset = True
        session.flush()
        if linked_asset:
            sync_inherited_security(session, activity)
        activities.append(activity)
    return activities, proposal_ids


def _get_batch(session: Session, batch_id: str) -> ImportBatch:
    batch = session.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404)
    return batch


def _upload_response(
    request: Request, user: User, *, error: str | None = None, status_code: int = 200
):
    return templates.TemplateResponse(
        request,
        "imports/upload.html",
        {"user": user, "csrf_token": get_csrf_token(request), "error": error},
        status_code=status_code,
    )


def _grouped_proposals(reports: list[RowReport]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for report in reports:
        for column, names in report.proposals.items():
            bucket = grouped.setdefault(column, [])
            for name in names:
                if name not in bucket:
                    bucket.append(name)
    return grouped


def _preview_response(
    request: Request,
    user: User,
    batch: ImportBatch,
    reports: list[RowReport],
    *,
    status_code: int = 200,
):
    error_rows = sum(1 for r in reports if r.errors)
    warning_rows = sum(1 for r in reports if r.warnings and not r.errors)
    context = {
        "user": user,
        "batch": batch,
        "processed": False,
        "reports": reports,
        "row_count": len(reports),
        "error_count": error_rows,
        "warning_count": warning_rows,
        "can_confirm": error_rows == 0,
        "proposals": _grouped_proposals(reports),
        "column_labels": COLUMN_LABELS,
        "csrf_token": get_csrf_token(request),
    }
    return templates.TemplateResponse(
        request, "imports/preview.html", context, status_code=status_code
    )


@router.get("/imports")
def import_upload_form(
    request: Request, user: User = Depends(require_curator_or_approver)
):
    return _upload_response(request, user)


@router.post("/imports")
async def import_upload(
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(...),
    user: User = Depends(require_curator_or_approver),
    session: Session = Depends(get_session),
):
    verify_csrf(request, csrf_token)
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _upload_response(
            request, user, error="Could not read the file as UTF-8 text", status_code=422
        )
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    missing = [h for h in REQUIRED_HEADERS if h not in fieldnames]
    if missing:
        return _upload_response(
            request,
            user,
            error=f"Missing required column(s): {', '.join(missing)}",
            status_code=422,
        )
    rows = [
        {key: (value or "").strip() for key, value in row.items() if key is not None}
        for row in reader
    ]
    if not rows:
        return _upload_response(
            request, user, error="The CSV file has no data rows", status_code=422
        )
    batch = ImportBatch(filename=file.filename or "questionnaire.csv", rows=rows)
    session.add(batch)
    session.flush()
    return RedirectResponse(f"/imports/{batch.id}", status_code=302)


@router.get("/imports/{batch_id}")
def import_preview(
    batch_id: str,
    request: Request,
    user: User = Depends(require_curator_or_approver),
    session: Session = Depends(get_session),
):
    batch = _get_batch(session, batch_id)
    if batch.status != ImportBatchStatus.PENDING:
        return templates.TemplateResponse(
            request,
            "imports/preview.html",
            {
                "user": user,
                "batch": batch,
                "processed": True,
                "csrf_token": get_csrf_token(request),
            },
        )
    reports = analyse_rows(session, batch.rows)
    return _preview_response(request, user, batch, reports)


@router.post("/imports/{batch_id}/confirm")
async def import_confirm(
    batch_id: str,
    request: Request,
    user: User = Depends(require_curator_or_approver),
    session: Session = Depends(get_session),
):
    batch = _get_batch(session, batch_id)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    if batch.status != ImportBatchStatus.PENDING:
        raise HTTPException(status_code=422, detail="Batch has already been processed")
    reports = analyse_rows(session, batch.rows)
    if any(r.errors for r in reports):
        return _preview_response(request, user, batch, reports, status_code=422)
    activities, proposal_ids = apply_batch(session, batch, reports, user)
    batch.status = ImportBatchStatus.CONFIRMED
    batch.change_note = "Import confirmed"
    session.flush()
    record_event(
        session,
        entity=batch,
        event="import_confirmed",
        actor=user,
        new_value={"activities": [a.id for a in activities], "proposals": proposal_ids},
    )
    return RedirectResponse("/activities", status_code=302)


@router.post("/imports/{batch_id}/cancel")
async def import_cancel(
    batch_id: str,
    request: Request,
    user: User = Depends(require_curator_or_approver),
    session: Session = Depends(get_session),
):
    batch = _get_batch(session, batch_id)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    if batch.status != ImportBatchStatus.PENDING:
        raise HTTPException(status_code=422, detail="Batch has already been processed")
    batch.status = ImportBatchStatus.CANCELLED
    batch.change_note = "Import cancelled"
    session.flush()
    record_event(session, entity=batch, event="import_cancelled", actor=user)
    return RedirectResponse("/imports", status_code=302)

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

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
    AssetStatus,
    AssetType,
    BusinessFunction,
    DataSubjectCategory,
    EntryStatus,
    ImportBatch,
    ImportBatchStatus,
    InformationAsset,
    LegalEntity,
    PersonalDataCategory,
    PersonalDataSource,
    ProcessingActivity,
    Recipient,
    RecipientType,
    RecordStatus,
    RegimeSource,
    RetentionRule,
    Role,
    SecurityClassification,
    SecurityMeasure,
    SecurityMeasureCategory,
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


ASSET_REQUIRED_HEADERS = ("label", "asset_type")
ASSET_YES_VALUES = {"yes", "y", "true"}
ASSET_NO_VALUES = {"no", "n", "false"}


def _parse_flexible_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        pass
    return datetime.strptime(raw, "%d/%m/%Y").date()


@dataclass
class AssetRowReport:
    index: int
    values: dict
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    is_duplicate: bool = False
    security_measure_matches: list[tuple[str, str]] = field(default_factory=list)
    security_measure_proposals: list[str] = field(default_factory=list)


def analyse_asset_rows(session: Session, rows: list[dict]) -> list[AssetRowReport]:
    existing_labels = {a.label.lower() for a in session.scalars(select(InformationAsset)).all()}
    business_functions = {
        bf.label.lower(): bf for bf in session.scalars(select(BusinessFunction)).all()
    }
    users_by_email = {u.email.lower(): u for u in session.scalars(select(User)).all() if u.email}
    suppliers = {le.label.lower(): le for le in session.scalars(select(LegalEntity)).all()}
    retention_rules = {
        r.label.lower(): r
        for r in session.scalars(select(RetentionRule)).all()
        if r.entry_status != EntryStatus.REJECTED
    }
    measure_active, measure_rejected = _vocab_maps(session, SecurityMeasure)
    proposal_registry: dict[str, str] = {}

    reports = []
    for index, row in enumerate(rows, start=1):
        errors: list[str] = []
        warnings: list[str] = []
        values: dict = {}

        label = (row.get("label") or "").strip()
        values["label"] = label
        if not label:
            errors.append("Enter a label")

        is_duplicate = bool(label) and label.lower() in existing_labels
        if is_duplicate:
            warnings.append(f"An asset named '{label}' already exists — this row will be skipped")

        asset_type_raw = (row.get("asset_type") or "").strip()
        if not asset_type_raw:
            errors.append("Enter an asset type")
            values["asset_type"] = None
        else:
            try:
                values["asset_type"] = AssetType(asset_type_raw.lower())
            except ValueError:
                errors.append(f"Unknown asset type: '{asset_type_raw}'")
                values["asset_type"] = None

        values["description"] = (row.get("description") or "").strip() or None
        values["custodian"] = (row.get("custodian") or "").strip() or None
        values["location"] = (row.get("location") or "").strip() or None
        values["hosting_country"] = (row.get("hosting_country") or "").strip() or None

        iao_email = (row.get("iao_email") or "").strip()
        if iao_email:
            matched_user = users_by_email.get(iao_email.lower())
            if matched_user is None:
                warnings.append(f"Unknown IAO email: '{iao_email}' — leaving IAO unset")
                values["iao_user_id"] = None
            else:
                values["iao_user_id"] = matched_user.id
        else:
            values["iao_user_id"] = None

        function_raw = (row.get("business_function") or "").strip()
        function_ids: list[str] = []
        for token_name in _split_names(function_raw):
            bf = business_functions.get(token_name.lower())
            if bf is None:
                warnings.append(f"Unknown business function: '{token_name}' — skipped")
            else:
                function_ids.append(bf.id)
        values["business_function_ids"] = function_ids

        classification_raw = (row.get("classification") or "").strip()
        if classification_raw:
            try:
                values["classification"] = SecurityClassification(classification_raw.lower())
            except ValueError:
                errors.append(f"Unknown classification: '{classification_raw}'")
                values["classification"] = None
        else:
            values["classification"] = None

        personal_data_raw = (row.get("contains_personal_data") or "").strip().lower()
        if not personal_data_raw:
            values["contains_personal_data"] = None
        elif personal_data_raw in ASSET_YES_VALUES:
            values["contains_personal_data"] = True
        elif personal_data_raw in ASSET_NO_VALUES:
            values["contains_personal_data"] = False
        else:
            errors.append(f"Unknown value for contains personal data: '{personal_data_raw}'")
            values["contains_personal_data"] = None

        status_raw = (row.get("status") or "").strip()
        if status_raw:
            try:
                values["status"] = AssetStatus(status_raw.lower())
            except ValueError:
                errors.append(f"Unknown status: '{status_raw}'")
                values["status"] = None
        else:
            values["status"] = None

        review_raw = (row.get("next_review_date") or "").strip()
        if review_raw:
            try:
                values["next_review_date"] = _parse_flexible_date(review_raw)
            except ValueError:
                errors.append(f"Invalid next review date: '{review_raw}'")
                values["next_review_date"] = None
        else:
            values["next_review_date"] = None

        supplier_raw = (row.get("supplier") or "").strip()
        if supplier_raw:
            supplier = suppliers.get(supplier_raw.lower())
            if supplier is None:
                warnings.append(f"Unknown supplier: '{supplier_raw}' — leaving unset")
                values["supplier_entity_id"] = None
            else:
                values["supplier_entity_id"] = supplier.id
        else:
            values["supplier_entity_id"] = None

        retention_raw = (row.get("retention_rule") or "").strip()
        if retention_raw:
            rule = retention_rules.get(retention_raw.lower())
            if rule is None:
                warnings.append(f"Unknown retention rule: '{retention_raw}' — leaving unset")
                values["default_retention_id"] = None
            else:
                values["default_retention_id"] = rule.id
        else:
            values["default_retention_id"] = None

        measures_raw = (row.get("security_measures") or "").strip()
        measure_matches: list[tuple[str, str]] = []
        measure_proposals: list[str] = []
        for token_name in _split_names(measures_raw):
            key = token_name.lower()
            entry = measure_active.get(key)
            if entry is not None:
                measure_matches.append((entry.id, entry.label))
                continue
            if key in measure_rejected:
                errors.append(f"'{token_name}' was previously rejected")
                continue
            canonical = proposal_registry.setdefault(key, token_name)
            if canonical not in measure_proposals:
                measure_proposals.append(canonical)

        reports.append(
            AssetRowReport(
                index=index,
                values=values,
                errors=errors,
                warnings=warnings,
                is_duplicate=is_duplicate,
                security_measure_matches=measure_matches,
                security_measure_proposals=measure_proposals,
            )
        )
    return reports


def apply_asset_batch(
    session: Session, reports: list[AssetRowReport], actor: User
) -> tuple[list[InformationAsset], list[str]]:
    proposal_names: dict[str, str] = {}
    for report in reports:
        for name in report.security_measure_proposals:
            proposal_names.setdefault(name.lower(), name)
    proposal_entities: dict[str, SecurityMeasure] = {}
    for key, name in proposal_names.items():
        entry = SecurityMeasure(
            label=name,
            category=SecurityMeasureCategory.TECHNICAL,
            entry_status=EntryStatus.PROPOSED,
        )
        session.add(entry)
        proposal_entities[key] = entry
    session.flush()

    assets = []
    for report in reports:
        if report.is_duplicate:
            continue
        values = report.values
        asset = InformationAsset(label=values["label"], asset_type=values["asset_type"])
        for field_name in (
            "description",
            "iao_user_id",
            "custodian",
            "classification",
            "contains_personal_data",
            "status",
            "next_review_date",
            "supplier_entity_id",
            "location",
            "hosting_country",
            "default_retention_id",
        ):
            value = values[field_name]
            if value is not None:
                setattr(asset, field_name, value)
        asset.entry_status = EntryStatus.APPROVED
        session.add(asset)
        session.flush()
        for bf_id in values["business_function_ids"]:
            bf = session.get(BusinessFunction, bf_id)
            asset.business_functions.append(bf)
        for entry_id, _label in report.security_measure_matches:
            measure = session.get(SecurityMeasure, entry_id)
            asset.security_measures.append(measure)
        for name in report.security_measure_proposals:
            asset.security_measures.append(proposal_entities[name.lower()])
        assets.append(asset)
    session.flush()
    return assets, [entry.id for entry in proposal_entities.values()]


def _asset_upload_response(
    request: Request, user: User, *, error: str | None = None, status_code: int = 200
):
    return templates.TemplateResponse(
        request,
        "imports/assets_upload.html",
        {"user": user, "csrf_token": get_csrf_token(request), "error": error},
        status_code=status_code,
    )


def _asset_preview_response(
    request: Request,
    user: User,
    batch: ImportBatch,
    reports: list[AssetRowReport],
    *,
    status_code: int = 200,
):
    error_rows = sum(1 for r in reports if r.errors)
    warning_rows = sum(1 for r in reports if r.warnings and not r.errors)
    duplicate_rows = sum(1 for r in reports if r.is_duplicate)
    context = {
        "user": user,
        "batch": batch,
        "processed": False,
        "reports": reports,
        "row_count": len(reports),
        "error_count": error_rows,
        "warning_count": warning_rows,
        "duplicate_count": duplicate_rows,
        "can_confirm": error_rows == 0,
        "csrf_token": get_csrf_token(request),
    }
    return templates.TemplateResponse(
        request, "imports/assets_preview.html", context, status_code=status_code
    )


@router.get("/imports/assets/new")
def import_asset_upload_form(request: Request, user: User = Depends(require_curator_or_approver)):
    return _asset_upload_response(request, user)


@router.post("/imports/assets")
async def import_asset_upload(
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
        return _asset_upload_response(
            request, user, error="Could not read the file as UTF-8 text", status_code=422
        )
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    missing = [h for h in ASSET_REQUIRED_HEADERS if h not in fieldnames]
    if missing:
        return _asset_upload_response(
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
        return _asset_upload_response(
            request, user, error="The CSV file has no data rows", status_code=422
        )
    batch = ImportBatch(filename=file.filename or "assets.csv", rows=rows)
    session.add(batch)
    session.flush()
    return RedirectResponse(f"/imports/assets/{batch.id}", status_code=302)


@router.get("/imports/assets/{batch_id}")
def import_asset_preview(
    batch_id: str,
    request: Request,
    user: User = Depends(require_curator_or_approver),
    session: Session = Depends(get_session),
):
    batch = _get_batch(session, batch_id)
    if batch.status != ImportBatchStatus.PENDING:
        return templates.TemplateResponse(
            request,
            "imports/assets_preview.html",
            {
                "user": user,
                "batch": batch,
                "processed": True,
                "csrf_token": get_csrf_token(request),
            },
        )
    reports = analyse_asset_rows(session, batch.rows)
    return _asset_preview_response(request, user, batch, reports)


@router.post("/imports/assets/{batch_id}/confirm")
async def import_asset_confirm(
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
    reports = analyse_asset_rows(session, batch.rows)
    if any(r.errors for r in reports):
        return _asset_preview_response(request, user, batch, reports, status_code=422)
    assets, proposal_ids = apply_asset_batch(session, reports, user)
    batch.status = ImportBatchStatus.CONFIRMED
    batch.change_note = "Asset import confirmed"
    session.flush()
    record_event(
        session,
        entity=batch,
        event="asset_import_confirmed",
        actor=user,
        new_value={"assets": [a.id for a in assets], "proposals": proposal_ids},
    )
    return RedirectResponse("/assets", status_code=302)


@router.post("/imports/assets/{batch_id}/cancel")
async def import_asset_cancel(
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
    batch.change_note = "Asset import cancelled"
    session.flush()
    record_event(session, entity=batch, event="asset_import_cancelled", actor=user)
    return RedirectResponse("/imports/assets/new", status_code=302)

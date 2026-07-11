import csv
import io
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import (
    BusinessFunction,
    ControllerOrProcessor,
    DataSubjectCategory,
    LEClassification,
    LegalEntity,
    LegalEntityRoleType,
    OrganisationProfile,
    ProcessingActivity,
    RecordStatus,
    Regime,
    User,
)
from cairn.regime import active_basis


def export_views(activity: ProcessingActivity, profile: OrganisationProfile) -> set[str]:
    if activity.regime == Regime.LAW_ENFORCEMENT:
        if Regime.LAW_ENFORCEMENT in profile.applicable_regimes:
            return {"s61"}
        return set()
    if activity.controller_or_processor == ControllerOrProcessor.PROCESSOR:
        return {"art30_2"}
    return {"art30_1"}


@dataclass(frozen=True)
class ExportContext:
    profile: OrganisationProfile
    entities_by_role: dict[LegalEntityRoleType, list[LegalEntity]]
    function_labels: dict[str, str]
    owner_labels: dict[str, str]
    subject_labels: dict[str, str]


def build_export_context(session: Session, profile: OrganisationProfile) -> ExportContext:
    entities_by_role: dict[LegalEntityRoleType, list[LegalEntity]] = {}
    for entity in session.scalars(select(LegalEntity)).all():
        entities_by_role.setdefault(entity.role_type, []).append(entity)
    function_labels = {
        f.id: f.label for f in session.scalars(select(BusinessFunction)).all()
    }
    owner_labels = {u.id: u.display_name for u in session.scalars(select(User)).all()}
    subject_labels = {
        d.id: d.label for d in session.scalars(select(DataSubjectCategory)).all()
    }
    return ExportContext(
        profile=profile,
        entities_by_role=entities_by_role,
        function_labels=function_labels,
        owner_labels=owner_labels,
        subject_labels=subject_labels,
    )


@dataclass(frozen=True)
class ExportColumn:
    label: str
    extract: Callable[[ProcessingActivity, ExportContext], str]


@dataclass(frozen=True)
class ExportView:
    key: str
    filename_stem: str
    title: str
    columns: list[ExportColumn]
    include: Callable[[ProcessingActivity, OrganisationProfile], bool]


def _join(values) -> str:
    return "; ".join(sorted(v for v in values if v))


def _entity(entity: LegalEntity) -> str:
    parts = [entity.label, entity.contact, entity.address, entity.country]
    return " — ".join(p for p in parts if p)


def _entities(ctx: ExportContext, role: LegalEntityRoleType) -> str:
    return _join(_entity(e) for e in ctx.entities_by_role.get(role, []))


def _org_cell(ctx: ExportContext) -> str:
    parts = [ctx.profile.org_name]
    parts.extend(
        sorted(_entity(e) for e in ctx.entities_by_role.get(LegalEntityRoleType.OWN_ORG, []))
    )
    return "; ".join(p for p in parts if p)


def _joint_controllers(activity: ProcessingActivity, ctx: ExportContext) -> str:
    entities = {
        e.id: e for e in ctx.entities_by_role.get(LegalEntityRoleType.JOINT_CONTROLLER, [])
    }
    for entity in activity.controllers:
        entities.setdefault(entity.id, entity)
    return _join(_entity(e) for e in entities.values())


def _transfer(transfer) -> str:
    return f"{transfer.third_country.label} — {transfer.recipient.label}"


def _safeguards(transfer) -> str:
    text = transfer.mechanism.label
    if transfer.data_protection_test:
        text += "; transfer test documented"
    return text


def _retention(link) -> str:
    rule = link.rule
    return f"{rule.label}: {rule.period}, {rule.trigger}"


def _security(link) -> str:
    label = link.measure.label
    if link.inherited_from_system:
        return f"{label} (inherited)"
    return label


def _category(link, ctx: ExportContext) -> str:
    label = link.category.label
    if link.data_subject_scope_id:
        subject_label = ctx.subject_labels.get(link.data_subject_scope_id, "")
        return f"{label} (scope: {subject_label})"
    return label


def _le_data_subjects(activity: ProcessingActivity) -> str:
    cells = []
    for subject in activity.data_subjects:
        if subject.le_classification != LEClassification.NONE:
            cells.append(f"{subject.label} [{subject.le_classification}]")
        else:
            cells.append(subject.label)
    return _join(cells)


def _profiling(activity: ProcessingActivity) -> str:
    def describe(record) -> str:
        text = str(record.use_mode)
        if record.technique:
            text += f" — {record.technique}"
        return text

    return _join(describe(r) for r in activity.adm_records)


def _legal_basis(activity: ProcessingActivity) -> str:
    basis = active_basis(activity)
    if basis is None:
        return ""
    parts = []
    if basis.s35_basis is not None:
        parts.append(basis.s35_basis.label)
    if basis.schedule8_condition is not None:
        parts.append(basis.schedule8_condition.label)
    return "; ".join(p for p in parts if p)


def _s62_systems(activity: ProcessingActivity) -> str:
    return _join(s.label for s in activity.systems if s.s62_logging_in_scope)


ART30_1_COLUMNS = [
    ExportColumn("Controller", lambda a, ctx: _org_cell(ctx)),
    ExportColumn("Joint controllers", lambda a, ctx: _joint_controllers(a, ctx)),
    ExportColumn(
        "Representative", lambda a, ctx: _entities(ctx, LegalEntityRoleType.REPRESENTATIVE)
    ),
    ExportColumn("DPO", lambda a, ctx: _entities(ctx, LegalEntityRoleType.DPO)),
    ExportColumn("Processing activity", lambda a, ctx: a.name),
    ExportColumn(
        "Business function", lambda a, ctx: ctx.function_labels.get(a.business_function_id, "")
    ),
    ExportColumn("Purposes", lambda a, ctx: a.purpose),
    ExportColumn(
        "Categories of individuals", lambda a, ctx: _join(d.label for d in a.data_subjects)
    ),
    ExportColumn(
        "Categories of personal data",
        lambda a, ctx: _join(_category(link, ctx) for link in a.data_category_links),
    ),
    ExportColumn(
        "Categories of recipients", lambda a, ctx: _join(r.label for r in a.recipients)
    ),
    ExportColumn(
        "Third-country transfers", lambda a, ctx: _join(_transfer(t) for t in a.transfers)
    ),
    ExportColumn(
        "Transfer safeguards", lambda a, ctx: _join(_safeguards(t) for t in a.transfers)
    ),
    ExportColumn(
        "Retention", lambda a, ctx: _join(_retention(link) for link in a.retention_links)
    ),
    ExportColumn(
        "Security measures", lambda a, ctx: _join(_security(link) for link in a.security_links)
    ),
]

ART30_2_COLUMNS = [
    ExportColumn("Processor", lambda a, ctx: _org_cell(ctx)),
    ExportColumn("Processor DPO", lambda a, ctx: _entities(ctx, LegalEntityRoleType.DPO)),
    ExportColumn("Processing activity", lambda a, ctx: a.name),
    ExportColumn(
        "Business function", lambda a, ctx: ctx.function_labels.get(a.business_function_id, "")
    ),
    ExportColumn(
        "Controllers acted for", lambda a, ctx: _join(_entity(c) for c in a.controllers)
    ),
    ExportColumn(
        "Categories of processing", lambda a, ctx: a.categories_of_processing or ""
    ),
    ExportColumn(
        "Third-country transfers", lambda a, ctx: _join(_transfer(t) for t in a.transfers)
    ),
    ExportColumn(
        "Transfer safeguards", lambda a, ctx: _join(_safeguards(t) for t in a.transfers)
    ),
    ExportColumn(
        "Security measures", lambda a, ctx: _join(_security(link) for link in a.security_links)
    ),
]

S61_COLUMNS = [
    ExportColumn("Controller", lambda a, ctx: _org_cell(ctx)),
    ExportColumn("Joint controllers", lambda a, ctx: _joint_controllers(a, ctx)),
    ExportColumn("DPO", lambda a, ctx: _entities(ctx, LegalEntityRoleType.DPO)),
    ExportColumn("Processing activity", lambda a, ctx: a.name),
    ExportColumn(
        "Business function", lambda a, ctx: ctx.function_labels.get(a.business_function_id, "")
    ),
    ExportColumn("Purposes", lambda a, ctx: a.purpose),
    ExportColumn(
        "Categories of recipients", lambda a, ctx: _join(r.label for r in a.recipients)
    ),
    ExportColumn("Categories of data subjects", lambda a, ctx: _le_data_subjects(a)),
    ExportColumn(
        "LE classifications noted",
        lambda a, ctx: _join(a.le_data_subject_classification or []),
    ),
    ExportColumn(
        "Categories of personal data",
        lambda a, ctx: _join(_category(link, ctx) for link in a.data_category_links),
    ),
    ExportColumn("Use of profiling", lambda a, ctx: _profiling(a)),
    ExportColumn(
        "Third-country transfers", lambda a, ctx: _join(_transfer(t) for t in a.transfers)
    ),
    ExportColumn(
        "Transfer safeguards", lambda a, ctx: _join(_safeguards(t) for t in a.transfers)
    ),
    ExportColumn("Legal basis", lambda a, ctx: _legal_basis(a)),
    ExportColumn(
        "Retention", lambda a, ctx: _join(_retention(link) for link in a.retention_links)
    ),
    ExportColumn(
        "Security measures", lambda a, ctx: _join(_security(link) for link in a.security_links)
    ),
    ExportColumn("Systems in scope for s62 logging", lambda a, ctx: _s62_systems(a)),
    ExportColumn("s62 logging note", lambda a, ctx: a.s62_logging_note or ""),
]

COMBINED_COLUMNS = [
    ExportColumn("Name", lambda a, ctx: a.name),
    ExportColumn("Reference", lambda a, ctx: a.reference or ""),
    ExportColumn(
        "Business function", lambda a, ctx: ctx.function_labels.get(a.business_function_id, "")
    ),
    ExportColumn("Owner", lambda a, ctx: ctx.owner_labels.get(a.owner_id, "")),
    ExportColumn("Record status", lambda a, ctx: str(a.record_status)),
    ExportColumn("Lifecycle stage", lambda a, ctx: str(a.lifecycle_stage)),
    ExportColumn("Regime", lambda a, ctx: str(a.regime)),
    ExportColumn("Regime source", lambda a, ctx: str(a.regime_source)),
    ExportColumn("Controller/processor", lambda a, ctx: str(a.controller_or_processor)),
    ExportColumn("Activity type", lambda a, ctx: str(a.activity_type)),
    ExportColumn(
        "Export views", lambda a, ctx: _join(sorted(export_views(a, ctx.profile)))
    ),
    ExportColumn("Purpose", lambda a, ctx: a.purpose),
    ExportColumn("Data subjects", lambda a, ctx: _join(d.label for d in a.data_subjects)),
    ExportColumn(
        "Data categories",
        lambda a, ctx: _join(_category(link, ctx) for link in a.data_category_links),
    ),
    ExportColumn("Recipients", lambda a, ctx: _join(r.label for r in a.recipients)),
    ExportColumn("Systems", lambda a, ctx: _join(s.label for s in a.systems)),
    ExportColumn("Special category", lambda a, ctx: "yes" if a.special_category_flag else ""),
    ExportColumn("Criminal offence", lambda a, ctx: "yes" if a.criminal_offence_flag else ""),
    ExportColumn("ADM/profiling", lambda a, ctx: "yes" if a.adm_profiling_flag else ""),
    ExportColumn(
        "Last reviewed", lambda a, ctx: str(a.last_reviewed_at) if a.last_reviewed_at else ""
    ),
    ExportColumn("Next review", lambda a, ctx: str(a.next_review_at) if a.next_review_at else ""),
    ExportColumn("Trial end", lambda a, ctx: str(a.trial_end) if a.trial_end else ""),
]


def _active_ico_include(view_key: str):
    def include(activity: ProcessingActivity, profile: OrganisationProfile) -> bool:
        return (
            activity.record_status == RecordStatus.ACTIVE
            and view_key in export_views(activity, profile)
        )

    return include


EXPORT_VIEWS: dict[str, ExportView] = {
    "art30_1": ExportView(
        key="art30_1",
        filename_stem="art30-1",
        title="Art 30(1) — record of controller processing",
        columns=ART30_1_COLUMNS,
        include=_active_ico_include("art30_1"),
    ),
    "art30_2": ExportView(
        key="art30_2",
        filename_stem="art30-2",
        title="Art 30(2) — record of processor processing",
        columns=ART30_2_COLUMNS,
        include=_active_ico_include("art30_2"),
    ),
    "s61": ExportView(
        key="s61",
        filename_stem="s61",
        title="DPA 2018 s61 — law-enforcement processing record",
        columns=S61_COLUMNS,
        include=_active_ico_include("s61"),
    ),
    "combined": ExportView(
        key="combined",
        filename_stem="combined-register",
        title="Combined internal register",
        columns=COMBINED_COLUMNS,
        include=lambda a, p: True,
    ),
}


def render_csv(
    view: ExportView, activities: list[ProcessingActivity], ctx: ExportContext
) -> tuple[str, int]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([col.label for col in view.columns])
    rows = 0
    for activity in activities:
        if not view.include(activity, ctx.profile):
            continue
        writer.writerow([col.extract(activity, ctx) for col in view.columns])
        rows += 1
    return buffer.getvalue(), rows

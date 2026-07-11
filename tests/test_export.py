import csv
import io
from datetime import date

from sqlalchemy import select

from cairn.export import EXPORT_VIEWS, build_export_context, render_csv
from cairn.models import (
    ActivityDataCategory,
    ActivityRetention,
    ActivitySecurity,
    AdequacyStatus,
    APDScope,
    DataSubjectCategory,
    LawfulBasisRecord,
    LEClassification,
    LegalEntity,
    LegalEntityRoleType,
    PersonalDataCategory,
    ProcessingActivity,
    Recipient,
    RecordStatus,
    Regime,
    RegimeScope,
    RetentionRule,
    SecurityMeasure,
    SystemAsset,
    ThirdCountry,
    Transfer,
)
from conftest import business_function, make_apd, s35, schedule8, transfer_mechanism


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def _lookup(session, model, label):
    return session.scalars(select(model).where(model.label == label)).one()


def _basic_activity(session, actor, *, name, business_function_label, **overrides):
    defaults = dict(
        name=name,
        business_function_id=business_function(session, business_function_label).id,
        purpose="Purpose text.",
        personal_data_source=["from_data_subject"],
        owner_id=actor.id,
        next_review_at=date(2026, 12, 1),
        record_status=RecordStatus.ACTIVE,
    )
    defaults.update(overrides)
    activity = ProcessingActivity(**defaults)
    session.add(activity)
    session.flush()
    return activity


def test_header_rows_match_expected_labels(session, frs_profile):
    ctx = build_export_context(session, frs_profile)

    art30_1_text, _ = render_csv(EXPORT_VIEWS["art30_1"], [], ctx)
    assert _rows(art30_1_text)[0] == [
        "Controller",
        "Joint controllers",
        "Representative",
        "DPO",
        "Processing activity",
        "Business function",
        "Purposes",
        "Categories of individuals",
        "Categories of personal data",
        "Categories of recipients",
        "Third-country transfers",
        "Transfer safeguards",
        "Retention",
        "Security measures",
    ]

    art30_2_text, _ = render_csv(EXPORT_VIEWS["art30_2"], [], ctx)
    assert _rows(art30_2_text)[0] == [
        "Processor",
        "Processor DPO",
        "Processing activity",
        "Business function",
        "Controllers acted for",
        "Categories of processing",
        "Third-country transfers",
        "Transfer safeguards",
        "Security measures",
    ]

    s61_text, _ = render_csv(EXPORT_VIEWS["s61"], [], ctx)
    assert _rows(s61_text)[0] == [
        "Controller",
        "Joint controllers",
        "DPO",
        "Processing activity",
        "Business function",
        "Purposes",
        "Categories of recipients",
        "Categories of data subjects",
        "LE classifications noted",
        "Categories of personal data",
        "Use of profiling",
        "Third-country transfers",
        "Transfer safeguards",
        "Legal basis",
        "Retention",
        "Security measures",
        "Systems in scope for s62 logging",
        "s62 logging note",
    ]

    combined_text, _ = render_csv(EXPORT_VIEWS["combined"], [], ctx)
    assert _rows(combined_text)[0] == [
        "Name",
        "Reference",
        "Business function",
        "Owner",
        "Record status",
        "Lifecycle stage",
        "Regime",
        "Regime source",
        "Controller/processor",
        "Activity type",
        "Export views",
        "Purpose",
        "Data subjects",
        "Data categories",
        "Recipients",
        "Systems",
        "Special category",
        "Criminal offence",
        "ADM/profiling",
        "Last reviewed",
        "Next review",
        "Trial end",
    ]


def test_art30_1_rich_activity_columns(session, actor, frs_profile):
    own_org = LegalEntity(
        label="Example FRS", role_type=LegalEntityRoleType.OWN_ORG, contact="dpo@example.fire"
    )
    dpo = LegalEntity(
        label="Data Protection Officer",
        role_type=LegalEntityRoleType.DPO,
        contact="dpo@example.fire",
        address="HQ",
        country="UK",
    )
    joint_org_level = LegalEntity(
        label="County Council", role_type=LegalEntityRoleType.JOINT_CONTROLLER
    )
    session.add_all([own_org, dpo, joint_org_level])
    session.flush()

    activity = _basic_activity(
        session,
        actor,
        name="HFSV Delivery",
        business_function_label="Prevention & Community Safety",
    )
    activity.controllers.append(joint_org_level)
    joint_activity_level = LegalEntity(
        label="Neighbouring Authority", role_type=LegalEntityRoleType.JOINT_CONTROLLER
    )
    session.add(joint_activity_level)
    session.flush()
    activity.controllers.append(joint_activity_level)

    police = _lookup(session, Recipient, "police")
    nhs = _lookup(session, Recipient, "ambulance / NHS trusts")
    activity.recipients.extend([police, nhs])

    vulnerable = _lookup(session, DataSubjectCategory, "vulnerable persons (HFSV / Safe & Well)")
    activity.data_subjects.append(vulnerable)
    safeguarding = _lookup(session, PersonalDataCategory, "safeguarding concerns")
    session.add(
        ActivityDataCategory(
            activity_id=activity.id,
            category_id=safeguarding.id,
            data_subject_scope_id=vulnerable.id,
        )
    )

    inherited_measure = _lookup(session, SecurityMeasure, "encryption at rest")
    own_measure = _lookup(session, SecurityMeasure, "role-based access control")
    session.add_all(
        [
            ActivitySecurity(
                activity_id=activity.id,
                security_measure_id=inherited_measure.id,
                inherited_from_system=True,
            ),
            ActivitySecurity(
                activity_id=activity.id,
                security_measure_id=own_measure.id,
                inherited_from_system=False,
            ),
        ]
    )

    rule = RetentionRule(
        label="Standard casework retention", period="7 years", trigger="case closure"
    )
    session.add(rule)
    session.flush()
    session.add(ActivityRetention(activity_id=activity.id, retention_rule_id=rule.id))

    third_country = ThirdCountry(label="United States", adequacy_status=AdequacyStatus.NOT_ADEQUATE)
    session.add(third_country)
    session.flush()
    session.add(
        Transfer(
            activity_id=activity.id,
            recipient_id=police.id,
            third_country_id=third_country.id,
            mechanism_id=transfer_mechanism(session, "idta").id,
            data_protection_test="Documented transfer risk assessment.",
        )
    )
    session.flush()
    session.expire_all()

    ctx = build_export_context(session, frs_profile)
    text, rows = render_csv(EXPORT_VIEWS["art30_1"], [activity], ctx)
    parsed = _rows(text)
    assert rows == 1
    header, row = parsed[0], parsed[1]
    cell = dict(zip(header, row, strict=True))

    assert cell["Controller"] == f"{frs_profile.org_name}; Example FRS — dpo@example.fire"
    assert "County Council" in cell["Joint controllers"]
    assert "Neighbouring Authority" in cell["Joint controllers"]
    assert cell["DPO"] == "Data Protection Officer — dpo@example.fire — HQ — UK"
    assert set(cell["Categories of recipients"].split("; ")) == {
        "police",
        "ambulance / NHS trusts",
    }
    assert cell["Categories of personal data"] == (
        "safeguarding concerns (scope: vulnerable persons (HFSV / Safe & Well))"
    )
    security_cells = cell["Security measures"].split("; ")
    assert "encryption at rest (inherited)" in security_cells
    assert "role-based access control" in security_cells
    assert cell["Retention"] == "Standard casework retention: 7 years, case closure"
    assert cell["Third-country transfers"] == "United States — police"
    assert cell["Transfer safeguards"] == (
        "International Data Transfer Agreement; transfer test documented"
    )


def test_joint_controllers_deduped_by_id(session, actor, frs_profile):
    joint = LegalEntity(
        label="Shared Joint Controller", role_type=LegalEntityRoleType.JOINT_CONTROLLER
    )
    session.add(joint)
    session.flush()
    activity = _basic_activity(
        session,
        actor,
        name="Joint Activity",
        business_function_label="Prevention & Community Safety",
    )
    activity.controllers.append(joint)
    session.flush()
    session.expire_all()

    ctx = build_export_context(session, frs_profile)
    text, _ = render_csv(EXPORT_VIEWS["art30_1"], [activity], ctx)
    header, row = _rows(text)[0], _rows(text)[1]
    cell = dict(zip(header, row, strict=True))
    assert cell["Joint controllers"].count("Shared Joint Controller") == 1


def test_active_only_filters_ico_views_but_combined_includes_all(session, actor, frs_profile):
    active = _basic_activity(
        session,
        actor,
        name="Active Activity",
        business_function_label="Prevention & Community Safety",
        record_status=RecordStatus.ACTIVE,
    )
    draft = _basic_activity(
        session,
        actor,
        name="Draft Activity",
        business_function_label="Prevention & Community Safety",
        record_status=RecordStatus.DRAFT,
    )
    session.flush()
    session.expire_all()

    ctx = build_export_context(session, frs_profile)
    art30_1_text, art30_1_rows = render_csv(EXPORT_VIEWS["art30_1"], [active, draft], ctx)
    assert art30_1_rows == 1
    assert "Draft Activity" not in art30_1_text
    assert "Active Activity" in art30_1_text

    combined_text, combined_rows = render_csv(EXPORT_VIEWS["combined"], [active, draft], ctx)
    assert combined_rows == 2
    header = _rows(combined_text)[0]
    draft_row = next(r for r in _rows(combined_text)[1:] if r[0] == "Draft Activity")
    cell = dict(zip(header, draft_row, strict=True))
    assert cell["Record status"] == "draft"


def test_s61_le_classification_legal_basis_and_s62_systems(session, actor, frs_profile):
    apd = make_apd(session, title="s42 APD", scope=APDScope.S42_PART3, document_ref="apd_ref")
    activity = _basic_activity(
        session,
        actor,
        name="LE Activity",
        business_function_label="Protection (Fire Safety Regulation & Enforcement)",
        regime=Regime.LAW_ENFORCEMENT,
    )
    activity.basis_records.append(
        LawfulBasisRecord(
            regime_scope=RegimeScope.PART3,
            s35_basis=s35(session, "s35_task"),
            schedule8_condition=schedule8(session, 1),
            apd=apd,
        )
    )
    suspect = DataSubjectCategory(label="suspects", le_classification=LEClassification.SUSPECT)
    session.add(suspect)
    session.flush()
    activity.data_subjects.append(suspect)

    in_scope = SystemAsset(label="Case Management System", s62_logging_in_scope=True)
    out_scope = SystemAsset(label="Rostering System", s62_logging_in_scope=False)
    session.add_all([in_scope, out_scope])
    session.flush()
    activity.systems.extend([in_scope, out_scope])
    session.flush()
    session.expire_all()

    ctx = build_export_context(session, frs_profile)
    text, rows = render_csv(EXPORT_VIEWS["s61"], [activity], ctx)
    assert rows == 1
    header, row = _rows(text)[0], _rows(text)[1]
    cell = dict(zip(header, row, strict=True))
    assert cell["Categories of data subjects"] == "suspects [suspect]"
    assert s35(session, "s35_task").label in cell["Legal basis"]
    assert schedule8(session, 1).label in cell["Legal basis"]
    assert cell["Systems in scope for s62 logging"] == "Case Management System"


def test_s61_empty_legal_basis_no_crash(session, actor, frs_profile):
    activity = _basic_activity(
        session,
        actor,
        name="LE Activity No Basis",
        business_function_label="Protection (Fire Safety Regulation & Enforcement)",
        regime=Regime.LAW_ENFORCEMENT,
    )
    session.flush()
    session.expire_all()

    ctx = build_export_context(session, frs_profile)
    text, rows = render_csv(EXPORT_VIEWS["s61"], [activity], ctx)
    assert rows == 1
    header, row = _rows(text)[0], _rows(text)[1]
    cell = dict(zip(header, row, strict=True))
    assert cell["Legal basis"] == ""


def test_no_legal_entities_falls_back_to_org_name(session, actor, frs_profile):
    activity = _basic_activity(
        session,
        actor,
        name="No Entities Activity",
        business_function_label="Prevention & Community Safety",
    )
    session.flush()
    session.expire_all()

    ctx = build_export_context(session, frs_profile)
    text, rows = render_csv(EXPORT_VIEWS["art30_1"], [activity], ctx)
    assert rows == 1
    header, row = _rows(text)[0], _rows(text)[1]
    cell = dict(zip(header, row, strict=True))
    assert cell["Controller"] == frs_profile.org_name
    assert cell["DPO"] == ""


def test_le_activity_excluded_from_ico_views_without_law_enforcement_regime(
    session, actor, private_profile
):
    activity = _basic_activity(
        session,
        actor,
        name="LE Activity Under Private Profile",
        business_function_label="Prevention & Community Safety",
        regime=Regime.LAW_ENFORCEMENT,
    )
    session.flush()
    session.expire_all()

    ctx = build_export_context(session, private_profile)
    for key in ("art30_1", "art30_2", "s61"):
        _, rows = render_csv(EXPORT_VIEWS[key], [activity], ctx)
        assert rows == 0

    _, combined_rows = render_csv(EXPORT_VIEWS["combined"], [activity], ctx)
    assert combined_rows == 1

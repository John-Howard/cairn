from datetime import date

from sqlalchemy import select

from cairn.export import export_views
from cairn.models import (
    DPIA,
    ActivityDataCategory,
    ActivityFeeds,
    ActivityType,
    ADMUseMode,
    APDScope,
    ContractDSA,
    ContractType,
    ControllerOrProcessor,
    DataSubjectCategory,
    DecisionSupportADM,
    ExternalDataSource,
    ExternalDataUseMode,
    LawfulBasisRecord,
    LegalEntity,
    LegalEntityRoleType,
    LineageGranularity,
    PersonalDataCategory,
    ProcessingActivity,
    RecordStatus,
    RegimeScope,
    ResidualRisk,
    ScreeningOutcome,
    SourceSpecialCategory,
    SupplierRole,
)
from cairn.rules import evaluate
from conftest import art6, art9, business_function, make_apd, schedule1


def lookup(session, model, label):
    return session.scalars(select(model).where(model.label == label)).one()


def make_basis(session, activity):
    apd = make_apd(
        session,
        title="APD — Safeguarding",
        scope=APDScope.SCHEDULE1,
        document_ref="apd_safeguarding",
    )
    basis = LawfulBasisRecord(
        activity_id=activity.id,
        regime_scope=RegimeScope.PART2,
        art6_basis=art6(session, "e"),
        art6_justification="Statutory community fire safety function (FRSA 2004 s6).",
        art9_condition=art9(session, "g"),
        schedule1_condition=schedule1(session, 18),
        apd=apd,
    )
    session.add(basis)
    session.flush()
    return basis


def test_hfsv_risk_model_feeds_operational_targeting(session, actor, frs_profile):
    caci = LegalEntity(label="CACI Ltd", role_type=LegalEntityRoleType.DATA_SUPPLIER)
    council = LegalEntity(label="County Council", role_type=LegalEntityRoleType.PARTNER_AGENCY)
    session.add_all([caci, council])
    session.flush()

    eds_acorn = ExternalDataSource(
        name="CACI Acorn",
        supplier_legal_entity_id=caci.id,
        supplier_role=SupplierRole.SEPARATE_CONTROLLER,
        agreement_ref="CACI-2026-01",
        special_category=SourceSpecialCategory.INFERRED,
        art14_relationship="Geodemographic data not collected from the individual.",
    )
    eds_adultcare = ExternalDataSource(
        name="Adult Care referrals",
        supplier_legal_entity_id=council.id,
        supplier_role=SupplierRole.SEPARATE_CONTROLLER,
        agreement_ref="DSA-AC-2026",
        special_category=SourceSpecialCategory.DIRECT,
    )
    session.add_all([eds_acorn, eds_adultcare])

    prevention = business_function(session, "Prevention & Community Safety")
    operational = ProcessingActivity(
        name="Home Fire Safety Visits (delivery)",
        business_function_id=prevention.id,
        activity_type=ActivityType.OPERATIONAL,
        record_status=RecordStatus.ACTIVE,
        purpose="Deliver home fire safety visits to prioritised and self-referred households.",
        personal_data_source=["from_data_subject", "from_third_party"],
        vulnerable_or_safeguarding_flag=True,
        children_flag=False,
        owner_id=actor.id,
        next_review_at=date(2026, 12, 1),
    )
    model = ProcessingActivity(
        name="HFSV Household Risk Model",
        business_function_id=prevention.id,
        activity_type=ActivityType.ANALYTICS_MODELLING,
        record_status=RecordStatus.ACTIVE,
        purpose="Score households by fire risk to prioritise Home Fire Safety Visits.",
        personal_data_source=["from_third_party", "public_source"],
        external_data_use_mode=ExternalDataUseMode.AUTOMATED,
        lineage_granularity=LineageGranularity.RECORD,
        vulnerable_or_safeguarding_flag=True,
        high_risk_flag=True,
        owner_id=actor.id,
        next_review_at=date(2026, 12, 1),
        data_sources=[eds_acorn, eds_adultcare],
    )
    session.add_all([operational, model])
    session.flush()

    session.add(
        ActivityFeeds(source_activity_id=model.id, consumer_activity_id=operational.id)
    )

    vulnerable = lookup(session, DataSubjectCategory, "vulnerable persons (HFSV / Safe & Well)")
    safeguarding = lookup(session, PersonalDataCategory, "safeguarding concerns")
    household = lookup(session, PersonalDataCategory, "household & premises data")
    for activity in (operational, model):
        activity.data_subjects.append(vulnerable)
        session.add(
            ActivityDataCategory(
                activity_id=activity.id,
                category_id=safeguarding.id,
                data_subject_scope_id=vulnerable.id,
            )
        )
        session.add(ActivityDataCategory(activity_id=activity.id, category_id=household.id))

    make_basis(session, operational)
    make_basis(session, model)

    session.add(
        DecisionSupportADM(
            activity_id=model.id,
            use_mode=ADMUseMode.AUTOMATED,
            solely_automated=False,
            significant_effects=False,
            technique=(
                "Weighted risk score combining incident history, Acorn segmentation and "
                "Adult Care flags."
            ),
            human_review="Prevention officer reviews and schedules; model only prioritises.",
            accuracy_bias_checks="Quarterly review against actual incident outcomes.",
            data_sources=[eds_acorn, eds_adultcare],
        )
    )
    session.add(
        DPIA(
            activity_id=model.id,
            screening_outcome=ScreeningOutcome.REQUIRED,
            residual_risk=ResidualRisk.MEDIUM,
        )
    )
    session.add(
        DPIA(
            activity_id=operational.id,
            screening_outcome=ScreeningOutcome.REQUIRED,
            residual_risk=ResidualRisk.LOW,
        )
    )
    session.flush()
    session.expire_all()

    assert model.special_category_flag is True
    assert model.adm_profiling_flag is True
    assert operational.special_category_flag is True
    assert operational.adm_profiling_flag is False

    scoped = session.scalars(
        select(ActivityDataCategory).where(
            ActivityDataCategory.activity_id == model.id,
            ActivityDataCategory.category_id == safeguarding.id,
        )
    ).one()
    assert scoped.data_subject_scope_id == vulnerable.id

    feed = session.scalars(
        select(ActivityFeeds).where(ActivityFeeds.consumer_activity_id == operational.id)
    ).one()
    assert feed.source_activity_id == model.id

    assert evaluate(model, frs_profile) == []
    assert evaluate(operational, frs_profile) == []
    assert export_views(model, frs_profile) == {"art30_1"}
    assert export_views(operational, frs_profile) == {"art30_1"}


def test_control_room_processor_activity_rule13(session, actor, frs_profile):
    """Spec §9.3 — Activity C: FRS as processor for a neighbouring fire authority."""
    neighbour = LegalEntity(
        label="Neighbouring Fire Authority", role_type=LegalEntityRoleType.PARTNER_AGENCY
    )
    session.add(neighbour)
    session.flush()

    control = business_function(session, "Control / Mobilising")
    activity = ProcessingActivity(
        name="Regional Control & Mobilising Service (for Neighbouring Fire Authority)",
        business_function_id=control.id,
        activity_type=ActivityType.OPERATIONAL,
        controller_or_processor=ControllerOrProcessor.PROCESSOR,
        record_status=RecordStatus.ACTIVE,
        purpose="Receive emergency calls and mobilise resources on behalf of the controlling "
        "authority.",
        personal_data_source=["from_data_subject", "from_third_party"],
        owner_id=actor.id,
        next_review_at=date(2026, 11, 1),
    )
    session.add(activity)
    session.flush()

    findings = evaluate(activity, frs_profile)
    assert "13" in [f.rule_id for f in findings]

    activity.categories_of_processing = (
        "Call handling, incident logging, resource mobilising and retention carried out "
        "on the controller's documented instructions."
    )
    activity.controllers.append(neighbour)
    activity.contracts.append(
        ContractDSA(
            type=ContractType.CONTROLLER_PROCESSOR,
            art28_checklist_complete=True,
            start_date=date(2026, 4, 1),
            review_date=date(2027, 4, 1),
            parties=[neighbour],
        )
    )
    session.flush()

    findings = evaluate(activity, frs_profile)
    assert "13" not in [f.rule_id for f in findings]
    assert export_views(activity, frs_profile) == {"art30_2"}

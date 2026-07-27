from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from cairn.models import (
    DPIA,
    ActivityDataCategory,
    ActivityFeeds,
    ActivityRetention,
    ActivitySecurity,
    AdequacyStatus,
    ADMUseMode,
    APDScope,
    AuditEvent,
    BreachRecord,
    ComplaintRecord,
    ConsentMethod,
    ConsentRecord,
    ContractDSA,
    ContractType,
    DataSubjectCategory,
    DecisionSupportADM,
    ExternalDataSource,
    InformationAsset,
    LawfulBasisRecord,
    LegalEntity,
    LegalEntityRoleType,
    LIADecision,
    LIARLIRecord,
    PersonalDataCategory,
    PrivacyNotice,
    ProcessingActivity,
    Recipient,
    RecordVersion,
    RegimeScope,
    RetentionRule,
    ScreeningOutcome,
    SecurityMeasure,
    SupplierRole,
    ThirdCountry,
    Transfer,
    TransferMechanism,
)
from conftest import art6, art9, business_function, make_apd, schedule1


def make_activity(session, actor, name):
    activity = ProcessingActivity(
        name=name,
        business_function_id=business_function(session, "Prevention & Community Safety").id,
        purpose="Test purpose.",
        personal_data_source=["from_data_subject"],
        owner_id=actor.id,
        next_review_at=date(2026, 12, 1),
    )
    session.add(activity)
    session.flush()
    return activity


def test_every_entity_instantiates_and_flushes(session, actor, frs_profile):
    retention = RetentionRule(
        label="Incident records", period="7 years", trigger="incident closure"
    )
    security = session.scalars(select(SecurityMeasure)).first()
    system = InformationAsset(
        label="Incident Recording System",
        security_measures=[security],
        s62_logging_in_scope=True,
    )
    country = ThirdCountry(label="United States", adequacy_status=AdequacyStatus.NOT_ADEQUATE)
    supplier = LegalEntity(label="CACI Ltd", role_type=LegalEntityRoleType.DATA_SUPPLIER)
    session.add_all([retention, system, country, supplier])
    session.flush()

    source = ExternalDataSource(
        name="CACI Acorn",
        supplier_legal_entity_id=supplier.id,
        supplier_role=SupplierRole.SEPARATE_CONTROLLER,
        agreement_ref="CACI-2026-01",
        data_categories=[session.scalars(select(PersonalDataCategory)).first()],
    )
    session.add(source)

    activity = make_activity(session, actor, "Schema Coverage Activity")
    consumer = make_activity(session, actor, "Schema Coverage Consumer")

    activity.data_subjects.append(session.scalars(select(DataSubjectCategory)).first())
    activity.recipients.append(session.scalars(select(Recipient)).first())
    activity.assets.append(system)
    activity.data_sources.append(source)

    contract = ContractDSA(
        type=ContractType.CONTROLLER_PROCESSOR,
        art28_checklist_complete=True,
        start_date=date(2026, 4, 1),
        review_date=date(2027, 4, 1),
        parties=[supplier],
    )
    notice = PrivacyNotice(
        notice_version="v1", publish_date=date(2026, 1, 1), covers_art13=True, covers_art14=True
    )
    session.add_all([contract, notice])
    activity.contracts.append(contract)
    activity.privacy_notices.append(notice)

    scoped = ActivityDataCategory(
        activity_id=activity.id,
        category_id=session.scalars(select(PersonalDataCategory)).first().id,
        data_subject_scope_id=session.scalars(select(DataSubjectCategory)).first().id,
    )
    inherited = ActivitySecurity(
        activity_id=activity.id, security_measure_id=security.id, inherited_from_system=True
    )
    retention_link = ActivityRetention(activity_id=activity.id, retention_rule_id=retention.id)
    feed = ActivityFeeds(source_activity_id=activity.id, consumer_activity_id=consumer.id)
    session.add_all([scoped, inherited, retention_link, feed])

    apd = make_apd(
        session, title="APD", scope=APDScope.SCHEDULE1, document_ref="apd_schema_test"
    )
    basis = LawfulBasisRecord(
        activity_id=activity.id,
        regime_scope=RegimeScope.PART2,
        art6_basis=art6(session, "a"),
        art9_condition=art9(session, "g"),
        schedule1_condition=schedule1(session, 18),
        apd=apd,
    )
    session.add(basis)
    session.flush()

    consent = ConsentRecord(
        lawful_basis_record_id=basis.id,
        consented_to="Home fire safety visit",
        wording_shown="I agree to a home fire safety visit.",
        consent_datetime=datetime(2026, 1, 1, 9, 0),
        consent_method=ConsentMethod.ONLINE_FORM,
    )
    lia = LIARLIRecord(
        lawful_basis_record_id=basis.id,
        interest_identified="Community safety",
        necessity_test="Necessary to target visits.",
        decision=LIADecision.PROCEED,
        decision_date=date(2026, 1, 1),
    )
    transfer = Transfer(
        activity_id=activity.id,
        recipient_id=session.scalars(select(Recipient)).first().id,
        third_country_id=country.id,
        mechanism_id=session.scalars(select(TransferMechanism)).first().id,
    )
    dpia = DPIA(activity_id=activity.id, screening_outcome=ScreeningOutcome.REQUIRED)
    breach = BreachRecord(
        summary="Test breach",
        occurred_at=datetime(2026, 2, 1, 12, 0),
        detected_at=datetime(2026, 2, 2, 9, 0),
        reportable_to_ico=False,
    )
    complaint = ComplaintRecord(
        received_at=datetime(2026, 3, 1, 10, 0),
        response_due=date(2026, 3, 31),
        ico_escalation_flagged=True,
    )
    adm = DecisionSupportADM(
        activity_id=activity.id,
        use_mode=ADMUseMode.AUTOMATED,
        solely_automated=False,
        data_sources=[source],
        transparency_ref=notice.id,
    )
    audit = AuditEvent(
        entity_type="processing_activity",
        entity_id=activity.id,
        event="created",
        actor_id=actor.id,
    )
    record_version = RecordVersion(
        entity_type="processing_activity",
        entity_id=activity.id,
        entity_version=1,
        snapshot={"name": activity.name},
        changed_by=actor.id,
    )
    session.add_all([consent, lia, transfer, dpia, breach, complaint, adm, audit, record_version])
    session.flush()

    assert activity.special_category_flag in (True, False)
    assert activity.adm_profiling_flag is False


def test_foreign_keys_enforced(session, actor):
    activity = ProcessingActivity(
        name="Bad FK Activity",
        business_function_id="nonexistent",
        purpose="Test purpose.",
        personal_data_source=["from_data_subject"],
        owner_id=actor.id,
        next_review_at=date(2026, 12, 1),
    )
    session.add(activity)
    with pytest.raises(IntegrityError):
        session.flush()


def test_activity_feeds_rejects_self_reference(session, actor):
    activity = make_activity(session, actor, "Self Feed Activity")
    session.add(
        ActivityFeeds(source_activity_id=activity.id, consumer_activity_id=activity.id)
    )
    with pytest.raises(IntegrityError):
        session.flush()

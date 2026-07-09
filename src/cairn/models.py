import uuid
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import JSON, Column, ForeignKey, Table, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Regime(StrEnum):
    GENERAL = "general"
    LAW_ENFORCEMENT = "law_enforcement"


class RegimeScope(StrEnum):
    PART2 = "part2"
    PART3 = "part3"


ACTIVE_SCOPE = {Regime.GENERAL: RegimeScope.PART2, Regime.LAW_ENFORCEMENT: RegimeScope.PART3}


class RegimeSource(StrEnum):
    POLICY = "policy"
    MANUAL_OVERRIDE = "manual_override"


class ActivityDomain(StrEnum):
    FIRE_SAFETY_ENFORCEMENT = "fire_safety_enforcement"
    FIRE_INVESTIGATION = "fire_investigation"
    FIRESETTER_INTERVENTION = "firesetter_intervention"
    OTHER = "other"


class ActivityType(StrEnum):
    OPERATIONAL = "operational"
    ANALYTICS_MODELLING = "analytics_modelling"


class ControllerOrProcessor(StrEnum):
    CONTROLLER = "controller"
    PROCESSOR = "processor"
    JOINT = "joint"


class RecordStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    ACTIVE = "active"
    RETIRED = "retired"


class LifecycleStage(StrEnum):
    TRIAL = "trial"
    LIVE = "live"
    RETIRED = "retired"


class ExternalDataUseMode(StrEnum):
    NONE = "none"
    MANUAL = "manual"
    AUTOMATED = "automated"


class OrgType(StrEnum):
    PUBLIC_AUTHORITY = "public_authority"
    PRIVATE_BODY = "private_body"
    MIXED = "mixed"


class Role(StrEnum):
    CONTRIBUTOR = "contributor"
    CURATOR = "curator"
    APPROVER_DPO = "approver_dpo"
    VIEWER = "viewer"


class SourceSpecialCategory(StrEnum):
    NONE = "none"
    INFERRED = "inferred"
    DIRECT = "direct"


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class AuditedBase(Base):
    __abstract__ = True

    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    version: Mapped[int] = mapped_column(default=1)
    change_note: Mapped[str | None]


class OrganisationProfile(AuditedBase):
    __tablename__ = "organisation_profile"

    org_name: Mapped[str]
    org_type: Mapped[OrgType]
    sector_pack: Mapped[str] = mapped_column(default="frs")
    applicable_regimes: Mapped[list[str]] = mapped_column(JSON)
    active_modules: Mapped[list[str]] = mapped_column(JSON)
    public_authority_guards: Mapped[bool] = mapped_column(default=False)


class RegimePolicy(AuditedBase):
    __tablename__ = "regime_policy"

    activity_domain: Mapped[ActivityDomain] = mapped_column(unique=True)
    assigned_regime: Mapped[Regime]
    rationale: Mapped[str] = mapped_column(Text)


class User(AuditedBase):
    __tablename__ = "user"

    display_name: Mapped[str]
    role: Mapped[Role] = mapped_column(default=Role.VIEWER)


class PersonalDataCategory(AuditedBase):
    __tablename__ = "personal_data_category"

    label: Mapped[str]
    is_special_category: Mapped[bool] = mapped_column(default=False)
    is_criminal_offence: Mapped[bool] = mapped_column(default=False)


class ExternalDataSource(AuditedBase):
    __tablename__ = "external_data_source"

    name: Mapped[str]
    special_category: Mapped[SourceSpecialCategory] = mapped_column(
        default=SourceSpecialCategory.NONE
    )


activity_datacategory = Table(
    "activity_datacategory",
    Base.metadata,
    Column("activity_id", ForeignKey("processing_activity.id"), primary_key=True),
    Column("category_id", ForeignKey("personal_data_category.id"), primary_key=True),
)

activity_datasource = Table(
    "activity_datasource",
    Base.metadata,
    Column("activity_id", ForeignKey("processing_activity.id"), primary_key=True),
    Column("source_id", ForeignKey("external_data_source.id"), primary_key=True),
)


class ProcessingActivity(AuditedBase):
    __tablename__ = "processing_activity"

    name: Mapped[str]
    activity_domain: Mapped[ActivityDomain | None]
    activity_type: Mapped[ActivityType] = mapped_column(default=ActivityType.OPERATIONAL)
    regime: Mapped[Regime] = mapped_column(default=Regime.GENERAL)
    regime_source: Mapped[RegimeSource] = mapped_column(default=RegimeSource.POLICY)
    regime_override_reason: Mapped[str | None]
    controller_or_processor: Mapped[ControllerOrProcessor] = mapped_column(
        default=ControllerOrProcessor.CONTROLLER
    )
    record_status: Mapped[RecordStatus] = mapped_column(default=RecordStatus.DRAFT)
    lifecycle_stage: Mapped[LifecycleStage] = mapped_column(default=LifecycleStage.LIVE)
    purpose: Mapped[str] = mapped_column(Text)
    is_statutory_task: Mapped[bool] = mapped_column(default=False)
    external_data_use_mode: Mapped[ExternalDataUseMode] = mapped_column(
        default=ExternalDataUseMode.NONE
    )
    vulnerable_or_safeguarding_flag: Mapped[bool] = mapped_column(default=False)
    children_flag: Mapped[bool] = mapped_column(default=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey("user.id"))
    next_review_at: Mapped[date]

    data_categories: Mapped[list[PersonalDataCategory]] = relationship(
        secondary=activity_datacategory
    )
    data_sources: Mapped[list[ExternalDataSource]] = relationship(secondary=activity_datasource)
    basis_records: Mapped[list[LawfulBasisRecord]] = relationship(back_populates="activity")

    @property
    def special_category_flag(self) -> bool:
        return any(c.is_special_category for c in self.data_categories)

    @property
    def criminal_offence_flag(self) -> bool:
        return any(c.is_criminal_offence for c in self.data_categories)


class LawfulBasisRecord(AuditedBase):
    __tablename__ = "lawful_basis_record"
    __table_args__ = (UniqueConstraint("activity_id", "regime_scope"),)

    activity_id: Mapped[str] = mapped_column(ForeignKey("processing_activity.id"))
    regime_scope: Mapped[RegimeScope]
    art6_basis: Mapped[str | None]
    art6_justification: Mapped[str | None] = mapped_column(Text)
    art9_condition: Mapped[str | None]
    schedule1_condition: Mapped[str | None]
    art10_basis: Mapped[str | None]
    s35_basis: Mapped[str | None]
    schedule8_condition: Mapped[str | None]
    apd_ref: Mapped[str | None]

    activity: Mapped[ProcessingActivity] = relationship(back_populates="basis_records")


class AuditEvent(AuditedBase):
    __tablename__ = "audit_event"

    entity_type: Mapped[str]
    entity_id: Mapped[str]
    event: Mapped[str]
    actor_id: Mapped[str] = mapped_column(ForeignKey("user.id"))
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow)
    reason: Mapped[str | None] = mapped_column(Text)
    old_value: Mapped[dict | None] = mapped_column(JSON)
    new_value: Mapped[dict | None] = mapped_column(JSON)


class RecordVersion(AuditedBase):
    __tablename__ = "record_version"

    entity_type: Mapped[str]
    entity_id: Mapped[str]
    entity_version: Mapped[int]
    snapshot: Mapped[dict] = mapped_column(JSON)
    changed_by: Mapped[str] = mapped_column(ForeignKey("user.id"))
    changed_at: Mapped[datetime] = mapped_column(default=utcnow)
    version_change_note: Mapped[str | None]

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import JSON, CheckConstraint, Column, ForeignKey, Table, Text, UniqueConstraint
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn.models.base import AuditedBase, Base
from cairn.models.enums import (
    ActivityDomain,
    ActivityType,
    ControllerOrProcessor,
    ExternalDataUseMode,
    LifecycleStage,
    LineageGranularity,
    RecordStatus,
    Regime,
    RegimeSource,
)
from cairn.models.vocab import (
    DataSubjectCategory,
    ExternalDataSource,
    LegalEntity,
    PersonalDataCategory,
    Recipient,
    RetentionRule,
    SecurityMeasure,
    SystemAsset,
)

if TYPE_CHECKING:
    from cairn.models.supporting import (
        DPIA,
        ContractDSA,
        DecisionSupportADM,
        LawfulBasisRecord,
        PrivacyNotice,
        Transfer,
    )

activity_datasubject = Table(
    "activity_datasubject",
    Base.metadata,
    Column("activity_id", ForeignKey("processing_activity.id"), primary_key=True),
    Column("datasubject_id", ForeignKey("data_subject_category.id"), primary_key=True),
)

activity_recipient = Table(
    "activity_recipient",
    Base.metadata,
    Column("activity_id", ForeignKey("processing_activity.id"), primary_key=True),
    Column("recipient_id", ForeignKey("recipient.id"), primary_key=True),
)

activity_system = Table(
    "activity_system",
    Base.metadata,
    Column("activity_id", ForeignKey("processing_activity.id"), primary_key=True),
    Column("system_id", ForeignKey("system_asset.id"), primary_key=True),
)

activity_contract = Table(
    "activity_contract",
    Base.metadata,
    Column("activity_id", ForeignKey("processing_activity.id"), primary_key=True),
    Column("contract_id", ForeignKey("contract_dsa.id"), primary_key=True),
)

activity_privacynotice = Table(
    "activity_privacynotice",
    Base.metadata,
    Column("activity_id", ForeignKey("processing_activity.id"), primary_key=True),
    Column("privacynotice_id", ForeignKey("privacy_notice.id"), primary_key=True),
)

activity_datasource = Table(
    "activity_datasource",
    Base.metadata,
    Column("activity_id", ForeignKey("processing_activity.id"), primary_key=True),
    Column("source_id", ForeignKey("external_data_source.id"), primary_key=True),
)

activity_controller = Table(
    "activity_controller",
    Base.metadata,
    Column("activity_id", ForeignKey("processing_activity.id"), primary_key=True),
    Column("legal_entity_id", ForeignKey("legal_entity.id"), primary_key=True),
)


class ProcessingActivity(AuditedBase):
    __tablename__ = "processing_activity"

    name: Mapped[str]
    reference: Mapped[str | None]
    business_function_id: Mapped[str] = mapped_column(ForeignKey("business_function.id"))
    description: Mapped[str | None] = mapped_column(Text)
    activity_type: Mapped[ActivityType] = mapped_column(default=ActivityType.OPERATIONAL)
    activity_domain: Mapped[ActivityDomain | None]
    regime: Mapped[Regime] = mapped_column(default=Regime.GENERAL)
    regime_source: Mapped[RegimeSource] = mapped_column(default=RegimeSource.POLICY)
    regime_override_reason: Mapped[str | None]
    controller_or_processor: Mapped[ControllerOrProcessor] = mapped_column(
        default=ControllerOrProcessor.CONTROLLER
    )
    record_status: Mapped[RecordStatus] = mapped_column(default=RecordStatus.DRAFT)
    lifecycle_stage: Mapped[LifecycleStage] = mapped_column(default=LifecycleStage.LIVE)
    trial_start: Mapped[date | None]
    trial_end: Mapped[date | None]
    purpose: Mapped[str] = mapped_column(Text)
    categories_of_processing: Mapped[str | None] = mapped_column(Text)
    is_further_processing: Mapped[bool] = mapped_column(default=False)
    further_processing_note: Mapped[str | None] = mapped_column(Text)
    personal_data_source: Mapped[list[str]] = mapped_column(JSON)
    is_statutory_task: Mapped[bool] = mapped_column(default=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey("user.id"))
    last_reviewed_at: Mapped[date | None]
    next_review_at: Mapped[date]
    vulnerable_or_safeguarding_flag: Mapped[bool] = mapped_column(default=False)
    children_flag: Mapped[bool] = mapped_column(default=False)
    online_childrens_service_flag: Mapped[bool] = mapped_column(default=False)
    childrens_matters_note: Mapped[str | None] = mapped_column(Text)
    external_data_use_mode: Mapped[ExternalDataUseMode] = mapped_column(
        default=ExternalDataUseMode.NONE
    )
    lineage_granularity: Mapped[LineageGranularity] = mapped_column(
        default=LineageGranularity.ACTIVITY
    )
    high_risk_flag: Mapped[bool] = mapped_column(default=False)
    le_data_subject_classification: Mapped[list[str] | None] = mapped_column(JSON)
    le_fact_vs_assessment_noted: Mapped[bool | None]
    s62_logging_note: Mapped[str | None] = mapped_column(Text)

    data_subjects: Mapped[list[DataSubjectCategory]] = relationship(secondary=activity_datasubject)
    data_sources: Mapped[list[ExternalDataSource]] = relationship(secondary=activity_datasource)
    recipients: Mapped[list[Recipient]] = relationship(secondary=activity_recipient)
    systems: Mapped[list[SystemAsset]] = relationship(secondary=activity_system)
    controllers: Mapped[list[LegalEntity]] = relationship(secondary=activity_controller)
    contracts: Mapped[list[ContractDSA]] = relationship(
        "ContractDSA", secondary="activity_contract"
    )
    privacy_notices: Mapped[list[PrivacyNotice]] = relationship(
        "PrivacyNotice", secondary="activity_privacynotice"
    )
    basis_records: Mapped[list[LawfulBasisRecord]] = relationship(
        "LawfulBasisRecord", back_populates="activity"
    )
    adm_records: Mapped[list[DecisionSupportADM]] = relationship(
        "DecisionSupportADM", back_populates="activity"
    )
    dpias: Mapped[list[DPIA]] = relationship("DPIA", back_populates="activity")
    transfers: Mapped[list[Transfer]] = relationship("Transfer", back_populates="activity")
    feeds: Mapped[list[ActivityFeeds]] = relationship(
        "ActivityFeeds",
        foreign_keys="ActivityFeeds.source_activity_id",
        back_populates="source_activity",
    )
    fed_by: Mapped[list[ActivityFeeds]] = relationship(
        "ActivityFeeds",
        foreign_keys="ActivityFeeds.consumer_activity_id",
        back_populates="consumer_activity",
    )
    retention_links: Mapped[list[ActivityRetention]] = relationship(back_populates="activity")
    security_links: Mapped[list[ActivitySecurity]] = relationship(back_populates="activity")
    data_category_links: Mapped[list[ActivityDataCategory]] = relationship(
        back_populates="activity"
    )
    data_categories = association_proxy(
        "data_category_links",
        "category",
        creator=lambda category: ActivityDataCategory(category=category),
    )

    @property
    def special_category_flag(self) -> bool:
        return any(c.is_special_category for c in self.data_categories)

    @property
    def criminal_offence_flag(self) -> bool:
        return any(c.is_criminal_offence for c in self.data_categories)

    @property
    def adm_profiling_flag(self) -> bool:
        if self.external_data_use_mode == ExternalDataUseMode.AUTOMATED:
            return True
        return any(r.solely_automated for r in self.adm_records)


class ActivityDataCategory(AuditedBase):
    __tablename__ = "activity_datacategory"
    __table_args__ = (UniqueConstraint("activity_id", "category_id"),)

    activity_id: Mapped[str] = mapped_column(ForeignKey("processing_activity.id"))
    category_id: Mapped[str] = mapped_column(ForeignKey("personal_data_category.id"))
    data_subject_scope_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_subject_category.id")
    )

    activity: Mapped[ProcessingActivity] = relationship(back_populates="data_category_links")
    category: Mapped[PersonalDataCategory] = relationship()


class ActivitySecurity(AuditedBase):
    __tablename__ = "activity_security"
    __table_args__ = (UniqueConstraint("activity_id", "security_measure_id"),)

    activity_id: Mapped[str] = mapped_column(ForeignKey("processing_activity.id"))
    security_measure_id: Mapped[str] = mapped_column(ForeignKey("security_measure.id"))
    inherited_from_system: Mapped[bool] = mapped_column(default=False)

    activity: Mapped[ProcessingActivity] = relationship(back_populates="security_links")
    measure: Mapped[SecurityMeasure] = relationship()


class ActivityRetention(AuditedBase):
    __tablename__ = "activity_retention"
    __table_args__ = (
        UniqueConstraint("activity_id", "retention_rule_id", "data_category_scope_id"),
    )

    activity_id: Mapped[str] = mapped_column(ForeignKey("processing_activity.id"))
    retention_rule_id: Mapped[str] = mapped_column(ForeignKey("retention_rule.id"))
    data_category_scope_id: Mapped[str | None] = mapped_column(
        ForeignKey("personal_data_category.id")
    )

    activity: Mapped[ProcessingActivity] = relationship(back_populates="retention_links")
    rule: Mapped[RetentionRule] = relationship()


class ActivityFeeds(AuditedBase):
    __tablename__ = "activity_feeds"
    __table_args__ = (
        UniqueConstraint("source_activity_id", "consumer_activity_id"),
        CheckConstraint("source_activity_id != consumer_activity_id"),
    )

    source_activity_id: Mapped[str] = mapped_column(ForeignKey("processing_activity.id"))
    consumer_activity_id: Mapped[str] = mapped_column(ForeignKey("processing_activity.id"))

    source_activity: Mapped[ProcessingActivity] = relationship(
        foreign_keys=[source_activity_id], back_populates="feeds"
    )
    consumer_activity: Mapped[ProcessingActivity] = relationship(
        foreign_keys=[consumer_activity_id], back_populates="fed_by"
    )

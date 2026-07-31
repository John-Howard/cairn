from datetime import date

from sqlalchemy import Column, ForeignKey, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn.models.base import AuditedBase, Base
from cairn.models.enums import (
    AdequacyStatus,
    AssetStatus,
    AssetType,
    EntryStatus,
    LEClassification,
    LegalEntityRoleType,
    RecipientType,
    SecurityClassification,
    SecurityMeasureCategory,
    SourceSpecialCategory,
    SupplierRole,
)


class ProposableMixin:
    entry_status: Mapped[EntryStatus] = mapped_column(default=EntryStatus.APPROVED)


class LegalEntity(ProposableMixin, AuditedBase):
    __tablename__ = "legal_entity"

    label: Mapped[str]
    role_type: Mapped[LegalEntityRoleType]
    contact: Mapped[str | None]
    address: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None]


class BusinessFunction(AuditedBase):
    __tablename__ = "business_function"

    label: Mapped[str]


class DataSubjectCategory(ProposableMixin, AuditedBase):
    __tablename__ = "data_subject_category"

    label: Mapped[str]
    le_classification: Mapped[LEClassification] = mapped_column(default=LEClassification.NONE)


class PersonalDataCategory(ProposableMixin, AuditedBase):
    __tablename__ = "personal_data_category"

    label: Mapped[str]
    is_special_category: Mapped[bool] = mapped_column(default=False)
    is_criminal_offence: Mapped[bool] = mapped_column(default=False)


class Recipient(ProposableMixin, AuditedBase):
    __tablename__ = "recipient"

    label: Mapped[str]
    type: Mapped[RecipientType]
    legal_entity_id: Mapped[str | None] = mapped_column(ForeignKey("legal_entity.id"))


class LawfulBasisGeneral(AuditedBase):
    __tablename__ = "lawful_basis_general"

    code: Mapped[str] = mapped_column(unique=True)
    label: Mapped[str]
    public_authority_restricted: Mapped[bool] = mapped_column(default=False)


class LawfulBasisLE(AuditedBase):
    __tablename__ = "lawful_basis_le"

    code: Mapped[str] = mapped_column(unique=True)
    label: Mapped[str]


class SpecialCategoryCondition(AuditedBase):
    __tablename__ = "special_category_condition"

    code: Mapped[str] = mapped_column(unique=True)
    label: Mapped[str]
    needs_schedule1: Mapped[bool] = mapped_column(default=False)
    needs_apd: Mapped[bool] = mapped_column(default=False)


class Schedule1Condition(AuditedBase):
    __tablename__ = "schedule1_condition"

    paragraph: Mapped[int] = mapped_column(unique=True)
    label: Mapped[str]
    part: Mapped[int]
    needs_apd: Mapped[bool] = mapped_column(default=False)


class Schedule8Condition(AuditedBase):
    __tablename__ = "schedule8_condition"

    paragraph: Mapped[int] = mapped_column(unique=True)
    label: Mapped[str]


class SecurityMeasure(ProposableMixin, AuditedBase):
    __tablename__ = "security_measure"

    label: Mapped[str]
    category: Mapped[SecurityMeasureCategory]


class RetentionRule(ProposableMixin, AuditedBase):
    __tablename__ = "retention_rule"

    label: Mapped[str]
    period: Mapped[str]
    trigger: Mapped[str]
    legal_driver: Mapped[str | None] = mapped_column(Text)
    disposal_method: Mapped[str | None]


asset_securitymeasure = Table(
    "asset_securitymeasure",
    Base.metadata,
    Column("asset_id", ForeignKey("information_asset.id"), primary_key=True),
    Column("security_measure_id", ForeignKey("security_measure.id"), primary_key=True),
)

asset_businessfunction = Table(
    "asset_businessfunction",
    Base.metadata,
    Column("asset_id", ForeignKey("information_asset.id"), primary_key=True),
    Column("business_function_id", ForeignKey("business_function.id"), primary_key=True),
)


class InformationAsset(ProposableMixin, AuditedBase):
    __tablename__ = "information_asset"

    label: Mapped[str]
    asset_type: Mapped[AssetType] = mapped_column(default=AssetType.SYSTEM)
    description: Mapped[str | None] = mapped_column(Text)
    iao_user_id: Mapped[str | None] = mapped_column(ForeignKey("user.id"))
    custodian: Mapped[str | None]
    classification: Mapped[SecurityClassification] = mapped_column(
        default=SecurityClassification.NOT_CLASSIFIED
    )
    contains_personal_data: Mapped[bool] = mapped_column(default=False)
    status: Mapped[AssetStatus] = mapped_column(default=AssetStatus.IN_USE)
    next_review_date: Mapped[date | None]
    supplier_entity_id: Mapped[str | None] = mapped_column(ForeignKey("legal_entity.id"))
    owner: Mapped[str | None]
    location: Mapped[str | None]
    hosting_country: Mapped[str | None]
    default_retention_id: Mapped[str | None] = mapped_column(ForeignKey("retention_rule.id"))
    s62_logging_in_scope: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    security_measures: Mapped[list[SecurityMeasure]] = relationship(
        secondary=asset_securitymeasure
    )
    business_functions: Mapped[list[BusinessFunction]] = relationship(
        secondary=asset_businessfunction
    )
    supplier: Mapped[LegalEntity | None] = relationship()


class ThirdCountry(AuditedBase):
    __tablename__ = "third_country"

    label: Mapped[str]
    adequacy_status: Mapped[AdequacyStatus]


class TransferMechanism(AuditedBase):
    __tablename__ = "transfer_mechanism"

    code: Mapped[str] = mapped_column(unique=True)
    label: Mapped[str]


externaldatasource_datacategory = Table(
    "externaldatasource_datacategory",
    Base.metadata,
    Column("source_id", ForeignKey("external_data_source.id"), primary_key=True),
    Column("category_id", ForeignKey("personal_data_category.id"), primary_key=True),
)


class ExternalDataSource(ProposableMixin, AuditedBase):
    __tablename__ = "external_data_source"

    name: Mapped[str]
    supplier_legal_entity_id: Mapped[str | None] = mapped_column(ForeignKey("legal_entity.id"))
    supplier_role: Mapped[SupplierRole | None]
    agreement_ref: Mapped[str | None]
    special_category: Mapped[SourceSpecialCategory] = mapped_column(
        default=SourceSpecialCategory.NONE
    )
    art14_relationship: Mapped[str | None] = mapped_column(Text)

    data_categories: Mapped[list[PersonalDataCategory]] = relationship(
        secondary=externaldatasource_datacategory
    )

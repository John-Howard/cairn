from sqlalchemy import JSON, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from cairn.models.base import AuditedBase
from cairn.models.enums import ActivityDomain, LegalEntityTopology, OrgType, Regime, Role


class OrganisationProfile(AuditedBase):
    __tablename__ = "organisation_profile"

    org_name: Mapped[str]
    org_type: Mapped[OrgType]
    sector_pack: Mapped[str] = mapped_column(default="frs")
    legal_entity_topology: Mapped[LegalEntityTopology] = mapped_column(
        default=LegalEntityTopology.SINGLE
    )
    applicable_regimes: Mapped[list[str]] = mapped_column(JSON)
    active_modules: Mapped[list[str]] = mapped_column(JSON)
    public_authority_guards: Mapped[bool] = mapped_column(default=False)
    commencement_watch: Mapped[dict | None] = mapped_column(JSON)


class RegimePolicy(AuditedBase):
    __tablename__ = "regime_policy"

    activity_domain: Mapped[ActivityDomain] = mapped_column(unique=True)
    assigned_regime: Mapped[Regime]
    rationale: Mapped[str] = mapped_column(Text)


class User(AuditedBase):
    __tablename__ = "user"

    display_name: Mapped[str]
    role: Mapped[Role] = mapped_column(default=Role.VIEWER)
    business_function_id: Mapped[str | None] = mapped_column(ForeignKey("business_function.id"))

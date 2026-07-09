from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from cairn.models import (
    ActivityDomain,
    Base,
    LawfulBasisRecord,
    OrganisationProfile,
    OrgType,
    PersonalDataCategory,
    ProcessingActivity,
    Regime,
    RegimeScope,
    Role,
    User,
)
from cairn.regime import set_regime_policy


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def actor(session):
    user = User(display_name="IG Curator", role=Role.CURATOR)
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def frs_profile(session):
    profile = OrganisationProfile(
        org_name="Example Fire & Rescue Service",
        org_type=OrgType.PUBLIC_AUTHORITY,
        applicable_regimes=[Regime.GENERAL, Regime.LAW_ENFORCEMENT],
        active_modules=["external_data", "dpia", "contracts", "assets", "complaints"],
        public_authority_guards=True,
    )
    session.add(profile)
    session.flush()
    return profile


@pytest.fixture
def private_profile(session):
    profile = OrganisationProfile(
        org_name="Example Private Body",
        org_type=OrgType.PRIVATE_BODY,
        applicable_regimes=[Regime.GENERAL],
        active_modules=["dpia", "contracts"],
        public_authority_guards=False,
    )
    session.add(profile)
    session.flush()
    return profile


@pytest.fixture
def criminal_category(session):
    category = PersonalDataCategory(label="criminal offence data", is_criminal_offence=True)
    session.add(category)
    session.flush()
    return category


@pytest.fixture
def enforcement_activity(session, actor, criminal_category):
    """Activity D from Spec §9.4, under a law_enforcement Regime Policy, with a Part 3 mapping."""
    set_regime_policy(
        session,
        domain=ActivityDomain.FIRE_SAFETY_ENFORCEMENT,
        regime=Regime.LAW_ENFORCEMENT,
        reason="Fire-safety prosecution treated as competent-authority processing",
        actor=actor,
    )
    activity = ProcessingActivity(
        name="Fire Safety Enforcement & Prosecution",
        activity_domain=ActivityDomain.FIRE_SAFETY_ENFORCEMENT,
        regime=Regime.LAW_ENFORCEMENT,
        purpose="Investigate and prosecute breaches of the Fire Safety Order 2005.",
        is_statutory_task=True,
        owner_id=actor.id,
        next_review_at=date(2026, 10, 1),
        data_categories=[criminal_category],
    )
    activity.basis_records.append(
        LawfulBasisRecord(
            regime_scope=RegimeScope.PART3,
            s35_basis="s35_task",
            schedule8_condition="sch8_1_statutory",
            apd_ref="apd_s42_enforcement",
        )
    )
    session.add(activity)
    session.flush()
    return activity

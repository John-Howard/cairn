from datetime import date

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from cairn.db import get_session
from cairn.models import (
    ActivityDomain,
    APDScope,
    AppropriatePolicyDocument,
    Base,
    BusinessFunction,
    LawfulBasisGeneral,
    LawfulBasisLE,
    LawfulBasisRecord,
    OrganisationProfile,
    OrgType,
    PersonalDataCategory,
    ProcessingActivity,
    Regime,
    RegimeScope,
    Role,
    Schedule1Condition,
    Schedule8Condition,
    SpecialCategoryCondition,
    User,
)
from cairn.regime import set_regime_policy
from cairn.seeds import seed_frs_pack, seed_legal
from cairn.web import create_app


@pytest.fixture
def session():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_fks(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_legal(session)
        seed_frs_pack(session)
        yield session


@pytest.fixture
def actor(session):
    user = User(display_name="IG Curator", role=Role.CURATOR)
    session.add(user)
    session.flush()
    session.info["actor_id"] = user.id
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
    return session.scalars(
        select(PersonalDataCategory).where(PersonalDataCategory.is_criminal_offence)
    ).one()


def business_function(session, label):
    return session.scalars(select(BusinessFunction).where(BusinessFunction.label == label)).one()


def art6(session, code):
    return session.scalars(select(LawfulBasisGeneral).where(LawfulBasisGeneral.code == code)).one()


def s35(session, code):
    return session.scalars(select(LawfulBasisLE).where(LawfulBasisLE.code == code)).one()


def art9(session, code):
    return session.scalars(
        select(SpecialCategoryCondition).where(SpecialCategoryCondition.code == code)
    ).one()


def schedule1(session, paragraph):
    return session.scalars(
        select(Schedule1Condition).where(Schedule1Condition.paragraph == paragraph)
    ).one()


def schedule8(session, paragraph):
    return session.scalars(
        select(Schedule8Condition).where(Schedule8Condition.paragraph == paragraph)
    ).one()


def make_apd(session, *, title, scope, document_ref):
    apd = AppropriatePolicyDocument(
        title=title, scope=scope, document_ref=document_ref, retain_until=date(2030, 1, 1)
    )
    session.add(apd)
    session.flush()
    return apd


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
    apd = make_apd(
        session,
        title="s42 APD — Enforcement",
        scope=APDScope.S42_PART3,
        document_ref="apd_s42_enforcement",
    )
    activity = ProcessingActivity(
        name="Fire Safety Enforcement & Prosecution",
        business_function_id=business_function(
            session, "Protection (Fire Safety Regulation & Enforcement)"
        ).id,
        activity_domain=ActivityDomain.FIRE_SAFETY_ENFORCEMENT,
        regime=Regime.LAW_ENFORCEMENT,
        purpose="Investigate and prosecute breaches of the Fire Safety Order 2005.",
        personal_data_source=["from_data_subject", "from_third_party"],
        is_statutory_task=True,
        owner_id=actor.id,
        next_review_at=date(2026, 10, 1),
        data_categories=[criminal_category],
    )
    activity.basis_records.append(
        LawfulBasisRecord(
            regime_scope=RegimeScope.PART3,
            s35_basis=s35(session, "s35_task"),
            schedule8_condition=schedule8(session, 1),
            apd=apd,
        )
    )
    session.add(activity)
    session.flush()
    return activity


def _sqlite_engine(db_path):
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def enable_fks(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def _wire_app(engine):
    app = create_app()
    session_factory = sessionmaker(bind=engine)

    def override_get_session(request: Request):
        db = session_factory()
        db.info["actor_id"] = request.session.get("user_id")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_session] = override_get_session
    return app


@pytest.fixture
def web_engine(tmp_path):
    engine = _sqlite_engine(tmp_path / "web.db")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def web_app(web_engine):
    return _wire_app(web_engine)


@pytest.fixture
def client(web_app):
    return TestClient(web_app, follow_redirects=False)


@pytest.fixture
def seeded_web_engine(tmp_path):
    engine = _sqlite_engine(tmp_path / "seeded.db")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        profile = OrganisationProfile(
            org_name="Seeded Fire & Rescue Service",
            org_type=OrgType.PUBLIC_AUTHORITY,
            applicable_regimes=[Regime.GENERAL],
            active_modules=["complaints"],
            public_authority_guards=True,
        )
        db.add(profile)
        db.flush()
        seed_legal(db)
        seed_frs_pack(db)
        db.add_all(
            [
                User(display_name="Ada Approver", role=Role.APPROVER_DPO),
                User(display_name="Vic Viewer", role=Role.VIEWER),
            ]
        )
        db.commit()
    return engine


@pytest.fixture
def seeded_client(seeded_web_engine):
    return TestClient(_wire_app(seeded_web_engine), follow_redirects=False)


@pytest.fixture
def activities_web_engine(tmp_path):
    engine = _sqlite_engine(tmp_path / "activities.db")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        profile = OrganisationProfile(
            org_name="Activities Fire & Rescue Service",
            org_type=OrgType.PUBLIC_AUTHORITY,
            applicable_regimes=[Regime.GENERAL, Regime.LAW_ENFORCEMENT],
            active_modules=["complaints", "external_data", "dpia"],
            public_authority_guards=True,
        )
        db.add(profile)
        db.flush()
        seed_legal(db)
        seed_frs_pack(db)
        prevention = business_function(db, "Prevention & Community Safety")
        protection = business_function(
            db, "Protection (Fire Safety Regulation & Enforcement)"
        )
        db.add_all(
            [
                User(display_name="Ada Approver", role=Role.APPROVER_DPO),
                User(display_name="Cara Curator", role=Role.CURATOR),
                User(
                    display_name="Cody Contributor",
                    role=Role.CONTRIBUTOR,
                    business_function_id=prevention.id,
                ),
                User(
                    display_name="Ollie OtherFunction",
                    role=Role.CONTRIBUTOR,
                    business_function_id=protection.id,
                ),
                User(display_name="Vic Viewer", role=Role.VIEWER),
            ]
        )
        db.commit()
    return engine


@pytest.fixture
def activities_client(activities_web_engine):
    return TestClient(_wire_app(activities_web_engine), follow_redirects=False)

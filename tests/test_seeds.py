from sqlalchemy import func, select

from cairn.models import (
    BusinessFunction,
    DataSubjectCategory,
    LawfulBasisGeneral,
    LawfulBasisLE,
    PersonalDataCategory,
    Recipient,
    Schedule1Condition,
    Schedule8Condition,
    SecurityMeasure,
    SecurityMeasureCategory,
    SpecialCategoryCondition,
    TransferMechanism,
)


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_art6_bases(session):
    assert count(session, LawfulBasisGeneral) == 7
    restricted = {
        b.code
        for b in session.scalars(
            select(LawfulBasisGeneral).where(LawfulBasisGeneral.public_authority_restricted)
        )
    }
    assert restricted == {"ea", "f"}


def test_s35_bases(session):
    assert count(session, LawfulBasisLE) == 2
    codes = {b.code for b in session.scalars(select(LawfulBasisLE))}
    assert codes == {"s35_consent", "s35_task"}


def test_art9_conditions(session):
    assert count(session, SpecialCategoryCondition) == 10
    h = session.scalars(
        select(SpecialCategoryCondition).where(SpecialCategoryCondition.code == "h")
    ).one()
    assert h.needs_schedule1 is True
    assert h.needs_apd is False
    g = session.scalars(
        select(SpecialCategoryCondition).where(SpecialCategoryCondition.code == "g")
    ).one()
    assert g.needs_schedule1 is True
    assert g.needs_apd is True


def test_schedule1_conditions(session):
    assert count(session, Schedule1Condition) == 36
    paragraphs = {c.paragraph for c in session.scalars(select(Schedule1Condition))}
    assert 5 not in paragraphs
    para18 = session.scalars(
        select(Schedule1Condition).where(Schedule1Condition.paragraph == 18)
    ).one()
    assert para18.needs_apd is True
    assert para18.part == 2
    para2 = session.scalars(
        select(Schedule1Condition).where(Schedule1Condition.paragraph == 2)
    ).one()
    assert para2.needs_apd is False
    assert para2.part == 1


def test_schedule8_conditions(session):
    assert count(session, Schedule8Condition) == 9
    paragraphs = {c.paragraph for c in session.scalars(select(Schedule8Condition))}
    assert paragraphs == set(range(1, 10))


def test_transfer_mechanisms(session):
    codes = {m.code for m in session.scalars(select(TransferMechanism))}
    assert codes == {"adequacy", "idta", "addendum", "bcr", "art49_exception"}


def test_frs_pack_counts(session):
    assert count(session, BusinessFunction) == 16
    assert count(session, DataSubjectCategory) == 19
    assert count(session, PersonalDataCategory) == 16
    assert count(session, Recipient) == 17
    assert count(session, SecurityMeasure) == 18


def test_frs_pack_sentinels(session):
    special = {
        c.label
        for c in session.scalars(
            select(PersonalDataCategory).where(PersonalDataCategory.is_special_category)
        )
    }
    assert "safeguarding concerns" in special
    assert len(special) == 8

    criminal = session.scalars(
        select(PersonalDataCategory).where(PersonalDataCategory.is_criminal_offence)
    ).all()
    assert len(criminal) == 1

    organisational = session.scalars(
        select(SecurityMeasure).where(
            SecurityMeasure.category == SecurityMeasureCategory.ORGANISATIONAL
        )
    ).all()
    assert len(organisational) == 5

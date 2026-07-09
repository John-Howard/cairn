"""Draft — verify against latest revised legislation before production seeding (Spec §11)."""

from sqlalchemy.orm import Session

from cairn.models import (
    LawfulBasisGeneral,
    LawfulBasisLE,
    Schedule1Condition,
    Schedule8Condition,
    SpecialCategoryCondition,
    TransferMechanism,
)

ART6_BASES = [
    ("a", "Consent", False),
    ("b", "Contract", False),
    ("c", "Legal obligation", False),
    ("d", "Vital interests", False),
    ("e", "Public task", False),
    ("ea", "Recognised legitimate interest", True),
    ("f", "Legitimate interests", True),
]

S35_BASES = [
    ("s35_consent", "Based on law and consent"),
    ("s35_task", "Based on law and necessary for a competent authority's law-enforcement task"),
]

ART9_CONDITIONS = [
    ("a", "Explicit consent", False, False),
    ("b", "Employment, social security and social protection", True, True),
    ("c", "Vital interests", False, False),
    ("d", "Not-for-profit body", False, False),
    ("e", "Made public by the data subject", False, False),
    ("f", "Legal claims", False, False),
    ("g", "Substantial public interest", True, True),
    ("h", "Health or social care purposes", True, False),
    ("i", "Public health", True, False),
    ("j", "Archiving, research and statistics", True, False),
]

SCHEDULE1_CONDITIONS = [
    (1, "Employment, social security and social protection", 1, True),
    (2, "Health or social care purposes", 1, False),
    (3, "Public health", 1, False),
    (4, "Research etc (archiving/research/statistics)", 1, False),
    (6, "Statutory etc and government purposes", 2, True),
    (7, "Administration of justice and parliamentary purposes", 2, True),
    (8, "Equality of opportunity or treatment", 2, True),
    (9, "Racial and ethnic diversity at senior levels of organisations", 2, True),
    (10, "Preventing or detecting unlawful acts", 2, True),
    (11, "Protecting the public against dishonesty etc", 2, True),
    (12, "Regulatory requirements relating to unlawful acts and dishonesty etc", 2, True),
    (13, "Journalism etc in connection with unlawful acts and dishonesty etc", 2, False),
    (14, "Preventing fraud", 2, True),
    (15, "Suspicion of terrorist financing or money laundering", 2, True),
    (16, "Support for individuals with a particular disability or medical condition", 2, True),
    (17, "Counselling etc", 2, True),
    (18, "Safeguarding of children and of individuals at risk", 2, True),
    (19, "Safeguarding of economic well-being of certain individuals", 2, True),
    (20, "Insurance", 2, True),
    (21, "Occupational pensions", 2, True),
    (22, "Political parties", 2, True),
    (23, "Elected representatives responding to requests", 2, True),
    (24, "Disclosure to elected representatives", 2, True),
    (25, "Informing elected representatives about prisoners", 2, True),
    (26, "Publication of legal judgments", 2, True),
    (27, "Anti-doping in sport", 2, True),
    (28, "Standards of behaviour in sport", 2, True),
    (29, "Consent", 3, False),
    (30, "Protecting individual's vital interests", 3, False),
    (31, "Processing by not-for-profit bodies", 3, False),
    (32, "Personal data in the public domain", 3, False),
    (33, "Legal claims", 3, False),
    (34, "Judicial acts", 3, False),
    (
        35,
        "Administration of accounts used in commission of indecency offences involving children",
        3,
        True,
    ),
    (
        36,
        "Extension of Part 2 conditions (removes the substantial public interest requirement)",
        3,
        True,
    ),
    (37, "Extension of insurance conditions", 3, True),
]

SCHEDULE8_CONDITIONS = [
    (1, "Statutory etc purposes (function conferred by law + substantial public interest)"),
    (2, "Administration of justice"),
    (3, "Protecting individual's vital interests"),
    (4, "Safeguarding of children and of individuals at risk"),
    (5, "Personal data already in the public domain (manifestly made public)"),
    (6, "Legal claims"),
    (7, "Judicial acts"),
    (8, "Preventing fraud"),
    (9, "Archiving etc (archiving in the public interest / research / statistics)"),
]

TRANSFER_MECHANISMS = [
    ("adequacy", "Adequacy decision"),
    ("idta", "International Data Transfer Agreement"),
    ("addendum", "UK Addendum to EU SCCs"),
    ("bcr", "Binding Corporate Rules"),
    ("art49_exception", "Article 49 exception"),
]


def seed_legal(session: Session) -> None:
    for code, label, restricted in ART6_BASES:
        session.add(
            LawfulBasisGeneral(code=code, label=label, public_authority_restricted=restricted)
        )
    for code, label in S35_BASES:
        session.add(LawfulBasisLE(code=code, label=label))
    for code, label, needs_schedule1, needs_apd in ART9_CONDITIONS:
        session.add(
            SpecialCategoryCondition(
                code=code, label=label, needs_schedule1=needs_schedule1, needs_apd=needs_apd
            )
        )
    for paragraph, label, part, needs_apd in SCHEDULE1_CONDITIONS:
        session.add(
            Schedule1Condition(paragraph=paragraph, label=label, part=part, needs_apd=needs_apd)
        )
    for paragraph, label in SCHEDULE8_CONDITIONS:
        session.add(Schedule8Condition(paragraph=paragraph, label=label))
    for code, label in TRANSFER_MECHANISMS:
        session.add(TransferMechanism(code=code, label=label))
    session.flush()

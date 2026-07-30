"""FRS intake question sets — seeded per question set (activity | asset).

Wording, hints, ordering and options are data (Intake & Pilot Plan §2); the
`populates` keys name field-mapping handlers in cairn.intake. The activity set
below is Information Audit Question Set v0.1: its Section A (department and
respondent) is collected on the intake start screen, and B1/B2 (identifying and
naming the activity) become the start screen's subject-name field — each wizard
run documents one activity.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.models import IntakeAnswerKind, IntakeQuestion, IntakeQuestionSet

# Business functions whose respondents see Section K (Question Set §K scope).
ENFORCEMENT_FUNCTIONS = {
    "Protection (Fire Safety Regulation & Enforcement)",
    "Fire Investigation",
    "Youth & Early Intervention",
}

PROMPT_LIST = (
    "Think about your regular duties, not IT systems — recruiting, complaints, "
    "community or school programmes, home visits, incidents, inspections or "
    "enforcement, contracts, surveys, CCTV or body-worn video, referrals, mailing lists."
)

# (code, section, section_title, text, hint, kind, options, populates, enforcement_only)
QUESTIONS: list[tuple] = [
    # Section B — about this activity
    ("B3", "B", "About this activity",
     "Is this work new, a trial or a pilot?",
     "If it is business as usual, answer No.",
     IntakeAnswerKind.YES_NO, None, "lifecycle_trial", False),
    ("B3_START", "B", "About this activity",
     "When did it start?",
     None, IntakeAnswerKind.DATE, None, "trial_start", False),
    ("B3_END", "B", "About this activity",
     "When is it due to end?",
     None, IntakeAnswerKind.DATE, None, "trial_end", False),
    ("B4", "B", "About this activity",
     "Is your team doing anything with people's information that you think isn't "
     "written down anywhere?",
     PROMPT_LIST, IntakeAnswerKind.TEXTAREA, None, None, False),
    # Section C — what the activity is for
    ("C1", "C", "What the activity is for",
     "In plain English, what is this activity and why do you do it?",
     None, IntakeAnswerKind.TEXTAREA, None, "purpose", False),
    ("C2", "C", "What the activity is for",
     "What would happen if you didn't collect this information?",
     None, IntakeAnswerKind.TEXTAREA, None, None, False),
    ("C3", "C", "What the activity is for",
     "Is there a law, statutory duty or policy that requires or allows you to do this?",
     None, IntakeAnswerKind.YES_NO, None, "statutory_task", False),
    ("C3_DETAIL", "C", "What the activity is for",
     "Which one, if you know?",
     None, IntakeAnswerKind.TEXT, None, None, False),
    ("C4", "C", "What the activity is for",
     "Are you doing this work for another organisation, under their instructions?",
     None, IntakeAnswerKind.YES_NO, None, "processor", False),
    ("C4_ORG", "C", "What the activity is for",
     "Which organisation?",
     None, IntakeAnswerKind.TEXT, None, None, False),
    ("C5", "C", "What the activity is for",
     "Are you doing this jointly with another organisation, where you both decide how it works?",
     None, IntakeAnswerKind.YES_NO, None, "joint", False),
    # Section D — whose information is it?
    ("D1", "D", "Whose information is it?",
     "Whose information do you handle in this activity?",
     "For example: members of the public, people at incidents, employees, applicants, "
     "cadets, business owners, partner-agency staff.",
     IntakeAnswerKind.VOCAB_MULTI, {"vocab": "data_subjects"}, "data_subjects", False),
    ("D2", "D", "Whose information is it?",
     "Does this activity involve information about children or young people?",
     None, IntakeAnswerKind.YES_NO, None, "children_flag", False),
    ("D3", "D", "Whose information is it?",
     "Does it involve vulnerable people, or people at risk?",
     None, IntakeAnswerKind.YES_NO, None, "vulnerable_flag", False),
    ("D4", "D", "Whose information is it?",
     "Roughly how many people's records are involved?",
     None, IntakeAnswerKind.SINGLE_CHOICE,
     {"choices": [["handful", "A handful"], ["hundreds", "Hundreds"],
                  ["thousands", "Thousands or more"]]},
     None, False),
    # Section E — what information do you hold?
    ("E1", "E", "What information do you hold?",
     "What information do you record about them?",
     "For example: name, address, phone, date of birth, case notes, photos.",
     IntakeAnswerKind.VOCAB_MULTI, {"vocab": "data_categories"}, "data_categories", False),
    ("E2", "E", "What information do you hold?",
     "Do you record any of the following?",
     "Tick all that apply. These are 'special category' types with extra protection.",
     IntakeAnswerKind.VOCAB_MULTI, {"vocab": "special_categories"}, "data_categories", False),
    ("E3", "E", "What information do you hold?",
     "Do you record anything about criminal offences, convictions, cautions, or suspected "
     "offences (including vetting/DBS)?",
     None, IntakeAnswerKind.YES_NO, None, "criminal_offence", False),
    ("E4", "E", "What information do you hold?",
     "If the people involved are different types (e.g. adults and children, or staff and "
     "public) — do you hold different information about each? Please say which.",
     None, IntakeAnswerKind.TEXTAREA, None, None, False),
    # Section F — where does the information come from?
    ("F1", "F", "Where does the information come from?",
     "Where do you get it from?",
     "Tick all that apply.",
     IntakeAnswerKind.MULTI_CHOICE,
     {"choices": [
         ["from_data_subject", "Directly from the person"],
         ["from_third_party", "From a colleague, another team, another organisation or a supplier"],
         ["public_source", "From a publicly available source"],
     ]},
     "personal_data_source", False),
    ("F2", "F", "Where does the information come from?",
     "If it comes from another organisation or a supplier — which one?",
     "The IG team will check whether an agreement or contract is in place.",
     IntakeAnswerKind.VOCAB_MULTI, {"vocab": "external_sources"}, "data_sources", False),
    ("F3", "F", "Where does the information come from?",
     "Do you combine information from different places to build a picture of someone, or "
     "to score, rank or prioritise them?",
     None, IntakeAnswerKind.YES_NO, None, "external_data_use", False),
    ("F4", "F", "Where does the information come from?",
     "Is that done by a person reviewing it, or automatically by a system or model?",
     None, IntakeAnswerKind.SINGLE_CHOICE,
     {"choices": [["person", "By a person"], ["system", "Automatically by a system or model"]]},
     "external_data_use", False),
    ("F5", "F", "Where does the information come from?",
     "Does the system make the decision, or does it only suggest and a person decides?",
     None, IntakeAnswerKind.SINGLE_CHOICE,
     {"choices": [["decides", "The system decides"],
                  ["suggests", "It suggests — a person decides"]]},
     None, False),
    ("F6", "F", "Where does the information come from?",
     "Are people told their information comes from these sources?",
     None, IntakeAnswerKind.YES_NO, None, None, False),
    # Section G — who else sees it?
    ("G1", "G", "Who else sees it?",
     "Who do you share this information with, outside your team?",
     "Internal teams, other organisations, suppliers.",
     IntakeAnswerKind.VOCAB_MULTI, {"vocab": "recipients"}, "recipients", False),
    ("G2", "G", "Who else sees it?",
     "For each one — why do you share it, and is there an agreement, contract or "
     "information-sharing agreement in place?",
     None, IntakeAnswerKind.TEXTAREA, None, None, False),
    ("G3", "G", "Who else sees it?",
     "Do you share it with any organisation outside the UK, or use any system that stores "
     "data outside the UK (including cloud services)?",
     None, IntakeAnswerKind.YES_NO, None, None, False),
    ("G4", "G", "Who else sees it?",
     "Does anyone else handle this information on your behalf (e.g. a supplier, contractor "
     "or IT provider)?",
     None, IntakeAnswerKind.TEXTAREA, None, None, False),
    # Section H — where is it kept, and for how long?
    ("H1", "H", "Where is it kept, and for how long?",
     "Which systems, applications or databases hold this information?",
     None, IntakeAnswerKind.VOCAB_MULTI, {"vocab": "systems"}, "systems", False),
    ("H2", "H", "Where is it kept, and for how long?",
     "Is any of it kept outside those systems — spreadsheets, shared drives, email, paper "
     "files, notebooks, mobile devices?",
     None, IntakeAnswerKind.TEXTAREA, None, None, False),
    ("H3", "H", "Where is it kept, and for how long?",
     "How long do you keep it, and what happens at the end?",
     None, IntakeAnswerKind.TEXTAREA, None, None, False),
    ("H4", "H", "Where is it kept, and for how long?",
     "Is that retention period written down anywhere, or based on a legal requirement?",
     None, IntakeAnswerKind.TEXT, None, None, False),
    ("H5", "H", "Where is it kept, and for how long?",
     "If you hold different types of information in this activity, do they have different "
     "retention periods? Please say which.",
     None, IntakeAnswerKind.TEXTAREA, None, None, False),
    ("H6", "H", "Where is it kept, and for how long?",
     "How is it destroyed or deleted when no longer needed?",
     None, IntakeAnswerKind.TEXT, None, None, False),
    # Section I — how is it protected?
    ("I1", "I", "How is it protected?",
     "Who in your team can access this information — everyone, or specific roles?",
     None, IntakeAnswerKind.TEXT, None, None, False),
    ("I2", "I", "How is it protected?",
     "Is access restricted by log-in, permissions, or physical security (e.g. locked cabinets)?",
     "The IG/IT team will complete the technical detail for each system centrally — just "
     "tell us where the information is and who can get to it.",
     IntakeAnswerKind.TEXT, None, None, False),
    ("I3", "I", "How is it protected?",
     "Is it ever taken out of the office — on laptops, mobiles, tablets or appliance terminals?",
     None, IntakeAnswerKind.YES_NO, None, None, False),
    ("I4", "I", "How is it protected?",
     "Have you had any near-misses, losses or incidents involving this information?",
     None, IntakeAnswerKind.TEXTAREA, None, None, False),
    # Section J — rights, consent and risk
    ("J1", "J", "Rights, consent and risk",
     "Do you ask people for their consent for this activity?",
     None, IntakeAnswerKind.YES_NO, None, None, False),
    ("J1_DETAIL", "J", "Rights, consent and risk",
     "How is consent recorded, and how can someone withdraw it?",
     None, IntakeAnswerKind.TEXTAREA, None, None, False),
    ("J2", "J", "Rights, consent and risk",
     "How do you check age, and do you get parental consent?",
     None, IntakeAnswerKind.TEXTAREA, None, None, False),
    ("J3", "J", "Rights, consent and risk",
     "Are people told what you do with their information (e.g. a privacy notice, a leaflet, "
     "a form, verbally)?",
     None, IntakeAnswerKind.TEXTAREA, None, None, False),
    ("J4", "J", "Rights, consent and risk",
     "If someone asked to see everything you hold about them, could you find it?",
     None, IntakeAnswerKind.YES_NO, None, None, False),
    ("J5", "J", "Rights, consent and risk",
     "Has a Data Protection Impact Assessment (DPIA) ever been done for this activity?",
     None, IntakeAnswerKind.YES_NO, None, None, False),
    ("J6", "J", "Rights, consent and risk",
     "What's the worst thing that could happen if this information was lost, leaked or wrong?",
     None, IntakeAnswerKind.TEXTAREA, None, None, False),
    ("J7", "J", "Rights, consent and risk",
     "Is there anything about this activity that worries you, or that you think we should look at?",
     None, IntakeAnswerKind.TEXTAREA, None, None, False),
    # Section K — enforcement and investigation teams only
    ("K1", "K", "Enforcement and investigation",
     "Does this activity involve investigating or prosecuting a possible offence?",
     "Whether this work is treated as 'law enforcement processing' is a decision for the "
     "DPO — your answers inform it.",
     IntakeAnswerKind.YES_NO, None, None, True),
    ("K2", "K", "Enforcement and investigation",
     "Do you record whether someone is a suspect, witness, victim, or convicted?",
     "Tick all that you record.",
     IntakeAnswerKind.MULTI_CHOICE,
     {"choices": [
         ["suspect", "Suspect"], ["witness", "Witness"],
         ["victim", "Victim"], ["convicted", "Convicted"], ["other", "Other"],
     ]},
     "le_classification", True),
    ("K3", "K", "Enforcement and investigation",
     "Do you distinguish between facts and your professional assessment or opinion "
     "in case records?",
     None, IntakeAnswerKind.YES_NO, None, "le_fact_vs_assessment", True),
    ("K4", "K", "Enforcement and investigation",
     "Does your case system record who accessed or disclosed a record, and when?",
     None, IntakeAnswerKind.TEXTAREA, None, "s62_logging", True),
]


# Conditional logic (Question Set structure, held as configuration).
# {"question": code, "in": [values]}: asked only when that answer matches;
# {"all": [...]} requires every condition. Parents in the same section render
# as GOV.UK conditional reveals; parents in earlier sections gate rendering.
DEPENDS_ON: dict[str, dict] = {
    "B3_START": {"question": "B3", "in": ["yes"]},
    "B3_END": {"question": "B3", "in": ["yes"]},
    "C3_DETAIL": {"question": "C3", "in": ["yes"]},
    "C4_ORG": {"question": "C4", "in": ["yes"]},
    "F4": {"question": "F3", "in": ["yes"]},
    "F5": {"question": "F4", "in": ["system"]},
    "J1_DETAIL": {"question": "J1", "in": ["yes"]},
    "J2": {"all": [
        {"question": "D2", "in": ["yes"]},
        {"question": "J1", "in": ["yes"]},
    ]},
    "K2": {"question": "K1", "in": ["yes"]},
    "K3": {"question": "K1", "in": ["yes"]},
    "K4": {"question": "K1", "in": ["yes"]},
}


def seed_question_set(
    session: Session,
    question_set: IntakeQuestionSet,
    questions: list[tuple],
    depends_on: dict[str, dict],
) -> None:
    """Seed one question set, idempotently. A no-op if that set already has rows —
    the mechanism a later admin screen or one-off backfill (backlog 7/8) reseeds
    through — regardless of whether the other set is populated."""
    existing = session.scalars(
        select(IntakeQuestion.code).where(IntakeQuestion.question_set == question_set)
    ).all()
    if existing:
        return
    for order, row in enumerate(questions, start=1):
        code, section, section_title, text, hint, kind, options, populates, enforcement = row
        session.add(
            IntakeQuestion(
                code=code,
                question_set=question_set,
                section=section,
                section_title=section_title,
                order=order,
                text=text,
                hint=hint,
                answer_kind=kind,
                options=options,
                depends_on=depends_on.get(code),
                populates=populates,
                enforcement_only=enforcement,
            )
        )
    session.flush()


def seed_activity_questions(session: Session) -> None:
    seed_question_set(session, IntakeQuestionSet.ACTIVITY, QUESTIONS, DEPENDS_ON)


# Cairn IAR Question Set v0.1 (docs/Cairn-iar-questions.md). AS-D2 is split into
# AS-D2 (yes/no gate) + AS-D2_NAME (the supplier name) + AS-D3, since depends_on
# can only express "conditional on a specific answer", not "if answered" — the
# same pattern as the activity set's C3/C3_DETAIL pair.
ASSET_QUESTIONS: list[tuple] = [
    # Section A — what it is
    ("AS-A1", "A", "What it is",
     "Which of these best describes it?",
     None, IntakeAnswerKind.SINGLE_CHOICE,
     {"choices": [
         ["system", "A computer system or online service"],
         ["database", "A database or large collection of records"],
         ["software", "A software application"],
         ["paper", "Paper files or records"],
         ["physical", "Equipment, devices or media that hold information"],
     ]},
     "asset_type", False),
    ("AS-A2", "A", "What it is",
     "In plain English, what is it and what is it used for?",
     None, IntakeAnswerKind.TEXTAREA, None, "description", False),
    ("AS-A3", "A", "What it is",
     "Is it still in everyday use?",
     None, IntakeAnswerKind.SINGLE_CHOICE,
     {"choices": [
         ["in_use", "Still used"],
         ["retiring", "Being phased out or replaced"],
         ["disposed", "No longer used at all"],
     ]},
     "status", False),
    # Section B — who looks after it
    ("AS-B1", "B", "Who looks after it",
     "Who looks after it day to day?",
     "A person or team, e.g. \"HR admin team\".",
     IntakeAnswerKind.TEXT, None, "custodian", False),
    ("AS-B2", "B", "Who looks after it",
     "Who is the senior person responsible for it?",
     "The person who would decide if it changed or was got rid of — its owner.",
     IntakeAnswerKind.TEXT, None, "notes", False),
    ("AS-B3", "B", "Who looks after it",
     "Do any other teams or departments use or rely on it? Which ones?",
     "Your own department is already recorded — list any others.",
     IntakeAnswerKind.TEXT, None, "business_functions", False),
    # Section C — the information it holds
    ("AS-C1", "C", "The information it holds",
     "Does it hold information about people?",
     "Staff, the public, anyone — however routine.",
     IntakeAnswerKind.YES_NO, None, "contains_personal_data", False),
    ("AS-C2", "C", "The information it holds",
     "Roughly what information about people does it hold?",
     "Names and contact details? Health information? Photographs or recordings?",
     IntakeAnswerKind.TEXTAREA, None, "notes", False),
    # Section D — where it is
    ("AS-D1", "D", "Where it is",
     "Where is it kept?",
     "A building or room for paper; a supplier, data centre or \"the cloud\" for systems.",
     IntakeAnswerKind.TEXT, None, "location", False),
    ("AS-D2", "D", "Where it is",
     "Is it provided or hosted by an outside company?",
     None, IntakeAnswerKind.YES_NO, None, None, False),
    ("AS-D2_NAME", "D", "Where it is",
     "Which company?",
     None, IntakeAnswerKind.TEXT, None, "supplier", False),
    ("AS-D3", "D", "Where it is",
     "Is any of the information kept outside the UK? Where?",
     None, IntakeAnswerKind.TEXT, None, "hosting_country", False),
    # Section E — how it's protected
    ("AS-E1", "E", "How it's protected",
     "How is it protected?",
     "Locked rooms or cabinets, passwords, restricted access, encryption — pick all "
     "that apply or suggest new ones.",
     IntakeAnswerKind.VOCAB_MULTI, {"vocab": "security_measures"}, "security_measures", False),
    # Section F — keeping and disposing
    ("AS-F1", "F", "Keeping and disposing",
     "How long is the information kept, and is that written down anywhere?",
     None, IntakeAnswerKind.TEXT, None, "retention", False),
    ("AS-F2", "F", "Keeping and disposing",
     "When should this asset next be checked or reviewed?",
     "Leave blank if you don't know.",
     IntakeAnswerKind.DATE, None, "next_review_date", False),
]


ASSET_DEPENDS_ON: dict[str, dict] = {
    "AS-D2_NAME": {"question": "AS-D2", "in": ["yes"]},
    "AS-D3": {"question": "AS-D2", "in": ["yes"]},
    "AS-C2": {"question": "AS-C1", "in": ["yes"]},
}


def seed_asset_questions(session: Session) -> None:
    seed_question_set(session, IntakeQuestionSet.ASSET, ASSET_QUESTIONS, ASSET_DEPENDS_ON)

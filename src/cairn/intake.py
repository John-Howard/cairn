"""Intake wizard — the information-audit questionnaire as Cairn's intake screen.

A guided front end over the draft-activity model (Intake & Pilot Plan §2): each
completed run creates one Processing Activity in record_status=draft with its
junction links populated. Answers matching controlled vocabularies link directly;
unmatched answers become proposed reference values; "don't know" is stored as an
explicit IntakeGap for IG follow-up. Lawful-basis determination, regime
classification, DPIA and sign-off are out of scope — curation turns facts into
compliant records.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.audit import record_event
from cairn.auth import get_csrf_token, require_role, verify_csrf
from cairn.db import get_session
from cairn.inheritance import sync_inherited_security
from cairn.models import (
    AssetStatus,
    AssetType,
    BusinessFunction,
    ControllerOrProcessor,
    DataSubjectCategory,
    EntryStatus,
    ExternalDataSource,
    ExternalDataUseMode,
    InformationAsset,
    IntakeAnswerKind,
    IntakeGap,
    IntakeQuestion,
    IntakeQuestionSet,
    IntakeStatus,
    IntakeSubmission,
    LegalEntity,
    LegalEntityRoleType,
    LifecycleStage,
    PersonalDataCategory,
    ProcessingActivity,
    Recipient,
    RecipientType,
    RecordStatus,
    RegimeSource,
    RetentionRule,
    Role,
    SecurityMeasure,
    SecurityMeasureCategory,
    User,
)
from cairn.regime import resolve_regime
from cairn.seeds.intake import ENFORCEMENT_FUNCTIONS
from cairn.templating import templates

router = APIRouter()

require_intake_user = require_role(Role.CONTRIBUTOR, Role.CURATOR, Role.APPROVER_DPO)
require_curator_or_approver = require_role(Role.CURATOR, Role.APPROVER_DPO)


@dataclass(frozen=True)
class VocabConfig:
    model: type
    label_attr: str = "label"
    proposable: bool = True
    activity_attr: str | None = None


VOCABS: dict[str, VocabConfig] = {
    "data_subjects": VocabConfig(DataSubjectCategory, activity_attr="data_subjects"),
    "data_categories": VocabConfig(PersonalDataCategory, activity_attr="data_categories"),
    # Special-category types are a closed legal list — selectable, never proposable.
    "special_categories": VocabConfig(
        PersonalDataCategory, proposable=False, activity_attr="data_categories"
    ),
    "recipients": VocabConfig(Recipient, activity_attr="recipients"),
    "systems": VocabConfig(InformationAsset, activity_attr="assets"),
    "external_sources": VocabConfig(
        ExternalDataSource, label_attr="name", activity_attr="data_sources"
    ),
    "security_measures": VocabConfig(SecurityMeasure),
}


def _vocab_entries(session: Session, key: str) -> list:
    config = VOCABS[key]
    entries = session.scalars(select(config.model)).all()
    entries = [e for e in entries if e.entry_status != EntryStatus.REJECTED]
    if config.model is PersonalDataCategory:
        if key == "special_categories":
            entries = [e for e in entries if e.is_special_category]
        else:
            entries = [
                e for e in entries if not (e.is_special_category or e.is_criminal_offence)
            ]
    return sorted(entries, key=lambda e: getattr(e, config.label_attr).lower())


def is_enforcement_function(function: BusinessFunction) -> bool:
    return function.label in ENFORCEMENT_FUNCTIONS


def _section_order(session: Session, question_set: IntakeQuestionSet) -> list[str]:
    """Distinct sections for a question set, in seeded order — B–K for activity,
    A–F for asset. Derived from the seed data rather than hardcoded."""
    questions = session.scalars(
        select(IntakeQuestion.section)
        .where(IntakeQuestion.question_set == question_set)
        .order_by(IntakeQuestion.order)
    ).all()
    sections: list[str] = []
    for section in questions:
        if section not in sections:
            sections.append(section)
    return sections


def sections_for(session: Session, submission: IntakeSubmission) -> list[str]:
    sections = _section_order(session, submission.question_set)
    if submission.question_set != IntakeQuestionSet.ACTIVITY:
        return sections
    if is_enforcement_function(submission.business_function):
        return sections
    return [s for s in sections if s != "K"]


def _questions(
    session: Session,
    section: str | None = None,
    question_set: IntakeQuestionSet = IntakeQuestionSet.ACTIVITY,
) -> list[IntakeQuestion]:
    stmt = select(IntakeQuestion).where(
        IntakeQuestion.is_active, IntakeQuestion.question_set == question_set
    )
    if section is not None:
        stmt = stmt.where(IntakeQuestion.section == section)
    return list(session.scalars(stmt.order_by(IntakeQuestion.order)))


def _get_submission(
    session: Session, submission_id: str, user: User
) -> IntakeSubmission:
    submission = session.get(IntakeSubmission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404)
    if user.role == Role.CONTRIBUTOR and submission.respondent_id != user.id:
        raise HTTPException(status_code=403, detail="Not your intake submission")
    return submission


def _require_in_progress(submission: IntakeSubmission) -> None:
    if submission.status != IntakeStatus.IN_PROGRESS:
        raise HTTPException(status_code=422, detail="Submission is no longer editable")


def _answer(submission: IntakeSubmission, code: str) -> dict:
    return submission.answers.get(code) or {}


def _dont_know(submission: IntakeSubmission, code: str) -> bool:
    return bool(_answer(submission, code).get("dk"))


def _effective_value(answers: dict, code: str, default=None):
    answer = answers.get(code) or {}
    if answer.get("dk") or answer.get("na"):
        return default
    return answer.get("v", default)


def _value(submission: IntakeSubmission, code: str, default=None):
    return _effective_value(submission.answers, code, default)


def condition_met(answers: dict, condition: dict | None) -> bool:
    """Evaluate a depends_on condition against an answers dict. A don't-know or
    not-applicable parent answer never satisfies a condition."""
    if not condition:
        return True
    if "all" in condition:
        return all(condition_met(answers, part) for part in condition["all"])
    return _effective_value(answers, condition["question"]) in condition["in"]


def _split_conditions(
    question: IntakeQuestion, section_codes: set[str]
) -> tuple[dict | None, list[dict]]:
    """Split depends_on into (same-section condition, cross-section conditions).

    Same-section parents become GOV.UK conditional reveals; cross-section
    parents were answered in earlier sections and gate rendering outright.
    Every seeded case has at most one same-section parent.
    """
    condition = question.depends_on
    if not condition:
        return None, []
    parts = condition["all"] if "all" in condition else [condition]
    same = [p for p in parts if p["question"] in section_codes]
    cross = [p for p in parts if p["question"] not in section_codes]
    return (same[0] if same else None), cross


def parse_section_form(
    session: Session, questions: list[IntakeQuestion], form
) -> dict[str, dict]:
    answers: dict[str, dict] = {}
    for question in questions:
        code = question.code
        dk = form.get(f"{code}__dk") is not None
        value: object
        kind = question.answer_kind.value
        if kind == "multi_choice":
            value = [v for v in form.getlist(code) if v]
        elif kind == "vocab_multi":
            ids = [v for v in form.getlist(code) if v]
            config = VOCABS[question.options["vocab"]]
            valid_ids = []
            for entry_id in ids:
                if session.get(config.model, entry_id) is not None:
                    valid_ids.append(entry_id)
            new_raw = (form.get(f"{code}__new") or "").strip()
            new_names = [part.strip() for part in new_raw.split(";") if part.strip()]
            if not config.proposable:
                new_names = []
            value = {"ids": valid_ids, "new": new_names}
        else:
            value = (form.get(code) or "").strip()
        answers[code] = {"v": value, "dk": dk}
    return answers


def _vocab_selection(
    session: Session, submission: IntakeSubmission, code: str, vocab_key: str
) -> tuple[list, list[str]]:
    """Resolve a vocab_multi answer to (matched entries, names to propose)."""
    value = _value(submission, code) or {}
    config = VOCABS[vocab_key]
    entries = []
    for entry_id in value.get("ids", []):
        entry = session.get(config.model, entry_id)
        if entry is not None:
            entries.append(entry)
    existing = {
        getattr(e, config.label_attr).lower(): e
        for e in session.scalars(select(config.model)).all()
        if e.entry_status != EntryStatus.REJECTED
    }
    proposals: list[str] = []
    for name in value.get("new", []):
        match = existing.get(name.lower())
        if match is not None:
            if match not in entries:
                entries.append(match)
        elif name.lower() not in {p.lower() for p in proposals}:
            proposals.append(name)
    return entries, proposals


def _yes(submission: IntakeSubmission, code: str) -> bool:
    return _value(submission, code) == "yes"


def _match_legal_entity(session: Session, name: str) -> LegalEntity | None:
    entities = {
        le.label.lower(): le
        for le in session.scalars(select(LegalEntity)).all()
        if le.entry_status != EntryStatus.REJECTED
    }
    return entities.get(name.lower())


def answer_display(
    session: Session, submission: IntakeSubmission, question: IntakeQuestion
) -> str:
    """Human-readable form of a stored answer, for the review and read-only views."""
    if _answer(submission, question.code).get("na") or not condition_met(
        submission.answers, question.depends_on
    ):
        return "Not applicable"
    if _dont_know(submission, question.code):
        return "Don't know"
    value = _value(submission, question.code)
    kind = question.answer_kind.value
    if value in (None, "", [], {}):
        return "—"
    if kind == "yes_no":
        return {"yes": "Yes", "no": "No"}.get(value, "—")
    if kind in ("single_choice", "multi_choice"):
        labels = dict(question.options["choices"])
        selected = value if isinstance(value, list) else [value]
        return ", ".join(labels.get(v, v) for v in selected) or "—"
    if kind == "vocab_multi":
        config = VOCABS[question.options["vocab"]]
        entries, new_names = _vocab_selection(
            session, submission, question.code, question.options["vocab"]
        )
        parts = [getattr(e, config.label_attr) for e in entries]
        parts.extend(f"{name} (new — for approval)" for name in new_names)
        return ", ".join(parts) or "—"
    return str(value)


def _display_map(
    session: Session, submission: IntakeSubmission, questions: list[IntakeQuestion]
) -> dict[str, str]:
    return {q.code: answer_display(session, submission, q) for q in questions}


def submission_view(session: Session, submission: IntakeSubmission) -> dict:
    """Questions, rendered answers and open gaps for one run — what a "created
    from intake" panel needs. Keyed off the submission's own question set, so it
    serves the asset panel now and the activity one when that lands."""
    questions = _questions(session, question_set=submission.question_set)
    return {
        "submission": submission,
        "questions": questions,
        "display": _display_map(session, submission, questions),
        "open_gaps": sorted(
            (g for g in submission.gaps if not g.resolved), key=lambda g: g.question_code
        ),
    }


def _parse_date(raw: object) -> date | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _split_team_names(raw: str) -> list[str]:
    return [part.strip() for part in raw.replace(",", ";").split(";") if part.strip()]


def _coerce_enum(enum_type, raw: object, default):
    """Single-choice answers are stored as posted, so a malformed form must not
    reach the model as an invalid enum value."""
    if not isinstance(raw, str) or not raw:
        return default
    try:
        return enum_type(raw)
    except ValueError:
        return default


def apply_submission(
    session: Session, submission: IntakeSubmission, actor: User
) -> ProcessingActivity:
    """Create the draft Processing Activity (and proposals, and gaps) from the answers."""
    purpose = _value(submission, "C1") or ""
    if not purpose:
        purpose = "(not yet stated — see intake gaps)"

    if _yes(submission, "C4"):
        role = ControllerOrProcessor.PROCESSOR
    elif _yes(submission, "C5"):
        role = ControllerOrProcessor.JOINT
    else:
        role = ControllerOrProcessor.CONTROLLER

    if not _yes(submission, "F3"):
        use_mode = ExternalDataUseMode.NONE
    elif _value(submission, "F4") == "system":
        use_mode = ExternalDataUseMode.AUTOMATED
    else:
        use_mode = ExternalDataUseMode.MANUAL

    activity = ProcessingActivity(
        name=submission.subject_name,
        business_function_id=submission.business_function_id,
        purpose=purpose,
        controller_or_processor=role,
        record_status=RecordStatus.DRAFT,
        lifecycle_stage=(
            LifecycleStage.TRIAL if _yes(submission, "B3") else LifecycleStage.LIVE
        ),
        trial_start=_parse_date(_value(submission, "B3_START")),
        trial_end=_parse_date(_value(submission, "B3_END")),
        is_statutory_task=_yes(submission, "C3"),
        children_flag=_yes(submission, "D2"),
        vulnerable_or_safeguarding_flag=_yes(submission, "D3"),
        external_data_use_mode=use_mode,
        personal_data_source=list(_value(submission, "F1") or []),
        owner_id=submission.respondent_id,
        next_review_at=date.today() + timedelta(days=365),
    )
    if is_enforcement_function(submission.business_function):
        classification = list(_value(submission, "K2") or [])
        activity.le_data_subject_classification = classification or None
        k3 = _value(submission, "K3")
        activity.le_fact_vs_assessment_noted = k3 == "yes" if k3 in ("yes", "no") else None
        activity.s62_logging_note = _value(submission, "K4") or None
    activity.regime = resolve_regime(session, activity)
    activity.regime_source = RegimeSource.POLICY
    session.add(activity)
    session.flush()

    proposals: dict[str, list[str]] = {}
    vocab_questions = [
        ("D1", "data_subjects"),
        ("E1", "data_categories"),
        ("E2", "special_categories"),
        ("F2", "external_sources"),
        ("G1", "recipients"),
        ("H1", "systems"),
    ]
    for code, vocab_key in vocab_questions:
        config = VOCABS[vocab_key]
        entries, new_names = _vocab_selection(session, submission, code, vocab_key)
        collection = getattr(activity, config.activity_attr)
        for entry in entries:
            if entry not in collection:
                collection.append(entry)
        for name in new_names:
            kwargs = {config.label_attr: name, "entry_status": EntryStatus.PROPOSED}
            if config.model is Recipient:
                kwargs["type"] = RecipientType.OTHER
            if config.model is InformationAsset:
                kwargs["asset_type"] = AssetType.SYSTEM
                kwargs["contains_personal_data"] = True
            entry = config.model(**kwargs)
            session.add(entry)
            session.flush()
            collection.append(entry)
            proposals.setdefault(vocab_key, []).append(name)

    if _yes(submission, "E3"):
        criminal = session.scalars(
            select(PersonalDataCategory).where(PersonalDataCategory.is_criminal_offence)
        ).all()
        for category in criminal:
            if category not in activity.data_categories:
                activity.data_categories.append(category)

    session.flush()
    if activity.assets:
        sync_inherited_security(session, activity)

    asked = {q.code: q for q in _questions(session, question_set=submission.question_set)}
    if not is_enforcement_function(submission.business_function):
        asked = {c: q for c, q in asked.items() if not q.enforcement_only}
    for code, question in asked.items():
        if _dont_know(submission, code) and condition_met(
            submission.answers, question.depends_on
        ):
            session.add(
                IntakeGap(
                    submission_id=submission.id,
                    activity_id=activity.id,
                    question_code=code,
                    question_text=question.text,
                )
            )

    submission.status = IntakeStatus.SUBMITTED
    submission.activity_id = activity.id
    submission.change_note = "Intake submitted"
    session.flush()
    record_event(
        session,
        entity=submission,
        event="intake_submitted",
        actor=actor,
        new_value={"activity": activity.id, "proposals": proposals},
    )
    return activity


def apply_asset_submission(
    session: Session, submission: IntakeSubmission, actor: User
) -> InformationAsset:
    """Create the proposed InformationAsset (and proposals, and gaps) from the answers.
    The IAO named in AS-B2 is text, not an account pick — deny-by-default account
    linking is preserved; the curator binds iao_user_id on approval."""
    questions_by_code = {
        q.code: q for q in _questions(session, question_set=IntakeQuestionSet.ASSET)
    }
    notes: list[str] = []

    def add_gap(code: str) -> None:
        session.add(
            IntakeGap(
                submission_id=submission.id,
                asset_id=asset.id,
                question_code=code,
                question_text=questions_by_code[code].text,
            )
        )

    asset_type_value = _value(submission, "AS-A1")
    status_value = _value(submission, "AS-A3")
    asset = InformationAsset(
        label=submission.subject_name,
        asset_type=_coerce_enum(AssetType, asset_type_value, AssetType.SYSTEM),
        description=_value(submission, "AS-A2") or None,
        status=_coerce_enum(AssetStatus, status_value, AssetStatus.IN_USE),
        custodian=_value(submission, "AS-B1") or None,
        contains_personal_data=_yes(submission, "AS-C1"),
        location=_value(submission, "AS-D1") or None,
        hosting_country=_value(submission, "AS-D3") or None,
        next_review_date=_parse_date(_value(submission, "AS-F2")),
        entry_status=EntryStatus.PROPOSED,
    )
    session.add(asset)
    session.flush()

    asset.business_functions.append(submission.business_function)
    other_teams_raw = _value(submission, "AS-B3") or ""
    if other_teams_raw:
        existing_functions = {
            bf.label.lower(): bf for bf in session.scalars(select(BusinessFunction)).all()
        }
        unmatched = []
        for name in _split_team_names(other_teams_raw):
            match = existing_functions.get(name.lower())
            if match is None:
                unmatched.append(name)
            elif match not in asset.business_functions:
                asset.business_functions.append(match)
        if unmatched:
            notes.append("Other teams named but not matched: " + "; ".join(unmatched))
            add_gap("AS-B3")

    named_owner = _value(submission, "AS-B2")
    if named_owner:
        notes.append(f"Named senior owner: {named_owner}")
        add_gap("AS-B2")

    what_it_holds = _value(submission, "AS-C2")
    if what_it_holds:
        notes.append(f"What it holds (respondent's words): {what_it_holds}")

    proposals: dict[str, list[str]] = {}

    supplier_name = _value(submission, "AS-D2_NAME")
    if supplier_name:
        supplier = _match_legal_entity(session, supplier_name)
        if supplier is not None:
            asset.supplier_entity_id = supplier.id
        else:
            supplier = LegalEntity(
                label=supplier_name,
                role_type=LegalEntityRoleType.PROCESSOR,
                entry_status=EntryStatus.PROPOSED,
            )
            session.add(supplier)
            session.flush()
            asset.supplier_entity_id = supplier.id
            proposals.setdefault("legal_entities", []).append(supplier_name)
            notes.append(f"Named supplier proposed as a new reference entry: {supplier_name}")
            add_gap("AS-D2_NAME")

    retention_name = _value(submission, "AS-F1")
    if retention_name:
        rules = {
            r.label.lower(): r
            for r in session.scalars(select(RetentionRule)).all()
            if r.entry_status != EntryStatus.REJECTED
        }
        rule = rules.get(retention_name.lower())
        if rule is not None:
            asset.default_retention_id = rule.id
        else:
            notes.append(f"Stated retention (not matched to a rule): {retention_name}")
            add_gap("AS-F1")

    entries, new_names = _vocab_selection(session, submission, "AS-E1", "security_measures")
    for entry in entries:
        if entry not in asset.security_measures:
            asset.security_measures.append(entry)
    for name in new_names:
        measure = SecurityMeasure(
            label=name,
            category=SecurityMeasureCategory.ORGANISATIONAL,
            entry_status=EntryStatus.PROPOSED,
        )
        session.add(measure)
        session.flush()
        asset.security_measures.append(measure)
        proposals.setdefault("security_measures", []).append(name)

    asset.notes = "\n".join(notes) if notes else None
    session.flush()

    for code, question in questions_by_code.items():
        if _dont_know(submission, code) and condition_met(
            submission.answers, question.depends_on
        ):
            session.add(
                IntakeGap(
                    submission_id=submission.id,
                    asset_id=asset.id,
                    question_code=code,
                    question_text=question.text,
                )
            )

    submission.status = IntakeStatus.SUBMITTED
    submission.asset_id = asset.id
    submission.change_note = "Intake submitted"
    session.flush()
    record_event(
        session,
        entity=submission,
        event="intake_submitted",
        actor=actor,
        new_value={"asset": asset.id, "proposals": proposals},
    )
    return asset


def resolve_supplier_gaps(
    session: Session, entity: LegalEntity, actor: User
) -> list[IntakeGap]:
    """Auto-resolve AS-D2_NAME gaps for assets whose supplier proposal was just approved."""
    gaps = session.scalars(
        select(IntakeGap)
        .join(InformationAsset, IntakeGap.asset_id == InformationAsset.id)
        .where(
            IntakeGap.resolved.is_(False),
            IntakeGap.question_code == "AS-D2_NAME",
            InformationAsset.supplier_entity_id == entity.id,
        )
    ).all()
    note = f"Resolved automatically: supplier '{entity.label}' was approved as a legal entity."
    for gap in gaps:
        gap.resolved = True
        gap.resolution_note = note
        gap.change_note = "Gap resolved"
    session.flush()
    for gap in gaps:
        record_event(
            session,
            entity=gap,
            event="intake_gap_resolved",
            actor=actor,
            reason=note,
            new_value={"question_code": gap.question_code, "submission": gap.submission_id},
        )
    return gaps


def _base_context(request: Request, user: User) -> dict:
    return {"user": user, "csrf_token": get_csrf_token(request)}


@router.get("/intake")
def intake_list(
    request: Request,
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    stmt = select(IntakeSubmission).order_by(IntakeSubmission.created_at.desc())
    if user.role == Role.CONTRIBUTOR:
        stmt = stmt.where(IntakeSubmission.respondent_id == user.id)
    submissions = session.scalars(stmt).all()
    open_gaps = {
        s.id: sum(1 for g in s.gaps if not g.resolved) for s in submissions
    }
    return templates.TemplateResponse(
        request,
        "intake/list.html",
        {**_base_context(request, user), "submissions": submissions, "open_gaps": open_gaps},
    )


def _start_context(request: Request, user: User, session: Session, error: str | None) -> dict:
    functions = session.scalars(
        select(BusinessFunction).order_by(BusinessFunction.label)
    ).all()
    return {
        **_base_context(request, user),
        "functions": functions,
        "own_function_id": user.business_function_id,
        "error": error,
    }


def _resolve_start_function(session: Session, user: User, form) -> BusinessFunction | None:
    function_id = form.get("business_function_id")
    if user.role == Role.CONTRIBUTOR and user.business_function_id:
        function_id = user.business_function_id
    return session.get(BusinessFunction, function_id) if function_id else None


async def _handle_start(
    request: Request,
    user: User,
    session: Session,
    *,
    question_set: IntakeQuestionSet,
    template: str,
    missing_error: str,
):
    """Shared start-screen submit for both question sets: returns the created
    submission, or a 422 re-render of the same template on missing input."""
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    subject_name = (form.get("subject_name") or "").strip()
    function = _resolve_start_function(session, user, form)
    if not subject_name or function is None:
        context = _start_context(request, user, session, missing_error)
        return None, templates.TemplateResponse(
            request, template, context, status_code=422
        )
    submission = IntakeSubmission(
        subject_name=subject_name,
        question_set=question_set,
        business_function_id=function.id,
        respondent_id=user.id,
        respondent_contact=(form.get("respondent_contact") or "").strip() or None,
        answers={},
    )
    session.add(submission)
    session.flush()
    return submission, None


@router.get("/intake/new")
def intake_start_form(
    request: Request,
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request, "intake/start.html", _start_context(request, user, session, None)
    )


@router.post("/intake")
async def intake_start(
    request: Request,
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    submission, error_response = await _handle_start(
        request,
        user,
        session,
        question_set=IntakeQuestionSet.ACTIVITY,
        template="intake/start.html",
        missing_error="Enter a short name for the activity and choose a department",
    )
    if error_response is not None:
        return error_response
    return RedirectResponse(f"/intake/{submission.id}/section/B", status_code=302)


# Registered before /intake/{submission_id} so the literal path wins the match.
@router.get("/intake/assets/new")
def intake_asset_start_form(
    request: Request,
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request, "intake/asset_start.html", _start_context(request, user, session, None)
    )


@router.post("/intake/assets")
async def intake_asset_start(
    request: Request,
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    submission, error_response = await _handle_start(
        request,
        user,
        session,
        question_set=IntakeQuestionSet.ASSET,
        template="intake/asset_start.html",
        missing_error="Enter a short name for the asset and choose a department",
    )
    if error_response is not None:
        return error_response
    first_section = _section_order(session, IntakeQuestionSet.ASSET)[0]
    return RedirectResponse(
        f"/intake/{submission.id}/section/{first_section}", status_code=302
    )


@router.get("/intake/assets/similar")
def intake_asset_similar(
    request: Request,
    subject_name: str = "",
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    """Advisory like-named-asset hint for the start screen. The parameter is named
    for the input htmx reads it from — htmx posts the field's own name."""
    query = subject_name.strip()
    matches: list[InformationAsset] = []
    if len(query) >= 2:
        matches = list(
            session.scalars(
                select(InformationAsset)
                .where(
                    InformationAsset.entry_status != EntryStatus.REJECTED,
                    InformationAsset.label.ilike(f"%{query}%"),
                )
                .order_by(InformationAsset.label)
                .limit(5)
            )
        )
    return templates.TemplateResponse(
        request,
        "intake/_asset_similar.html",
        {"user": user, "matches": matches},
    )


# Registered before /intake/{submission_id} so the literal path wins the match.
@router.get("/intake/gaps")
def intake_gaps(
    request: Request,
    user: User = Depends(require_curator_or_approver),
    session: Session = Depends(get_session),
):
    gaps = session.scalars(
        select(IntakeGap)
        .join(IntakeSubmission, IntakeGap.submission_id == IntakeSubmission.id)
        .order_by(IntakeSubmission.created_at, IntakeGap.question_code)
    ).all()
    open_groups: dict[str, dict] = {}
    for gap in gaps:
        if gap.resolved:
            continue
        group = open_groups.setdefault(
            gap.submission_id, {"submission": gap.submission, "gaps": []}
        )
        group["gaps"].append(gap)
    resolved = [g for g in gaps if g.resolved]
    return templates.TemplateResponse(
        request,
        "intake/gaps.html",
        {
            **_base_context(request, user),
            "open_groups": list(open_groups.values()),
            "open_count": sum(len(g["gaps"]) for g in open_groups.values()),
            "resolved": resolved,
        },
    )


def _get_gap(session: Session, gap_id: str) -> IntakeGap:
    gap = session.get(IntakeGap, gap_id)
    if gap is None:
        raise HTTPException(status_code=404)
    return gap


@router.post("/intake/gaps/{gap_id}/resolve")
async def intake_gap_resolve(
    gap_id: str,
    request: Request,
    user: User = Depends(require_curator_or_approver),
    session: Session = Depends(get_session),
):
    gap = _get_gap(session, gap_id)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    if gap.resolved:
        raise HTTPException(status_code=422, detail="Gap is already resolved")
    note = (form.get("resolution_note") or "").strip()
    if not note:
        raise HTTPException(
            status_code=422,
            detail="Record how the gap was resolved (e.g. what the interview established)",
        )
    gap.resolved = True
    gap.resolution_note = note
    gap.change_note = "Gap resolved"
    session.flush()
    record_event(
        session,
        entity=gap,
        event="intake_gap_resolved",
        actor=user,
        reason=note,
        new_value={"question_code": gap.question_code, "submission": gap.submission_id},
    )
    return RedirectResponse("/intake/gaps", status_code=302)


@router.post("/intake/gaps/{gap_id}/reopen")
async def intake_gap_reopen(
    gap_id: str,
    request: Request,
    user: User = Depends(require_curator_or_approver),
    session: Session = Depends(get_session),
):
    gap = _get_gap(session, gap_id)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    if not gap.resolved:
        raise HTTPException(status_code=422, detail="Gap is not resolved")
    old_note = gap.resolution_note
    gap.resolved = False
    gap.resolution_note = None
    gap.change_note = "Gap reopened"
    session.flush()
    record_event(
        session,
        entity=gap,
        event="intake_gap_reopened",
        actor=user,
        old_value={"resolution_note": old_note},
        new_value={"question_code": gap.question_code, "submission": gap.submission_id},
    )
    return RedirectResponse("/intake/gaps", status_code=302)


@router.get("/intake/{submission_id}")
def intake_view(
    submission_id: str,
    request: Request,
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    submission = _get_submission(session, submission_id, user)
    if submission.status == IntakeStatus.IN_PROGRESS:
        first_section = sections_for(session, submission)[0]
        return RedirectResponse(
            f"/intake/{submission_id}/section/{first_section}", status_code=302
        )
    questions = _questions(session, question_set=submission.question_set)
    if not is_enforcement_function(submission.business_function):
        questions = [q for q in questions if not q.enforcement_only]
    return templates.TemplateResponse(
        request,
        "intake/view.html",
        {
            **_base_context(request, user),
            "submission": submission,
            "questions": questions,
            "display": _display_map(session, submission, questions),
            "gaps": sorted(submission.gaps, key=lambda g: (g.resolved, g.question_code)),
        },
    )


def _section_or_404(session: Session, submission: IntakeSubmission, section: str) -> list[str]:
    sections = sections_for(session, submission)
    if section not in sections:
        raise HTTPException(status_code=404)
    return sections


def _render_tree(submission_answers: dict, questions: list[IntakeQuestion]) -> list[dict]:
    """Nest same-section dependents under their parent (for conditional
    reveals) and drop questions whose cross-section conditions are unmet."""
    section_codes = {q.code for q in questions}
    nodes: dict[str, dict] = {}
    items: list[dict] = []
    for question in questions:
        same, cross = _split_conditions(question, section_codes)
        if not all(condition_met(submission_answers, c) for c in cross):
            continue
        node = {"question": question, "children": [], "reveal_values": None}
        if same is not None:
            parent = nodes.get(same["question"])
            if parent is None:
                continue  # parent itself not asked → neither is the child
            node["reveal_values"] = same["in"]
            nodes[question.code] = node
            parent["children"].append(node)
        else:
            nodes[question.code] = node
            items.append(node)
    return items


def normalise_answers(
    session: Session, answers: dict, question_set: IntakeQuestionSet
) -> dict:
    """Reset any lingering answer whose depends_on is no longer met — e.g. the
    respondent went back and changed the parent. Server-side authority; the
    conditional reveals are only a courtesy."""
    for question in _questions(session, question_set=question_set):
        if question.depends_on is None:
            continue
        entry = answers.get(question.code)
        if entry and not entry.get("na") and not condition_met(answers, question.depends_on):
            answers[question.code] = {"na": True}
    return answers


def _vocab_questions(session: Session, question_set: IntakeQuestionSet) -> list[tuple[str, str]]:
    return [
        (q.code, q.options["vocab"])
        for q in _questions(session, question_set=question_set)
        if q.answer_kind == IntakeAnswerKind.VOCAB_MULTI
    ]


def validate_section(
    section: str, answers: dict, question_set: IntakeQuestionSet
) -> list[dict]:
    """True contradictions only — intake stays tolerant of everything else.
    The C4/C5 processor-vs-joint contradiction is an activity-only check; the
    asset set also has a section "C" (a different meaning), so gate explicitly
    on question_set rather than relying on the code lookup to simply miss."""
    errors: list[dict] = []
    if question_set == IntakeQuestionSet.ACTIVITY and section == "C":
        if (
            _effective_value(answers, "C4") == "yes"
            and _effective_value(answers, "C5") == "yes"
        ):
            errors.append(
                {
                    "code": "C5",
                    "message": (
                        "An activity is recorded as either done for another "
                        "organisation (the previous question) or done jointly — "
                        "it can't be both. Answer Yes to whichever is the closer "
                        "fit, or ask the IG team."
                    ),
                }
            )
    return errors


def _section_context(
    request: Request,
    user: User,
    session: Session,
    submission: IntakeSubmission,
    section: str,
    sections: list[str],
    *,
    answers: dict | None = None,
    errors: list[dict] | None = None,
) -> dict:
    questions = _questions(session, section, submission.question_set)
    vocab_options = {}
    for question in questions:
        if question.answer_kind.value == "vocab_multi":
            key = question.options["vocab"]
            config = VOCABS[key]
            vocab_options[question.code] = {
                "entries": [
                    (e.id, getattr(e, config.label_attr))
                    for e in _vocab_entries(session, key)
                ],
                "proposable": config.proposable,
            }
    answers = submission.answers if answers is None else answers
    index = sections.index(section)
    return {
        **_base_context(request, user),
        "submission": submission,
        "answers": answers,
        "section": section,
        "section_title": questions[0].section_title if questions else section,
        "items": _render_tree(answers, questions),
        "vocab_options": vocab_options,
        "sections": sections,
        "prev_section": sections[index - 1] if index > 0 else None,
        "is_last": index == len(sections) - 1,
        "errors": errors or [],
        "error_map": {e["code"]: e["message"] for e in (errors or [])},
    }


@router.get("/intake/{submission_id}/section/{section}")
def intake_section_form(
    submission_id: str,
    section: str,
    request: Request,
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    submission = _get_submission(session, submission_id, user)
    _require_in_progress(submission)
    sections = _section_or_404(session, submission, section)
    context = _section_context(request, user, session, submission, section, sections)
    return templates.TemplateResponse(request, "intake/section.html", context)


@router.post("/intake/{submission_id}/section/{section}")
async def intake_section_save(
    submission_id: str,
    section: str,
    request: Request,
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    submission = _get_submission(session, submission_id, user)
    _require_in_progress(submission)
    sections = _section_or_404(session, submission, section)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    questions = _questions(session, section, submission.question_set)
    merged = normalise_answers(
        session,
        {**submission.answers, **parse_section_form(session, questions, form)},
        submission.question_set,
    )
    errors = validate_section(section, merged, submission.question_set)
    if errors:
        context = _section_context(
            request, user, session, submission, section, sections,
            answers=merged, errors=errors,
        )
        return templates.TemplateResponse(
            request, "intake/section.html", context, status_code=422
        )
    submission.answers = merged
    session.flush()
    index = sections.index(section)
    if form.get("nav") == "back" and index > 0:
        return RedirectResponse(
            f"/intake/{submission_id}/section/{sections[index - 1]}", status_code=302
        )
    if index == len(sections) - 1:
        return RedirectResponse(f"/intake/{submission_id}/review", status_code=302)
    return RedirectResponse(
        f"/intake/{submission_id}/section/{sections[index + 1]}", status_code=302
    )


@router.get("/intake/{submission_id}/review")
def intake_review(
    submission_id: str,
    request: Request,
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    submission = _get_submission(session, submission_id, user)
    _require_in_progress(submission)
    sections = sections_for(session, submission)
    questions = _questions(session, question_set=submission.question_set)
    if "K" not in sections:
        questions = [q for q in questions if not q.enforcement_only]
    proposals: dict[str, list[str]] = {}
    for code, vocab_key in _vocab_questions(session, submission.question_set):
        _entries, new_names = _vocab_selection(session, submission, code, vocab_key)
        if new_names:
            proposals[vocab_key] = new_names
    if submission.question_set == IntakeQuestionSet.ASSET:
        supplier_name = _value(submission, "AS-D2_NAME")
        if supplier_name and _match_legal_entity(session, supplier_name) is None:
            proposals.setdefault("legal_entities", []).append(supplier_name)
    dont_know_codes = [
        q.code
        for q in questions
        if _dont_know(submission, q.code)
        and condition_met(submission.answers, q.depends_on)
    ]
    return templates.TemplateResponse(
        request,
        "intake/review.html",
        {
            **_base_context(request, user),
            "submission": submission,
            "questions": questions,
            "sections": sections,
            "display": _display_map(session, submission, questions),
            "proposals": proposals,
            "dont_know_codes": dont_know_codes,
        },
    )


@router.post("/intake/{submission_id}/submit")
async def intake_submit(
    submission_id: str,
    request: Request,
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    submission = _get_submission(session, submission_id, user)
    _require_in_progress(submission)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    if submission.question_set == IntakeQuestionSet.ASSET:
        asset = apply_asset_submission(session, submission, user)
        return RedirectResponse(f"/assets/{asset.id}", status_code=302)
    activity = apply_submission(session, submission, user)
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.post("/intake/{submission_id}/cancel")
async def intake_cancel(
    submission_id: str,
    request: Request,
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    submission = _get_submission(session, submission_id, user)
    _require_in_progress(submission)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    submission.status = IntakeStatus.CANCELLED
    submission.change_note = "Intake cancelled"
    session.flush()
    record_event(session, entity=submission, event="intake_cancelled", actor=user)
    return RedirectResponse("/intake", status_code=302)

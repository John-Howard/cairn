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
    BusinessFunction,
    ControllerOrProcessor,
    DataSubjectCategory,
    EntryStatus,
    ExternalDataSource,
    ExternalDataUseMode,
    IntakeGap,
    IntakeQuestion,
    IntakeStatus,
    IntakeSubmission,
    LifecycleStage,
    PersonalDataCategory,
    ProcessingActivity,
    Recipient,
    RecipientType,
    RecordStatus,
    RegimeSource,
    Role,
    SystemAsset,
    User,
)
from cairn.regime import resolve_regime
from cairn.seeds.intake import ENFORCEMENT_FUNCTIONS
from cairn.templating import templates

router = APIRouter()

require_intake_user = require_role(Role.CONTRIBUTOR, Role.CURATOR, Role.APPROVER_DPO)

SECTION_ORDER = ["B", "C", "D", "E", "F", "G", "H", "I", "J", "K"]


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
    "systems": VocabConfig(SystemAsset, activity_attr="systems"),
    "external_sources": VocabConfig(
        ExternalDataSource, label_attr="name", activity_attr="data_sources"
    ),
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


def sections_for(submission: IntakeSubmission) -> list[str]:
    if is_enforcement_function(submission.business_function):
        return SECTION_ORDER
    return [s for s in SECTION_ORDER if s != "K"]


def _questions(session: Session, section: str | None = None) -> list[IntakeQuestion]:
    stmt = select(IntakeQuestion).where(IntakeQuestion.is_active)
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


def _value(submission: IntakeSubmission, code: str, default=None):
    answer = _answer(submission, code)
    if answer.get("dk"):
        return default
    return answer.get("v", default)


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


def answer_display(
    session: Session, submission: IntakeSubmission, question: IntakeQuestion
) -> str:
    """Human-readable form of a stored answer, for the review and read-only views."""
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


def _parse_date(raw: object) -> date | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


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
        name=submission.activity_name,
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
    if activity.systems:
        sync_inherited_security(session, activity)

    asked = {q.code: q for q in _questions(session)}
    if not is_enforcement_function(submission.business_function):
        asked = {c: q for c, q in asked.items() if not q.enforcement_only}
    for code, question in asked.items():
        if _dont_know(submission, code):
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


@router.get("/intake/new")
def intake_start_form(
    request: Request,
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    functions = session.scalars(
        select(BusinessFunction).order_by(BusinessFunction.label)
    ).all()
    return templates.TemplateResponse(
        request,
        "intake/start.html",
        {
            **_base_context(request, user),
            "functions": functions,
            "own_function_id": user.business_function_id,
            "error": None,
        },
    )


@router.post("/intake")
async def intake_start(
    request: Request,
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    activity_name = (form.get("activity_name") or "").strip()
    function_id = form.get("business_function_id")
    if user.role == Role.CONTRIBUTOR and user.business_function_id:
        function_id = user.business_function_id
    function = session.get(BusinessFunction, function_id) if function_id else None
    if not activity_name or function is None:
        functions = session.scalars(
            select(BusinessFunction).order_by(BusinessFunction.label)
        ).all()
        return templates.TemplateResponse(
            request,
            "intake/start.html",
            {
                **_base_context(request, user),
                "functions": functions,
                "own_function_id": user.business_function_id,
                "error": "Enter a short name for the activity and choose a department",
            },
            status_code=422,
        )
    submission = IntakeSubmission(
        activity_name=activity_name,
        business_function_id=function.id,
        respondent_id=user.id,
        respondent_contact=(form.get("respondent_contact") or "").strip() or None,
        answers={},
    )
    session.add(submission)
    session.flush()
    return RedirectResponse(f"/intake/{submission.id}/section/B", status_code=302)


@router.get("/intake/{submission_id}")
def intake_view(
    submission_id: str,
    request: Request,
    user: User = Depends(require_intake_user),
    session: Session = Depends(get_session),
):
    submission = _get_submission(session, submission_id, user)
    if submission.status == IntakeStatus.IN_PROGRESS:
        return RedirectResponse(f"/intake/{submission_id}/section/B", status_code=302)
    questions = _questions(session)
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
            "gaps": [g for g in submission.gaps if not g.resolved],
        },
    )


def _section_or_404(submission: IntakeSubmission, section: str) -> list[str]:
    sections = sections_for(submission)
    if section not in sections:
        raise HTTPException(status_code=404)
    return sections


def _section_context(
    request: Request,
    user: User,
    session: Session,
    submission: IntakeSubmission,
    section: str,
    sections: list[str],
) -> dict:
    questions = _questions(session, section)
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
    index = sections.index(section)
    return {
        **_base_context(request, user),
        "submission": submission,
        "section": section,
        "section_title": questions[0].section_title if questions else section,
        "questions": questions,
        "vocab_options": vocab_options,
        "sections": sections,
        "prev_section": sections[index - 1] if index > 0 else None,
        "is_last": index == len(sections) - 1,
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
    sections = _section_or_404(submission, section)
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
    sections = _section_or_404(submission, section)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    questions = _questions(session, section)
    submission.answers = {
        **submission.answers,
        **parse_section_form(session, questions, form),
    }
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
    sections = sections_for(submission)
    questions = _questions(session)
    if "K" not in sections:
        questions = [q for q in questions if not q.enforcement_only]
    proposals: dict[str, list[str]] = {}
    for code, vocab_key in [
        ("D1", "data_subjects"),
        ("E1", "data_categories"),
        ("F2", "external_sources"),
        ("G1", "recipients"),
        ("H1", "systems"),
    ]:
        _entries, new_names = _vocab_selection(session, submission, code, vocab_key)
        if new_names:
            proposals[vocab_key] = new_names
    dont_know_codes = [q.code for q in questions if _dont_know(submission, q.code)]
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

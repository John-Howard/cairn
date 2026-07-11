from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.auth import current_user, get_csrf_token, verify_csrf
from cairn.db import get_session
from cairn.models import DPIA as DPIAModel
from cairn.models import (
    ActivityFeeds,
    ActivityRetention,
    ActivitySecurity,
    ActivityType,
    ADMUseMode,
    ContractDSA,
    ContractType,
    DecisionSupportADM,
    EntryStatus,
    ExternalDataSource,
    ExternalDataUseMode,
    LegalEntity,
    PersonalDataCategory,
    PrivacyNotice,
    ProcessingActivity,
    Recipient,
    Regime,
    ResidualRisk,
    RetentionRule,
    Role,
    ScreeningOutcome,
    SecurityMeasure,
    SubProcessorAuthorisation,
    ThirdCountry,
    Transfer,
    TransferMechanism,
    User,
)
from cairn.regime import active_basis
from cairn.rules import APPROPRIATE_SAFEGUARDS_MECHANISMS
from cairn.templating import templates

router = APIRouter()

SCREENING_OUTCOME_LABELS = {
    ScreeningOutcome.REQUIRED: "Required",
    ScreeningOutcome.NOT_REQUIRED: "Not required",
    ScreeningOutcome.DOCUMENTED_NOT_REQUIRED: "Documented not required",
}
RESIDUAL_RISK_LABELS = {
    ResidualRisk.LOW: "Low",
    ResidualRisk.MEDIUM: "Medium",
    ResidualRisk.HIGH: "High",
}
CONTRACT_TYPE_LABELS = {
    ContractType.CONTROLLER_PROCESSOR: "Controller-processor",
    ContractType.JOINT_CONTROLLER: "Joint controller",
    ContractType.DATA_SHARING: "Data sharing",
}
SUB_PROCESSOR_AUTHORISATION_LABELS = {
    SubProcessorAuthorisation.NONE: "None",
    SubProcessorAuthorisation.GENERAL: "General",
    SubProcessorAuthorisation.SPECIFIC: "Specific",
}
ADM_USE_MODE_LABELS = {ADMUseMode.MANUAL: "Manual", ADMUseMode.AUTOMATED: "Automated"}


def _display_label(obj) -> str:
    label = getattr(obj, "label", None) or getattr(obj, "name", None) or str(obj.id)
    if getattr(obj, "entry_status", None) == EntryStatus.PROPOSED:
        return f"{label} (proposed)"
    return label


def _get_activity(session: Session, activity_id: str) -> ProcessingActivity:
    activity = session.get(ProcessingActivity, activity_id)
    if activity is None:
        raise HTTPException(status_code=404)
    return activity


def _require_can_author(user: User) -> None:
    if user.role not in (Role.CURATOR, Role.APPROVER_DPO):
        raise HTTPException(status_code=403, detail="Not permitted to author register records")


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate_fk(session: Session, model: type, value: str, field: str, label: str) -> dict | None:
    if value and session.get(model, value) is None:
        return {"field": field, "message": f"Select a valid {label}"}
    return None


def _validate_required_fk(
    session: Session, model: type, value: str, field: str, label: str
) -> dict | None:
    if not value:
        return {"field": field, "message": f"Select a {label}"}
    return _validate_fk(session, model, value, field, label)


def _approver_dpo_options(session: Session) -> list[tuple[str, str]]:
    users = session.scalars(
        select(User)
        .where(User.role == Role.APPROVER_DPO, User.is_active)
        .order_by(User.display_name)
    ).all()
    return [("", "Not set")] + [(u.id, u.display_name) for u in users]


def _new_dpia_values() -> dict:
    return {
        "screening_outcome": ScreeningOutcome.NOT_REQUIRED.value,
        "nature_scope_context_purposes": "",
        "necessity_proportionality": "",
        "risks_to_individuals": "",
        "mitigations": "",
        "residual_risk": "",
        "dpo_advice": "",
        "sign_off_by": "",
        "review_date": "",
    }


def _dpia_to_values(dpia: DPIAModel) -> dict:
    return {
        "screening_outcome": dpia.screening_outcome.value,
        "nature_scope_context_purposes": dpia.nature_scope_context_purposes or "",
        "necessity_proportionality": dpia.necessity_proportionality or "",
        "risks_to_individuals": dpia.risks_to_individuals or "",
        "mitigations": dpia.mitigations or "",
        "residual_risk": dpia.residual_risk.value if dpia.residual_risk else "",
        "dpo_advice": dpia.dpo_advice or "",
        "sign_off_by": dpia.sign_off_by or "",
        "review_date": dpia.review_date.isoformat() if dpia.review_date else "",
    }


def _parse_dpia_form(form) -> dict:
    return {
        "screening_outcome": form.get("screening_outcome", ScreeningOutcome.NOT_REQUIRED.value),
        "nature_scope_context_purposes": form.get("nature_scope_context_purposes", "").strip(),
        "necessity_proportionality": form.get("necessity_proportionality", "").strip(),
        "risks_to_individuals": form.get("risks_to_individuals", "").strip(),
        "mitigations": form.get("mitigations", "").strip(),
        "residual_risk": form.get("residual_risk", ""),
        "dpo_advice": form.get("dpo_advice", "").strip(),
        "sign_off_by": form.get("sign_off_by", ""),
        "review_date": form.get("review_date", ""),
    }


def _validate_dpia(session: Session, values: dict) -> list[dict]:
    errors = []
    try:
        ScreeningOutcome(values["screening_outcome"])
    except ValueError:
        errors.append({"field": "screening_outcome", "message": "Select a valid screening outcome"})
    if values["residual_risk"]:
        try:
            ResidualRisk(values["residual_risk"])
        except ValueError:
            errors.append({"field": "residual_risk", "message": "Select a valid residual risk"})
    if values["sign_off_by"]:
        sign_off_user = session.get(User, values["sign_off_by"])
        if sign_off_user is None or sign_off_user.role != Role.APPROVER_DPO:
            errors.append(
                {"field": "sign_off_by", "message": "Select a valid approver_dpo user"}
            )
    if values["review_date"] and not _valid_date(values["review_date"]):
        errors.append({"field": "review_date", "message": "Enter a valid date"})
    return errors


def _apply_dpia_values(dpia: DPIAModel, values: dict) -> None:
    dpia.screening_outcome = ScreeningOutcome(values["screening_outcome"])
    dpia.nature_scope_context_purposes = values["nature_scope_context_purposes"] or None
    dpia.necessity_proportionality = values["necessity_proportionality"] or None
    dpia.risks_to_individuals = values["risks_to_individuals"] or None
    dpia.mitigations = values["mitigations"] or None
    dpia.residual_risk = ResidualRisk(values["residual_risk"]) if values["residual_risk"] else None
    dpia.dpo_advice = values["dpo_advice"] or None
    dpia.sign_off_by = values["sign_off_by"] or None
    dpia.review_date = date.fromisoformat(values["review_date"]) if values["review_date"] else None


def _dpia_form_context(
    activity: ProcessingActivity,
    user: User,
    session: Session,
    *,
    values: dict,
    errors: list[dict],
    csrf_token: str,
    is_edit: bool,
    dpia_id: str | None = None,
) -> dict:
    error_map = {e["field"]: e["message"] for e in errors}
    return {
        "user": user,
        "activity": activity,
        "is_edit": is_edit,
        "dpia_id": dpia_id,
        "values": values,
        "errors": errors,
        "error_map": error_map,
        "csrf_token": csrf_token,
        "screening_outcome_options": list(SCREENING_OUTCOME_LABELS.items()),
        "residual_risk_options": [("", "Not set")] + list(RESIDUAL_RISK_LABELS.items()),
        "sign_off_options": _approver_dpo_options(session),
    }


def _get_dpia_or_404(session: Session, activity: ProcessingActivity, dpia_id: str) -> DPIAModel:
    dpia = session.get(DPIAModel, dpia_id)
    if dpia is None or dpia.activity_id != activity.id:
        raise HTTPException(status_code=404)
    return dpia


@router.get("/activities/{activity_id}/dpias/new")
def dpia_new_form(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    context = _dpia_form_context(
        activity,
        user,
        session,
        values=_new_dpia_values(),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=False,
    )
    return templates.TemplateResponse(request, "activities/dpia_form.html", context)


@router.post("/activities/{activity_id}/dpias/new")
async def dpia_create(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_dpia_form(form)
    errors = _validate_dpia(session, values)
    if errors:
        context = _dpia_form_context(
            activity,
            user,
            session,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=False,
        )
        return templates.TemplateResponse(
            request, "activities/dpia_form.html", context, status_code=422
        )
    dpia = DPIAModel(activity_id=activity.id)
    _apply_dpia_values(dpia, values)
    session.add(dpia)
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.get("/activities/{activity_id}/dpias/{dpia_id}/edit")
def dpia_edit_form(
    activity_id: str,
    dpia_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    dpia = _get_dpia_or_404(session, activity, dpia_id)
    context = _dpia_form_context(
        activity,
        user,
        session,
        values=_dpia_to_values(dpia),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=True,
        dpia_id=dpia.id,
    )
    return templates.TemplateResponse(request, "activities/dpia_form.html", context)


@router.post("/activities/{activity_id}/dpias/{dpia_id}/edit")
async def dpia_update(
    activity_id: str,
    dpia_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    dpia = _get_dpia_or_404(session, activity, dpia_id)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_dpia_form(form)
    errors = _validate_dpia(session, values)
    if errors:
        context = _dpia_form_context(
            activity,
            user,
            session,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=True,
            dpia_id=dpia.id,
        )
        return templates.TemplateResponse(
            request, "activities/dpia_form.html", context, status_code=422
        )
    _apply_dpia_values(dpia, values)
    change_note = form.get("change_note", "").strip()
    if change_note:
        dpia.change_note = change_note
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


def _new_transfer_values() -> dict:
    return {
        "recipient_id": "",
        "third_country_id": "",
        "mechanism_id": "",
        "data_protection_test": "",
    }


def _transfer_to_values(transfer: Transfer) -> dict:
    return {
        "recipient_id": transfer.recipient_id,
        "third_country_id": transfer.third_country_id,
        "mechanism_id": transfer.mechanism_id,
        "data_protection_test": transfer.data_protection_test or "",
    }


def _parse_transfer_form(form) -> dict:
    return {
        "recipient_id": form.get("recipient_id", ""),
        "third_country_id": form.get("third_country_id", ""),
        "mechanism_id": form.get("mechanism_id", ""),
        "data_protection_test": form.get("data_protection_test", "").strip(),
    }


def _validate_transfer(session: Session, values: dict) -> list[dict]:
    errors = []
    for model, field, label in [
        (Recipient, "recipient_id", "recipient"),
        (ThirdCountry, "third_country_id", "third country"),
        (TransferMechanism, "mechanism_id", "transfer mechanism"),
    ]:
        error = _validate_required_fk(session, model, values[field], field, label)
        if error:
            errors.append(error)
    return errors


def _apply_transfer_values(transfer: Transfer, values: dict) -> None:
    transfer.recipient_id = values["recipient_id"]
    transfer.third_country_id = values["third_country_id"]
    transfer.mechanism_id = values["mechanism_id"]
    transfer.data_protection_test = values["data_protection_test"] or None


def _transfer_form_context(
    activity: ProcessingActivity,
    user: User,
    session: Session,
    *,
    values: dict,
    errors: list[dict],
    csrf_token: str,
    is_edit: bool,
    transfer_id: str | None = None,
) -> dict:
    error_map = {e["field"]: e["message"] for e in errors}
    recipients = session.scalars(select(Recipient).order_by(Recipient.label)).all()
    countries = session.scalars(select(ThirdCountry).order_by(ThirdCountry.label)).all()
    mechanisms = session.scalars(select(TransferMechanism).order_by(TransferMechanism.label)).all()
    return {
        "user": user,
        "activity": activity,
        "is_edit": is_edit,
        "transfer_id": transfer_id,
        "values": values,
        "errors": errors,
        "error_map": error_map,
        "csrf_token": csrf_token,
        "recipient_options": [("", "Select a recipient")] + [(r.id, r.label) for r in recipients],
        "third_country_options": [("", "Select a third country")]
        + [(c.id, c.label) for c in countries],
        "mechanism_options": [("", "Select a mechanism")] + [(m.id, m.label) for m in mechanisms],
        "appropriate_safeguards_codes": sorted(APPROPRIATE_SAFEGUARDS_MECHANISMS),
    }


def _get_transfer_or_404(
    session: Session, activity: ProcessingActivity, transfer_id: str
) -> Transfer:
    transfer = session.get(Transfer, transfer_id)
    if transfer is None or transfer.activity_id != activity.id:
        raise HTTPException(status_code=404)
    return transfer


@router.get("/activities/{activity_id}/transfers/new")
def transfer_new_form(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    context = _transfer_form_context(
        activity,
        user,
        session,
        values=_new_transfer_values(),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=False,
    )
    return templates.TemplateResponse(request, "activities/transfer_form.html", context)


@router.post("/activities/{activity_id}/transfers/new")
async def transfer_create(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_transfer_form(form)
    errors = _validate_transfer(session, values)
    if errors:
        context = _transfer_form_context(
            activity,
            user,
            session,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=False,
        )
        return templates.TemplateResponse(
            request, "activities/transfer_form.html", context, status_code=422
        )
    transfer = Transfer(activity_id=activity.id)
    _apply_transfer_values(transfer, values)
    session.add(transfer)
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.get("/activities/{activity_id}/transfers/{transfer_id}/edit")
def transfer_edit_form(
    activity_id: str,
    transfer_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    transfer = _get_transfer_or_404(session, activity, transfer_id)
    context = _transfer_form_context(
        activity,
        user,
        session,
        values=_transfer_to_values(transfer),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=True,
        transfer_id=transfer.id,
    )
    return templates.TemplateResponse(request, "activities/transfer_form.html", context)


@router.post("/activities/{activity_id}/transfers/{transfer_id}/edit")
async def transfer_update(
    activity_id: str,
    transfer_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    transfer = _get_transfer_or_404(session, activity, transfer_id)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_transfer_form(form)
    errors = _validate_transfer(session, values)
    if errors:
        context = _transfer_form_context(
            activity,
            user,
            session,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=True,
            transfer_id=transfer.id,
        )
        return templates.TemplateResponse(
            request, "activities/transfer_form.html", context, status_code=422
        )
    _apply_transfer_values(transfer, values)
    change_note = form.get("change_note", "").strip()
    if change_note:
        transfer.change_note = change_note
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


def _new_contract_values() -> dict:
    return {
        "type": ContractType.CONTROLLER_PROCESSOR.value,
        "parties": [],
        "art28_checklist_complete": False,
        "security_schedule": "",
        "sub_processor_authorisation": "",
        "start_date": "",
        "review_date": "",
        "expiry_date": "",
    }


def _contract_to_values(contract: ContractDSA) -> dict:
    return {
        "type": contract.type.value,
        "parties": [p.id for p in contract.parties],
        "art28_checklist_complete": bool(contract.art28_checklist_complete),
        "security_schedule": contract.security_schedule or "",
        "sub_processor_authorisation": (
            contract.sub_processor_authorisation.value
            if contract.sub_processor_authorisation
            else ""
        ),
        "start_date": contract.start_date.isoformat(),
        "review_date": contract.review_date.isoformat(),
        "expiry_date": contract.expiry_date.isoformat() if contract.expiry_date else "",
    }


def _parse_contract_form(form) -> dict:
    return {
        "type": form.get("type", ContractType.CONTROLLER_PROCESSOR.value),
        "parties": form.getlist("parties"),
        "art28_checklist_complete": form.get("art28_checklist_complete") is not None,
        "security_schedule": form.get("security_schedule", "").strip(),
        "sub_processor_authorisation": form.get("sub_processor_authorisation", ""),
        "start_date": form.get("start_date", ""),
        "review_date": form.get("review_date", ""),
        "expiry_date": form.get("expiry_date", ""),
    }


def _validate_contract(session: Session, values: dict) -> list[dict]:
    errors = []
    try:
        ContractType(values["type"])
    except ValueError:
        errors.append({"field": "type", "message": "Select a valid contract type"})
    if not values["parties"]:
        errors.append({"field": "parties", "message": "Select at least one party"})
    else:
        for party_id in values["parties"]:
            if session.get(LegalEntity, party_id) is None:
                errors.append({"field": "parties", "message": "Select valid parties"})
                break
    if values["sub_processor_authorisation"]:
        try:
            SubProcessorAuthorisation(values["sub_processor_authorisation"])
        except ValueError:
            errors.append(
                {
                    "field": "sub_processor_authorisation",
                    "message": "Select a valid sub-processor authorisation",
                }
            )
    if not values["start_date"]:
        errors.append({"field": "start_date", "message": "Enter a start date"})
    elif not _valid_date(values["start_date"]):
        errors.append({"field": "start_date", "message": "Enter a valid date"})
    if not values["review_date"]:
        errors.append({"field": "review_date", "message": "Enter a review date"})
    elif not _valid_date(values["review_date"]):
        errors.append({"field": "review_date", "message": "Enter a valid date"})
    if values["expiry_date"] and not _valid_date(values["expiry_date"]):
        errors.append({"field": "expiry_date", "message": "Enter a valid date"})
    return errors


def _apply_contract_values(session: Session, contract: ContractDSA, values: dict) -> None:
    contract.type = ContractType(values["type"])
    contract.parties = [session.get(LegalEntity, pid) for pid in values["parties"]]
    contract.art28_checklist_complete = values["art28_checklist_complete"]
    contract.security_schedule = values["security_schedule"] or None
    contract.sub_processor_authorisation = (
        SubProcessorAuthorisation(values["sub_processor_authorisation"])
        if values["sub_processor_authorisation"]
        else None
    )
    contract.start_date = date.fromisoformat(values["start_date"])
    contract.review_date = date.fromisoformat(values["review_date"])
    contract.expiry_date = (
        date.fromisoformat(values["expiry_date"]) if values["expiry_date"] else None
    )


def _contract_form_context(
    activity: ProcessingActivity,
    user: User,
    session: Session,
    *,
    values: dict,
    errors: list[dict],
    csrf_token: str,
    is_edit: bool,
    contract_id: str | None = None,
) -> dict:
    error_map = {e["field"]: e["message"] for e in errors}
    entities = session.scalars(select(LegalEntity).order_by(LegalEntity.label)).all()
    return {
        "user": user,
        "activity": activity,
        "is_edit": is_edit,
        "contract_id": contract_id,
        "values": values,
        "errors": errors,
        "error_map": error_map,
        "csrf_token": csrf_token,
        "contract_type_options": list(CONTRACT_TYPE_LABELS.items()),
        "sub_processor_authorisation_options": [("", "Not set")]
        + list(SUB_PROCESSOR_AUTHORISATION_LABELS.items()),
        "party_options": [(e.id, e.label) for e in entities],
    }


def _get_contract_or_404(session: Session, contract_id: str) -> ContractDSA:
    contract = session.get(ContractDSA, contract_id)
    if contract is None:
        raise HTTPException(status_code=404)
    return contract


@router.get("/activities/{activity_id}/contracts/new")
def contract_new_form(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    context = _contract_form_context(
        activity,
        user,
        session,
        values=_new_contract_values(),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=False,
    )
    return templates.TemplateResponse(request, "activities/contract_form.html", context)


@router.post("/activities/{activity_id}/contracts/new")
async def contract_create(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_contract_form(form)
    errors = _validate_contract(session, values)
    if errors:
        context = _contract_form_context(
            activity,
            user,
            session,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=False,
        )
        return templates.TemplateResponse(
            request, "activities/contract_form.html", context, status_code=422
        )
    contract = ContractDSA()
    _apply_contract_values(session, contract, values)
    session.add(contract)
    activity.contracts.append(contract)
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.get("/activities/{activity_id}/contracts/{contract_id}/edit")
def contract_edit_form(
    activity_id: str,
    contract_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    contract = _get_contract_or_404(session, contract_id)
    if contract not in activity.contracts:
        raise HTTPException(status_code=404)
    context = _contract_form_context(
        activity,
        user,
        session,
        values=_contract_to_values(contract),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=True,
        contract_id=contract.id,
    )
    return templates.TemplateResponse(request, "activities/contract_form.html", context)


@router.post("/activities/{activity_id}/contracts/{contract_id}/edit")
async def contract_update(
    activity_id: str,
    contract_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    contract = _get_contract_or_404(session, contract_id)
    if contract not in activity.contracts:
        raise HTTPException(status_code=404)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_contract_form(form)
    errors = _validate_contract(session, values)
    if errors:
        context = _contract_form_context(
            activity,
            user,
            session,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=True,
            contract_id=contract.id,
        )
        return templates.TemplateResponse(
            request, "activities/contract_form.html", context, status_code=422
        )
    _apply_contract_values(session, contract, values)
    change_note = form.get("change_note", "").strip()
    if change_note:
        contract.change_note = change_note
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.post("/activities/{activity_id}/contracts/link")
async def contract_link(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    contract_id = form.get("contract_id")
    contract = session.get(ContractDSA, contract_id) if contract_id else None
    if contract is None:
        raise HTTPException(status_code=422, detail="Select a contract")
    if contract not in activity.contracts:
        activity.contracts.append(contract)
        session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.post("/activities/{activity_id}/contracts/{contract_id}/unlink")
async def contract_unlink(
    activity_id: str,
    contract_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    contract = session.get(ContractDSA, contract_id)
    if contract is not None and contract in activity.contracts:
        activity.contracts.remove(contract)
        session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


def _new_adm_values() -> dict:
    return {
        "use_mode": ADMUseMode.MANUAL.value,
        "technique": "",
        "solely_automated": False,
        "significant_effects": False,
        "accuracy_bias_checks": "",
        "human_review": "",
        "contestability": "",
        "transparency_ref": "",
        "data_sources": [],
    }


def _adm_to_values(adm: DecisionSupportADM) -> dict:
    return {
        "use_mode": adm.use_mode.value,
        "technique": adm.technique or "",
        "solely_automated": bool(adm.solely_automated),
        "significant_effects": bool(adm.significant_effects),
        "accuracy_bias_checks": adm.accuracy_bias_checks or "",
        "human_review": adm.human_review or "",
        "contestability": adm.contestability or "",
        "transparency_ref": adm.transparency_ref or "",
        "data_sources": [s.id for s in adm.data_sources],
    }


def _parse_adm_form(form) -> dict:
    return {
        "use_mode": form.get("use_mode", ADMUseMode.MANUAL.value),
        "technique": form.get("technique", "").strip(),
        "solely_automated": form.get("solely_automated") is not None,
        "significant_effects": form.get("significant_effects") is not None,
        "accuracy_bias_checks": form.get("accuracy_bias_checks", "").strip(),
        "human_review": form.get("human_review", "").strip(),
        "contestability": form.get("contestability", "").strip(),
        "transparency_ref": form.get("transparency_ref", ""),
        "data_sources": form.getlist("data_sources"),
    }


def _validate_adm(activity: ProcessingActivity, values: dict) -> list[dict]:
    errors = []
    try:
        ADMUseMode(values["use_mode"])
    except ValueError:
        errors.append({"field": "use_mode", "message": "Select a valid use mode"})
    linked_source_ids = {s.id for s in activity.data_sources}
    if not values["data_sources"]:
        errors.append({"field": "data_sources", "message": "Select at least one data source"})
    elif not set(values["data_sources"]) <= linked_source_ids:
        errors.append(
            {
                "field": "data_sources",
                "message": "Data sources must already be linked to this activity",
            }
        )
    if values["transparency_ref"]:
        linked_notice_ids = {n.id for n in activity.privacy_notices}
        if values["transparency_ref"] not in linked_notice_ids:
            errors.append(
                {
                    "field": "transparency_ref",
                    "message": "Transparency reference must be a privacy notice linked to this "
                    "activity",
                }
            )
    return errors


def _apply_adm_values(session: Session, adm: DecisionSupportADM, values: dict) -> None:
    adm.use_mode = ADMUseMode(values["use_mode"])
    adm.technique = values["technique"] or None
    adm.solely_automated = values["solely_automated"]
    adm.significant_effects = values["significant_effects"]
    adm.accuracy_bias_checks = values["accuracy_bias_checks"] or None
    adm.human_review = values["human_review"] or None
    adm.contestability = values["contestability"] or None
    adm.transparency_ref = values["transparency_ref"] or None
    adm.data_sources = [session.get(ExternalDataSource, sid) for sid in values["data_sources"]]


def _adm_form_context(
    activity: ProcessingActivity,
    user: User,
    *,
    values: dict,
    errors: list[dict],
    csrf_token: str,
    is_edit: bool,
    adm_id: str | None = None,
) -> dict:
    error_map = {e["field"]: e["message"] for e in errors}
    return {
        "user": user,
        "activity": activity,
        "is_edit": is_edit,
        "adm_id": adm_id,
        "values": values,
        "errors": errors,
        "error_map": error_map,
        "csrf_token": csrf_token,
        "use_mode_options": list(ADM_USE_MODE_LABELS.items()),
        "data_source_options": [(s.id, _display_label(s)) for s in activity.data_sources],
        "transparency_ref_options": [("", "Not set")]
        + [(n.id, n.notice_version) for n in activity.privacy_notices],
    }


def _get_adm_or_404(
    session: Session, activity: ProcessingActivity, adm_id: str
) -> DecisionSupportADM:
    adm = session.get(DecisionSupportADM, adm_id)
    if adm is None or adm.activity_id != activity.id:
        raise HTTPException(status_code=404)
    return adm


@router.get("/activities/{activity_id}/adm/new")
def adm_new_form(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    context = _adm_form_context(
        activity,
        user,
        values=_new_adm_values(),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=False,
    )
    return templates.TemplateResponse(request, "activities/adm_form.html", context)


@router.post("/activities/{activity_id}/adm/new")
async def adm_create(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_adm_form(form)
    errors = _validate_adm(activity, values)
    if errors:
        context = _adm_form_context(
            activity,
            user,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=False,
        )
        return templates.TemplateResponse(
            request, "activities/adm_form.html", context, status_code=422
        )
    adm = DecisionSupportADM(activity_id=activity.id)
    _apply_adm_values(session, adm, values)
    session.add(adm)
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.get("/activities/{activity_id}/adm/{adm_id}/edit")
def adm_edit_form(
    activity_id: str,
    adm_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    adm = _get_adm_or_404(session, activity, adm_id)
    context = _adm_form_context(
        activity,
        user,
        values=_adm_to_values(adm),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=True,
        adm_id=adm.id,
    )
    return templates.TemplateResponse(request, "activities/adm_form.html", context)


@router.post("/activities/{activity_id}/adm/{adm_id}/edit")
async def adm_update(
    activity_id: str,
    adm_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    adm = _get_adm_or_404(session, activity, adm_id)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_adm_form(form)
    errors = _validate_adm(activity, values)
    if errors:
        context = _adm_form_context(
            activity,
            user,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=True,
            adm_id=adm.id,
        )
        return templates.TemplateResponse(
            request, "activities/adm_form.html", context, status_code=422
        )
    _apply_adm_values(session, adm, values)
    change_note = form.get("change_note", "").strip()
    if change_note:
        adm.change_note = change_note
    session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.post("/activities/{activity_id}/feeds")
async def feed_add(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    if activity.activity_type != ActivityType.ANALYTICS_MODELLING:
        raise HTTPException(
            status_code=422, detail="Feeds can only be added to analytics activities"
        )
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    consumer_id = form.get("consumer_activity_id")
    consumer = session.get(ProcessingActivity, consumer_id) if consumer_id else None
    if (
        consumer is None
        or consumer.id == activity.id
        or consumer.activity_type != ActivityType.OPERATIONAL
    ):
        raise HTTPException(status_code=422, detail="Select a valid operational activity")
    existing = session.scalars(
        select(ActivityFeeds).where(
            ActivityFeeds.source_activity_id == activity.id,
            ActivityFeeds.consumer_activity_id == consumer.id,
        )
    ).first()
    if existing is None:
        session.add(ActivityFeeds(source_activity_id=activity.id, consumer_activity_id=consumer.id))
        session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.post("/activities/{activity_id}/feeds/{feed_id}/remove")
async def feed_remove(
    activity_id: str,
    feed_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    feed = session.get(ActivityFeeds, feed_id)
    if feed is not None and feed.source_activity_id == activity.id:
        session.delete(feed)
        session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.post("/activities/{activity_id}/retention")
async def retention_add(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    rule_id = form.get("retention_rule_id")
    rule = session.get(RetentionRule, rule_id) if rule_id else None
    if rule is None:
        raise HTTPException(status_code=422, detail="Select a retention rule")
    if rule.entry_status == EntryStatus.REJECTED:
        raise HTTPException(status_code=422, detail="This entry has been rejected")
    scope_id = form.get("data_category_scope_id") or None
    if scope_id and scope_id not in {c.id for c in activity.data_categories}:
        raise HTTPException(
            status_code=422,
            detail="Scope must be a personal data category already linked to this activity",
        )
    existing = session.scalars(
        select(ActivityRetention).where(
            ActivityRetention.activity_id == activity.id,
            ActivityRetention.retention_rule_id == rule.id,
            ActivityRetention.data_category_scope_id == scope_id,
        )
    ).first()
    if existing is None:
        session.add(
            ActivityRetention(
                activity_id=activity.id, retention_rule_id=rule.id, data_category_scope_id=scope_id
            )
        )
        session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.post("/activities/{activity_id}/retention/{link_id}/remove")
async def retention_remove(
    activity_id: str,
    link_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    link = session.get(ActivityRetention, link_id)
    if link is not None and link.activity_id == activity.id:
        session.delete(link)
        session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.post("/activities/{activity_id}/security")
async def security_add(
    activity_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    measure_id = form.get("security_measure_id")
    measure = session.get(SecurityMeasure, measure_id) if measure_id else None
    if measure is None:
        raise HTTPException(status_code=422, detail="Select a security measure")
    if measure.entry_status == EntryStatus.REJECTED:
        raise HTTPException(status_code=422, detail="This entry has been rejected")
    existing = session.scalars(
        select(ActivitySecurity).where(
            ActivitySecurity.activity_id == activity.id,
            ActivitySecurity.security_measure_id == measure.id,
        )
    ).first()
    if existing is None:
        session.add(
            ActivitySecurity(
                activity_id=activity.id, security_measure_id=measure.id, inherited_from_system=False
            )
        )
        session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.post("/activities/{activity_id}/security/{link_id}/remove")
async def security_remove(
    activity_id: str,
    link_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    activity = _get_activity(session, activity_id)
    _require_can_author(user)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    link = session.get(ActivitySecurity, link_id)
    if link is not None and link.activity_id == activity.id:
        if link.inherited_from_system:
            raise HTTPException(
                status_code=422, detail="Cannot remove an inherited security measure"
            )
        session.delete(link)
        session.flush()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


def _dpia_hint(activity: ProcessingActivity) -> bool:
    if activity.regime != Regime.GENERAL:
        return False
    if not (activity.vulnerable_or_safeguarding_flag or activity.children_flag):
        return False
    basis = active_basis(activity)
    return basis is None or not basis.art9_condition_id


def _id_map(session: Session, model: type, label_attr: str = "label") -> dict[str, str]:
    return {o.id: getattr(o, label_attr) for o in session.scalars(select(model)).all()}


def _retention_suggestions(activity: ProcessingActivity, rule_labels: dict[str, str]) -> list[dict]:
    existing = {
        (link.retention_rule_id, link.data_category_scope_id) for link in activity.retention_links
    }
    suggestions = []
    seen_rules = set()
    for system in activity.systems:
        if system.default_retention_id is None or system.default_retention_id in seen_rules:
            continue
        if (system.default_retention_id, None) in existing:
            continue
        seen_rules.add(system.default_retention_id)
        suggestions.append(
            {
                "system_label": _display_label(system),
                "rule_id": system.default_retention_id,
                "rule_label": rule_labels.get(system.default_retention_id, ""),
            }
        )
    return suggestions


def register_detail_context(session: Session, activity: ProcessingActivity, user: User) -> dict:
    can_author = user.role in (Role.CURATOR, Role.APPROVER_DPO)
    show_adm = (
        activity.external_data_use_mode != ExternalDataUseMode.NONE
        or activity.activity_type == ActivityType.ANALYTICS_MODELLING
    )
    show_feeds_editor = activity.activity_type == ActivityType.ANALYTICS_MODELLING
    show_fed_by = activity.activity_type == ActivityType.OPERATIONAL
    operational_options = session.scalars(
        select(ProcessingActivity).where(
            ProcessingActivity.activity_type == ActivityType.OPERATIONAL,
            ProcessingActivity.id != activity.id,
        )
    ).all()
    linked_consumer_ids = {f.consumer_activity_id for f in activity.feeds}
    all_retention_rules = session.scalars(select(RetentionRule).order_by(RetentionRule.label)).all()
    retention_rule_labels = {r.id: _display_label(r) for r in all_retention_rules}
    category_labels = _id_map(session, PersonalDataCategory)
    linked_security_ids = {link.security_measure_id for link in activity.security_links}
    all_security_measures = session.scalars(
        select(SecurityMeasure).order_by(SecurityMeasure.label)
    ).all()
    security_measure_labels = {m.id: _display_label(m) for m in all_security_measures}
    all_contracts = session.scalars(select(ContractDSA)).all()
    linked_contract_ids = {c.id for c in activity.contracts}
    recipient_labels = _id_map(session, Recipient)
    third_country_labels = _id_map(session, ThirdCountry)
    user_labels = _id_map(session, User, "display_name")
    notice_labels = _id_map(session, PrivacyNotice, "notice_version")
    return {
        "can_author_registers": can_author,
        "dpia_rows": [
            {
                "dpia": dpia,
                "sign_off_label": user_labels.get(dpia.sign_off_by, "") if dpia.sign_off_by else "",
            }
            for dpia in activity.dpias
        ],
        "screening_outcome_labels": SCREENING_OUTCOME_LABELS,
        "residual_risk_labels": RESIDUAL_RISK_LABELS,
        "dpia_hint": _dpia_hint(activity),
        "transfer_rows": [
            {
                "transfer": transfer,
                "recipient_label": recipient_labels.get(transfer.recipient_id, ""),
                "third_country_label": third_country_labels.get(transfer.third_country_id, ""),
            }
            for transfer in activity.transfers
        ],
        "appropriate_safeguards_codes": sorted(APPROPRIATE_SAFEGUARDS_MECHANISMS),
        "contracts": activity.contracts,
        "contract_type_labels": CONTRACT_TYPE_LABELS,
        "contract_link_options": [
            (c.id, f"{CONTRACT_TYPE_LABELS[c.type]} — {c.start_date}")
            for c in all_contracts
            if c.id not in linked_contract_ids
        ],
        "show_adm": show_adm,
        "adm_rows": [
            {
                "adm": adm,
                "transparency_label": notice_labels.get(adm.transparency_ref, "")
                if adm.transparency_ref
                else "",
                "data_source_labels": [_display_label(s) for s in adm.data_sources],
            }
            for adm in activity.adm_records
        ],
        "adm_use_mode_labels": ADM_USE_MODE_LABELS,
        "show_feeds_editor": show_feeds_editor,
        "feed_rows": [
            {"feed_id": f.id, "consumer_label": f.consumer_activity.name} for f in activity.feeds
        ],
        "consumer_options": [
            (a.id, a.name) for a in operational_options if a.id not in linked_consumer_ids
        ],
        "show_fed_by": show_fed_by,
        "fed_by_rows": [f.source_activity.name for f in activity.fed_by],
        "retention_rows": [
            {
                "link_id": link.id,
                "rule_label": retention_rule_labels.get(link.retention_rule_id, ""),
                "scope_label": category_labels.get(link.data_category_scope_id, "")
                if link.data_category_scope_id
                else "All linked categories",
            }
            for link in activity.retention_links
        ],
        "retention_rule_options": [
            (r.id, _display_label(r))
            for r in all_retention_rules
            if r.entry_status != EntryStatus.REJECTED
        ],
        "retention_scope_options": [(c.id, _display_label(c)) for c in activity.data_categories],
        "retention_suggestions": _retention_suggestions(activity, retention_rule_labels),
        "security_inherited_rows": [
            {
                "link_id": link.id,
                "measure_label": security_measure_labels.get(link.security_measure_id, ""),
            }
            for link in activity.security_links
            if link.inherited_from_system
        ],
        "security_manual_rows": [
            {
                "link_id": link.id,
                "measure_label": security_measure_labels.get(link.security_measure_id, ""),
            }
            for link in activity.security_links
            if not link.inherited_from_system
        ],
        "security_measure_options": [
            (m.id, _display_label(m))
            for m in all_security_measures
            if m.id not in linked_security_ids and m.entry_status != EntryStatus.REJECTED
        ],
    }

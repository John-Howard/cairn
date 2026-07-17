from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cairn.audit import record_event
from cairn.auth import get_csrf_token, require_role, verify_csrf
from cairn.db import get_session
from cairn.models import BusinessFunction, Role, User
from cairn.templating import templates

router = APIRouter()

require_approver = require_role(Role.APPROVER_DPO)

ROLE_LABELS = {
    Role.CONTRIBUTOR: "Contributor",
    Role.CURATOR: "Curator",
    Role.APPROVER_DPO: "Approver (DPO)",
    Role.VIEWER: "Viewer",
}


def _business_function_options(session: Session) -> list[tuple[str, str]]:
    functions = session.scalars(select(BusinessFunction).order_by(BusinessFunction.label)).all()
    return [("", "None")] + [(f.id, f.label) for f in functions]


def _new_values() -> dict:
    return {
        "display_name": "",
        "email": "",
        "role": Role.VIEWER.value,
        "business_function_id": "",
    }


def _user_to_values(target: User) -> dict:
    return {
        "display_name": target.display_name,
        "email": target.email or "",
        "role": target.role.value,
        "business_function_id": target.business_function_id or "",
    }


def _parse_user_form(form) -> dict:
    return {
        "display_name": form.get("display_name", "").strip(),
        "email": form.get("email", "").strip().lower(),
        "role": form.get("role", Role.VIEWER.value),
        "business_function_id": form.get("business_function_id", ""),
    }


def _validate_user(
    session: Session, values: dict, *, target_id: str | None = None
) -> list[dict]:
    errors = []
    if not values["display_name"]:
        errors.append({"field": "display_name", "message": "Enter a name"})
    email = values["email"]
    if email:
        if "@" not in email:
            errors.append({"field": "email", "message": "Enter a valid email address"})
        else:
            clash = session.scalar(
                select(User).where(func.lower(User.email) == email, User.id != (target_id or ""))
            )
            if clash is not None:
                errors.append(
                    {"field": "email", "message": "Another user already has this email"}
                )
    try:
        role = Role(values["role"])
    except ValueError:
        errors.append({"field": "role", "message": "Select a valid role"})
        role = None
    if role == Role.CONTRIBUTOR:
        if not values["business_function_id"]:
            errors.append(
                {"field": "business_function_id", "message": "Select a business function"}
            )
        elif session.get(BusinessFunction, values["business_function_id"]) is None:
            errors.append(
                {"field": "business_function_id", "message": "Select a valid business function"}
            )
    return errors


def _apply_user_values(target: User, values: dict) -> None:
    target.display_name = values["display_name"]
    target.email = values["email"] or None
    target.role = Role(values["role"])
    target.business_function_id = (
        values["business_function_id"] if target.role == Role.CONTRIBUTOR else None
    )


def _form_context(
    session: Session,
    user: User,
    *,
    values: dict,
    errors: list[dict],
    csrf_token: str,
    is_edit: bool,
    target_id: str | None = None,
) -> dict:
    error_map = {e["field"]: e["message"] for e in errors}
    return {
        "user": user,
        "is_edit": is_edit,
        "target_id": target_id,
        "values": values,
        "errors": errors,
        "error_map": error_map,
        "csrf_token": csrf_token,
        "role_options": [(r.value, label) for r, label in ROLE_LABELS.items()],
        "business_function_options": _business_function_options(session),
    }


def _get_user_or_404(session: Session, user_id: str) -> User:
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404)
    return target


@router.get("/users")
def user_list(
    request: Request,
    user: User = Depends(require_approver),
    session: Session = Depends(get_session),
):
    function_labels = dict(_business_function_options(session))
    users = session.scalars(select(User).order_by(User.display_name)).all()
    rows = [
        {
            "user": target,
            "role_label": ROLE_LABELS[target.role],
            "function_label": function_labels.get(target.business_function_id or "", ""),
        }
        for target in users
    ]
    return templates.TemplateResponse(
        request,
        "users/list.html",
        {"user": user, "rows": rows, "csrf_token": get_csrf_token(request)},
    )


@router.get("/users/new")
def user_new_form(
    request: Request,
    user: User = Depends(require_approver),
    session: Session = Depends(get_session),
):
    context = _form_context(
        session,
        user,
        values=_new_values(),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=False,
    )
    return templates.TemplateResponse(request, "users/form.html", context)


@router.post("/users")
async def user_create(
    request: Request,
    user: User = Depends(require_approver),
    session: Session = Depends(get_session),
):
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_user_form(form)
    errors = _validate_user(session, values)
    if errors:
        context = _form_context(
            session,
            user,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=False,
        )
        return templates.TemplateResponse(request, "users/form.html", context, status_code=422)
    target = User()
    _apply_user_values(target, values)
    session.add(target)
    session.flush()
    return RedirectResponse("/users", status_code=302)


@router.get("/users/{user_id}/edit")
def user_edit_form(
    user_id: str,
    request: Request,
    user: User = Depends(require_approver),
    session: Session = Depends(get_session),
):
    target = _get_user_or_404(session, user_id)
    context = _form_context(
        session,
        user,
        values=_user_to_values(target),
        errors=[],
        csrf_token=get_csrf_token(request),
        is_edit=True,
        target_id=target.id,
    )
    return templates.TemplateResponse(request, "users/form.html", context)


@router.post("/users/{user_id}")
async def user_update(
    user_id: str,
    request: Request,
    user: User = Depends(require_approver),
    session: Session = Depends(get_session),
):
    target = _get_user_or_404(session, user_id)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    values = _parse_user_form(form)
    errors = _validate_user(session, values, target_id=target.id)
    if errors:
        context = _form_context(
            session,
            user,
            values=values,
            errors=errors,
            csrf_token=get_csrf_token(request),
            is_edit=True,
            target_id=target.id,
        )
        return templates.TemplateResponse(request, "users/form.html", context, status_code=422)
    old_role = target.role
    _apply_user_values(target, values)
    change_note = form.get("change_note", "").strip()
    if change_note:
        target.change_note = change_note
    session.flush()
    if old_role != target.role:
        record_event(
            session,
            entity=target,
            event="user_role_change",
            actor=user,
            old_value={"role": old_role.value},
            new_value={"role": target.role.value},
        )
    return RedirectResponse("/users", status_code=302)


@router.post("/users/{user_id}/deactivate")
async def user_deactivate(
    user_id: str,
    request: Request,
    user: User = Depends(require_approver),
    session: Session = Depends(get_session),
):
    target = _get_user_or_404(session, user_id)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    if target.id == user.id:
        raise HTTPException(status_code=422, detail="Cannot deactivate yourself")
    if not target.is_active:
        raise HTTPException(status_code=422, detail="User is already deactivated")
    target.is_active = False
    target.change_note = "User deactivated"
    session.flush()
    record_event(session, entity=target, event="user_deactivated", actor=user)
    return RedirectResponse("/users", status_code=302)


@router.post("/users/{user_id}/reactivate")
async def user_reactivate(
    user_id: str,
    request: Request,
    user: User = Depends(require_approver),
    session: Session = Depends(get_session),
):
    target = _get_user_or_404(session, user_id)
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    if target.is_active:
        raise HTTPException(status_code=422, detail="User is already active")
    target.is_active = True
    target.change_note = "User reactivated"
    session.flush()
    record_event(session, entity=target, event="user_reactivated", actor=user)
    return RedirectResponse("/users", status_code=302)

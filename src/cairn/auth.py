import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.db import get_session
from cairn.models import Role, User
from cairn.settings import get_settings
from cairn.templating import templates

CSRF_SESSION_KEY = "csrf_token"


class LoginRequired(Exception):
    pass


def get_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def verify_csrf(request: Request, submitted: str | None) -> None:
    expected = request.session.get(CSRF_SESSION_KEY)
    if not expected or not submitted or not secrets.compare_digest(expected, submitted):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise LoginRequired
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise LoginRequired
    return user


def require_role(*roles: Role):
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user

    return dependency


router = APIRouter()


def _require_dev_mode() -> None:
    if get_settings().auth_mode != "dev":
        raise HTTPException(status_code=404)


@router.get("/login")
def login_form(request: Request, session: Session = Depends(get_session)):
    _require_dev_mode()
    users = session.scalars(
        select(User).where(User.is_active).order_by(User.display_name)
    ).all()
    user_options = [(user.id, f"{user.display_name} — {user.role.value}") for user in users]
    return templates.TemplateResponse(
        request,
        "login.html",
        {"user_options": user_options, "csrf_token": get_csrf_token(request)},
    )


@router.post("/login")
def login_submit(
    request: Request,
    user_id: str = Form(...),
    csrf_token: str = Form(...),
    session: Session = Depends(get_session),
):
    _require_dev_mode()
    verify_csrf(request, csrf_token)
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="Unknown user")
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=302)


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    verify_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/login", status_code=302)

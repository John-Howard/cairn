"""OIDC SSO (Security Architecture §2) — Authorization Code + PKCE.

Microsoft Entra ID is the confirmed IdP for staging/production; the flow is
standard OIDC, so any conformant IdP works. Identity mapping is deny-by-default:
a token signs in an existing active Cairn user or nobody. The email claim
matches the first login; the token's stable subject is then bound to the user
so later logins do not depend on the email. No just-in-time provisioning.
"""

import logging

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cairn.audit import record_event
from cairn.auth import start_authenticated_session
from cairn.db import get_session
from cairn.models import User
from cairn.settings import get_settings

logger = logging.getLogger("cairn.oidc")

router = APIRouter()

_oauth: OAuth | None = None


def _require_oidc_mode() -> None:
    if get_settings().auth_mode != "oidc":
        raise HTTPException(status_code=404)


def _client():
    global _oauth
    if _oauth is None:
        settings = get_settings()
        _oauth = OAuth()
        _oauth.register(
            name="idp",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=(
                settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
            ),
            client_kwargs={
                "scope": "openid profile email",
                "code_challenge_method": "S256",
            },
        )
    return _oauth.idp


def _claimed_email(claims: dict) -> str | None:
    # Entra puts the sign-in address in `email` or (older app registrations)
    # `preferred_username`; either is acceptable for the first-login match.
    email = claims.get("email") or claims.get("preferred_username") or ""
    return email.strip().lower() or None


class OIDCDenied(Exception):
    def __init__(self, reason: str):
        self.reason = reason


def resolve_oidc_user(session: Session, claims: dict) -> User:
    """Map validated token claims to an active Cairn user, binding the subject
    on first login. Raises OIDCDenied for anyone the DPO has not provisioned."""
    subject = claims.get("sub")
    if not subject:
        raise OIDCDenied("token has no subject")
    user = session.scalar(select(User).where(User.oidc_subject == subject))
    if user is None:
        email = _claimed_email(claims)
        if email is None:
            raise OIDCDenied("token has no email claim to match")
        user = session.scalar(
            select(User).where(
                func.lower(User.email) == email, User.oidc_subject.is_(None)
            )
        )
        if user is None:
            raise OIDCDenied("no Cairn user with this email")
        if not user.is_active:
            raise OIDCDenied("user is deactivated")
        # The user being signed in is the actor for their own subject binding —
        # the versioning hook requires an actor before any audited update.
        session.info["actor_id"] = user.id
        user.oidc_subject = subject
        user.change_note = "OIDC subject bound on first SSO login"
        session.flush()
        record_event(
            session,
            entity=user,
            event="oidc_subject_bound",
            actor=user,
            new_value={"subject": subject},
        )
    if not user.is_active:
        raise OIDCDenied("user is deactivated")
    return user


@router.get("/auth/oidc/login")
async def oidc_login(request: Request):
    _require_oidc_mode()
    redirect_uri = str(request.url_for("oidc_callback"))
    return await _client().authorize_redirect(request, redirect_uri)


@router.get("/auth/oidc/callback")
async def oidc_callback(request: Request, session: Session = Depends(get_session)):
    _require_oidc_mode()
    try:
        token = await _client().authorize_access_token(request)
    except OAuthError as exc:
        logger.warning("oidc token exchange failed: %s", exc.error)
        return RedirectResponse("/login?error=exchange_failed", status_code=302)
    claims = token.get("userinfo") or {}
    try:
        user = resolve_oidc_user(session, claims)
    except OIDCDenied as exc:
        # Unknown identities have no User row to audit against; the JSON log
        # carries the denial (subject only — no email in logs, per NFR §logging).
        logger.warning(
            "oidc login denied: %s (subject=%s)", exc.reason, claims.get("sub")
        )
        return RedirectResponse("/login?error=denied", status_code=302)
    session.info["actor_id"] = user.id
    start_authenticated_session(request, user.id)
    record_event(session, entity=user, event="login_succeeded", actor=user)
    return RedirectResponse("/", status_code=302)

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from cairn.activities import ACTIVITY_DOMAIN_LABELS, REGIME_LABELS
from cairn.auth import get_csrf_token, require_role, verify_csrf
from cairn.db import get_session
from cairn.models import (
    ActivityDomain,
    AuditEvent,
    ProcessingActivity,
    Regime,
    RegimePolicy,
    RegimeSource,
    Role,
    User,
)
from cairn.regime import set_regime_policy
from cairn.templating import templates

router = APIRouter()

require_approver = require_role(Role.APPROVER_DPO)


def _domain_rows(session: Session) -> list[dict]:
    policies = {p.activity_domain: p for p in session.scalars(select(RegimePolicy)).all()}
    rows = []
    for domain, label in ACTIVITY_DOMAIN_LABELS.items():
        policy = policies.get(domain)
        rows.append(
            {
                "domain": domain,
                "label": label,
                "policy": policy,
                "current_regime": policy.assigned_regime if policy else None,
            }
        )
    return rows


def _history(session: Session) -> list[AuditEvent]:
    return session.scalars(
        select(AuditEvent)
        .where(
            or_(
                AuditEvent.entity_type == "regime_policy",
                (AuditEvent.entity_type == "processing_activity")
                & (AuditEvent.event == "regime_change"),
            )
        )
        .order_by(AuditEvent.occurred_at.desc())
    ).all()


def _render_index(
    request: Request,
    session: Session,
    user: User,
    *,
    errors: list[dict] | None = None,
    moved: int | None = None,
    moved_domain: str | None = None,
    status_code: int = 200,
):
    users_by_id = {u.id: u.display_name for u in session.scalars(select(User)).all()}
    activity_names = {
        a.id: a.name for a in session.scalars(select(ProcessingActivity)).all()
    }
    context = {
        "user": user,
        "rows": _domain_rows(session),
        "history": _history(session),
        "users_by_id": users_by_id,
        "activity_names": activity_names,
        "regime_labels": REGIME_LABELS,
        "domain_labels": ACTIVITY_DOMAIN_LABELS,
        "errors": errors or [],
        "moved": moved,
        "moved_domain": moved_domain,
        "csrf_token": get_csrf_token(request),
    }
    return templates.TemplateResponse(
        request, "regime_policy.html", context, status_code=status_code
    )


@router.get("/regime-policy")
def regime_policy_index(
    request: Request,
    moved: int | None = None,
    domain: str | None = None,
    user: User = Depends(require_approver),
    session: Session = Depends(get_session),
):
    moved_domain = None
    if domain:
        try:
            moved_domain = ACTIVITY_DOMAIN_LABELS[ActivityDomain(domain)]
        except ValueError:
            moved = None
    return _render_index(request, session, user, moved=moved, moved_domain=moved_domain)


@router.post("/regime-policy/{domain}")
async def set_policy(
    domain: str,
    request: Request,
    user: User = Depends(require_approver),
    session: Session = Depends(get_session),
):
    try:
        target_domain = ActivityDomain(domain)
    except ValueError:
        raise HTTPException(status_code=404) from None
    form = await request.form()
    verify_csrf(request, form.get("csrf_token"))
    domain_label = ACTIVITY_DOMAIN_LABELS[target_domain]
    rationale = form.get("rationale", "").strip()
    errors = []
    try:
        target_regime = Regime(form.get("assigned_regime"))
    except ValueError:
        target_regime = None
        errors.append(
            {"field": "assigned_regime", "message": f"Select a regime for {domain_label}"}
        )
    if not rationale:
        errors.append({"field": "rationale", "message": f"Enter a rationale for {domain_label}"})
    if errors:
        return _render_index(request, session, user, errors=errors, status_code=422)
    moved = len(
        session.scalars(
            select(ProcessingActivity).where(
                ProcessingActivity.activity_domain == target_domain,
                ProcessingActivity.regime_source == RegimeSource.POLICY,
                ProcessingActivity.regime != target_regime,
            )
        ).all()
    )
    set_regime_policy(
        session, domain=target_domain, regime=target_regime, reason=rationale, actor=user
    )
    session.flush()
    return RedirectResponse(f"/regime-policy?moved={moved}&domain={domain}", status_code=302)

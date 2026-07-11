from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn.activities import RECORD_STATUS_LABELS, REGIME_LABELS
from cairn.audit import record_event
from cairn.auth import current_user, get_csrf_token
from cairn.db import get_session
from cairn.export import EXPORT_VIEWS, build_export_context, export_views, render_csv
from cairn.models import (
    BusinessFunction,
    LifecycleStage,
    OrganisationProfile,
    ProcessingActivity,
    RecordStatus,
    Regime,
    User,
)
from cairn.rules import Severity, evaluate
from cairn.templating import templates
from cairn.vocabularies import pending_proposals_count

router = APIRouter()

TRIAL_WINDOW_DAYS = 60


def _function_labels(session: Session) -> dict[str, str]:
    return {
        f.id: f.label
        for f in session.scalars(select(BusinessFunction).order_by(BusinessFunction.label)).all()
    }


def _function_counts(activities, function_labels: dict[str, str]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for activity in activities:
        counts[activity.business_function_id] = counts.get(activity.business_function_id, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], function_labels.get(item[0], "")))
    top = [(function_labels.get(fid, fid), count) for fid, count in ranked[:5]]
    other = sum(count for _, count in ranked[5:])
    if other:
        top.append(("Other", other))
    return top


@router.get("/")
def dashboard(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    profile = session.scalars(select(OrganisationProfile)).first()
    if profile is None:
        return RedirectResponse("/setup", status_code=302)
    activities = session.scalars(
        select(ProcessingActivity).order_by(ProcessingActivity.name)
    ).all()
    function_labels = _function_labels(session)
    today = date.today()

    status_counts = {status: 0 for status in RECORD_STATUS_LABELS}
    regime_counts = {regime: 0 for regime in REGIME_LABELS}
    for activity in activities:
        status_counts[activity.record_status] += 1
        regime_counts[activity.regime] += 1

    non_retired = [a for a in activities if a.record_status != RecordStatus.RETIRED]
    overdue = [a for a in non_retired if a.next_review_at and a.next_review_at < today]
    trial_horizon = today + timedelta(days=TRIAL_WINDOW_DAYS)
    trials_due = [
        a
        for a in non_retired
        if a.lifecycle_stage == LifecycleStage.TRIAL
        and a.trial_end is not None
        and a.trial_end <= trial_horizon
    ]

    block_count = 0
    warn_count = 0
    blocked_activities = 0
    for activity in non_retired:
        activity_blocked = False
        for finding in evaluate(activity, profile):
            if finding.severity == Severity.BLOCK:
                block_count += 1
                activity_blocked = True
            else:
                warn_count += 1
        if activity_blocked:
            blocked_activities += 1

    review_compliance = (
        round(100 * (len(non_retired) - len(overdue)) / len(non_retired))
        if non_retired
        else None
    )

    show_s61 = Regime.LAW_ENFORCEMENT in profile.applicable_regimes
    export_keys = ["art30_1", "art30_2", *(["s61"] if show_s61 else [])]
    export_coverage = [
        (
            EXPORT_VIEWS[key].title,
            key,
            sum(1 for a in activities if EXPORT_VIEWS[key].include(a, profile)),
        )
        for key in export_keys
    ]
    export_coverage.append(("Combined internal register", "combined", len(activities)))

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "user": user,
            "profile": profile,
            "total_activities": len(activities),
            "status_counts": [
                (label, status_counts[status]) for status, label in RECORD_STATUS_LABELS.items()
            ],
            "regime_counts": [
                (label, regime_counts[regime]) for regime, label in REGIME_LABELS.items()
            ],
            "function_counts": _function_counts(activities, function_labels),
            "overdue": overdue,
            "trials_due": trials_due,
            "today": today,
            "block_count": block_count,
            "warn_count": warn_count,
            "blocked_activities": blocked_activities,
            "review_compliance": review_compliance,
            "pending_proposals": pending_proposals_count(session),
            "export_coverage": export_coverage,
            "function_labels": function_labels,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.get("/register")
def register(
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    profile = session.scalars(select(OrganisationProfile)).first()
    if profile is None:
        return RedirectResponse("/setup", status_code=302)
    activities = session.scalars(
        select(ProcessingActivity).order_by(ProcessingActivity.name)
    ).all()
    function_labels = _function_labels(session)
    users_by_id = {u.id: u.display_name for u in session.scalars(select(User)).all()}
    rows = [
        {
            "activity": activity,
            "business_function_label": function_labels.get(activity.business_function_id, ""),
            "export_views": sorted(export_views(activity, profile)),
            "owner": users_by_id.get(activity.owner_id, ""),
        }
        for activity in activities
    ]
    return templates.TemplateResponse(
        request,
        "register.html",
        {
            "user": user,
            "rows": rows,
            "record_status_labels": RECORD_STATUS_LABELS,
            "regime_labels": REGIME_LABELS,
            "show_s61": Regime.LAW_ENFORCEMENT in profile.applicable_regimes,
            "csrf_token": get_csrf_token(request),
        },
    )


@router.get("/register/export/{view_key}")
def register_export(
    view_key: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    profile = session.scalars(select(OrganisationProfile)).first()
    if profile is None:
        return RedirectResponse("/setup", status_code=302)
    view = EXPORT_VIEWS.get(view_key)
    if view is None:
        raise HTTPException(status_code=404)
    if view_key == "s61" and Regime.LAW_ENFORCEMENT not in profile.applicable_regimes:
        raise HTTPException(status_code=404)
    activities = session.scalars(
        select(ProcessingActivity).order_by(ProcessingActivity.name)
    ).all()
    ctx = build_export_context(session, profile)
    text, row_count = render_csv(view, activities, ctx)
    record_event(
        session,
        entity=profile,
        event="register_exported",
        actor=user,
        new_value={"view": view_key, "rows": row_count},
    )
    filename = f"{view.filename_stem}-{date.today().isoformat()}.csv"
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

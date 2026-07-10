from sqlalchemy.orm import Session

from cairn.models import ActivitySecurity, ProcessingActivity


def sync_inherited_security(session: Session, activity: ProcessingActivity) -> None:
    target_ids = {
        measure.id for system in activity.systems for measure in system.security_measures
    }
    existing = {link.security_measure_id: link for link in activity.security_links}

    for measure_id, link in existing.items():
        if link.inherited_from_system and measure_id not in target_ids:
            activity.security_links.remove(link)
            session.delete(link)

    for measure_id in target_ids:
        if measure_id not in existing:
            activity.security_links.append(
                ActivitySecurity(security_measure_id=measure_id, inherited_from_system=True)
            )

    session.flush()

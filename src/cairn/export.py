from cairn.models import ControllerOrProcessor, OrganisationProfile, ProcessingActivity, Regime


def export_views(activity: ProcessingActivity, profile: OrganisationProfile) -> set[str]:
    if activity.regime == Regime.LAW_ENFORCEMENT:
        if Regime.LAW_ENFORCEMENT in profile.applicable_regimes:
            return {"s61"}
        return set()
    if activity.controller_or_processor == ControllerOrProcessor.PROCESSOR:
        return {"art30_2"}
    return {"art30_1"}

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from cairn.models import (
    AgeCheckOutcome,
    ContractType,
    ControllerOrProcessor,
    ExternalDataUseMode,
    OrganisationProfile,
    OrgType,
    ProcessingActivity,
    Regime,
    RegimeScope,
)
from cairn.regime import active_basis


class Severity(StrEnum):
    BLOCK = "block"
    WARN = "warn"


@dataclass(frozen=True)
class Applicability:
    org_type: OrgType | None = None
    required_module: str | None = None
    requires_guard: bool = False
    regime: Regime | None = None

    def applies(self, activity: ProcessingActivity, profile: OrganisationProfile) -> bool:
        if self.org_type is not None and profile.org_type != self.org_type:
            return False
        if self.required_module is not None and self.required_module not in profile.active_modules:
            return False
        if self.requires_guard and not profile.public_authority_guards:
            return False
        if self.regime is not None and activity.regime != self.regime:
            return False
        return True


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    severity: Severity
    trigger: str
    requirement: str
    applicability: Applicability = field(default_factory=Applicability)


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    message: str


def _active_basis_needs_schedule1(activity: ProcessingActivity) -> bool:
    basis = active_basis(activity)
    return (
        basis is not None
        and basis.art9_condition is not None
        and basis.art9_condition.needs_schedule1
    )


def _active_basis_art6_f(activity: ProcessingActivity) -> bool:
    basis = active_basis(activity)
    return (
        basis is not None
        and basis.regime_scope == RegimeScope.PART2
        and basis.art6_basis is not None
        and basis.art6_basis.code == "f"
    )


def _active_basis_art6_a(activity: ProcessingActivity) -> bool:
    basis = active_basis(activity)
    return (
        basis is not None
        and basis.regime_scope == RegimeScope.PART2
        and basis.art6_basis is not None
        and basis.art6_basis.code == "a"
    )


def _not_controller(activity: ProcessingActivity) -> bool:
    return activity.controller_or_processor != ControllerOrProcessor.CONTROLLER


TRIGGERS: dict[str, Callable[[ProcessingActivity], bool]] = {
    "always": lambda a: True,
    "has_special_category_data": lambda a: a.special_category_flag,
    "has_criminal_offence_data": lambda a: a.criminal_offence_flag,
    "is_statutory_task": lambda a: a.is_statutory_task,
    "uses_external_data": lambda a: a.external_data_use_mode != ExternalDataUseMode.NONE,
    "active_basis_needs_schedule1": _active_basis_needs_schedule1,
    "active_basis_art6_f": _active_basis_art6_f,
    "active_basis_art6_a": _active_basis_art6_a,
    "not_controller": _not_controller,
}


def _sensitive_condition(activity: ProcessingActivity) -> str | None:
    basis = active_basis(activity)
    if activity.regime == Regime.GENERAL:
        if basis is None or not basis.art9_condition_id:
            return "Special-category data requires an Art 9 condition on the active basis record"
        return None
    if basis is None or not basis.schedule8_condition_id or not basis.apd_id:
        return "LE sensitive processing requires a Schedule 8 condition and an s42 APD reference"
    return None


def _art10_present(activity: ProcessingActivity) -> str | None:
    basis = active_basis(activity)
    if basis is None or not basis.art10_basis:
        return "Criminal-offence data requires an Art 10 basis (official authority or Schedule 1)"
    return None


def _flag_f_ea(activity: ProcessingActivity) -> str | None:
    basis = active_basis(activity)
    if basis is not None and basis.art6_basis is not None and basis.art6_basis.code in ("f", "ea"):
        return (
            f"Basis ({basis.art6_basis.code}) on a statutory task — public task (e) is the "
            "natural basis; flag for DPO review"
        )
    return None


def _linked_external_source(activity: ProcessingActivity) -> str | None:
    if not activity.data_sources:
        return "External data use requires at least one linked External Data Source"
    return None


def _active_regime_basis(activity: ProcessingActivity) -> str | None:
    if activity.controller_or_processor == ControllerOrProcessor.PROCESSOR:
        return None
    basis = active_basis(activity)
    if activity.regime == Regime.LAW_ENFORCEMENT:
        if basis is None or not basis.s35_basis_id:
            return "Law-enforcement regime requires an s35 basis on the active (Part 3) record"
        return None
    if basis is None or not basis.art6_basis_id:
        return "General regime requires an Art 6 basis on the active (Part 2) record"
    return None


def _schedule1_and_apd_present(activity: ProcessingActivity) -> str | None:
    basis = active_basis(activity)
    if basis.schedule1_condition is None:
        return "Special-category data on this Art 9 condition requires a Schedule 1 condition"
    if basis.schedule1_condition.needs_apd and basis.apd_id is None:
        return "This Schedule 1 condition requires an Appropriate Policy Document (APD)"
    return None


def _lia_balancing_test_present(activity: ProcessingActivity) -> str | None:
    basis = active_basis(activity)
    if not any(r.balancing_test for r in basis.lia_rli_records):
        return (
            "Art 6(f) legitimate interests requires an LIA/RLI record with a completed "
            "balancing test"
        )
    return None


def _consent_requirements_met(activity: ProcessingActivity) -> str | None:
    basis = active_basis(activity)
    if not basis.consent_records:
        return "Art 6(a) consent requires at least one linked Consent record"
    if not activity.children_flag:
        return None
    for consent in basis.consent_records:
        if consent.age_check_outcome is None:
            return "Children's data requires an age-check outcome on each consent record"
        if (
            consent.age_check_outcome == AgeCheckOutcome.CHILD_UNDER_13
            and not consent.parental_consent_captured
        ):
            return "Under-13 consent requires parental consent to be captured"
    return None


def _processor_or_joint_arrangement_present(activity: ProcessingActivity) -> str | None:
    if activity.controller_or_processor == ControllerOrProcessor.PROCESSOR:
        if not activity.categories_of_processing:
            return "Processor activities require categories_of_processing to be documented"
        if not activity.controllers:
            return "Processor activities require at least one linked controller (Legal Entity)"
        return None
    if not any(c.type == ContractType.JOINT_CONTROLLER for c in activity.contracts):
        return "Joint controller arrangements require a linked Art 26 joint-controller contract"
    return None


REQUIREMENTS: dict[str, Callable[[ProcessingActivity], str | None]] = {
    "active_sensitive_condition": _sensitive_condition,
    "art10_basis_present": _art10_present,
    "flag_f_ea_for_dpo": _flag_f_ea,
    "linked_external_source": _linked_external_source,
    "active_regime_basis_set": _active_regime_basis,
    "schedule1_and_apd_present": _schedule1_and_apd_present,
    "lia_balancing_test_present": _lia_balancing_test_present,
    "consent_requirements_met": _consent_requirements_met,
    "processor_or_joint_arrangement_present": _processor_or_joint_arrangement_present,
}


RULES: list[Rule] = [
    Rule(
        id="1",
        description="Special-category data needs an Art 9 condition (general) or Sch 8 route (LE)",
        severity=Severity.BLOCK,
        trigger="has_special_category_data",
        requirement="active_sensitive_condition",
    ),
    Rule(
        id="2",
        description="Art 9 condition needing Schedule 1 must cite one, with APD where required",
        severity=Severity.BLOCK,
        trigger="active_basis_needs_schedule1",
        requirement="schedule1_and_apd_present",
    ),
    Rule(
        id="3",
        description="Criminal-offence data needs an Art 10 basis (general regime only)",
        severity=Severity.BLOCK,
        trigger="has_criminal_offence_data",
        requirement="art10_basis_present",
        applicability=Applicability(regime=Regime.GENERAL),
    ),
    Rule(
        id="4",
        description="Public-authority guard: flag (f)/(ea) on statutory tasks for DPO review",
        severity=Severity.WARN,
        trigger="is_statutory_task",
        requirement="flag_f_ea_for_dpo",
        applicability=Applicability(
            org_type=OrgType.PUBLIC_AUTHORITY, requires_guard=True, regime=Regime.GENERAL
        ),
    ),
    Rule(
        id="5",
        description="Art 6(f) legitimate interests needs a completed LIA/RLI balancing test",
        severity=Severity.BLOCK,
        trigger="active_basis_art6_f",
        requirement="lia_balancing_test_present",
    ),
    Rule(
        id="6",
        description="Art 6(a) consent needs a Consent record, plus age checks for children",
        severity=Severity.BLOCK,
        trigger="active_basis_art6_a",
        requirement="consent_requirements_met",
    ),
    Rule(
        id="8",
        description="External data use requires a linked External Data Source",
        severity=Severity.BLOCK,
        trigger="uses_external_data",
        requirement="linked_external_source",
        applicability=Applicability(required_module="external_data"),
    ),
    Rule(
        id="12",
        description="The active regime selects the required lawful-basis set",
        severity=Severity.BLOCK,
        trigger="always",
        requirement="active_regime_basis_set",
    ),
    Rule(
        id="13",
        description="Processor/joint activities need the Art 26/28 links (controller, arrangement)",
        severity=Severity.BLOCK,
        trigger="not_controller",
        requirement="processor_or_joint_arrangement_present",
    ),
]


def evaluate(activity: ProcessingActivity, profile: OrganisationProfile) -> list[Finding]:
    findings = []
    for rule in RULES:
        if not rule.applicability.applies(activity, profile):
            continue
        if not TRIGGERS[rule.trigger](activity):
            continue
        message = REQUIREMENTS[rule.requirement](activity)
        if message is not None:
            findings.append(Finding(rule_id=rule.id, severity=rule.severity, message=message))
    return findings

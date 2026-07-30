"""Site-wide navigation — path-to-section resolution for the GOV.UK Service
Navigation bar in base.html. Pure functions so the resolver is unit-testable
without going through a request/template cycle."""

from dataclasses import dataclass

from cairn.models import Role


@dataclass(frozen=True)
class NavItem:
    label: str
    href: str
    active: bool


@dataclass(frozen=True)
class _Section:
    label: str
    href: str
    roles: frozenset[Role]
    # Path prefixes that count as "in this section" for the active state.
    # Longest match wins, so a more specific child section (e.g. intake gaps
    # under Review) takes priority over its parent (intake under Add information).
    prefixes: tuple[str, ...]


_ALL_ROLES = frozenset({Role.VIEWER, Role.CONTRIBUTOR, Role.CURATOR, Role.APPROVER_DPO})

_SECTIONS: tuple[_Section, ...] = (
    _Section("Dashboard", "/", _ALL_ROLES, ("/",)),
    _Section(
        "Registers",
        "/register",
        _ALL_ROLES,
        ("/register", "/activities", "/assets"),
    ),
    _Section(
        "Add information",
        "/add",
        frozenset({Role.CONTRIBUTOR, Role.CURATOR, Role.APPROVER_DPO}),
        ("/add", "/intake"),
    ),
    _Section(
        "Review",
        "/review",
        frozenset({Role.CURATOR, Role.APPROVER_DPO}),
        ("/review", "/intake/gaps", "/vocabularies", "/complaints"),
    ),
    _Section(
        "Manage",
        "/manage",
        frozenset({Role.APPROVER_DPO}),
        ("/manage", "/users", "/regime-policy"),
    ),
)


def _matches(path: str, prefix: str) -> bool:
    if prefix == "/":
        return path == "/"
    return path == prefix or path.startswith(prefix + "/")


def _active_label(path: str) -> str | None:
    best_label: str | None = None
    best_len = -1
    for section in _SECTIONS:
        for prefix in section.prefixes:
            if _matches(path, prefix) and len(prefix) > best_len:
                best_label, best_len = section.label, len(prefix)
    return best_label


def nav_items(path: str, role: Role) -> list[NavItem]:
    active_label = _active_label(path)
    return [
        NavItem(section.label, section.href, section.label == active_label)
        for section in _SECTIONS
        if role in section.roles
    ]

from cairn.models import Role
from cairn.nav import nav_items


def _labels(path: str, role: Role) -> list[str]:
    return [item.label for item in nav_items(path, role)]


def _active_label(path: str, role: Role) -> str | None:
    for item in nav_items(path, role):
        if item.active:
            return item.label
    return None


def test_dashboard_path_activates_dashboard():
    assert _active_label("/", Role.APPROVER_DPO) == "Dashboard"


def test_register_path_activates_registers():
    assert _active_label("/register", Role.APPROVER_DPO) == "Registers"


def test_activity_detail_path_activates_registers():
    assert _active_label("/activities/abc", Role.APPROVER_DPO) == "Registers"


def test_asset_intake_path_activates_add_information():
    assert _active_label("/intake/assets/new", Role.APPROVER_DPO) == "Add information"


def test_intake_gaps_path_activates_review():
    assert _active_label("/intake/gaps", Role.APPROVER_DPO) == "Review"


def test_manage_path_activates_manage():
    assert _active_label("/manage", Role.APPROVER_DPO) == "Manage"


def test_viewer_sees_dashboard_and_registers_only():
    assert _labels("/", Role.VIEWER) == ["Dashboard", "Registers"]


def test_contributor_sees_add_information():
    assert _labels("/", Role.CONTRIBUTOR) == ["Dashboard", "Registers", "Add information"]


def test_curator_sees_review():
    assert _labels("/", Role.CURATOR) == [
        "Dashboard",
        "Registers",
        "Add information",
        "Review",
    ]


def test_approver_dpo_sees_all_five():
    assert _labels("/", Role.APPROVER_DPO) == [
        "Dashboard",
        "Registers",
        "Add information",
        "Review",
        "Manage",
    ]


def test_only_current_item_is_active():
    items = nav_items("/register", Role.APPROVER_DPO)
    active = [item.label for item in items if item.active]
    assert active == ["Registers"]

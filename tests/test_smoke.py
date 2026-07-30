import tomllib
from pathlib import Path

import cairn


def test_package_importable():
    assert cairn.__version__


def test_version_matches_pyproject():
    """Environments & DevOps §3.2: `cairn.__version__` and the release tag move
    together. /healthz reports this value, so a version left behind at release
    time makes a deployed instance misreport itself — pin the two declarations
    to each other rather than to a literal that needs editing every release.
    """
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    )
    assert cairn.__version__ == pyproject["project"]["version"]

import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from cairn.models import Base

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


def _table_columns(inspector) -> dict[str, set[str]]:
    return {
        table: {col["name"] for col in inspector.get_columns(table)}
        for table in inspector.get_table_names()
        if table != "alembic_version"
    }


def test_alembic_upgrade_matches_metadata_create_all(tmp_path, monkeypatch):
    migrated_db = tmp_path / "migrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{migrated_db}")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    from cairn.settings import get_settings

    get_settings.cache_clear()

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        command.upgrade(config, "head")
    finally:
        os.chdir(cwd)
        get_settings.cache_clear()

    migrated_engine = create_engine(f"sqlite:///{migrated_db}")
    migrated_tables = _table_columns(inspect(migrated_engine))

    reference_engine = create_engine(f"sqlite:///{tmp_path / 'reference.db'}")
    Base.metadata.create_all(reference_engine)
    reference_tables = _table_columns(inspect(reference_engine))

    assert migrated_tables == reference_tables

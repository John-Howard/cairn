import os
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from cairn.models import Base

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
PRE_ASSET_MULTI_FUNCTION_REVISION = "538c7c1b29ab"
PRE_QUESTION_SET_GENERALISATION_REVISION = "fd7079e47765"


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


def test_asset_business_function_migration_copies_data_into_junction(tmp_path, monkeypatch):
    db_path = tmp_path / "pre_migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    from cairn.settings import get_settings

    get_settings.cache_clear()

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        command.upgrade(config, PRE_ASSET_MULTI_FUNCTION_REVISION)

        engine = create_engine(f"sqlite:///{db_path}")
        bf_id = uuid.uuid4().hex
        asset_id = uuid.uuid4().hex
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO business_function (id, label, created_at, updated_at, version) "
                    "VALUES (:id, :label, datetime('now'), datetime('now'), 1)"
                ),
                {"id": bf_id, "label": "Prevention & Community Safety"},
            )
            conn.execute(
                text(
                    "INSERT INTO information_asset "
                    "(id, label, asset_type, business_function_id, classification, "
                    "contains_personal_data, status, s62_logging_in_scope, entry_status, "
                    "created_at, updated_at, version) "
                    "VALUES (:id, :label, 'SYSTEM', :bf_id, 'NOT_CLASSIFIED', 0, 'IN_USE', 0, "
                    "'APPROVED', datetime('now'), datetime('now'), 1)"
                ),
                {"id": asset_id, "label": "Pre-migration Asset", "bf_id": bf_id},
            )
        engine.dispose()

        command.upgrade(config, "head")
    finally:
        os.chdir(cwd)
        get_settings.cache_clear()

    migrated_engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(migrated_engine)
    asset_columns = {col["name"] for col in inspector.get_columns("information_asset")}
    assert "business_function_id" not in asset_columns

    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT asset_id, business_function_id FROM asset_businessfunction "
                "WHERE asset_id = :asset_id"
            ),
            {"asset_id": asset_id},
        ).all()
    assert rows == [(asset_id, bf_id)]


def test_intake_submission_migration_preserves_subject_name(tmp_path, monkeypatch):
    db_path = tmp_path / "pre_migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    from cairn.settings import get_settings

    get_settings.cache_clear()

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        command.upgrade(config, PRE_QUESTION_SET_GENERALISATION_REVISION)

        engine = create_engine(f"sqlite:///{db_path}")
        bf_id = uuid.uuid4().hex
        user_id = uuid.uuid4().hex
        submission_id = uuid.uuid4().hex
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO business_function (id, label, created_at, updated_at, version) "
                    "VALUES (:id, :label, datetime('now'), datetime('now'), 1)"
                ),
                {"id": bf_id, "label": "Prevention & Community Safety"},
            )
            conn.execute(
                text(
                    "INSERT INTO user (id, display_name, role, is_active, "
                    "created_at, updated_at, version) "
                    "VALUES (:id, :name, 'CONTRIBUTOR', 1, datetime('now'), datetime('now'), 1)"
                ),
                {"id": user_id, "name": "Cody Contributor"},
            )
            conn.execute(
                text(
                    "INSERT INTO intake_submission "
                    "(id, activity_name, business_function_id, respondent_id, status, "
                    "answers, created_at, updated_at, version) "
                    "VALUES (:id, :name, :bf_id, :user_id, 'IN_PROGRESS', '{}', "
                    "datetime('now'), datetime('now'), 1)"
                ),
                {
                    "id": submission_id,
                    "name": "Pre-migration Activity",
                    "bf_id": bf_id,
                    "user_id": user_id,
                },
            )
        engine.dispose()

        command.upgrade(config, "head")
    finally:
        os.chdir(cwd)
        get_settings.cache_clear()

    migrated_engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(migrated_engine)
    submission_columns = {col["name"] for col in inspector.get_columns("intake_submission")}
    assert "activity_name" not in submission_columns
    assert "subject_name" in submission_columns

    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT subject_name, question_set FROM intake_submission "
                "WHERE id = :id"
            ),
            {"id": submission_id},
        ).all()
    assert rows == [("Pre-migration Activity", "ACTIVITY")]

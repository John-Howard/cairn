from collections.abc import Iterator
from functools import lru_cache

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from cairn.settings import get_settings


@lru_cache
def _engine_for(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, connection_record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def get_engine() -> Engine:
    return _engine_for(get_settings().database_url)


def get_sessionmaker() -> sessionmaker:
    return sessionmaker(bind=get_engine())


def get_session(request: Request) -> Iterator[Session]:
    session = get_sessionmaker()()
    session.info["actor_id"] = request.session.get("user_id")
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

"""Database bootstrap shared by the application, scripts, and Alembic."""

from __future__ import annotations

from collections.abc import Iterator
import os

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_session_factory(
    database_url: str | None = None,
    *,
    echo: bool = False,
) -> sessionmaker[Session]:
    """Create sessions without coupling domain services to a SQL dialect."""
    engine = create_engine(database_url or resolve_database_url(), echo=echo)
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )


def resolve_database_url(*, default: str | None = None) -> str:
    """Resolve the canonical URL while preserving the legacy environment key.

    `DATABASE_URL` wins so deployment platforms can use their conventional
    variable. A caller may explicitly supply SQLite for isolated local tools.
    """

    database_url = (
        os.getenv("DATABASE_URL")
        or os.getenv("CAMPUSPILOT_DATABASE_URL")
        or default
    )
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required (CAMPUSPILOT_DATABASE_URL remains "
            "supported for compatibility)"
        )
    return database_url


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit one unit of work or roll it back before closing the session."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_schema(engine: Engine) -> None:
    """Create tables for tests; production schema evolution uses Alembic."""
    Base.metadata.create_all(engine)

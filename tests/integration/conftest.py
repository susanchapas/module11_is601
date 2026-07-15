# tests/integration/conftest.py
"""
Database fixtures for calculation integration tests.

These fixtures provide a real SQLAlchemy session bound to a PostgreSQL
database (the service container defined in the GitHub Actions workflow).
When no database is reachable — e.g. a local checkout without PostgreSQL —
the fixtures skip the dependent tests instead of failing, so the rest of the
suite still runs.

Imports of ``app.database``/``app.models`` happen lazily inside the fixtures
because importing them builds a psycopg2-backed engine; keeping that out of
module import means a missing driver skips the DB tests rather than breaking
collection of every integration test.
"""

import os
import pytest

DEFAULT_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/calculator_db"


@pytest.fixture(scope="session")
def db_engine():
    """Create the schema on a reachable PostgreSQL database, or skip."""
    url = os.getenv("DATABASE_URL", DEFAULT_TEST_DB_URL)
    try:
        from sqlalchemy import create_engine

        engine = create_engine(url)
        connection = engine.connect()
        connection.close()
    except Exception as exc:  # noqa: BLE001 - any failure means "no DB", so skip
        pytest.skip(f"PostgreSQL not available at {url}: {exc}")

    from app.database import Base
    import app.models  # noqa: F401 - registers User + Calculation on Base.metadata

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Yield a session and clean both tables afterwards for test isolation."""
    from sqlalchemy.orm import sessionmaker
    from app.models import Calculation, User

    SessionLocal = sessionmaker(bind=db_engine, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.query(Calculation).delete()
        session.query(User).delete()
        session.commit()
        session.close()


@pytest.fixture
def test_user(db_session):
    """Persist a User so calculations have a valid foreign key to reference."""
    from app.models import User

    user = User(username="calc_tester", email="calc_tester@example.com")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user

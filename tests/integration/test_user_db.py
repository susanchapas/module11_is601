# tests/integration/test_user_db.py
"""
Database Integration Tests for the User Model

These persist User records to PostgreSQL and verify storage, the unique
constraints on username/email, and the relationship to calculations. They
share the DB fixtures in conftest.py and skip when no database is reachable.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.calculation import Addition
from app.models.user import User


def test_insert_and_read_user(db_session):
    """A user record round-trips through the database with correct data."""
    user = User(username="alice", email="alice@example.com")
    db_session.add(user)
    db_session.commit()

    fetched = db_session.get(User, user.id)
    assert fetched is not None
    assert fetched.username == "alice"
    assert fetched.email == "alice@example.com"
    assert fetched.id is not None
    assert fetched.created_at is not None


def test_username_must_be_unique(db_session):
    """Duplicate usernames are rejected by the unique constraint."""
    db_session.add(User(username="bob", email="bob1@example.com"))
    db_session.commit()

    db_session.add(User(username="bob", email="bob2@example.com"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_email_must_be_unique(db_session):
    """Duplicate emails are rejected by the unique constraint."""
    db_session.add(User(username="carol1", email="carol@example.com"))
    db_session.commit()

    db_session.add(User(username="carol2", email="carol@example.com"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_new_user_has_no_calculations(test_user):
    """A freshly created user starts with an empty calculations list."""
    assert test_user.calculations == []


def test_user_owns_persisted_calculations(db_session, test_user):
    """Calculations added for a user are reachable via the relationship."""
    calc = Addition(user_id=test_user.id, inputs=[1, 2])
    calc.result = calc.get_result()
    db_session.add(calc)
    db_session.commit()

    db_session.refresh(test_user)
    assert len(test_user.calculations) == 1
    assert test_user.calculations[0].user_id == test_user.id

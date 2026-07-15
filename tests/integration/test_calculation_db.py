# tests/integration/test_calculation_db.py
"""
Database Integration Tests for Calculation Models

Unlike test_calculation.py (which exercises the model logic in memory), these
tests persist records to a real PostgreSQL database and read them back. They
verify that:

1. A calculation record is stored and retrieved with correct data.
2. Polymorphic loading returns the right subclass based on the ``type`` column.
3. The ``user_id`` foreign key is enforced.
4. Cascade delete removes a user's calculations.
5. Schema -> model -> database -> response works end to end.
6. Error cases are rejected (invalid type, division by zero, missing user).

These require the PostgreSQL service from the CI workflow; without a reachable
database the shared fixtures skip the module.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.calculation import (
    Addition,
    Calculation,
    Division,
    Multiplication,
    Subtraction,
)
from app.schemas.calculation import CalculationCreate, CalculationResponse


def _persist(session, calc):
    """Compute and store the result, commit, and return the fresh row."""
    calc.result = calc.get_result()
    session.add(calc)
    session.commit()
    session.refresh(calc)
    return calc


# ============================================================================
# Insert / read: confirm the DB stores correct data
# ============================================================================

def test_insert_and_read_addition(db_session, test_user):
    """An Addition record round-trips through the database intact."""
    calc = Addition(user_id=test_user.id, inputs=[10, 5, 3.5])
    saved = _persist(db_session, calc)

    fetched = db_session.get(Calculation, saved.id)
    assert fetched is not None
    assert isinstance(fetched, Addition)
    assert fetched.type == "addition"
    assert fetched.inputs == [10, 5, 3.5]
    assert fetched.result == 18.5
    assert fetched.user_id == test_user.id
    assert fetched.created_at is not None


@pytest.mark.parametrize(
    "cls, calc_type, inputs, expected",
    [
        (Addition, "addition", [1, 2, 3], 6),
        (Subtraction, "subtraction", [20, 5, 3], 12),
        (Multiplication, "multiplication", [2, 3, 4], 24),
        (Division, "division", [100, 2, 5], 10),
    ],
    ids=["addition", "subtraction", "multiplication", "division"],
)
def test_all_operation_types_persist(
    db_session, test_user, cls, calc_type, inputs, expected
):
    """Each calculation type stores its discriminator and computed result."""
    saved = _persist(db_session, cls(user_id=test_user.id, inputs=inputs))

    fetched = db_session.get(Calculation, saved.id)
    assert isinstance(fetched, cls)
    assert fetched.type == calc_type
    assert fetched.result == expected


def test_factory_created_record_persists(db_session, test_user):
    """Records built via the Calculation.create factory persist correctly."""
    calc = Calculation.create("multiplication", test_user.id, [3, 4, 2])
    saved = _persist(db_session, calc)

    fetched = db_session.get(Calculation, saved.id)
    assert isinstance(fetched, Multiplication)
    assert fetched.result == 24


# ============================================================================
# Polymorphic query behavior against the database
# ============================================================================

def test_polymorphic_query_returns_correct_subclasses(db_session, test_user):
    """Querying the base Calculation returns type-specific subclasses."""
    for calc_type, inputs in [
        ("addition", [1, 2]),
        ("subtraction", [10, 4]),
        ("multiplication", [2, 5]),
        ("division", [20, 4]),
    ]:
        _persist(db_session, Calculation.create(calc_type, test_user.id, inputs))

    rows = db_session.query(Calculation).all()
    by_type = {row.type: row for row in rows}

    assert len(rows) == 4
    assert isinstance(by_type["addition"], Addition)
    assert isinstance(by_type["subtraction"], Subtraction)
    assert isinstance(by_type["multiplication"], Multiplication)
    assert isinstance(by_type["division"], Division)
    assert by_type["division"].get_result() == 5


def test_user_calculations_relationship(db_session, test_user):
    """The user.calculations relationship is populated from the database."""
    _persist(db_session, Addition(user_id=test_user.id, inputs=[1, 1]))
    _persist(db_session, Division(user_id=test_user.id, inputs=[8, 2]))

    db_session.refresh(test_user)
    assert len(test_user.calculations) == 2
    assert {c.type for c in test_user.calculations} == {"addition", "division"}


# ============================================================================
# Foreign key + cascade behavior
# ============================================================================

def test_cascade_delete_removes_calculations(db_session, test_user):
    """Deleting a user removes their calculations (ON DELETE CASCADE)."""
    _persist(db_session, Addition(user_id=test_user.id, inputs=[2, 2]))

    db_session.delete(test_user)
    db_session.commit()

    assert db_session.query(Calculation).count() == 0


def test_invalid_user_id_violates_foreign_key(db_session):
    """A calculation referencing a non-existent user is rejected by the FK."""
    orphan = Addition(user_id=uuid.uuid4(), inputs=[1, 2])
    orphan.result = orphan.get_result()
    db_session.add(orphan)

    with pytest.raises(IntegrityError):
        db_session.commit()


# ============================================================================
# End-to-end: validated schema -> model -> database -> response
# ============================================================================

def test_create_from_schema_persist_and_serialize(db_session, test_user):
    """A validated CalculationCreate persists and reads back as a response."""
    payload = CalculationCreate(
        type="addition", inputs=[10.5, 3, 2], user_id=test_user.id
    )
    calc = Calculation.create(payload.type.value, payload.user_id, payload.inputs)
    saved = _persist(db_session, calc)

    response = CalculationResponse.model_validate(saved)
    assert response.id == saved.id
    assert response.user_id == test_user.id
    assert response.type.value == "addition"
    assert response.result == 15.5


# ============================================================================
# Error cases: invalid data must never reach the database
# ============================================================================

def test_invalid_type_rejected_before_persist(test_user):
    """An unsupported calculation type is rejected by the factory."""
    with pytest.raises(ValueError, match="Unsupported calculation type"):
        Calculation.create("modulus", test_user.id, [10, 3])


def test_division_by_zero_prevented_before_persist(db_session, test_user):
    """Division by zero raises during computation and is never stored."""
    calc = Division(user_id=test_user.id, inputs=[100, 0])
    with pytest.raises(ValueError, match="Cannot divide by zero."):
        calc.result = calc.get_result()

    assert db_session.query(Calculation).count() == 0

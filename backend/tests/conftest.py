"""Shared test fixtures.

fake_session gives DB-touching functions (execute_retry, audit.append/
verify, run_pipeline) a minimal in-memory stand-in for a SQLAlchemy
Session, so their control flow -- idempotency lookups, incident
creation, hash-chain ordering -- is unit testable without a live
Postgres connection. It is deliberately narrow: it only supports the
exact query shapes those functions actually issue (a single equality
filter, or an order_by + first/all), introspected off the real
SQLAlchemy Column expressions rather than reimplementing SQL. Anything
wider belongs in a live Postgres integration run
(app/demo_pipeline.py), not here.
"""

from __future__ import annotations

from collections.abc import Generator
from itertools import count
from typing import Any

import pytest


class _FakeQuery:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def filter(self, expr: Any) -> _FakeQuery:
        column_name = expr.left.key
        value = expr.right.value
        matches = [r for r in self._rows if getattr(r, column_name, None) == value]
        return _FakeQuery(matches)

    def order_by(self, expr: Any) -> _FakeQuery:
        column_name = expr.element.key
        reverse = expr.modifier.__name__ == "desc_op"
        ordered = sorted(self._rows, key=lambda r: getattr(r, column_name), reverse=reverse)
        return _FakeQuery(ordered)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    """Stands in for a SQLAlchemy Session across one call. Rows persist
    only for this instance's lifetime -- construct a fresh one per test."""

    def __init__(self) -> None:
        self._rows_by_type: dict[type, list[Any]] = {}
        self._ids = count(1)
        self.committed = False

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = next(self._ids)
        self._rows_by_type.setdefault(type(obj), []).append(obj)

    def query(self, model: type) -> _FakeQuery:
        return _FakeQuery(list(self._rows_by_type.get(model, [])))

    def commit(self) -> None:
        self.committed = True

    def refresh(self, obj: Any) -> None:
        pass

    def close(self) -> None:
        pass

    def rows_of(self, model: type) -> list[Any]:
        """Test-only inspection helper, not part of the Session API."""
        return list(self._rows_by_type.get(model, []))


@pytest.fixture
def fake_session() -> Generator[FakeSession, None, None]:
    yield FakeSession()

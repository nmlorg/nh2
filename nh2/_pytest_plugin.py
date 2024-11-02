"""Automatically disable nh2 when used in pytest."""

import pytest

import nh2.mock


@pytest.fixture(autouse=True)
def _connection_mock(monkeypatch):
    monkeypatch.setattr('nh2.connection.Connection', nh2.mock.MockConnection)
    monkeypatch.setattr('nh2.mock._servers', {})  # Don't let a failing test poison other tests.

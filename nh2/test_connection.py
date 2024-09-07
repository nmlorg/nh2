"""Tests for nh2.connection."""

from nh2 import connection


def test_simple():
    """Basic functionality."""

    conn = connection.Connection('http2.golang.org', 443)
    try:
        conn.request('GET', '/reqinfo')
        assert conn.read() == '<a href="https://go.dev/reqinfo">Found</a>.\n\n'
    finally:
        conn.close()

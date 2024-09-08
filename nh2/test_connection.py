"""Tests for nh2.connection."""

import json

from nh2 import connection


def test_simple():
    """Basic functionality."""

    conn = connection.Connection('httpbin.org', 443)
    try:
        conn.request('GET', '/get?a=b')
        responses = None
        while not responses:
            responses = conn.read()
        assert conn.streams == {}
        assert len(responses) == 1
        response = json.loads(responses[0].body)
        assert response['args'] == {'a': 'b'}

        conn.request('GET', '/get?c=d')
        responses = None
        while not responses:
            responses = conn.read()
        assert conn.streams == {}
        assert len(responses) == 1
        response = json.loads(responses[0].body)
        assert response['args'] == {'c': 'd'}
    finally:
        conn.close()

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
        assert not conn.streams
        assert len(responses) == 1
        assert responses[0].status == 200
        assert responses[0].headers['content-type'] == 'application/json'
        response = json.loads(responses[0].body)
        assert response['args'] == {'a': 'b'}

        conn.request('POST', '/post', [], '{"c": "d"}')
        responses = None
        while not responses:
            responses = conn.read()
        assert not conn.streams
        assert len(responses) == 1
        assert responses[0].status == 200
        assert responses[0].headers['content-type'] == 'application/json'
        response = json.loads(responses[0].body)
        assert response['json'] == {'c': 'd'}
    finally:
        conn.close()


def test_LiveRequest_send():  # pylint: disable=invalid-name
    """Verify the body-chunking logic."""

    class MockH2Connection:  # pylint: disable=missing-class-docstring,missing-function-docstring
        max_outbound_frame_size = 7
        window = 5

        def __init__(self):
            self.sent = []

        def local_flow_control_window(self, unused_stream_id):
            return self.window

        @staticmethod
        def send_headers(stream_id, unused_headers, **unused_kwargs):
            pass

        def send_data(self, unused_stream_id, data, **unused_kwargs):
            self.sent.append(data)
            self.window -= len(data)

    class MockConnection:  # pylint: disable=missing-class-docstring,missing-function-docstring
        c = MockH2Connection()

        @staticmethod
        def new_stream(unused_live_request):
            return 101

        @staticmethod
        def flush():
            pass

    conn = MockConnection()
    request = connection.Request('POST', 'example.com', '/data', (), '555557777777333')

    live_request = connection.LiveRequest(conn, request)
    assert conn.c.window == 0
    assert conn.c.sent == [b'55555']
    assert live_request.tosend == b'7777777333'

    live_request.send()
    assert conn.c.window == 0
    assert conn.c.sent == [b'55555']
    assert live_request.tosend == b'7777777333'

    conn.c.window = 100

    live_request.send()
    assert conn.c.window == 90
    assert conn.c.sent == [b'55555', b'7777777', b'333']
    assert live_request.tosend == b''

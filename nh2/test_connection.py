"""Tests for nh2.connection."""

import anyio
import pytest

import nh2.connection
import nh2.rex

pytestmark = pytest.mark.anyio


async def test_simple():
    """Basic functionality."""

    conn = await nh2.connection.Connection('httpbin.org', 443)
    try:
        await conn.request('GET', '/get?a=b')
        responses = None
        while not responses:
            responses = await conn.read()
        assert not conn.streams
        assert len(responses) == 1
        assert responses[0].status == 200
        assert responses[0].headers['content-type'] == 'application/json'
        response = responses[0].json()
        assert response['args'] == {'a': 'b'}

        await conn.request('POST', '/post', json={'c': 'd'})
        responses = None
        while not responses:
            responses = await conn.read()
        assert not conn.streams
        assert len(responses) == 1
        assert responses[0].status == 200
        assert responses[0].headers['content-type'] == 'application/json'
        response = responses[0].json()
        assert response['json'] == {'c': 'd'}
    finally:
        await conn.close()


async def test_concurrent():
    """Verify the Connection can handle multiple concurrent sends."""

    conn = await nh2.connection.Connection('httpbin.org', 443)
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(conn.request, 'GET', '/get?a=1')
            tg.start_soon(conn.request, 'GET', '/get?a=2')
    finally:
        await conn.close()


async def test_LiveRequest_send():  # pylint: disable=invalid-name
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
        h2_lock = anyio.Lock(fast_acquire=True)
        c = MockH2Connection()

        @staticmethod
        def new_stream(unused_live_request):
            return 101

        @staticmethod
        async def flush():
            pass

    conn = MockConnection()
    request = nh2.rex.Request('POST', 'example.com', '/data', body='555557777777333')

    live_request = await nh2.connection.LiveRequest(conn, request)
    assert conn.c.window == 0
    assert conn.c.sent == [b'55555']
    assert live_request.tosend == b'7777777333'

    await live_request.send_body()
    assert conn.c.window == 0
    assert conn.c.sent == [b'55555']
    assert live_request.tosend == b'7777777333'

    conn.c.window = 100

    await live_request.send_body()
    assert conn.c.window == 90
    assert conn.c.sent == [b'55555', b'7777777', b'333']
    assert live_request.tosend == b''

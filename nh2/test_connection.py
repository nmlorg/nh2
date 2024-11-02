"""Tests for nh2.connection."""

import anyio
import pytest

import nh2.connection
import nh2.mock
import nh2.rex

pytestmark = pytest.mark.anyio


async def test_simple():
    """Basic functionality."""

    async with nh2.mock.expect_connect('httpbin.org', 443, live=True):
        conn = await nh2.connection.Connection('httpbin.org', 443)
    try:
        assert not conn.streams
        live_request = await conn.request('GET', '/get?a=b')
        assert len(conn.streams) == 1
        response = await live_request.wait()
        assert not conn.streams
        assert response.status == 200
        assert response.headers['content-type'] == 'application/json'
        data = response.json()
        assert data['args'] == {'a': 'b'}

        live_request = await conn.request('POST', '/post', json={'c': 'd'})
        assert len(conn.streams) == 1
        response = await live_request.wait()
        assert not conn.streams
        assert response.status == 200
        assert response.headers['content-type'] == 'application/json'
        data = response.json()
        assert data['json'] == {'c': 'd'}
    finally:
        await conn.close()


async def test_concurrent_send():
    """Verify the Connection can handle multiple concurrent sends."""

    async with nh2.mock.expect_connect('httpbin.org', 443, live=True):
        conn = await nh2.connection.Connection('httpbin.org', 443)
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(conn.request, 'GET', '/get?a=1')
            tg.start_soon(conn.request, 'GET', '/get?a=2')
    finally:
        await conn.close()


async def test_concurrent_wait():
    """Verify the interaction between two concurrent LiveRequest.wait()s."""

    async with nh2.mock.expect_connect('httpbin.org', 443, live=True):
        conn = await nh2.connection.Connection('httpbin.org', 443)
    try:
        res1 = res2 = None

        async with anyio.create_task_group() as tg:
            assert not conn.streams
            req1 = await conn.request('GET', '/get?a=b')
            assert len(conn.streams) == 1
            req2 = await conn.request('POST', '/post', json={'c': 'd'})
            assert len(conn.streams) == 2

            async def run_req1():
                nonlocal res1
                res1 = await req1.wait()

            tg.start_soon(run_req1)

            async def run_req2():
                nonlocal res2
                res2 = await req2.wait()

            tg.start_soon(run_req2)

        assert res1.status == 200
        assert res1.headers['content-type'] == 'application/json'
        data = res1.json()
        assert data['args'] == {'a': 'b'}

        assert res2.status == 200
        assert res2.headers['content-type'] == 'application/json'
        data = res2.json()
        assert data['json'] == {'c': 'd'}
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

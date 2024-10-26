"""Tests for nh2.mock."""

import pytest

import nh2.anyio_util
import nh2.connection
import nh2.mock

pytestmark = pytest.mark.anyio


async def test_simple():
    """Manually run a complete connection and request."""

    mock_server = await nh2.mock.expect_connect('example.com', 443)
    conn = await nh2.connection.Connection('example.com', 443)
    assert await mock_server.read() == nh2.mock.CONNECTION_EVENT

    live_request = await conn.request('POST', '/dummy', json={'a': 1})
    assert await mock_server.read() == """
- [RequestReceived]
  headers:
    - (':method', 'POST')
    - (':path', '/dummy')
    - (':authority', 'example.com')
    - (':scheme', 'https')
    - ('content-type', 'application/json; charset=utf-8')
  priority_updated: None
  stream_ended: None
  stream_id: 1
- [DataReceived]
  data: b'{"a":1}'
  flow_controlled_length: 7
  stream_ended: [StreamEnded]
    stream_id: 1
  stream_id: 1
- [StreamEnded]
  stream_id: 1
"""

    mock_server.c.send_headers(1, [(':status', '200')])
    mock_server.c.send_data(1, b'dummy response', end_stream=True)
    await mock_server.flush()

    response = await live_request.wait()
    assert response.body == 'dummy response'
    assert await mock_server.read() == """
- [SettingsAcknowledged]
  changed_settings:
"""

    await conn.close()
    assert await mock_server.read() == """
- [ConnectionTerminated]
  additional_data: None
  error_code: <ErrorCodes.NO_ERROR: 0>
  last_stream_id: 0
"""
    assert await mock_server.read() == """
SOCKET CLOSED
"""


async def test_opaque_workflow():
    """Test an async function that blocks to wait for data from mock_server."""

    async def opaque_workflow():
        conn = await nh2.connection.Connection('example.com', 443)
        live_request = await conn.request('GET', '/dummy')
        response = await live_request.wait()
        assert response.body == 'dummy response'
        return 'finished'

    async with nh2.anyio_util.create_task_group() as tg:
        mock_server = await nh2.mock.expect_connect('example.com', 443)
        future = tg.start_soon(opaque_workflow)

        assert await mock_server.read() == nh2.mock.CONNECTION_EVENT

        assert await mock_server.read() == """
- [RequestReceived]
  headers:
    - (':method', 'GET')
    - (':path', '/dummy')
    - (':authority', 'example.com')
    - (':scheme', 'https')
  priority_updated: None
  stream_ended: [StreamEnded]
    stream_id: 1
  stream_id: 1
- [StreamEnded]
  stream_id: 1
"""

        mock_server.c.send_headers(1, [(':status', '200')])
        mock_server.c.send_data(1, b'dummy response', end_stream=True)
        await mock_server.flush()

        assert await future == 'finished'

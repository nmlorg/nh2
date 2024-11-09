"""Tests for nh2.mock."""

import pytest

import nh2.anyio_util
import nh2.connection
import nh2.mock

pytestmark = pytest.mark.anyio


async def test_simple():
    """Manually run a complete connection and request."""

    async with nh2.mock.expect_connect('example.com', 443) as mock_server:
        conn = await nh2.connection.Connection('example.com', 443)
    # On connect, client and server each send settings, but client does not block to receive them.
    assert mock_server.get_client_events() == ''
    assert await mock_server.read() == """
      - [RemoteSettingsChanged header_table_size=4096 enable_push=1 initial_window_size=65535 max_frame_size=16384 enable_connect_protocol=0 max_concurrent_streams=100 max_header_list_size=65536]
    """
    # Server sends an acknowledgment of client's settings, but client still does not receive it.
    assert mock_server.get_client_events() == ''

    # On request, client sends request, data, and stream-end frames:
    stream = await conn.request('POST', '/dummy', json={'a': 1})
    assert await mock_server.read() == """
      - [RequestReceived]
        stream_id: 1
        headers:
          - (':method', 'POST')
          - (':path', '/dummy')
          - (':authority', 'example.com')
          - (':scheme', 'https')
          - ('content-type', 'application/json; charset=utf-8')
        stream_ended: None
        priority_updated: None
      - [DataReceived]
        stream_id: 1
        data: b'{"a":1}'
        flow_controlled_length: 7
        stream_ended: [StreamEnded stream_id=1]
      - [StreamEnded stream_id=1]
    """
    # but still does not attempt to read anything from server.
    assert mock_server.get_client_events() == ''

    mock_server.c.send_headers(1, [(':status', '200')])
    mock_server.c.send_data(1, b'dummy response', end_stream=True)
    await mock_server.flush()
    assert mock_server.get_client_events() == ''

    response = await stream.wait()
    # When a request is awaited, client finally begins reading and dispatching data from server in a
    # loop (until it gets a stream-end for the request). Client finally sees server's on-connect
    # settings (which client acks) as well as server's ack of client's on-connect settings.
    assert mock_server.get_client_events() == """
      -
        - [RemoteSettingsChanged header_table_size=4096 enable_push=0 initial_window_size=65535 max_frame_size=16384 enable_connect_protocol=0 max_concurrent_streams=100 max_header_list_size=65536]
      -
        - [SettingsAcknowledged]
          changed_settings: []
      -
        - [ResponseReceived]
          stream_id: 1
          headers:
            - (':status', '200')
          stream_ended: None
          priority_updated: None
        - [DataReceived]
          stream_id: 1
          data: b'dummy response'
          flow_controlled_length: 14
          stream_ended: [StreamEnded stream_id=1]
        - [StreamEnded stream_id=1]
    """
    assert response.body == 'dummy response'
    # After the first request is awaited, server finally sees client's ack of its on-connect
    # settings.
    assert await mock_server.read() == """
      - [SettingsAcknowledged]
        changed_settings: []
    """

    # Closing client sends a terminate event and then immediately closes the socket.
    await conn.close()
    assert await mock_server.read() == """
      - [ConnectionTerminated error_code=<ErrorCodes.NO_ERROR: 0> last_stream_id=0 additional_data=None]
    """
    assert mock_server.get_client_events() == ''
    assert await mock_server.read() == """
      SOCKET CLOSED
    """
    assert mock_server.get_client_events() == ''


async def test_opaque_workflow():
    """Test an async function that blocks to wait for data from mock_server."""

    async def opaque_workflow():
        conn = await nh2.connection.Connection('example.com', 443)
        stream = await conn.request('GET', '/dummy')
        response = await stream.wait()
        assert response.body == 'dummy response'
        return 'finished'

    async with nh2.anyio_util.create_task_group() as tg:
        async with nh2.mock.expect_connect('example.com', 443) as mock_server:
            future = tg.start_soon(opaque_workflow)

        assert await mock_server.read() == """
          - [RemoteSettingsChanged header_table_size=4096 enable_push=1 initial_window_size=65535 max_frame_size=16384 enable_connect_protocol=0 max_concurrent_streams=100 max_header_list_size=65536]
        """

        assert await mock_server.read() == """
          - [RequestReceived]
            stream_id: 1
            headers:
              - (':method', 'GET')
              - (':path', '/dummy')
              - (':authority', 'example.com')
              - (':scheme', 'https')
            stream_ended: [StreamEnded stream_id=1]
            priority_updated: None
          - [StreamEnded stream_id=1]
        """

        mock_server.c.send_headers(1, [(':status', '200')])
        mock_server.c.send_data(1, b'dummy response', end_stream=True)
        await mock_server.flush()

        assert await future == 'finished'

"""Utilities to control nh2 during tests."""

import anyio
import h2

import nh2.anyio_util
import nh2.connection

_servers = {}


async def expect_connect(host, port, *, live=False):
    """Prepare for an upcoming attempt to connect to host:port."""

    assert (host, port) not in _servers
    if live is True:
        server = live
    else:
        server = await MockServer(host, port)
    _servers[host, port] = server
    return server


# The standard initial response after a connection is established.
CONNECTION_EVENT = """
- [RemoteSettingsChanged]
  changed_settings:
    1: [ChangedSetting]
      new_value: 4096
      original_value: 4096
      setting: <SettingCodes.HEADER_TABLE_SIZE: 1>
    2: [ChangedSetting]
      new_value: 1
      original_value: 1
      setting: <SettingCodes.ENABLE_PUSH: 2>
    3: [ChangedSetting]
      new_value: 100
      original_value: None
      setting: <SettingCodes.MAX_CONCURRENT_STREAMS: 3>
    4: [ChangedSetting]
      new_value: 65535
      original_value: 65535
      setting: <SettingCodes.INITIAL_WINDOW_SIZE: 4>
    5: [ChangedSetting]
      new_value: 16384
      original_value: 16384
      setting: <SettingCodes.MAX_FRAME_SIZE: 5>
    6: [ChangedSetting]
      new_value: 65536
      original_value: None
      setting: <SettingCodes.MAX_HEADER_LIST_SIZE: 6>
    8: [ChangedSetting]
      new_value: 0
      original_value: 0
      setting: <SettingCodes.ENABLE_CONNECT_PROTOCOL: 8>
"""


class MockConnection(nh2.connection.Connection):
    """An HTTP/2 client that connects to a previously prepared MockServer."""

    async def _connect(self, host, port):
        mock_server = _servers.pop((host, port))
        if mock_server is True:
            return await super()._connect(host, port)
        self.mock_server = mock_server
        return self.mock_server.client_pipe_end


class MockServer:
    """An HTTP/2 server connection."""

    async def __new__(cls, host, port):  # pylint: disable=invalid-overridden-method
        self = super().__new__(cls)
        await self.__init__(host, port)
        return self

    async def __init__(self, host, port):
        self.host = host
        self.port = port
        self.events = []
        self.client_pipe_end, self.s = nh2.anyio_util.create_pipe()

        self.c = h2.connection.H2Connection(
            config=h2.config.H2Configuration(client_side=False, header_encoding='utf8'))
        self.c.initiate_connection()
        await self.flush()

    async def read(self):
        """Wait until data is available. Return a string representing any received h2 events."""

        try:
            data = await self.s.receive(65536 * 1024)
        except anyio.EndOfStream:
            return

        events = self.c.receive_data(data)
        await self.flush()
        if not events:
            return ''
        return f'{_format(events)}\n'

    async def flush(self):
        """Send any pending data to the client."""

        if (data := self.c.data_to_send()):
            await self.s.send(data)


def _format(obj, indent=0):
    return '\n'.join(_do_format(obj, indent)).replace(' \n', '\n')


def _do_format(obj, indent):
    prefix = '  ' * indent
    if isinstance(obj, dict):
        yield ''
        for k, v in sorted(obj.items()):
            k = f'{k}'
            if not k.startswith('_'):
                yield f'{prefix}{k}: {_format(v, indent + 1)}'
    elif isinstance(obj, list):
        yield ''
        for v in obj:
            yield f'{prefix}- {_format(v, indent + 1)}'
    elif obj is None or isinstance(obj, (bytes, int, str, tuple)):
        yield f'{repr(obj)}'
    else:
        yield f'[{obj.__class__.__qualname__}] {_format(obj.__dict__, indent)}'

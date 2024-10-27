"""Utilities to control nh2 during tests."""

import textwrap

import anyio
import h2.config
import h2.connection
import h2.events

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
            return _DedentingString('SOCKET CLOSED')

        events = self.c.receive_data(data)
        await self.flush()
        if not events:
            return ''
        return _DedentingString(_format(events).strip())

    async def flush(self):
        """Send any pending data to the client."""

        if (data := self.c.data_to_send()):
            await self.s.send(data)


def _format(obj, indent=0):
    return '\n'.join(_do_format(obj, indent)).replace(' \n', '\n')


def _do_format(obj, indent):
    prefix = '  ' * indent
    if isinstance(obj, h2.events.RemoteSettingsChanged):
        yield '[RemoteSettingsChanged]'
        yield prefix + ' '.join(f'{setting.setting.name.lower()}={setting.new_value}'
                                for setting in obj.changed_settings.values())
    elif isinstance(obj, dict):
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


class _DedentingString(str):

    def __eq__(self, rhs):
        return super().__eq__(textwrap.dedent(rhs).strip('\n'))

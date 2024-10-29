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

    mock_server = None

    async def _connect(self, host, port):
        mock_server = _servers.pop((host, port))
        if mock_server is True:
            return await super()._connect(host, port)
        self.mock_server = mock_server
        return self.mock_server.client_pipe_end

    def _receive_data(self, data):
        events = super()._receive_data(data)
        if self.mock_server:
            self.mock_server.client_events.append(events)
        return events


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
        self.client_events = []

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
        return _DedentingString(_format(events))

    def get_client_events(self):
        """Return a string representing any h2 events recently received by the connected client."""

        events = self.client_events
        if not events:
            return ''
        self.client_events = []
        return _DedentingString(_format(events))

    async def flush(self):
        """Send any pending data to the client."""

        if (data := self.c.data_to_send()):
            await self.s.send(data)


def _format(obj):
    return ''.join(_do_format(obj, 0)).strip()


def _simple(obj):
    return obj is None or isinstance(obj, (bytes, int, str))


def _do_format(obj, indent, name=''):  # pylint: disable=too-many-branches
    prefix = '  ' * indent

    if isinstance(obj, dict):
        multiline = False
        items = []
        for k, v in obj.items():
            if not k.startswith('_'):
                items.append((k, v))
                if not multiline and not _simple(v):
                    multiline = True
        if not multiline:
            yield ' ['
            if name:
                yield f'{name} '
            yield ' '.join(f'{k}={repr(v)}' for k, v in items) + ']\n'
        else:
            if name:
                yield f' [{name}]'
            yield '\n'
            for k, v in items:
                yield f'{prefix}{k}:'
                yield from _do_format(v, indent + 1)
    elif isinstance(obj, list):
        multiline = False
        for v in obj:
            if not _simple(v):
                multiline = True
                break
        if not multiline:
            yield ' ['
            if name:
                yield f'{name} '
            yield ' '.join(repr(v) for v in obj) + ']\n'
        else:
            if name:
                yield f' [{name}]'
            yield '\n'
            for v in obj:
                yield f'{prefix}-'
                yield from _do_format(v, indent + 1)
    elif _simple(obj) or isinstance(obj, tuple):
        if name:
            name = f'[{name}] '
        yield f' {name}{repr(obj)}\n'
    else:
        name = obj.__class__.__qualname__
        if isinstance(obj, h2.events.RemoteSettingsChanged):
            obj = {chg.setting.name.lower(): chg.new_value for chg in obj.changed_settings.values()}
        else:
            obj = obj.__dict__
        yield from _do_format(obj, indent, name=name)


class _DedentingString(str):

    def __eq__(self, rhs):
        return super().__eq__(textwrap.dedent(rhs).strip('\n'))

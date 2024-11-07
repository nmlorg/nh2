"""An HTTP/2 client connection."""

import ssl

import anyio
import certifi
import h2.config
import h2.connection
import h2.events

import nh2.rex

ctx = ssl.create_default_context(cafile=certifi.where())
ctx.set_alpn_protocols(['h2'])


class Connection:
    """An HTTP/2 client connection."""

    async def __new__(cls, host, port):  # pylint: disable=invalid-overridden-method
        self = super().__new__(cls)
        await self.__init__(host, port)
        return self

    async def __init__(self, host, port):
        self.host = host
        self.running = False
        self.streams = {}
        self.h2_lock = anyio.Lock(fast_acquire=True)

        self.s = await self._connect(host, port)

        self.c = h2.connection.H2Connection(config=h2.config.H2Configuration(
            header_encoding='utf8'))
        self.c.initiate_connection()
        await self.flush()

    async def _connect(self, host, port):
        return await anyio.connect_tcp(host, port, ssl_context=ctx, tls_standard_compatible=False)

    async def request(self, method, path, *, headers=(), body=None, json=None):  # pylint: disable=too-many-arguments
        """Send a method request for path."""

        return await self.send(
            nh2.rex.Request(method, self.host, path, headers=headers, body=body, json=json))

    async def send(self, request):
        """Send the given Request."""

        return await LiveRequest(self, request)

    def new_stream(self, live_request):
        """Reserve a new stream_id and begin tracking the given LiveRequest."""

        stream_id = self.c.get_next_available_stream_id()
        self.streams[stream_id] = live_request
        return stream_id

    async def read(self):
        """Wait until data is available."""

        try:
            data = await self.s.receive(65536 * 1024)
        except anyio.EndOfStream:
            return ()

        async with self.h2_lock:
            for event in self._receive_data(data):
                if isinstance(event, h2.events.DataReceived):
                    # Update flow control so the server doesn't starve us.
                    self.c.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                    live_request = self.streams[event.stream_id]
                    live_request.receive(event.data)
                elif isinstance(event, h2.events.ResponseReceived):
                    live_event = self.streams[event.stream_id]
                    live_event.received_headers = dict(event.headers)
                elif isinstance(event, h2.events.WindowUpdated):
                    if event.stream_id:
                        live_request = self.streams[event.stream_id]
                        await live_request.send_body()
                elif isinstance(event, h2.events.StreamEnded):
                    live_request = self.streams.pop(event.stream_id)
                    live_request.ended()
            await self.flush()

    def _receive_data(self, data):
        return self.c.receive_data(data)

    async def flush(self):
        """Send any pending data to the server."""

        if (data := self.c.data_to_send()):
            await self.s.send(data)

    async def close(self):
        """Close the HTTP/2 connection, TLS session, and TCP socket."""

        async with self.h2_lock:
            self.c.close_connection()
            await self.flush()
            await self.s.aclose()


class LiveRequest:  # pylint: disable=too-many-instance-attributes
    """A Request that's been sent over a Connection that hasn't received a StreamEnded yet."""

    async def __new__(cls, connection, request):  # pylint: disable=invalid-overridden-method
        self = super().__new__(cls)
        await self.__init__(connection, request)
        return self

    async def __init__(self, connection, request):
        self.connection = connection
        self.request = request
        self.received_headers = None
        self.received = []
        self.tosend = request.body
        self.event = None
        self.response = None
        async with connection.h2_lock:
            self.stream_id = connection.new_stream(self)
            await self.send_headers()
            await self.send_body()

    async def send_headers(self):
        """Send the request's headers."""

        end_stream = not self.tosend
        self.connection.c.send_headers(self.stream_id,
                                       self.request.headers.items(),
                                       end_stream=end_stream)
        if end_stream:
            await self.connection.flush()

    async def send_body(self):
        """Send as much of the request's body as the stream's window allows."""

        while self.tosend and (window := self.connection.c.local_flow_control_window(
                self.stream_id)):
            limit = min(window, self.connection.c.max_outbound_frame_size)
            data = self.tosend[:limit]
            self.tosend = self.tosend[limit:]
            self.connection.c.send_data(self.stream_id, data, end_stream=not self.tosend)
            await self.connection.flush()

    def receive(self, data):
        """Store data received by a DataReceived."""

        self.received.append(data)

    def ended(self):
        """Mark the request as being finalized."""

        self.response = nh2.rex.Response(self.request, self.received_headers,
                                         b''.join(self.received).decode('utf8'))
        if self.event:
            self.event.set()

    async def wait(self):
        """Wait until self.ended is called (running the connection loop if nobody else is)."""

        while True:
            if self.response:
                return self.response

            if self.connection.running:
                if not self.event:
                    self.event = anyio.Event()
                await self.event.wait()
                self.event = None
            else:
                self.connection.running = True
                while True:
                    await self.connection.read()
                    if self.response:
                        self.connection.running = False
                        for live_request in self.connection.streams.values():
                            if live_request.event and not live_request.event.is_set():
                                live_request.event.set()
                                break
                        return self.response

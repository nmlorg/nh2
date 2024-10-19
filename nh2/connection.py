"""An HTTP/2 connection."""

import socket
import ssl

import anyio
import certifi
import h2.config
import h2.connection
import h2.events

import nh2.rex

socket.setdefaulttimeout(15)
ctx = ssl.create_default_context(cafile=certifi.where())
ctx.set_alpn_protocols(['h2'])


class Connection:
    """An HTTP/2 connection."""

    async def __new__(cls, host, port):  # pylint: disable=invalid-overridden-method
        self = super().__new__(cls)
        await self.__init__(host, port)
        return self

    async def __init__(self, host, port):
        self.host = host
        self.s = await anyio.connect_tcp(host, port, ssl_context=ctx, tls_standard_compatible=False)

        self.c = h2.connection.H2Connection(config=h2.config.H2Configuration(
            header_encoding='utf8'))
        self.c.initiate_connection()
        await self.flush()

        self.streams = {}

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
        """Wait until data is available. Return a list of Responses finalized by that data."""

        try:
            data = await self.s.receive(65536 * 1024)
        except anyio.EndOfStream:
            return ()

        responses = []
        for event in self.c.receive_data(data):
            print(event)
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
                responses.append(live_request.ended())
        await self.flush()
        return responses

    async def flush(self):
        """Send any pending data to the server."""

        if (data := self.c.data_to_send()):
            await self.s.send(data)

    async def close(self):
        """Close the HTTP/2 connection, TLS session, and TCP socket."""

        self.c.close_connection()
        await self.flush()
        await self.s.aclose()


class LiveRequest:
    """A Request that's been sent over a Connection that hasn't received a StreamEnded yet."""

    async def __new__(cls, connection, request):  # pylint: disable=invalid-overridden-method
        self = super().__new__(cls)
        await self.__init__(connection, request)
        return self

    async def __init__(self, connection, request):
        self.connection = connection
        self.stream_id = connection.new_stream(self)
        self.request = request
        self.received_headers = None
        self.received = []
        self.tosend = request.body
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

        return nh2.rex.Response(self.request, self.received_headers,
                                b''.join(self.received).decode('utf8'))

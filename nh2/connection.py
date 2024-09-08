"""An HTTP/2 connection."""

import socket
import ssl

import certifi
import h2.connection
import h2.events

socket.setdefaulttimeout(15)
ctx = ssl.create_default_context(cafile=certifi.where())
ctx.set_alpn_protocols(['h2'])


class Connection:
    """An HTTP/2 connection."""

    def __init__(self, host, port):
        self.host = host
        sock = socket.create_connection((host, port))
        self.s = ctx.wrap_socket(sock, server_hostname=host)

        self.c = h2.connection.H2Connection()
        self.c.initiate_connection()
        self.flush()

        self.streams = {}

    def request(self, method, path, headers=(), body=None):
        """Send a method request for path."""

        return self.send(Request(method, self.host, path, headers, body))

    def send(self, request):
        """Send the given Request."""

        return LiveRequest(self, request)

    def new_stream(self, live_request):
        """Reserve a new stream_id and begin tracking the given LiveRequest."""

        stream_id = self.c.get_next_available_stream_id()
        self.streams[stream_id] = live_request
        return stream_id

    def read(self):
        """Wait until data is available. Return a list of Responses finalized by that data."""

        data = self.s.recv(65536 * 1024)
        if not data:
            return ()

        responses = []
        for event in self.c.receive_data(data):
            print(event)
            if isinstance(event, h2.events.DataReceived):
                # Update flow control so the server doesn't starve us.
                self.c.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                live_request = self.streams[event.stream_id]
                live_request.receive(event.data)
            elif isinstance(event, h2.events.WindowUpdated):
                if event.stream_id:
                    live_request = self.streams[event.stream_id]
                    live_request.send()
            elif isinstance(event, h2.events.StreamEnded):
                live_request = self.streams.pop(event.stream_id)
                responses.append(live_request.ended())
        self.flush()
        return responses

    def flush(self):
        """Send any pending data to the server."""

        self.s.sendall(self.c.data_to_send())

    def close(self):
        """Close the HTTP/2 connection, TLS session, and TCP socket."""

        self.c.close_connection()
        self.flush()
        self.s.close()


class Request:
    """A unique request."""

    def __init__(self, method, host, path, headers, body):  # pylint: disable=too-many-arguments
        self.method = method
        self.host = host
        self.path = path
        self.headers = (
            (':method', method),
            (':path', path),
            (':authority', host),
            (':scheme', 'https'),
        ) + tuple(headers)
        if isinstance(body, str):
            body = body.encode('utf8')
        self.body = body or b''


class Response:
    """A response."""

    def __init__(self, request, body):
        self.request = request
        self.body = body


class LiveRequest:
    """A Request that's been sent over a Connection that hasn't received a StreamEnded yet."""

    def __init__(self, connection, request):
        self.connection = connection
        self.stream_id = connection.new_stream(self)
        self.request = request
        self.received = []
        self.tosend = request.body
        self.send_headers()
        self.send()

    def send_headers(self):
        """Send the request's headers."""

        end_stream = not self.tosend
        self.connection.c.send_headers(self.stream_id, self.request.headers, end_stream=end_stream)
        if end_stream:
            self.connection.flush()

    def send(self):
        """Send as much of the request's body as the stream's window allows."""

        while self.tosend and (window := self.connection.c.local_flow_control_window(
                self.stream_id)):
            limit = min(window, self.connection.c.max_outbound_frame_size)
            data = self.tosend[:limit]
            self.tosend = self.tosend[limit:]
            self.connection.c.send_data(self.stream_id, data, end_stream=not self.tosend)
            self.connection.flush()

    def receive(self, data):
        """Store data received by a DataReceived."""

        self.received.append(data)

    def ended(self):
        """Mark the request as being finalized."""

        return Response(self.request, b''.join(self.received).decode('utf8'))

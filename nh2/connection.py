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

    def request(self, method, path):  # pylint: disable=missing-function-docstring
        headers = [
            (':method', method),
            (':path', path),
            (':authority', self.host),
            (':scheme', 'https'),
        ]
        self.c.send_headers(1, headers, end_stream=True)
        self.flush()

    def read(self):  # pylint: disable=missing-function-docstring
        body = b''
        response_stream_ended = False
        while not response_stream_ended:
            # read raw data from the socket
            data = self.s.recv(65536 * 1024)
            if not data:
                break

            # feed raw data into h2, and process resulting events
            events = self.c.receive_data(data)
            for event in events:
                print(event)
                if isinstance(event, h2.events.DataReceived):
                    # update flow control so the server doesn't starve us
                    self.c.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                    # more response body data received
                    body += event.data
                if isinstance(event, h2.events.StreamEnded):
                    # response body completed, let's exit the loop
                    response_stream_ended = True
                    break
            self.flush()

        print("Response fully received:")
        print(body.decode())
        return body.decode()

    def flush(self):
        """Send any pending data to the server."""

        self.s.sendall(self.c.data_to_send())

    def close(self):
        """Close the HTTP/2 connection, TLS session, and TCP socket."""

        self.c.close_connection()
        self.flush()
        self.s.close()

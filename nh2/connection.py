import socket
import ssl

import certifi
import h2.connection
import h2.events

SERVER_NAME = 'http2.golang.org'
SERVER_PORT = 443

# generic socket and ssl configuration
socket.setdefaulttimeout(15)
ctx = ssl.create_default_context(cafile=certifi.where())
ctx.set_alpn_protocols(['h2'])


class Connection:

    def __init__(self):
        sock = socket.create_connection((SERVER_NAME, SERVER_PORT))
        self.s = ctx.wrap_socket(sock, server_hostname=SERVER_NAME)

        self.c = h2.connection.H2Connection()
        self.c.initiate_connection()
        self.s.sendall(self.c.data_to_send())

    def send(self):
        headers = [
            (':method', 'GET'),
            (':path', '/reqinfo'),
            (':authority', SERVER_NAME),
            (':scheme', 'https'),
        ]
        self.c.send_headers(1, headers, end_stream=True)
        self.s.sendall(self.c.data_to_send())

    def read(self):
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
            # send any pending data to the server
            self.s.sendall(self.c.data_to_send())

        print("Response fully received:")
        print(body.decode())
        return body.decode()

    def close(self):
        # tell the server we are closing the h2 connection
        self.c.close_connection()
        self.s.sendall(self.c.data_to_send())

        # close the socket
        self.s.close()

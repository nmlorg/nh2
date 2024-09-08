"""HTTP/2 requests and responses."""


class Request:
    """An HTTP/2 request."""

    def __init__(self, method, host, path, headers, body):  # pylint: disable=too-many-arguments
        self.method = method
        self.host = host
        self.path = path
        self.headers = {
            ':method': method,
            ':path': path,
            ':authority': host,
            ':scheme': 'https',
        }
        self.headers.update(headers)
        if isinstance(body, str):
            body = body.encode('utf8')
        self.body = body or b''


class Response:
    """An HTTP/2 response."""

    def __init__(self, request, headers, body):
        self.request = request
        self.headers = headers
        self.status = int(headers[':status'])
        self.body = body

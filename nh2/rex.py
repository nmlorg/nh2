"""HTTP/2 requests and responses."""


class ContentType:
    def __init__(self, value=''):
        pieces = [piece.strip() for piece in value.split(';')]
        self.mediatype = pieces and pieces.pop(0) or None
        params = dict(piece.split('=', 1) for piece in pieces)
        self.charset = params.get('charset')
        self.boundary = params.get('boundary')

    def __str__(self):
        if not self.mediatype:
            return ''
        pieces = [self.mediatype]
        if self.charset:
            pieces.append(f'charset={self.charset}')
        if self.boundary:
            pieces.append(f'boundary={self.boundary}')
        return '; '.join(pieces)


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
        self.contenttype = ContentType(self.headers.get('content-type', ''))
        if body and isinstance(body, str):
            assert self.contenttype.charset is None
            if self.contenttype.mediatype is None:
                self.contenttype.mediatype = 'text/plain'
            self.contenttype.charset = 'utf-8'
            body = body.encode('utf-8')
        if self.contenttype.mediatype:
            self.headers['content-type'] = str(self.contenttype)
        self.body = body or b''


class Response:
    """An HTTP/2 response."""

    def __init__(self, request, headers, body):
        self.request = request
        self.headers = headers
        self.status = int(headers[':status'])
        self.contenttype = ContentType(headers.get('content-type', ''))
        self.body = body

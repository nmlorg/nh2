"""Tests for nh2.rex."""

import nh2.rex


def test_contenttype():
    """Basic ContentType functionality."""

    contenttype = nh2.rex.ContentType('')
    assert contenttype.mediatype is None
    assert contenttype.charset is None
    assert contenttype.boundary is None
    assert str(contenttype) == ''

    contenttype = nh2.rex.ContentType('text/plain')
    assert contenttype.mediatype == 'text/plain'
    assert contenttype.charset is None
    assert contenttype.boundary is None
    assert str(contenttype) == 'text/plain'

    contenttype = nh2.rex.ContentType('text/plain;  charset=utf-8')
    assert contenttype.mediatype == 'text/plain'
    assert contenttype.charset == 'utf-8'
    assert contenttype.boundary is None
    assert str(contenttype) == 'text/plain; charset=utf-8'


def test_request_simple():
    """Basic Request functionality."""

    request = nh2.rex.Request('PUT', 'example.com', '/test')
    assert request.method == 'PUT'
    assert request.host == 'example.com'
    assert request.path == '/test'
    assert request.headers == {
        ':method': 'PUT',
        ':path': '/test',
        ':authority': 'example.com',
        ':scheme': 'https',
    }
    assert request.contenttype.mediatype is None
    assert request.contenttype.charset is None
    assert request.contenttype.boundary is None
    assert request.body == b''

    request = nh2.rex.Request('PUT', 'example.com', '/test', body='\u2022')
    assert request.method == 'PUT'
    assert request.host == 'example.com'
    assert request.path == '/test'
    assert request.headers == {
        ':method': 'PUT',
        ':path': '/test',
        ':authority': 'example.com',
        ':scheme': 'https',
        'content-type': 'text/plain; charset=utf-8',
    }
    assert request.contenttype.mediatype == 'text/plain'
    assert request.contenttype.charset == 'utf-8'
    assert request.contenttype.boundary is None
    assert request.body == b'\xe2\x80\xa2'


def test_response_simple():
    """Basic Response functionality."""

    request = nh2.rex.Request('PUT', 'example.com', '/test')
    response = nh2.rex.Response(request, {':status': '200'}, b'')
    assert response.request is request
    assert response.headers == {':status': '200'}
    assert response.status == 200
    assert response.contenttype.mediatype is None
    assert response.contenttype.charset is None
    assert response.contenttype.boundary is None
    assert response.body == b''

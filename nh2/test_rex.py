"""Tests for nh2.rex."""

import nh2.rex


def test_request_simple():
    """Basic functionality."""

    request = nh2.rex.Request('PUT', 'example.com', '/test', (), '')
    assert request.method == 'PUT'
    assert request.host == 'example.com'
    assert request.path == '/test'
    assert request.headers == (
        (':method', 'PUT'),
        (':path', '/test'),
        (':authority', 'example.com'),
        (':scheme', 'https'),
    )
    assert request.body == b''


def test_response_simple():
    """Basic functionality."""

    request = nh2.rex.Request('PUT', 'example.com', '/test', (), '')
    response = nh2.rex.Response(request, {':status': '200'}, b'')
    assert response.request is request
    assert response.headers == {':status': '200'}
    assert response.status == 200
    assert response.body == b''

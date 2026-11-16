"""Browser preflight and POST admission at both HTTP endpoints."""
import json

import pytest

from plugin import util
from plugin.protocol import Deferred, completed
from plugin.web import WebRequest, WebServer


@pytest.fixture
def cors_settings(monkeypatch):
    settings = {**util.DEFAULT_CONFIG, 'webCorsOriginList': ['http://localhost'],
                'webCorsOrigin': None, 'apiKey': 'secret'}
    monkeypatch.setattr(util, 'setting', settings.__getitem__)
    return settings


def response_parts(response):
    raw = response.value if isinstance(response, Deferred) else response
    head, body = raw.split(b'\r\n\r\n', 1)
    lines = head.split(b'\r\n')
    headers = dict(line.split(b': ', 1) for line in lines[1:])
    assert int(headers[b'Content-Length']) == len(body)
    return lines[0], headers, body


@pytest.mark.parametrize('path', [b'/', b'/api/v1'])
@pytest.mark.parametrize('wildcard', [False, True])
def test_preflight_explicitly_allows_authorization(cors_settings, path, wildcard):
    if wildcard:
        cors_settings['webCorsOriginList'] = ['*']
    calls = []
    server = WebServer(lambda request: calls.append(request),
                       lambda request, context: calls.append(request))
    status, headers, body = response_parts(server.handlerWrapper(WebRequest(b'OPTIONS', {
        b'origin': b'http://localhost', b'access-control-request-method': b'POST',
        b'access-control-request-headers': b'authorization,content-type',
    }, b'', path)))
    assert status == b'HTTP/1.1 200 OK' and body == b''
    assert headers[b'Access-Control-Allow-Origin'] == b'http://localhost'
    allowed_headers = {name.strip().lower() for name in headers[b'Access-Control-Allow-Headers'].split(b',')}
    assert {b'authorization', b'content-type'} <= allowed_headers
    assert b'POST' in headers[b'Access-Control-Allow-Methods'].split(b', ')
    assert headers[b'Vary'] == b'Origin'
    assert calls == []


@pytest.mark.parametrize('path', [b'/', b'/api/v1'])
@pytest.mark.parametrize('permission', ['granted', 'denied'])
def test_new_origin_preflights_and_awaits_permission(cors_settings, path, permission):
    origin = b'https://new.example'
    calls = []
    decision = Deferred()
    def dispatch(request, context=None):
        calls.append((request, context))
        return decision
    server = WebServer(dispatch, dispatch)
    status, headers, body = response_parts(server.handlerWrapper(WebRequest(b'OPTIONS', {
        b'origin': origin, b'access-control-request-method': b'POST',
        b'access-control-request-headers': b'content-type',
        b'access-control-request-private-network': b'true',
    }, b'', path)))
    assert status == b'HTTP/1.1 200 OK' and body == b''
    assert headers[b'Access-Control-Allow-Origin'] == origin
    assert headers[b'Access-Control-Allow-Private-Network'] == b'true'
    assert calls == []
    request = ({'jsonrpc': '2.0', 'id': 1, 'method': 'access.requestPermission'}
               if path == b'/api/v1' else {'action': 'requestPermission', 'version': 6,
                   'params': {'origin': 'https://spoofed.example', 'allowed': True}})
    pending = server.handlerWrapper(WebRequest(b'POST', {
        b'origin': origin, b'content-type': b'application/json',
    }, json.dumps(request).encode(), path))
    assert not pending.done
    assert len(calls) == 1
    context = calls[0][1] if path == b'/api/v1' else calls[0][0]['params']
    assert context == {'origin': origin.decode(), 'allowed': False}
    if permission == 'granted':
        cors_settings['webCorsOriginList'] = [origin.decode()]
    decision.resolve({'permission': permission})
    status, headers, body = response_parts(pending)
    assert status == b'HTTP/1.1 200 OK'
    assert headers[b'Access-Control-Allow-Origin'] == origin
    assert json.loads(body) == {'permission': permission}
    assert b'secret' not in body
    assert server.allowOrigin(WebRequest(b'POST', {b'origin': origin}, b''))[0] == (permission == 'granted')


def test_preflight_does_not_bypass_origin_or_api_key(cors_settings):
    calls = []
    server = WebServer(lambda request: calls.append(request) or completed(None),
                       lambda request, context: calls.append(request) or completed(None))
    for path in (b'/', b'/api/v1'):
        request = ({'jsonrpc': '2.0', 'id': 1, 'method': 'collection.get'}
                   if path == b'/api/v1' else {'action': 'version', 'version': 6, 'key': 'secret'})
        headers = {b'origin': b'https://unknown.example', b'authorization': b'Bearer secret'}
        response_parts(server.handlerWrapper(WebRequest(b'OPTIONS', headers, b'', path)))
        status, _, body = response_parts(server.handlerWrapper(WebRequest(
            b'POST', headers, json.dumps(request).encode(), path)))
        assert status == b'HTTP/1.1 403 Forbidden' and body == b''
        assert calls == []
    headers = {b'origin': b'http://localhost'}
    request = b'{"jsonrpc":"2.0","id":1,"method":"collection.get"}'
    response_parts(server.handlerWrapper(WebRequest(b'OPTIONS', headers, b'', b'/api/v1')))
    status, _, body = response_parts(server.handlerWrapper(WebRequest(b'POST', headers, request, b'/api/v1')))
    assert status == b'HTTP/1.1 401 Unauthorized' and body == b''
    assert calls == []
    headers[b'authorization'] = b'Bearer secret'
    status, _, body = response_parts(server.handlerWrapper(WebRequest(b'POST', headers, request, b'/api/v1')))
    assert status == b'HTTP/1.1 204 No Content' and body == b''
    assert len(calls) == 1


@pytest.mark.parametrize('path', [b'/?x=1', b'/anything', b'/api', b'/api/v1x'])
def test_legacy_accepts_any_non_rpc_path(cors_settings, path):
    calls = []
    server = WebServer(lambda request: calls.append(request) or 6,
                       lambda request, context: pytest.fail('JSON-RPC handler used'))
    request = json.dumps({'action': 'version', 'version': 6, 'key': 'secret'}).encode()
    status, _, body = response_parts(server.handlerWrapper(WebRequest(
        b'POST', {b'origin': b'http://localhost'}, request, path)))
    assert status == b'HTTP/1.1 200 OK' and json.loads(body) == 6
    assert calls[0]['action'] == 'version'


@pytest.mark.parametrize('path', [b'/api/v1?x=1', b'/api/v1/'])
def test_rpc_path_ignores_query_and_trailing_slash(cors_settings, path):
    calls = []
    server = WebServer(lambda request: pytest.fail('legacy handler used'),
                       lambda request, context: calls.append(request) or completed(None))
    status, _, _ = response_parts(server.handlerWrapper(WebRequest(
        b'POST', {b'origin': b'http://localhost', b'authorization': b'Bearer secret'},
        b'{"jsonrpc":"2.0","method":"collection.get"}', path)))
    assert status == b'HTTP/1.1 204 No Content' and len(calls) == 1


def test_empty_api_key_disables_authentication_for_both_apis(cors_settings):
    from plugin import AnkiConnect
    cors_settings['apiKey'] = ''
    calls = []
    server = WebServer(lambda request: pytest.fail('legacy handler used'),
                       lambda request, context: calls.append(request) or completed(None))
    status, _, _ = response_parts(server.handlerWrapper(WebRequest(
        b'POST', {}, b'{"jsonrpc":"2.0","id":1,"method":"collection.get"}', b'/api/v1')))
    assert status == b'HTTP/1.1 204 No Content' and len(calls) == 1
    owner = AnkiConnect()
    for request in ({'action': 'version', 'version': 6}, {'action': 'version', 'version': 6, 'key': ''}):
        assert owner.handler_async(request).value == {'result': 6, 'error': None}
    assert owner.permission('', True)['requireApikey'] is False

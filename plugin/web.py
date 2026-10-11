"""Nonblocking HTTP transport for the legacy and JSON-RPC endpoints."""
import json
import select
import socket
import time
import jsonschema
from . import util
from .protocol import Deferred, completed, ApiError, Dispatcher
from .contract import SCHEMA


class HttpError(ValueError):
    def __init__(self, status):
        self.status = status


class WebRequest:
    def __init__(self, method, headers, body, path=b'/'):
        self.method, self.headers, self.body, self.path = method, headers, body, path


class WebClient:
    def __init__(self, sock, handler):
        self.sock, self.handler = sock, handler
        self.readBuff = b''
        self.writeBuff = b''
        self.pending = False
        self.started = time.monotonic()

    def advance(self, recvSize=65536):
        if self.sock is None:
            return False
        if not self.pending and time.monotonic() - self.started > 10:
            self.close()
            return False
        rlist, wlist = select.select([self.sock] if not self.pending and not self.writeBuff else [], [self.sock] if self.writeBuff else [], [], 0)[:2]
        if rlist:
            try:
                msg = self.sock.recv(recvSize)
                if not msg:
                    self.close()
                    return False
                self.started = time.monotonic()
                self.readBuff += msg
                req, length = self.parseRequest(self.readBuff)
                if req is not None:
                    self.readBuff = b''
                    self.pending = True
                    reply = self.handler(req)
                    def finish(source):
                        self.pending = False
                        self.started = time.monotonic()
                        if self.sock is not None:
                            self.writeBuff = source.value if not source.error else b'HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\n\r\n'
                    (reply if isinstance(reply, Deferred) else completed(reply)).then(finish)
            except BlockingIOError:
                pass
            except HttpError as error:
                self.writeBuff = ('HTTP/1.1 ' + error.status + '\r\nContent-Length: 0\r\n\r\n').encode()
            except (ValueError, UnicodeError):
                self.writeBuff = b'HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n'
            except OSError:
                self.close()
                return False
        if wlist and self.writeBuff:
            try:
                length = self.sock.send(self.writeBuff)
                if length:
                    self.started = time.monotonic()
                self.writeBuff = self.writeBuff[length:]
                if not self.writeBuff:
                    self.close()
                    return False
            except BlockingIOError:
                pass
            except OSError:
                self.close()
                return False
        return True

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        self.readBuff = self.writeBuff = b''

    def parseRequest(self, data):
        parts = data.split(b'\r\n\r\n', 1)
        if len(parts[0]) > 65536:
            raise ValueError('Headers too large')
        if len(parts) == 1:
            return None, 0
        lines = parts[0].split(b'\r\n')
        method, path, version = lines[0].split(b' ')
        if version not in (b'HTTP/1.0', b'HTTP/1.1'):
            raise ValueError('Unsupported HTTP version')
        headers = {}
        for line in lines[1:]:
            key, value = line.split(b':', 1)
            key = key.strip().lower()
            if key in headers:
                raise ValueError('Duplicate header')
            headers[key] = value.strip()
        if b'transfer-encoding' in headers:
            raise ValueError('Chunked requests unsupported')
        size = int(headers.get(b'content-length', b'0'))
        if size > SCHEMA['x-limits']['maxRequestBytes']:
            raise HttpError('413 Payload Too Large')
        if size < 0:
            raise ValueError('Invalid body length')
        offset = len(parts[0]) + 4
        if len(data) < offset + size:
            return None, 0
        return WebRequest(method.upper(), headers, data[offset:offset + size], path), offset + size


class WebServer:
    def __init__(self, handler, rpc_handler=None):
        self.handler, self.rpc_handler = handler, rpc_handler
        self.clients, self.sock = [], None

    def advance(self):
        if self.sock is not None:
            self.acceptClients()
            self.advanceClients()

    def acceptClients(self):
        if not select.select([self.sock], [], [], 0)[0]:
            return
        sock = self.sock.accept()[0]
        sock.setblocking(False)
        self.clients.append(WebClient(sock, self.handlerWrapper))

    def advanceClients(self):
        self.clients = [client for client in self.clients if client.advance()]

    def listen(self):
        self.close()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setblocking(False)
        self.sock.bind((util.setting('webBindAddress'), util.setting('webBindPort')))
        self.sock.listen(util.setting('webBacklog'))

    def handlerWrapper(self, req):
        allowed, origin = self.allowOrigin(req)
        def response(value, status='200 OK'):
            body = b'' if value is None else json.dumps(value, allow_nan=False).encode('utf-8')
            headers = self.buildHeaders(origin, body)
            headers[0][0] = 'HTTP/1.1 ' + status
            if req.method == b'OPTIONS' and req.headers.get(b'access-control-request-private-network') == b'true':
                headers.append(['Access-Control-Allow-Private-Network', 'true'])
            return self.buildResponse(headers, body)
        if req.method == b'OPTIONS':
            return response(None)
        rpc = req.path == b'/api/v1'
        if req.path not in (b'/', b'/api/v1'):
            return response(None, '404 Not Found')
        if rpc and req.method != b'POST':
            return response(None, '405 Method Not Allowed')
        try:
            def reject_constant(value):
                raise ValueError('Non-finite JSON number')
            params = json.loads(req.body.decode('utf-8'), parse_constant=reject_constant)
            if not rpc:
                jsonschema.validate(params, request_schema)
        except (ValueError, UnicodeError, jsonschema.ValidationError) as error:
            if not allowed:
                return response(None, '403 Forbidden')
            if rpc:
                return response(Dispatcher.reply(None, error=ApiError('parseError', 'Invalid JSON.')))
            if not req.body:
                return response({'apiVersion': 'AnkiConnect v.{}'.format(util.setting('apiVersion'))})
            return response(format_exception_reply(util.setting('apiVersion'), error))
        permission = isinstance(params, dict) and params.get('method' if rpc else 'action') == ('access.requestPermission' if rpc else 'requestPermission')
        if not allowed and not permission:
            return response(None, '403 Forbidden')
        if permission:
            origin = req.headers.get(b'origin', b'').decode()
        if rpc:
            key = util.setting('apiKey')
            if key is not None and not permission and req.headers.get(b'authorization') != ('Bearer ' + key).encode():
                return response(None, '401 Unauthorized')
            if self.rpc_handler is None:
                return response(None, '404 Not Found')
            pending = self.rpc_handler(params, {'origin': req.headers.get(b'origin', b'').decode(), 'allowed': allowed})
            return pending.map(lambda value: response(value, '204 No Content' if value is None else '200 OK'))
        if permission:
            params.setdefault('params', {}).update(allowed=allowed, origin=origin)
        value = self.handler(params)
        return value.map(response) if isinstance(value, Deferred) else response(value)

    def allowOrigin(self, req):
        origins = list(util.setting('webCorsOriginList'))
        deprecated = util.setting('webCorsOrigin')
        if deprecated:
            origins.append(deprecated)
        origin = req.headers.get(b'origin', b'').decode()
        if '*' in origins:
            return True, '*'
        allowed = not origin or origin in origins
        if 'http://localhost' in origins and origin.startswith(('http://127.0.0.1:', 'https://127.0.0.1:', 'chrome-extension://', 'moz-extension://', 'safari-web-extension://')):
            allowed = True
        if 'http://localhost' in origins and origin in ('http://127.0.0.1', 'https://127.0.0.1'):
            allowed = True
        return allowed, origin if allowed and origin else 'http://localhost'

    def buildHeaders(self, corsOrigin, body):
        return [['HTTP/1.1 200 OK', None], ['Content-Type', 'application/json'],
                ['Access-Control-Allow-Origin', corsOrigin], ['Access-Control-Allow-Headers', '*'],
                ['Access-Control-Allow-Methods', 'POST, OPTIONS'], ['Connection', 'close'],
                ['Content-Length', str(len(body))]]

    def buildResponse(self, headers, body):
        return ''.join(key + (': ' + value if value is not None else '') + '\r\n' for key, value in headers).encode() + b'\r\n' + body

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        for client in self.clients:
            client.close()
        self.clients = []


def format_success_reply(api_version, result):
    if api_version <= 4:
        return result
    else:
        return {"result": result, "error": None}


def format_exception_reply(_api_version, exception):
    return {"result": None, "error": str(exception)}


request_schema = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "minLength": 1},
        "version": {"type": "integer"},
        "params": {"type": "object"},
    },
    "required": ["action"],
}

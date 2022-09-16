# Copyright 2016-2021 Alex Yatskov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import json
import jsonschema
import select
import socket
import mimetypes
from os import path

from . import util

#
# WebRequest
#

class WebRequest:
    def __init__(self, path, method, headers, body):
        self.path = path
        self.method = method
        self.headers = headers
        self.body = body


#
# WebClient
#

class WebClient:
    def __init__(self, sock, handler):
        self.sock = sock
        self.handler = handler
        self.readBuff = bytes()
        self.writeBuff = bytes()


    def advance(self, recvSize=1024):
        if self.sock is None:
            return False

        rlist, wlist = select.select([self.sock], [self.sock], [], 0)[:2]
        self.sock.settimeout(5.0)

        if rlist:
            while True:
                try:
                    msg = self.sock.recv(recvSize)
                except (ConnectionResetError, socket.timeout):
                    self.close()
                    return False
                if not msg:
                    self.close()
                    return False
                self.readBuff += msg

                req, length = self.parseRequest(self.readBuff)
                if req is not None:
                    self.readBuff = self.readBuff[length:]
                    self.writeBuff += self.handler(req)
                    break



        if wlist and self.writeBuff:
            try:
                length = self.sock.send(self.writeBuff)
                self.writeBuff = self.writeBuff[length:]
                if not self.writeBuff:
                    self.close()
                    return False
            except:
                self.close()
                return False
        return True


    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

        self.readBuff = bytes()
        self.writeBuff = bytes()


    def parseRequest(self, data):
        parts = data.split('\r\n\r\n'.encode('utf-8'), 1)
        if len(parts) == 1:
            return None, 0

        lines = parts[0].split('\r\n'.encode('utf-8'))
        method = None
        path = None

        if len(lines) > 0:
            request_line_parts = lines[0].split(' '.encode('utf-8'))
            method = request_line_parts[0].upper() if len(request_line_parts) > 0 else None
            path = request_line_parts[1].decode() if len(request_line_parts) > 1 else None
        headers = {}
        for line in lines[1:]:
            pair = line.split(': '.encode('utf-8'))
            headers[pair[0].lower()] = pair[1] if len(pair) > 1 else None

        headerLength = len(parts[0]) + 4
        bodyLength = int(headers.get('content-length'.encode('utf-8'), 0))
        totalLength = headerLength + bodyLength

        if totalLength > len(data):
            return None, 0

        body = data[headerLength : totalLength]
        return WebRequest(path, method, headers, body), totalLength

#
# WebServer
#

class WebServer:
    def __init__(self, handler):
        self.handler = handler
        self.clients = []
        self.sock = None


    def advance(self):
        if self.sock is not None:
            self.acceptClients()
            self.advanceClients()


    def acceptClients(self):
        rlist = select.select([self.sock], [], [], 0)[0]
        if not rlist:
            return

        clientSock = self.sock.accept()[0]
        if clientSock is not None:
            clientSock.setblocking(False)
            self.clients.append(WebClient(clientSock, self.handlerWrapper))


    def advanceClients(self):
        self.clients = list(filter(lambda c: c.advance(), self.clients))


    def listen(self):
        self.close()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setblocking(False)
        self.sock.bind((util.setting('webBindAddress'), util.setting('webBindPort')))
        self.sock.listen(util.setting('webBacklog'))


    def handlerWrapper(self, req):
        allowed, corsOrigin = self.allowOrigin(req)

        if req.method == b'OPTIONS':
            body = ''.encode('utf-8')
            headers = self.buildHeaders(corsOrigin, body)

            if b'access-control-request-private-network' in req.headers and (
            req.headers[b'access-control-request-private-network'] == b'true'):
                # include this header so that if a public origin is included in the whitelist,
                # then browsers won't fail requests due to the private network access check
                headers.append(['Access-Control-Allow-Private-Network', 'true'])

            return self.buildResponse(headers, body)
    
        try:
            params = json.loads(req.body.decode('utf-8'))
            jsonschema.validate(params, request_schema)
        except (ValueError, jsonschema.ValidationError) as e:
            if allowed:
                if len(req.body) == 0:
                    if req.path.startswith('/swaggerui'):
                        if len(req.path) == 11:
                            file_path = f"{path.dirname(__file__)}/swaggerui/index.html"
                        else:
                            file_path = f"{path.dirname(__file__)}/swaggerui/{req.path[11:]}"
                        if path.exists(file_path):
                            with open(file_path, 'rb') as f:
                                body = f.read()
                            headers = self.buildHeaders(corsOrigin, body, contentType=mimetypes.guess_type(file_path)[0])
                            return self.buildResponse(headers, body)
                    body = f"AnkiConnect v.{util.setting('apiVersion')}".encode()
                else:
                    reply = format_exception_reply(util.setting('apiVersion'), e)
                    body = json.dumps(reply).encode('utf-8')
                headers = self.buildHeaders(corsOrigin, body)
                return self.buildResponse(headers, body)
            else:
                params = {}  # trigger the 403 response below

        if allowed or params.get('action', '') == 'requestPermission':
            if params.get('action', '') == 'requestPermission':
                params['params'] = params.get('params', {})
                params['params']['allowed'] = allowed
                params['params']['origin'] = b'origin' in req.headers and req.headers[b'origin'].decode() or ''
                if not allowed :
                    corsOrigin = params['params']['origin']
                        
            body = json.dumps(self.handler(params)).encode('utf-8')
            headers = self.buildHeaders(corsOrigin, body)
        else :
            headers = [
                ['HTTP/1.1 403 Forbidden', None],
                ['Access-Control-Allow-Origin', corsOrigin],
                ['Access-Control-Allow-Headers', '*']
            ]
            body = ''.encode('utf-8')

        return self.buildResponse(headers, body)


    def allowOrigin(self, req):
        # handle multiple cors origins by checking the 'origin'-header against the allowed origin list from the config
        webCorsOriginList = util.setting('webCorsOriginList')

        # keep support for deprecated 'webCorsOrigin' field, as long it is not removed
        webCorsOrigin = util.setting('webCorsOrigin')
        if webCorsOrigin:
            webCorsOriginList.append(webCorsOrigin)

        allowed = False
        corsOrigin = 'http://localhost'
        allowAllCors = '*' in webCorsOriginList  # allow CORS for all domains
        
        if allowAllCors:
            corsOrigin = '*'
            allowed = True
        elif b'origin' in req.headers:
            originStr = req.headers[b'origin'].decode()
            if originStr in webCorsOriginList :
                corsOrigin = originStr
                allowed = True
            elif 'http://localhost' in webCorsOriginList and ( 
            originStr == 'http://127.0.0.1' or originStr == 'https://127.0.0.1' or # allow 127.0.0.1 if localhost allowed
            originStr.startswith('http://127.0.0.1:') or originStr.startswith('http://127.0.0.1:') or
            originStr.startswith('http://localhost:') or originStr.startswith('http://localhost:') or
            originStr.startswith('chrome-extension://') or originStr.startswith('moz-extension://') or originStr.startswith('safari-web-extension://') ) : # allow chrome, firefox and safari extension if localhost allowed
                corsOrigin = originStr
                allowed = True
        else:
            allowed = True
        
        return allowed, corsOrigin
    

    def buildHeaders(self, corsOrigin, body, contentType='text/json'):
        return [
            ['HTTP/1.1 200 OK', None],
            ['Content-Type', contentType],
            ['Access-Control-Allow-Origin', corsOrigin],
            ['Access-Control-Allow-Headers', '*'],
            ['Content-Length', str(len(body))]
        ]


    def buildResponse(self, headers, body):
        resp = bytes()
        for key, value in headers:
            if value is None:
                resp += '{}\r\n'.format(key).encode('utf-8')
            else:
                resp += '{}: {}\r\n'.format(key, value).encode('utf-8')

        resp += '\r\n'.encode('utf-8')
        resp += body
        return resp


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
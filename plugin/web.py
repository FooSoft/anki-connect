# Copyright 2016-2020 Alex Yatskov
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
import select
import socket

from . import web, util


#
# WebRequest
#

class WebRequest:
    def __init__(self, headers, body):
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

        if rlist:
            msg = self.sock.recv(recvSize)
            if not msg:
                self.close()
                return False

            self.readBuff += msg

            req, length = self.parseRequest(self.readBuff)
            if req is not None:
                self.readBuff = self.readBuff[length:]
                self.writeBuff += self.handler(req)

        if wlist and self.writeBuff:
            length = self.sock.send(self.writeBuff)
            self.writeBuff = self.writeBuff[length:]
            if not self.writeBuff:
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

        headers = {}
        for line in parts[0].split('\r\n'.encode('utf-8')):
            pair = line.split(': '.encode('utf-8'))
            headers[pair[0].lower()] = pair[1] if len(pair) > 1 else None

        headerLength = len(parts[0]) + 4
        bodyLength = int(headers.get('content-length'.encode('utf-8'), 0))
        totalLength = headerLength + bodyLength

        if totalLength > len(data):
            return None, 0

        body = data[headerLength : totalLength]
        return WebRequest(headers, body), totalLength


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
        if len(req.body) == 0:
            body = 'AnkiConnect v.{}'.format(util.setting('apiVersion')).encode('utf-8')
        else:
            try:
                params = json.loads(req.body.decode('utf-8'))
                body = json.dumps(self.handler(params)).encode('utf-8')
            except ValueError:
                body = json.dumps(None).encode('utf-8')

        # handle multiple cors origins by checking the 'origin'-header against the allowed origin list from the config
        webCorsOriginList = util.setting('webCorsOriginList')

        # keep support for deprecated 'webCorsOrigin' field, as long it is not removed
        webCorsOrigin = util.setting('webCorsOrigin')
        if webCorsOrigin:
            webCorsOriginList.append(webCorsOrigin)

        corsOrigin = 'http://localhost'
        allowAllCors = '*' in webCorsOriginList  # allow CORS for all domains
        if len(webCorsOriginList) == 1 and not allowAllCors:
            corsOrigin = webCorsOriginList[0]
        elif b'origin' in req.headers:
            originStr = req.headers[b'origin'].decode()
            if originStr in webCorsOriginList or allowAllCors:
                corsOrigin = originStr

        headers = [
            ['HTTP/1.1 200 OK', None],
            ['Content-Type', 'text/json'],
            ['Access-Control-Allow-Origin', corsOrigin],
            ['Content-Length', str(len(body))]
        ]

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

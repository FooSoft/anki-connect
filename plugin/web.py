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
import select
import socket


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
        self.socket = sock
        self.handler = handler
        self.readBuff = bytes()
        self.writeBuff = bytes()


    def advance(self):
        if not self.socket:
            return False

        rlist, wlist = select.select([self.socket], [self.socket], [], 0)[:2]
        self.socket.settimeout(5.0)

        if rlist:
            while True:
                try:
                    data = self.socket.recv(1024)
                    if not data:
                        raise Exception('failed to get data from socket')
                except:
                    self.close()
                    return False

                self.readBuff += data

                request, length = self.parseRequest(self.readBuff.decode('utf-8'))
                if request:
                    self.readBuff = self.readBuff[length:]
                    self.writeBuff += self.handler(request).encode('utf-8')
                    break

        if wlist and self.writeBuff:
            try:
                length = self.socket.send(self.writeBuff)
                self.writeBuff = self.writeBuff[length:]
                if not self.writeBuff:
                    self.close()
                    return False
            except:
                self.close()
                return False

        return True


    def close(self):
        if self.socket:
            self.socket.close()
            self.socket = None

        self.readBuff = bytes()
        self.writeBuff = bytes()


    def parseRequest(self, data):
        parts = data.split('\r\n\r\n', 1)
        if len(parts) == 1:
            return None, 0

        headers = {}
        for line in parts[0].split('\r\n'):
            pair = line.split(': ', 2)
            if len(pair) == 2:
                headers[pair[0].lower()] = pair[1]
            else:
                headers[pair[0]] = None

        headerLength = len(parts[0]) + 4
        bodyLength = int(headers.get('content-length', '0'))
        totalLength = headerLength + bodyLength
        if totalLength > len(data):
            return None, 0

        body = data[headerLength:totalLength]
        return WebRequest(headers, body), totalLength


#
# WebServer
#

class WebServer:
    def __init__(self, handler, origins):
        self.handler = handler
        self.origins = origins
        self.clients = []
        self.socket = None


    def advance(self):
        if self.socket:
            self.acceptClients()
            self.advanceClients()


    def acceptClients(self):
        rlist = select.select([self.socket], [], [], 0)[0]
        if not rlist:
            return

        socket = self.socket.accept()[0]
        if socket:
            socket.setblocking(False)
            self.clients.append(WebClient(socket, self.handlerWrapper))


    def advanceClients(self):
        self.clients = list(filter(lambda c: c.advance(), self.clients))


    def bindAndListen(self, address, port):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.setblocking(False)
        self.socket.bind((address, port))
        self.socket.listen(5)


    def handlerWrapper(self, request):
        if '*' in self.origins:
            origin = '*'
            allowed = True
        else:
            origin = request.headers.get('origin')
            allowed = origin in self.origins

        if not allowed:
            origin = 'http://127.0.0.1'

        try:
            call = json.loads(request.body)
            if call:
                call['allowed'] = allowed
                call['origin'] = origin
                body = json.dumps(self.handler(call))
            else:
                body = 'AnkiConnect'
        except Exception as e:
            body = str(e)

        headers = [
            ['HTTP/1.1 200 OK', None],
            ['Content-Type', 'text/json'],
            ['Access-Control-Allow-Origin', origin],
            ['Access-Control-Allow-Headers', '*'],
            ['Content-Length', len(body.encode('utf-8'))]
        ]

        header = bytes()
        for key, value in headers:
            header += f'{key}: {value}\r\n'

        return header + '\r\n' + body


    def close(self):
        if self.socket:
            self.socket.close()
            self.socket = None

        for client in self.clients:
            client.close()

        self.clients = []

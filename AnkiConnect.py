# Copyright (C) 2016 Alex Yatskov <alex@foosoft.net>
# Author: Alex Yatskov <alex@foosoft.net>
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


import anki
import aqt
import hashlib
import json
import os.path
import select
import socket


#
# Constants
#

API_VERSION = 3
TICK_INTERVAL = 25
URL_TIMEOUT = 10
URL_UPGRADE = 'https://raw.githubusercontent.com/FooSoft/anki-connect/master/anki_connect.py'
NET_ADDRESS = '127.0.0.1'
NET_BACKLOG = 5
NET_PORT = 8765


#
# General helpers
#

try:
    import urllib2
    web = urllib2
except ImportError:
    from urllib import request
    web = request

try:
    from PyQt4.QtCore import QTimer
    from PyQt4.QtGui import QMessageBox
except ImportError:
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QMessageBox

try:
    unicode
except:
    unicode = str


#
# Helpers
#

def makeBytes(data):
    return data.encode('utf-8')


def makeStr(data):
    return data.decode('utf-8')


def download(url):
    try:
        resp = web.urlopen(url, timeout=URL_TIMEOUT)
    except web.URLError:
        return None

    if resp.code != 200:
        return None

    return resp.read()


def audioInject(note, fields, filename):
    for field in fields:
        if field in note:
            note[field] += u'[sound:{}]'.format(filename)


def verifyString(string):
    t = type(string)
    return t == str or t == unicode


def verifyStringList(strings):
    for s in strings:
        if not verifyString(s):
            return False

    return True



#
# AjaxRequest
#

class AjaxRequest:
    def __init__(self, headers, body):
        self.headers = headers
        self.body = body


#
# AjaxClient
#

class AjaxClient:
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
        parts = data.split(makeBytes('\r\n\r\n'), 1)
        if len(parts) == 1:
            return None, 0

        headers = {}
        for line in parts[0].split(makeBytes('\r\n')):
            pair = line.split(makeBytes(': '))
            headers[pair[0]] = pair[1] if len(pair) > 1 else None

        headerLength = len(parts[0]) + 4
        bodyLength = int(headers.get(makeBytes('Content-Length'), 0))
        totalLength = headerLength + bodyLength

        if totalLength > len(data):
            return None, 0

        body = data[headerLength : totalLength]
        return AjaxRequest(headers, body), totalLength


#
# AjaxServer
#

class AjaxServer:
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
            self.clients.append(AjaxClient(clientSock, self.handlerWrapper))


    def advanceClients(self):
        self.clients = list(filter(lambda c: c.advance(), self.clients))


    def listen(self):
        self.close()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setblocking(False)
        self.sock.bind((NET_ADDRESS, NET_PORT))
        self.sock.listen(NET_BACKLOG)


    def handlerWrapper(self, req):
        if len(req.body) == 0:
            body = makeBytes('AnkiConnect v.{}'.format(API_VERSION))
        else:
            try:
                params = json.loads(makeStr(req.body))
                body = makeBytes(json.dumps(self.handler(params)))
            except ValueError:
                body = json.dumps(None);

        resp = bytes()
        headers = [
            ['HTTP/1.1 200 OK', None],
            ['Content-Type', 'text/json'],
            ['Content-Length', str(len(body))]
        ]

        for key, value in headers:
            if value is None:
                resp += makeBytes('{}\r\n'.format(key))
            else:
                resp += makeBytes('{}: {}\r\n'.format(key, value))

        resp += makeBytes('\r\n')
        resp += body

        return resp


    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

        for client in self.clients:
            client.close()

        self.clients = []


#
# AnkiNoteParams
#

class AnkiNoteParams:
    def __init__(self, params):
        self.deckName = params.get('deckName')
        self.modelName = params.get('modelName')
        self.fields = params.get('fields', {})
        self.tags = params.get('tags', [])

        class Audio:
            def __init__(self, params):
                self.url = params.get('url')
                self.filename = params.get('filename')
                self.skipHash = params.get('skipHash')
                self.fields = params.get('fields', [])

            def validate(self):
                return (
                    verifyString(self.url) and
                    verifyString(self.filename) and os.path.dirname(self.filename) == '' and
                    verifyStringList(self.fields) and
                    (verifyString(self.skipHash) or self.skipHash is None)
                )

        audio = Audio(params.get('audio', {}))
        self.audio = audio if audio.validate() else None


    def validate(self):
        return (
            verifyString(self.deckName) and
            verifyString(self.modelName) and
            type(self.fields) == dict and verifyStringList(list(self.fields.keys())) and verifyStringList(list(self.fields.values())) and
            type(self.tags) == list and verifyStringList(self.tags)
        )


#
# AnkiBridge
#

class AnkiBridge:
    def addNote(self, params):
        collection = self.collection()
        if collection is None:
            return

        note = self.createNote(params)
        if note is None:
            return

        if params.audio is not None and len(params.audio.fields) > 0:
            data = download(params.audio.url)
            if data is not None:
                if params.audio.skipHash is None:
                    skip = False
                else:
                    m = hashlib.md5()
                    m.update(data)
                    skip = params.audio.skipHash == m.hexdigest()

                if not skip:
                    audioInject(note, params.audio.fields, params.audio.filename)
                    self.media().writeData(params.audio.filename, data)

        self.startEditing()
        collection.addNote(note)
        collection.autosave()
        self.stopEditing()

        return note.id


    def canAddNote(self, note):
        return bool(self.createNote(note))


    def createNote(self, params):
        collection = self.collection()
        if collection is None:
            return

        model = collection.models.byName(params.modelName)
        if model is None:
            return

        deck = collection.decks.byName(params.deckName)
        if deck is None:
            return

        note = anki.notes.Note(collection, model)
        note.model()['did'] = deck['id']
        note.tags = params.tags

        for name, value in params.fields.items():
            if name in note:
                note[name] = value

        if not note.dupeOrEmpty():
            return note


    def startEditing(self):
        self.window().requireReset()


    def stopEditing(self):
        if self.collection() is not None:
            self.window().maybeReset()


    def window(self):
        return aqt.mw


    def collection(self):
        return self.window().col


    def media(self):
        collection = self.collection()
        if collection is not None:
            return collection.media


    def modelNames(self):
        collection = self.collection()
        if collection is not None:
            return collection.models.allNames()


    def modelFieldNames(self, modelName):
        collection = self.collection()
        if collection is None:
            return

        model = collection.models.byName(modelName)
        if model is not None:
            return [field['name'] for field in model['flds']]


    def deckNames(self):
        collection = self.collection()
        if collection is not None:
            return collection.decks.allNames()


    def guiBrowse(self, query):
        browser = aqt.dialogs.open('Browser', self.window())
        browser.activateWindow()

        if query:
            query = unicode('"{}"').format(query)
            browser.form.searchEdit.lineEdit().setText(query)
            browser.onSearch()

        return browser.model.cards


    def guiAddCards(self):
        addCards = aqt.dialogs.open('AddCards', self.window())
        addCards.activateWindow()


#
# AnkiConnect
#

class AnkiConnect:
    def __init__(self):
        self.anki = AnkiBridge()
        self.server = AjaxServer(self.handler)

        try:
            self.server.listen()

            self.timer = QTimer()
            self.timer.timeout.connect(self.advance)
            self.timer.start(TICK_INTERVAL)
        except:
            QMessageBox.critical(
                self.anki.window(),
                'AnkiConnect',
                'Failed to listen on port {}.\nMake sure it is available and is not in use.'.format(NET_PORT)
            )

    def advance(self):
        self.server.advance()


    def handler(self, request):
        action = 'api_' + request.get('action', '')
        if hasattr(self, action):
            try:
                return getattr(self, action)(**(request.get('params') or {}))
            except TypeError:
                return None


    def api_deckNames(self):
        return self.anki.deckNames()


    def api_modelNames(self):
        return self.anki.modelNames()


    def api_modelFieldNames(self, modelName):
        return self.anki.modelFieldNames(modelName)


    def api_addNote(self, note):
        params = AnkiNoteParams(note)
        if params.validate():
            return self.anki.addNote(params)


    def api_addNotes(self, notes):
        results = []
        for note in notes:
            params = AnkiNoteParams(note)
            if params.validate():
                results.append(self.anki.addNote(params))
            else:
                results.append(None)

        return results


    def api_canAddNotes(self, notes):
        results = []
        for note in notes:
            params = AnkiNoteParams(note)
            results.append(params.validate() and self.anki.canAddNote(params))

        return results


    def api_upgrade(self):
        response = QMessageBox.question(
            self.anki.window(),
            'AnkiConnect',
            'Upgrade to the latest version?',
            QMessageBox.Yes | QMessageBox.No
        )

        if response == QMessageBox.Yes:
            data = download(URL_UPGRADE)
            if data is None:
                QMessageBox.critical(self.anki.window, 'AnkiConnect', 'Failed to download latest version.')
            else:
                path = os.path.splitext(__file__)[0] + '.py'
                with open(path, 'w') as fp:
                    fp.write(makeStr(data))
                QMessageBox.information(self.anki.window(), 'AnkiConnect', 'Upgraded to the latest version, please restart Anki.')
                return True

        return False

    def api_version(self):
        return API_VERSION


    def api_guiBrowse(self, query):
        return self.anki.guiBrowse(query)


    def api_guiAddCards(self):
        return self.anki.guiAddCards()

#
#   Entry
#

ac = AnkiConnect()

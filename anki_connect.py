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


import PyQt4
import anki
import aqt
import hashlib
import json
import select
import socket
import urllib2


#
# Constants
#

API_VERSION = 1


#
# Audio helpers
#

def audioBuildFilename(kana, kanji):
    filename = u'yomichan_{}'.format(kana)
    if kanji:
        filename += u'_{}'.format(kanji)
    filename += u'.mp3'
    return filename


def audioDownload(kana, kanji):
    url = 'http://assets.languagepod101.com/dictionary/japanese/audiomp3.php?kana={}'.format(urllib2.quote(kana.encode('utf-8')))
    if kanji:
        url += '&kanji={}'.format(urllib2.quote(kanji.encode('utf-8')))

    try:
        resp = urllib2.urlopen(url)
    except urllib2.URLError:
        return None

    if resp.code != 200:
        return None

    data = resp.read()

    m = hashlib.md5()
    m.update(data)
    if m.hexdigest() == '7e2c2f954ef6051373ba916f000168dc':
        return None

    return data


def audioFixupField(field, kana, kanji):
    return field.replace(u'{audio}', audioBuildFilename(kana, kanji))


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
        self.readBuff = ''
        self.writeBuff = ''


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

        self.readBuff = ''
        self.writeBuff = ''


    def parseRequest(self, data):
        parts = data.split('\r\n\r\n', 1)
        if len(parts) == 1:
            return None, 0

        headers = {}
        for line in parts[0].split('\r\n'):
            pair = line.split(': ')
            headers[pair[0]] = pair[1] if len(pair) > 1 else None

        headerLength = len(parts[0]) + 4
        bodyLength = int(headers['Content-Length'])
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
        self.clients = filter(lambda c: c.advance(), self.clients)


    def listen(self, address='127.0.0.1', port=8765, backlog=5):
        self.close()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setblocking(False)
        self.sock.bind((address, port))
        self.sock.listen(backlog)


    def handlerWrapper(self, req):
        body = json.dumps(self.handler(json.loads(req.body)))
        resp = ''

        headers = {
            'HTTP/1.1 200 OK': None,
            'Content-Type': 'text/json',
            'Content-Length': str(len(body))
        }

        for key, value in headers.items():
            if value is None:
                resp += '{}\r\n'.format(key)
            else:
                resp += '{}: {}\r\n'.format(key, value)

        resp += '\r\n'
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
# AnkiBridge
#

class AnkiBridge:
    def addNote(self, deckName, modelName, fields, tags, audio):
        collection = self.collection()
        if collection is None:
            return

        note = self.createNote(deckName, modelName, fields, tags, audio)
        if note is None:
            return

        self.startEditing()

        collection.addNote(note)
        collection.autosave()

        return note.id


    def canAddNote(self, deckName, modelName, fields):
        return bool(self.createNote(deckName, modelName, fields))


    def createNote(self, deckName, modelName, fields, tags=[], audio=None):
        collection = self.collection()
        if collection is None:
            return

        model = collection.models.byName(modelName)
        if model is None:
            return

        deck = collection.decks.byName(deckName)
        if deck is None:
            return

        note = anki.notes.Note(collection, model)
        note.model()['did'] = deck['id']
        note.tags = tags

        for name, value in fields.items():
            if name in note:
                if audio is not None:
                    value = audioFixupField(value, **audio)
                note[name] = value

        if not note.dupeOrEmpty():
            return note


    def browseNote(self, noteId):
        browser = aqt.dialogs.open('Browser', self.window())
        browser.form.searchEdit.lineEdit().setText('nid:{0}'.format(noteId))
        browser.onSearch()


    def startEditing(self):
        self.window().requireReset()


    def stopEditing(self):
        if self.collection() is not None:
            self.window().maybeReset()


    def window(self):
        return aqt.mw


    def collection(self):
        return self.window().col


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


#
# AnkiConnect
#

class AnkiConnect:
    def __init__(self, interval=25):
        self.anki = AnkiBridge()
        self.server = AjaxServer(self.handler)
        self.server.listen()

        self.timer = PyQt4.QtCore.QTimer()
        self.timer.timeout.connect(self.advance)
        self.timer.start(interval)


    def advance(self):
        self.server.advance()


    def handler(self, request):
        action = 'api_' + (request.get('action') or '')
        if hasattr(self, action):
            return getattr(self, action)(**(request.get('params') or {}))


    def api_deckNames(self):
        return self.anki.deckNames()


    def api_modelNames(self):
        return self.anki.modelNames()


    def api_modelFieldNames(self, modelName):
        return self.anki.modelFieldNames(modelName)


    def api_addNote(self, note):
        return self.anki.addNote(
            note['deckName'],
            note['modelName'],
            note['fields'],
            note['tags'],
            note.get('audio')
        )


    def api_canAddNotes(self, notes):
        results = []
        for note in notes:
            results.append(self.anki.canAddNote(
                note['deckName'],
                note['modelName'],
                note['fields']
            ))

        return results


    def api_features(self):
        features = {}
        for name in dir(self):
            method = getattr(self, name)
            if name.startswith('api_') and callable(method):
                features[name[4:]] = list(method.func_code.co_varnames[1:])

        return features


    def api_version(self):
        return API_VERSION


#
#   Entry
#

ac = AnkiConnect()

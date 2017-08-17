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
import inspect
import json
import os.path
import select
import socket
import sys
from time import time


#
# Constants
#

API_VERSION = 4
TICK_INTERVAL = 25
URL_TIMEOUT = 10
URL_UPGRADE = 'https://raw.githubusercontent.com/FooSoft/anki-connect/master/AnkiConnect.py'
NET_ADDRESS = '127.0.0.1'
NET_BACKLOG = 5
NET_PORT = 8765


#
# General helpers
#

if sys.version_info[0] < 3:
    import urllib2
    web = urllib2

    from PyQt4.QtCore import QTimer
    from PyQt4.QtGui import QMessageBox
else:
    unicode = str

    from urllib import request
    web = request

    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QMessageBox


#
# Helpers
#

def webApi(func):
    func.webApi = True
    return func


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


    def addTags(self, notes, tags, add=True):
        self.startEditing()
        self.collection().tags.bulkAdd(notes, tags, add)
        self.stopEditing()


    def suspend(self, cards, suspend=True):
        for card in cards:
            isSuspended = self.isSuspended(card)
            if suspend and isSuspended:
                cards.remove(card)
            elif not suspend and not isSuspended:
                cards.remove(card)

        if cards:
            self.startEditing()
            if suspend:
                self.collection().sched.suspendCards(cards)
            else:
                self.collection().sched.unsuspendCards(cards)
            self.stopEditing()
            return True

        return False


    def areSuspended(self, cards):
        suspended = []
        for card in cards:
            card = self.collection().getCard(card)
            if card.queue == -1:
                suspended.append(True)
            else:
                suspended.append(False)
        return suspended


    def areDue(self, cards):
        due = []
        for card in cards:
            if self.findCards('cid:%s is:new' % card):
                due.append(True)
                continue

            date, ivl = self.collection().db.all('select id/1000.0, ivl from revlog where cid = ?', card)[-1]
            if (ivl >= -1200):
                if self.findCards('cid:%s is:due' % card):
                    due.append(True)
                else:
                    due.append(False)
            else:
                if date - ivl <= time():
                    due.append(True)
                else:
                    due.append(False)

        return due


    def getIntervals(self, cards, complete=False):
        intervals = []
        for card in cards:
            if self.findCards('cid:%s is:new' % card):
                intervals.append(0)
                continue

            interval = self.collection().db.list('select ivl from revlog where cid = ?', card)
            if not complete:
                interval = interval[-1]
            intervals.append(interval)
        return intervals


    def startEditing(self):
        self.window().requireReset()


    def stopEditing(self):
        if self.collection() is not None:
            self.window().maybeReset()


    def window(self):
        return aqt.mw


    def reviewer(self):
        return self.window().reviewer


    def collection(self):
        return self.window().col


    def scheduler(self):
        return self.collection().sched


    def media(self):
        collection = self.collection()
        if collection is not None:
            return collection.media


    def modelNames(self):
        collection = self.collection()
        if collection is not None:
            return collection.models.allNames()


    def modelNameFromId(self, modelId):
        collection = self.collection()
        if collection is not None:
            model = collection.models.get(modelId)
            if model is not None:
                return model['name']


    def modelFieldNames(self, modelName):
        collection = self.collection()
        if collection is not None:
            model = collection.models.byName(modelName)
            if model is not None:
                return [field['name'] for field in model['flds']]


    def multi(self, actions):
        response = []
        for item in actions:
            response.append(AnkiConnect.handler(ac, item))
        return response


    def deckNames(self):
        collection = self.collection()
        if collection is not None:
            return collection.decks.allNames()


    def deckNamesAndIds(self):
        decks = {}

        deckNames = self.deckNames()
        for deck in deckNames:
            id = self.collection().decks.id(deck)
            decks[deck] = id

        return decks


    def deckNameFromId(self, deckId):
        collection = self.collection()
        if collection is not None:
            deck = collection.decks.get(deckId)
            if deck is not None:
                return deck['name']


    def findNotes(self, query=None):
        if query is not None:
            return self.collection().findNotes(query)
        else:
            return []


    def findCards(self, query=None):
        if query is not None:
            return self.collection().findCards(query)
        else:
            return []


    def getDecks(self, cards):
        decks = {}
        for card in cards:
            did = self.collection().db.scalar('select did from cards where id = ?', card)
            deck = self.collection().decks.get(did)['name']

            if deck in decks:
                decks[deck].append(card)
            else:
                decks[deck] = [card]

        return decks


    def changeDeck(self, cards, deck):
        self.startEditing()

        did = self.collection().decks.id(deck)
        mod = anki.utils.intTime()
        usn = self.collection().usn()

        # normal cards
        scids = anki.utils.ids2str(cards)
        # remove any cards from filtered deck first
        self.collection().sched.remFromDyn(cards)

        # then move into new deck
        self.collection().db.execute('update cards set usn=?, mod=?, did=? where id in ' + scids, usn, mod, did)
        self.stopEditing()


    def deleteDecks(self, decks, cardsToo=False):
        self.startEditing()
        for deck in decks:
            id = self.collection().decks.id(deck)
            self.collection().decks.rem(id, cardsToo)
        self.stopEditing()


    def cardsToNotes(self, cards):
        return self.collection().db.list('select distinct nid from cards where id in ' + anki.utils.ids2str(cards))


    def guiBrowse(self, query=None):
        browser = aqt.dialogs.open('Browser', self.window())
        browser.activateWindow()

        if query is not None:
            browser.form.searchEdit.lineEdit().setText(query)
            if hasattr(browser, 'onSearch'):
                browser.onSearch()
            else:
                browser.onSearchActivated()

        return browser.model.cards


    def guiAddCards(self):
        addCards = aqt.dialogs.open('AddCards', self.window())
        addCards.activateWindow()


    def guiReviewActive(self):
        return self.reviewer().card is not None and self.window().state == 'review'


    def guiCurrentCard(self):
        if not self.guiReviewActive():
            return

        reviewer = self.reviewer()
        card = reviewer.card
        model = card.model()
        note = card.note()

        fields = {}
        for info in model['flds']:
            order = info['ord']
            name = info['name']
            fields[name] = {'value': note.fields[order], 'order': order}

        if card is not None:
            return {
                'cardId': card.id,
                'fields': fields,
                'fieldOrder': card.ord,
                'question': card._getQA()['q'],
                'answer': card._getQA()['a'],
                'buttons': map(lambda b: b[0], reviewer._answerButtonList()),
                'modelName': model['name'],
                'deckName': self.deckNameFromId(card.did)
            }


    def guiStartCardTimer(self):
        if not self.guiReviewActive():
            return False

        card = self.reviewer().card

        if card is not None:
            card.startTimer()
            return True
        else:
            return False

    def guiShowQuestion(self):
        if self.guiReviewActive():
            self.reviewer()._showQuestion()
            return True
        else:
            return False


    def guiShowAnswer(self):
        if self.guiReviewActive():
            self.window().reviewer._showAnswer()
            return True
        else:
            return False


    def guiAnswerCard(self, ease):
        if not self.guiReviewActive():
            return False

        reviewer = self.reviewer()
        if reviewer.state != 'answer':
            return False
        if ease <= 0 or ease > self.scheduler().answerButtons(reviewer.card):
            return False

        reviewer._answerCard(ease)
        return True


    def guiDeckOverview(self, name):
        collection = self.collection()
        if collection is not None:
            deck = collection.decks.byName(name)
            if deck is not None:
                collection.decks.select(deck['id'])
                self.window().onOverview()
                return True

        return False


    def guiDeckBrowser(self):
        self.window().moveToState('deckBrowser')


    def guiDeckReview(self, name):
        if self.guiDeckOverview(name):
            self.window().moveToState('review')
            return True
        else:
            return False


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
        action = request.get('action', '')
        if hasattr(self, action):
            handler = getattr(self, action)
            if callable(handler) and hasattr(handler, 'webApi') and getattr(handler, 'webApi'):
                spec = inspect.getargspec(handler)
                argsAll = spec.args[1:]
                argsReq = argsAll

                argsDef = spec.defaults
                if argsDef is not None:
                    argsReq = argsAll[:-len(argsDef)]

                params = request.get('params', {})
                for argReq in argsReq:
                    if argReq not in params:
                        return
                for param in params:
                    if param not in argsAll:
                        return

                return handler(**params)


    @webApi
    def deckNames(self):
        return self.anki.deckNames()


    @webApi
    def deckNamesAndIds(self):
        return self.anki.deckNamesAndIds()


    @webApi
    def modelNames(self):
        return self.anki.modelNames()


    @webApi
    def modelFieldNames(self, modelName):
        return self.anki.modelFieldNames(modelName)


    @webApi
    def multi(self, actions):
        return self.anki.multi(actions)


    @webApi
    def addNote(self, note):
        params = AnkiNoteParams(note)
        if params.validate():
            return self.anki.addNote(params)


    @webApi
    def addNotes(self, notes):
        results = []
        for note in notes:
            params = AnkiNoteParams(note)
            if params.validate():
                results.append(self.anki.addNote(params))
            else:
                results.append(None)

        return results


    @webApi
    def canAddNotes(self, notes):
        results = []
        for note in notes:
            params = AnkiNoteParams(note)
            results.append(params.validate() and self.anki.canAddNote(params))

        return results


    @webApi
    def addTags(self, notes, tags, add=True):
        return self.anki.addTags(notes, tags, add)


    @webApi
    def removeTags(self, notes, tags):
        return self.anki.addTags(notes, tags, False)


    @webApi
    def suspend(self, cards, suspend=True):
        return self.anki.suspend(cards, suspend)


    @webApi
    def unsuspend(self, cards):
        return self.anki.suspend(cards, False)


    @webApi
    def areSuspended(self, cards):
        return self.anki.areSuspended(cards)


    @webApi
    def areDue(self, cards):
        return self.anki.areDue(cards)


    @webApi
    def getIntervals(self, cards, complete=False):
        return self.anki.getIntervals(cards, complete)


    @webApi
    def upgrade(self):
        response = QMessageBox.question(
            self.anki.window(),
            'AnkiConnect',
            'Upgrade to the latest version?',
            QMessageBox.Yes | QMessageBox.No
        )

        if response == QMessageBox.Yes:
            data = download(URL_UPGRADE)
            if data is None:
                QMessageBox.critical(self.anki.window(), 'AnkiConnect', 'Failed to download latest version.')
            else:
                path = os.path.splitext(__file__)[0] + '.py'
                with open(path, 'w') as fp:
                    fp.write(makeStr(data))
                QMessageBox.information(self.anki.window(), 'AnkiConnect', 'Upgraded to the latest version, please restart Anki.')
                return True

        return False


    @webApi
    def version(self):
        return API_VERSION


    @webApi
    def findNotes(self, query=None):
        return self.anki.findNotes(query)


    @webApi
    def findCards(self, query=None):
        return self.anki.findCards(query)


    @webApi
    def getDecks(self, cards):
        return self.anki.getDecks(cards)


    @webApi
    def changeDeck(self, cards, deck):
        return self.anki.changeDeck(cards, deck)


    @webApi
    def deleteDecks(self, decks, cardsToo=False):
        return self.anki.deleteDecks(decks, cardsToo)


    @webApi
    def cardsToNotes(self, cards):
        return self.anki.cardsToNotes(cards)


    @webApi
    def guiBrowse(self, query=None):
        return self.anki.guiBrowse(query)


    @webApi
    def guiAddCards(self):
        return self.anki.guiAddCards()


    @webApi
    def guiCurrentCard(self):
        return self.anki.guiCurrentCard()


    @webApi
    def guiStartCardTimer(self):
        return self.anki.guiStartCardTimer()


    @webApi
    def guiAnswerCard(self, ease):
        return self.anki.guiAnswerCard(ease)


    @webApi
    def guiShowQuestion(self):
        return self.anki.guiShowQuestion()


    @webApi
    def guiShowAnswer(self):
        return self.anki.guiShowAnswer()


    @webApi
    def guiDeckOverview(self, name):
        return self.anki.guiDeckOverview(name)


    @webApi
    def guiDeckBrowser(self):
        return self.anki.guiDeckBrowser()


    @webApi
    def guiDeckReview(self, name):
        return self.anki.guiDeckReview(name)


#
#   Entry
#

ac = AnkiConnect()

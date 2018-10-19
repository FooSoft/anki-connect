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
import base64
import hashlib
import inspect
import json
import os
import os.path
import re
import select
import socket
import sys

from operator import itemgetter
from time import time
from unicodedata import normalize


#
# Constants
#

API_VERSION = 6
API_LOG_PATH = None
NET_ADDRESS = os.getenv('ANKICONNECT_BIND_ADDRESS', '127.0.0.1')
NET_BACKLOG = 5
NET_PORT = 8765
TICK_INTERVAL = 25
URL_TIMEOUT = 10
URL_UPGRADE = 'https://raw.githubusercontent.com/FooSoft/anki-connect/master/AnkiConnect.py'


#
# Helpers
#

if sys.version_info[0] < 3:
    import urllib2
    def download(url):
        contents = None
        resp = urllib2.urlopen(url, timeout=URL_TIMEOUT)
        if resp.code == 200:
            contents = resp.read()
        return (resp.code, contents)

    from PyQt4.QtCore import QTimer
    from PyQt4.QtGui import QMessageBox
else:
    unicode = str

    from anki.sync import AnkiRequestsClient
    def download(url):
        contents = None
        client = AnkiRequestsClient()
        client.timeout = URL_TIMEOUT
        resp = client.get(url)
        if resp.status_code == 200:
            contents = client.streamContent(resp)
        return (resp.status_code, contents)

    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QMessageBox


def makeBytes(data):
    return data.encode('utf-8')


def makeStr(data):
    return data.decode('utf-8')


def api(*versions):
    def decorator(func):
        method = lambda *args, **kwargs: func(*args, **kwargs)
        setattr(method, 'versions', versions)
        setattr(method, 'api', True)
        return method

    return decorator


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
        parts = data.split(makeBytes('\r\n\r\n'), 1)
        if len(parts) == 1:
            return None, 0

        headers = {}
        for line in parts[0].split(makeBytes('\r\n')):
            pair = line.split(makeBytes(': '))
            headers[pair[0].lower()] = pair[1] if len(pair) > 1 else None

        headerLength = len(parts[0]) + 4
        bodyLength = int(headers.get(makeBytes('content-length'), 0))
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
        self.resetHeaders()


    def setHeader(self, name, value):
        self.headersOpt[name] = value


    def resetHeaders(self):
        self.headers = [
            ['HTTP/1.1 200 OK', None],
            ['Content-Type', 'text/json'],
            ['Access-Control-Allow-Origin', '*']
        ]
        self.headersOpt = {}


    def getHeaders(self):
        headers = self.headers[:]
        for name in self.headersOpt:
            headers.append([name, self.headersOpt[name]])

        return headers


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
                body = makeBytes(json.dumps(None))

        resp = bytes()

        self.setHeader('Content-Length', str(len(body)))
        headers = self.getHeaders()

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
# AnkiConnect
#

class AnkiConnect:
    def __init__(self):
        self.server = WebServer(self.handler)
        self.log = None
        if API_LOG_PATH is not None:
            self.log = open(API_LOG_PATH, 'w')

        try:
            self.server.listen()

            self.timer = QTimer()
            self.timer.timeout.connect(self.advance)
            self.timer.start(TICK_INTERVAL)
        except:
            QMessageBox.critical(
                self.window(),
                'AnkiConnect',
                'Failed to listen on port {}.\nMake sure it is available and is not in use.'.format(NET_PORT)
            )


    def advance(self):
        self.server.advance()


    def handler(self, request):
        if self.log is not None:
            self.log.write('[request]\n')
            json.dump(request, self.log, indent=4, sort_keys=True)
            self.log.write('\n\n')

        name = request.get('action', '')
        version = request.get('version', 4)
        params = request.get('params', {})
        reply = {'result': None, 'error': None}

        try:
            method = None

            for methodName, methodInst in inspect.getmembers(self, predicate=inspect.ismethod):
                apiVersionLast = 0
                apiNameLast = None

                if getattr(methodInst, 'api', False):
                    for apiVersion, apiName in getattr(methodInst, 'versions', []):
                        if apiVersionLast < apiVersion <= version:
                            apiVersionLast = apiVersion
                            apiNameLast = apiName

                    if apiNameLast is None and apiVersionLast == 0:
                        apiNameLast = methodName

                    if apiNameLast is not None and apiNameLast == name:
                        method = methodInst
                        break

            if method is None:
                raise Exception('unsupported action')
            else:
                reply['result'] = methodInst(**params)
        except Exception as e:
            reply['error'] = str(e)

        if version <= 4:
            reply = reply['result']

        if self.log is not None:
            self.log.write('[reply]\n')
            json.dump(reply, self.log, indent=4, sort_keys=True)
            self.log.write('\n\n')

        return reply


    def download(self, url):
        try:
            (code, contents) = download(url)
        except Exception as e:
            raise Exception('{} download failed with error {}'.format(url, str(e)))
        if code == 200:
            return contents
        else:
            raise Exception('{} download failed with return code {}'.format(url, code))


    def window(self):
        return aqt.mw


    def reviewer(self):
        reviewer = self.window().reviewer
        if reviewer is None:
            raise Exception('reviewer is not available')
        else:
            return reviewer


    def collection(self):
        collection = self.window().col
        if collection is None:
            raise Exception('collection is not available')
        else:
            return collection


    def decks(self):
        decks = self.collection().decks
        if decks is None:
            raise Exception('decks are not available')
        else:
            return decks


    def scheduler(self):
        scheduler = self.collection().sched
        if scheduler is None:
            raise Exception('scheduler is not available')
        else:
            return scheduler


    def database(self):
        database = self.collection().db
        if database is None:
            raise Exception('database is not available')
        else:
            return database


    def media(self):
        media = self.collection().media
        if media is None:
            raise Exception('media is not available')
        else:
            return media


    def startEditing(self):
        self.window().requireReset()


    def stopEditing(self):
        if self.collection() is not None:
            self.window().maybeReset()


    def createNote(self, note):
        collection = self.collection()

        model = collection.models.byName(note['modelName'])
        if model is None:
            raise Exception('model was not found: {}'.format(note['modelName']))

        deck = collection.decks.byName(note['deckName'])
        if deck is None:
            raise Exception('deck was not found: {}'.format(note['deckName']))

        ankiNote = anki.notes.Note(collection, model)
        ankiNote.model()['did'] = deck['id']
        ankiNote.tags = note['tags']

        for name, value in note['fields'].items():
            if name in ankiNote:
                ankiNote[name] = value

        duplicateOrEmpty = ankiNote.dupeOrEmpty()
        if duplicateOrEmpty == 1:
            raise Exception('cannot create note because it is empty')
        elif duplicateOrEmpty == 2:
            raise Exception('cannot create note because it is a duplicate')
        elif duplicateOrEmpty == False:
            return ankiNote
        else:
            raise Exception('cannot create note for unknown reason')


    #
    # Miscellaneous
    #

    @api()
    def version(self):
        return API_VERSION


    @api()
    def upgrade(self):
        response = QMessageBox.question(
            self.window(),
            'AnkiConnect',
            'Upgrade to the latest version?',
            QMessageBox.Yes | QMessageBox.No
        )

        if response == QMessageBox.Yes:
            try:
                data = self.download(URL_UPGRADE)
                path = os.path.splitext(__file__)[0] + '.py'
                with open(path, 'w') as fp:
                    fp.write(makeStr(data))
                QMessageBox.information(
                    self.window(),
                    'AnkiConnect',
                    'Upgraded to the latest version, please restart Anki.'
                )
                return True
            except Exception as e:
                QMessageBox.critical(self.window(), 'AnkiConnect', 'Failed to download latest version.')
                raise e

        return False


    @api()
    def sync(self):
        self.window().onSync()


    @api()
    def multi(self, actions):
        return list(map(self.handler, actions))


    #
    # Decks
    #

    @api()
    def deckNames(self):
        return self.decks().allNames()


    @api()
    def deckNamesAndIds(self):
        decks = {}
        for deck in self.deckNames():
            decks[deck] = self.decks().id(deck)

        return decks


    @api()
    def getDecks(self, cards):
        decks = {}
        for card in cards:
            did = self.database().scalar('select did from cards where id=?', card)
            deck = self.decks().get(did)['name']
            if deck in decks:
                decks[deck].append(card)
            else:
                decks[deck] = [card]

        return decks


    @api()
    def createDeck(self, deck):
        try:
            self.startEditing()
            did = self.decks().id(deck)
        finally:
            self.stopEditing()

        return did


    @api()
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


    @api()
    def deleteDecks(self, decks, cardsToo=False):
        try:
            self.startEditing()
            decks = filter(lambda d: d in self.deckNames(), decks)
            for deck in decks:
                did = self.decks().id(deck)
                self.decks().rem(did, cardsToo)
        finally:
            self.stopEditing()


    @api()
    def getDeckConfig(self, deck):
        if not deck in self.deckNames():
            return False

        collection = self.collection()
        did = collection.decks.id(deck)
        return collection.decks.confForDid(did)


    @api()
    def saveDeckConfig(self, config):
        collection = self.collection()

        config['id'] = str(config['id'])
        config['mod'] = anki.utils.intTime()
        config['usn'] = collection.usn()

        if not config['id'] in collection.decks.dconf:
            return False

        collection.decks.dconf[config['id']] = config
        collection.decks.changed = True
        return True


    @api()
    def setDeckConfigId(self, decks, configId):
        configId = str(configId)
        for deck in decks:
            if not deck in self.deckNames():
                return False

        collection = self.collection()
        if not configId in collection.decks.dconf:
            return False

        for deck in decks:
            did = str(collection.decks.id(deck))
            aqt.mw.col.decks.decks[did]['conf'] = configId

        return True


    @api()
    def cloneDeckConfigId(self, name, cloneFrom='1'):
        configId = str(cloneFrom)
        if not configId in self.collection().decks.dconf:
            return False

        config = self.collection().decks.getConf(configId)
        return self.collection().decks.confId(name, config)


    @api()
    def removeDeckConfigId(self, configId):
        configId = str(configId)
        collection = self.collection()
        if configId == 1 or not configId in collection.decks.dconf:
            return False

        collection.decks.remConf(configId)
        return True


    @api()
    def storeMediaFile(self, filename, data):
        self.deleteMediaFile(filename)
        self.media().writeData(filename, base64.b64decode(data))


    @api()
    def retrieveMediaFile(self, filename):
        filename = os.path.basename(filename)
        filename = normalize('NFC', filename)
        filename = self.media().stripIllegal(filename)

        path = os.path.join(self.media().dir(), filename)
        if os.path.exists(path):
            with open(path, 'rb') as file:
                return base64.b64encode(file.read()).decode('ascii')

        return False


    @api()
    def deleteMediaFile(self, filename):
        self.media().syncDelete(filename)


    @api()
    def addNote(self, note):
        ankiNote = self.createNote(note)

        audio = note.get('audio')
        if audio is not None and len(audio['fields']) > 0:
            try:
                data = self.download(audio['url'])
                skipHash = audio.get('skipHash')
                if skipHash is None:
                    skip = False
                else:
                    m = hashlib.md5()
                    m.update(data)
                    skip = skipHash == m.hexdigest()

                if not skip:
                    for field in audio['fields']:
                        if field in ankiNote:
                            ankiNote[field] += u'[sound:{}]'.format(audio['filename'])

                    self.media().writeData(audio['filename'], data)
            except Exception as e:
                errorMessage = str(e).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                for field in audio['fields']:
                    if field in ankiNote:
                        ankiNote[field] += errorMessage

        collection = self.collection()
        self.startEditing()
        collection.addNote(ankiNote)
        collection.autosave()
        self.stopEditing()

        return ankiNote.id


    @api()
    def canAddNote(self, note):
        try:
            return bool(self.createNote(note))
        except:
            return False


    @api()
    def updateNoteFields(self, note):
        ankiNote = self.collection().getNote(note['id'])
        if ankiNote is None:
            raise Exception('note was not found: {}'.format(note['id']))

        for name, value in note['fields'].items():
            if name in ankiNote:
                ankiNote[name] = value

        ankiNote.flush()


    @api()
    def addTags(self, notes, tags, add=True):
        self.startEditing()
        self.collection().tags.bulkAdd(notes, tags, add)
        self.stopEditing()


    @api()
    def removeTags(self, notes, tags):
        return self.addTags(notes, tags, False)


    @api()
    def getTags(self):
        return self.collection().tags.all()


    @api()
    def suspend(self, cards, suspend=True):
        for card in cards:
            if self.suspended(card) == suspend:
                cards.remove(card)

        if len(cards) == 0:
            return False

        scheduler = self.scheduler()
        self.startEditing()
        if suspend:
            scheduler.suspendCards(cards)
        else:
            scheduler.unsuspendCards(cards)
        self.stopEditing()

        return True


    @api()
    def unsuspend(self, cards):
        self.suspend(cards, False)


    @api()
    def suspended(self, card):
        card = self.collection().getCard(card)
        return card.queue == -1


    @api()
    def areSuspended(self, cards):
        suspended = []
        for card in cards:
            suspended.append(self.suspended(card))

        return suspended


    @api()
    def areDue(self, cards):
        due = []
        for card in cards:
            if self.findCards('cid:{} is:new'.format(card)):
                due.append(True)
            else:
                date, ivl = self.collection().db.all('select id/1000.0, ivl from revlog where cid = ?', card)[-1]
                if ivl >= -1200:
                    due.append(bool(self.findCards('cid:{} is:due'.format(card))))
                else:
                    due.append(date - ivl <= time())

        return due


    @api()
    def getIntervals(self, cards, complete=False):
        intervals = []
        for card in cards:
            if self.findCards('cid:{} is:new'.format(card)):
                intervals.append(0)
            else:
                interval = self.collection().db.list('select ivl from revlog where cid = ?', card)
                if not complete:
                    interval = interval[-1]
                intervals.append(interval)

        return intervals



    @api()
    def modelNames(self):
        return self.collection().models.allNames()


    @api()
    def modelNamesAndIds(self):
        models = {}
        for model in self.modelNames():
            models[model] = int(self.collection().models.byName(model)['id'])

        return models


    @api()
    def modelNameFromId(self, modelId):
        model = self.collection().models.get(modelId)
        if model is None:
            raise Exception('model was not found: {}'.format(modelId))
        else:
            return model['name']


    @api()
    def modelFieldNames(self, modelName):
        model = self.collection().models.byName(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))
        else:
            return [field['name'] for field in model['flds']]


    @api()
    def modelFieldsOnTemplates(self, modelName):
        model = self.collection().models.byName(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))

        templates = {}
        for template in model['tmpls']:
            fields = []
            for side in ['qfmt', 'afmt']:
                fieldsForSide = []

                # based on _fieldsOnTemplate from aqt/clayout.py
                matches = re.findall('{{[^#/}]+?}}', template[side])
                for match in matches:
                    # remove braces and modifiers
                    match = re.sub(r'[{}]', '', match)
                    match = match.split(':')[-1]

                    # for the answer side, ignore fields present on the question side + the FrontSide field
                    if match == 'FrontSide' or side == 'afmt' and match in fields[0]:
                        continue
                    fieldsForSide.append(match)

                fields.append(fieldsForSide)

            templates[template['name']] = fields

        return templates


    @api()
    def deckNameFromId(self, deckId):
        deck = self.collection().decks.get(deckId)
        if deck is None:
            raise Exception('deck was not found: {}'.format(deckId))
        else:
            return deck['name']


    @api()
    def findNotes(self, query=None):
        if query is None:
            return []
        else:
            return self.collection().findNotes(query)


    @api()
    def findCards(self, query=None):
        if query is None:
            return []
        else:
            return self.collection().findCards(query)


    @api()
    def cardsInfo(self, cards):
        result = []
        for cid in cards:
            try:
                card = self.collection().getCard(cid)
                model = card.model()
                note = card.note()
                fields = {}
                for info in model['flds']:
                    order = info['ord']
                    name = info['name']
                    fields[name] = {'value': note.fields[order], 'order': order}

                result.append({
                    'cardId': card.id,
                    'fields': fields,
                    'fieldOrder': card.ord,
                    'question': card._getQA()['q'],
                    'answer': card._getQA()['a'],
                    'modelName': model['name'],
                    'deckName': self.deckNameFromId(card.did),
                    'css': model['css'],
                    'factor': card.factor,
                    #This factor is 10 times the ease percentage,
                    # so an ease of 310% would be reported as 3100
                    'interval': card.ivl,
                    'note': card.nid
                })
            except TypeError as e:
                # Anki will give a TypeError if the card ID does not exist.
                # Best behavior is probably to add an 'empty card' to the
                # returned result, so that the items of the input and return
                # lists correspond.
                result.append({})

        return result


    @api()
    def notesInfo(self, notes):
        result = []
        for nid in notes:
            try:
                note = self.collection().getNote(nid)
                model = note.model()

                fields = {}
                for info in model['flds']:
                    order = info['ord']
                    name = info['name']
                    fields[name] = {'value': note.fields[order], 'order': order}

                result.append({
                    'noteId': note.id,
                    'tags' : note.tags,
                    'fields': fields,
                    'modelName': model['name'],
                    'cards': self.collection().db.list('select id from cards where nid = ? order by ord', note.id)
                })
            except TypeError as e:
                # Anki will give a TypeError if the note ID does not exist.
                # Best behavior is probably to add an 'empty card' to the
                # returned result, so that the items of the input and return
                # lists correspond.
                result.append({})

        return result





    @api()
    def cardsToNotes(self, cards):
        return self.collection().db.list('select distinct nid from cards where id in ' + anki.utils.ids2str(cards))


    @api()
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


    @api()
    def guiAddCards(self):
        addCards = aqt.dialogs.open('AddCards', self.window())
        addCards.activateWindow()


    @api()
    def guiReviewActive(self):
        return self.reviewer().card is not None and self.window().state == 'review'


    @api()
    def guiCurrentCard(self):
        if not self.guiReviewActive():
            raise Exception('Gui review is not currently active.')

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
                'buttons': [b[0] for b in reviewer._answerButtonList()],
                'modelName': model['name'],
                'deckName': self.deckNameFromId(card.did),
                'css': model['css'],
                'template': card.template()['name']
            }


    @api()
    def guiStartCardTimer(self):
        if not self.guiReviewActive():
            return False

        card = self.reviewer().card

        if card is not None:
            card.startTimer()
            return True
        else:
            return False


    @api()
    def guiShowQuestion(self):
        if self.guiReviewActive():
            self.reviewer()._showQuestion()
            return True
        else:
            return False


    @api()
    def guiShowAnswer(self):
        if self.guiReviewActive():
            self.window().reviewer._showAnswer()
            return True
        else:
            return False


    @api()
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


    @api()
    def guiDeckOverview(self, name):
        collection = self.collection()
        if collection is not None:
            deck = collection.decks.byName(name)
            if deck is not None:
                collection.decks.select(deck['id'])
                self.window().onOverview()
                return True

        return False


    @api()
    def guiDeckBrowser(self):
        self.window().moveToState('deckBrowser')


    @api()
    def guiDeckReview(self, name):
        if self.guiDeckOverview(name):
            self.window().moveToState('review')
            return True
        else:
            return False


    @api()
    def guiExitAnki(self):
        timer = QTimer()
        def exitAnki():
            timer.stop()
            self.window().close()
        timer.timeout.connect(exitAnki)
        timer.start(1000) # 1s should be enough to allow the response to be sent.



    @api()
    def addNotes(self, notes):
        results = []
        for note in notes:
            try:
                results.append(self.addNote(note))
            except Exception:
                results.append(None)

        return results


    @api()
    def canAddNotes(self, notes):
        results = []
        for note in notes:
            results.append(self.canAddNote(note))

        return results


#
# Entry
#

ac = AnkiConnect()

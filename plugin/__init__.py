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

import aqt

anki_version = tuple(int(segment) for segment in aqt.appVersion.split("."))

if anki_version < (2, 1, 45):
    raise Exception("Minimum Anki version supported: 2.1.45")

import base64
import glob
import hashlib
import inspect
import json
import os
import os.path
import platform
import re
import time
import unicodedata

import anki
import anki.exporting
import anki.storage
from anki.cards import Card
from anki.consts import MODEL_CLOZE
from anki.exporting import AnkiPackageExporter
from anki.importing import AnkiPackageImporter
from anki.notes import Note
from anki.errors import NotFoundError
from aqt.qt import Qt, QTimer, QMessageBox, QCheckBox

from .web import format_exception_reply, format_success_reply
from .edit import Edit
from . import web, util


#
# AnkiConnect
#

class AnkiConnect:
    def __init__(self):
        self.log = None
        self.timer = None
        self.server = web.WebServer(self.handler)

    def initLogging(self):
        logPath = util.setting('apiLogPath')
        if logPath is not None:
            self.log = open(logPath, 'w')

    def startWebServer(self):
        try:
            self.server.listen()

            # only keep reference to prevent garbage collection
            self.timer = QTimer()
            self.timer.timeout.connect(self.advance)
            self.timer.start(util.setting('apiPollInterval'))
        except:
            QMessageBox.critical(
                self.window(),
                'AnkiConnect',
                'Failed to listen on port {}.\nMake sure it is available and is not in use.'.format(util.setting('webBindPort'))
            )

    def save_model(self, models, ankiModel):
        models.update_dict(ankiModel)

    def logEvent(self, name, data):
        if self.log is not None:
            self.log.write('[{}]\n'.format(name))
            json.dump(data, self.log, indent=4, sort_keys=True)
            self.log.write('\n\n')
            self.log.flush()


    def advance(self):
        self.server.advance()


    def handler(self, request):
        self.logEvent('request', request)

        name = request.get('action', '')
        version = request.get('version', 4)
        params = request.get('params', {})
        key = request.get('key')

        try:
            if key != util.setting('apiKey') and name != 'requestPermission':
                raise Exception('valid api key must be provided')

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

            api_return_value = methodInst(**params)
            reply = format_success_reply(version, api_return_value)

        except Exception as e:
            reply = format_exception_reply(version, e)

        self.logEvent('reply', reply)
        return reply


    def window(self):
        return aqt.mw


    def reviewer(self):
        reviewer = self.window().reviewer
        if reviewer is None:
            raise Exception('reviewer is not available')

        return reviewer


    def collection(self):
        collection = self.window().col
        if collection is None:
            raise Exception('collection is not available')

        return collection


    def decks(self):
        decks = self.collection().decks
        if decks is None:
            raise Exception('decks are not available')

        return decks


    def scheduler(self):
        scheduler = self.collection().sched
        if scheduler is None:
            raise Exception('scheduler is not available')

        return scheduler


    def database(self):
        database = self.collection().db
        if database is None:
            raise Exception('database is not available')

        return database


    def media(self):
        media = self.collection().media
        if media is None:
            raise Exception('media is not available')

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
        if 'tags' in note:
            ankiNote.tags = note['tags']

        for name, value in note['fields'].items():
            for ankiName in ankiNote.keys():
                if name.lower() == ankiName.lower():
                    ankiNote[ankiName] = value
                    break

        self.addMediaFromNote(ankiNote, note)

        allowDuplicate = False
        duplicateScope = None
        duplicateScopeDeckName = None
        duplicateScopeCheckChildren = False
        duplicateScopeCheckAllModels = False

        if 'options' in note:
            options = note['options']
            if 'allowDuplicate' in options:
                allowDuplicate = options['allowDuplicate']
                if type(allowDuplicate) is not bool:
                    raise Exception('option parameter "allowDuplicate" must be boolean')
            if 'duplicateScope' in options:
                duplicateScope = options['duplicateScope']
            if 'duplicateScopeOptions' in options:
                duplicateScopeOptions = options['duplicateScopeOptions']
                if 'deckName' in duplicateScopeOptions:
                    duplicateScopeDeckName = duplicateScopeOptions['deckName']
                if 'checkChildren' in duplicateScopeOptions:
                    duplicateScopeCheckChildren = duplicateScopeOptions['checkChildren']
                    if type(duplicateScopeCheckChildren) is not bool:
                        raise Exception('option parameter "duplicateScopeOptions.checkChildren" must be boolean')
                if 'checkAllModels' in duplicateScopeOptions:
                    duplicateScopeCheckAllModels = duplicateScopeOptions['checkAllModels']
                    if type(duplicateScopeCheckAllModels) is not bool:
                        raise Exception('option parameter "duplicateScopeOptions.checkAllModels" must be boolean')

        duplicateOrEmpty = self.isNoteDuplicateOrEmptyInScope(
            ankiNote,
            deck,
            collection,
            duplicateScope,
            duplicateScopeDeckName,
            duplicateScopeCheckChildren,
            duplicateScopeCheckAllModels
        )

        if duplicateOrEmpty == 1:
            raise Exception('cannot create note because it is empty')
        elif duplicateOrEmpty == 2:
            if allowDuplicate:
                return ankiNote
            raise Exception('cannot create note because it is a duplicate')
        elif duplicateOrEmpty == 0:
            return ankiNote
        else:
            raise Exception('cannot create note for unknown reason')


    def isNoteDuplicateOrEmptyInScope(
        self,
        note,
        deck,
        collection,
        duplicateScope,
        duplicateScopeDeckName,
        duplicateScopeCheckChildren,
        duplicateScopeCheckAllModels
    ):
        # Returns: 1 if first is empty, 2 if first is a duplicate, 0 otherwise.

        # note.dupeOrEmpty returns if a note is a global duplicate with the specific model.
        # This is used as the default check, and the rest of this function is manually
        # checking if the note is a duplicate with additional options.
        if duplicateScope != 'deck' and not duplicateScopeCheckAllModels:
            return note.dupeOrEmpty() or 0

        # Primary field for uniqueness
        val = note.fields[0]
        if not val.strip():
            return 1
        csum = anki.utils.fieldChecksum(val)

        # Create dictionary of deck ids
        dids = None
        if duplicateScope == 'deck':
            did = deck['id']
            if duplicateScopeDeckName is not None:
                deck2 = collection.decks.byName(duplicateScopeDeckName)
                if deck2 is None:
                    # Invalid deck, so cannot be duplicate
                    return 0
                did = deck2['id']

            dids = {did: True}
            if duplicateScopeCheckChildren:
                for kv in collection.decks.children(did):
                    dids[kv[1]] = True

        # Build query
        query = 'select id from notes where csum=?'
        queryArgs = [csum]
        if note.id:
            query += ' and id!=?'
            queryArgs.append(note.id)
        if not duplicateScopeCheckAllModels:
            query += ' and mid=?'
            queryArgs.append(note.mid)

        # Search
        for noteId in note.col.db.list(query, *queryArgs):
            if dids is None:
                # Duplicate note exists in the collection
                return 2
            # Validate that a card exists in one of the specified decks
            for cardDeckId in note.col.db.list('select did from cards where nid=?', noteId):
                if cardDeckId in dids:
                    return 2

        # Not a duplicate
        return 0

    def getCard(self, card_id: int) -> Card:
        try:
            return self.collection().getCard(card_id)
        except NotFoundError:
            raise NotFoundError('Card was not found: {}'.format(card_id))

    def getNote(self, note_id: int) -> Note:
        try:
            return self.collection().getNote(note_id)
        except NotFoundError:
            raise NotFoundError('Note was not found: {}'.format(note_id))

    def deckStatsToJson(self, due_tree):
        deckStats = {'deck_id': due_tree.deck_id,
                     'name': due_tree.name,
                     'new_count': due_tree.new_count,
                     'learn_count': due_tree.learn_count,
                     'review_count': due_tree.review_count}
        if anki_version > (2, 1, 46):
            # total_in_deck is not supported on lower Anki versions
            deckStats['total_in_deck'] = due_tree.total_in_deck
        return deckStats

    def collectDeckTreeChildren(self, parent_node):
        allNodes = {parent_node.deck_id: parent_node}
        for child in parent_node.children:
            for deckId, childNode in self.collectDeckTreeChildren(child).items():
                allNodes[deckId] = childNode
        return allNodes

    #
    # Miscellaneous
    #

    @util.api()
    def version(self):
        return util.setting('apiVersion')


    @util.api()
    def requestPermission(self, origin, allowed):
        results = {
                "permission": "denied",
        }

        if allowed:
            results = {
                    "permission": "granted",
                    "requireApikey": bool(util.setting('apiKey')),
                    "version": util.setting('apiVersion')
            }

        elif origin in util.setting('ignoreOriginList'):
            pass  # defaults to denied

        else:  # prompt the user
            msg = QMessageBox(None)
            msg.setWindowTitle("A website wants to access to Anki")
            msg.setText('"{}" requests permission to use Anki through AnkiConnect. Do you want to give it access?'.format(origin))
            msg.setInformativeText("By granting permission, you'll allow the website to modify your collection on your behalf, including the execution of destructive actions such as deck deletion.")
            msg.setWindowIcon(self.window().windowIcon())
            msg.setIcon(QMessageBox.Question)
            msg.setStandardButtons(QMessageBox.Yes|QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            msg.setCheckBox(QCheckBox(text='Ignore further requests from "{}"'.format(origin), parent=msg))
            msg.setWindowFlags(Qt.WindowStaysOnTopHint)
            pressedButton = msg.exec_()

            if pressedButton == QMessageBox.Yes:
                config = aqt.mw.addonManager.getConfig(__name__)
                config["webCorsOriginList"] = util.setting('webCorsOriginList')
                config["webCorsOriginList"].append(origin)
                aqt.mw.addonManager.writeConfig(__name__, config)
                results = {
                    "permission": "granted",
                    "requireApikey": bool(util.setting('apiKey')),
                    "version": util.setting('apiVersion')
                }

            # if the origin isn't an empty string, the user clicks "No", and the ignore box is checked
            elif origin and pressedButton == QMessageBox.No and msg.checkBox().isChecked():
                config = aqt.mw.addonManager.getConfig(__name__)
                config["ignoreOriginList"] = util.setting('ignoreOriginList')
                config["ignoreOriginList"].append(origin)
                aqt.mw.addonManager.writeConfig(__name__, config)

            # else defaults to denied

        return results


    @util.api()
    def getProfiles(self):
        return self.window().pm.profiles()


    @util.api()
    def loadProfile(self, name):
        if name not in self.window().pm.profiles():
            return False

        if self.window().isVisible():
            cur_profile = self.window().pm.name
            if cur_profile != name:
                self.window().unloadProfileAndShowProfileManager()

                def waiter():
                    # This function waits until main window is closed
                    # It's needed cause sync can take quite some time
                    # And if we call loadProfile until sync is ended things will go wrong
                    if self.window().isVisible():
                        QTimer.singleShot(1000, waiter)
                    else:
                        self.loadProfile(name)

                waiter()
        else:
            self.window().pm.load(name)
            self.window().loadProfile()
            self.window().profileDiag.closeWithoutQuitting()

        return True


    @util.api()
    def sync(self):
        self.window().onSync()


    @util.api()
    def multi(self, actions):
        return list(map(self.handler, actions))


    @util.api()
    def getNumCardsReviewedToday(self):
        return self.database().scalar('select count() from revlog where id > ?', (self.scheduler().dayCutoff - 86400) * 1000)

    @util.api()
    def getNumCardsReviewedByDay(self):
        return self.database().all('select date(id/1000 - ?, "unixepoch", "localtime") as day, count() from revlog group by day order by day desc',
                                    int(time.strftime("%H", time.localtime(self.scheduler().dayCutoff))) * 3600)


    @util.api()
    def getCollectionStatsHTML(self, wholeCollection=True):
        stats = self.collection().stats()
        stats.wholeCollection = wholeCollection
        return stats.report()


    #
    # Decks
    #

    @util.api()
    def deckNames(self):
        return self.decks().allNames()


    @util.api()
    def deckNamesAndIds(self):
        decks = {}
        for deck in self.deckNames():
            decks[deck] = self.decks().id(deck)

        return decks


    @util.api()
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


    @util.api()
    def createDeck(self, deck):
        try:
            self.startEditing()
            did = self.decks().id(deck)
        finally:
            self.stopEditing()

        return did


    @util.api()
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


    @util.api()
    def deleteDecks(self, decks, cardsToo=False):
        if not cardsToo:
            # since f592672fa952260655881a75a2e3c921b2e23857 (2.1.28)
            # (see anki$ git log "-Gassert cardsToo")
            # you can't delete decks without deleting cards as well.
            # however, since 62c23c6816adf912776b9378c008a52bb50b2e8d (2.1.45)
            # passing cardsToo to `rem` (long deprecated) won't raise an error!
            # this is dangerous, so let's raise our own exception
            raise Exception("Since Anki 2.1.28 it's not possible "
                            "to delete decks without deleting cards as well")
        try:
            self.startEditing()
            decks = filter(lambda d: d in self.deckNames(), decks)
            for deck in decks:
                did = self.decks().id(deck)
                self.decks().rem(did, cardsToo=cardsToo)
        finally:
            self.stopEditing()


    @util.api()
    def getDeckConfig(self, deck):
        if deck not in self.deckNames():
            return False

        collection = self.collection()
        did = collection.decks.id(deck)
        return collection.decks.confForDid(did)


    @util.api()
    def saveDeckConfig(self, config):
        collection = self.collection()

        config['id'] = str(config['id'])
        config['mod'] = anki.utils.intTime()
        config['usn'] = collection.usn()
        if int(config['id']) not in [c['id'] for c in collection.decks.all_config()]:
            return False
        try:
            collection.decks.save(config)
            collection.decks.updateConf(config)
        except:
            return False
        return True


    @util.api()
    def setDeckConfigId(self, decks, configId):
        configId = int(configId)
        for deck in decks:
            if not deck in self.deckNames():
                return False

        collection = self.collection()

        for deck in decks:
            try:
                did = str(collection.decks.id(deck))
                deck_dict = aqt.mw.col.decks.decks[did]
                deck_dict['conf'] = configId
                collection.decks.save(deck_dict)
            except:
                return False

        return True


    @util.api()
    def cloneDeckConfigId(self, name, cloneFrom='1'):
        configId = int(cloneFrom)
        collection = self.collection()
        if configId not in [c['id'] for c in collection.decks.all_config()]:
            return False

        config = collection.decks.getConf(configId)
        return collection.decks.confId(name, config)


    @util.api()
    def removeDeckConfigId(self, configId):
        collection = self.collection()
        if int(configId) not in [c['id'] for c in collection.decks.all_config()]:
            return False

        collection.decks.remConf(configId)
        return True

    @util.api()
    def getDeckStats(self, decks):
        collection = self.collection()
        scheduler = self.scheduler()
        responseDict = {}
        deckIds = list(map(lambda d: collection.decks.id(d), decks))

        allDeckNodes = self.collectDeckTreeChildren(scheduler.deck_due_tree())
        for deckId, deckNode in allDeckNodes.items():
            if deckId in deckIds:
                responseDict[deckId] = self.deckStatsToJson(deckNode)
        return responseDict

    @util.api()
    def storeMediaFile(self, filename, data=None, path=None, url=None, skipHash=None, deleteExisting=True):
        if not (data or path or url):
            raise Exception('You must provide a "data", "path", or "url" field.')
        if data:
            mediaData = base64.b64decode(data)
        elif path:
            with open(path, 'rb') as f:
                mediaData = f.read()
        elif url:
            mediaData = util.download(url)

        if skipHash is None:
            skip = False
        else:
            m = hashlib.md5()
            m.update(mediaData)
            skip = skipHash == m.hexdigest()

        if skip:
            return None
        if deleteExisting:
            self.deleteMediaFile(filename)
        return self.media().writeData(filename, mediaData)


    @util.api()
    def retrieveMediaFile(self, filename):
        filename = os.path.basename(filename)
        filename = unicodedata.normalize('NFC', filename)
        filename = self.media().stripIllegal(filename)

        path = os.path.join(self.media().dir(), filename)
        if os.path.exists(path):
            with open(path, 'rb') as file:
                return base64.b64encode(file.read()).decode('ascii')

        return False


    @util.api()
    def getMediaFilesNames(self, pattern='*'):
        path = os.path.join(self.media().dir(), pattern)
        return [os.path.basename(p) for p in glob.glob(path)]


    @util.api()
    def deleteMediaFile(self, filename):
        try:
            self.media().syncDelete(filename)
        except AttributeError:
            self.media().trash_files([filename])


    @util.api()
    def addNote(self, note):
        ankiNote = self.createNote(note)

        collection = self.collection()
        self.startEditing()
        nCardsAdded = collection.addNote(ankiNote)
        if nCardsAdded < 1:
            raise Exception('The field values you have provided would make an empty question on all cards.')
        collection.autosave()
        self.stopEditing()

        return ankiNote.id


    def addMediaFromNote(self, ankiNote, note):
        audioObjectOrList = note.get('audio')
        self.addMedia(ankiNote, audioObjectOrList, util.MediaType.Audio)

        videoObjectOrList = note.get('video')
        self.addMedia(ankiNote, videoObjectOrList, util.MediaType.Video)

        pictureObjectOrList = note.get('picture')
        self.addMedia(ankiNote, pictureObjectOrList, util.MediaType.Picture)



    def addMedia(self, ankiNote, mediaObjectOrList, mediaType):
        if mediaObjectOrList is None:
            return

        if isinstance(mediaObjectOrList, list):
            mediaList = mediaObjectOrList
        else:
            mediaList = [mediaObjectOrList]

        for media in mediaList:
            if media is not None and len(media['fields']) > 0:
                try:
                    mediaFilename = self.storeMediaFile(media['filename'],
                                                        data=media.get('data'),
                                                        path=media.get('path'),
                                                        url=media.get('url'),
                                                        skipHash=media.get('skipHash'),
                                                        deleteExisting=media.get('deleteExisting'))

                    if mediaFilename is not None:
                        for field in media['fields']:
                            if field in ankiNote:
                                if mediaType is util.MediaType.Picture:
                                    ankiNote[field] += u'<img src="{}">'.format(mediaFilename)
                                elif mediaType is util.MediaType.Audio or mediaType is util.MediaType.Video:
                                    ankiNote[field] += u'[sound:{}]'.format(mediaFilename)

                except Exception as e:
                    errorMessage = str(e).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    for field in media['fields']:
                        if field in ankiNote:
                            ankiNote[field] += errorMessage


    @util.api()
    def canAddNote(self, note):
        try:
            return bool(self.createNote(note))
        except:
            return False


    @util.api()
    def updateNoteFields(self, note):
        ankiNote = self.getNote(note['id'])

        self.startEditing()
        for name, value in note['fields'].items():
            if name in ankiNote:
                ankiNote[name] = value

        audioObjectOrList = note.get('audio')
        self.addMedia(ankiNote, audioObjectOrList, util.MediaType.Audio)

        videoObjectOrList = note.get('video')
        self.addMedia(ankiNote, videoObjectOrList, util.MediaType.Video)

        pictureObjectOrList = note.get('picture')
        self.addMedia(ankiNote, pictureObjectOrList, util.MediaType.Picture)

        ankiNote.flush()

        self.collection().autosave()
        self.stopEditing()


    @util.api()
    def addTags(self, notes, tags, add=True):
        self.startEditing()
        self.collection().tags.bulkAdd(notes, tags, add)
        self.stopEditing()


    @util.api()
    def removeTags(self, notes, tags):
        return self.addTags(notes, tags, False)


    @util.api()
    def getTags(self):
        return self.collection().tags.all()


    @util.api()
    def clearUnusedTags(self):
        self.collection().tags.registerNotes()


    @util.api()
    def replaceTags(self, notes, tag_to_replace, replace_with_tag):
        self.window().progress.start()

        for nid in notes:
            try:
                note = self.getNote(nid)
            except NotFoundError:
                continue

            if note.hasTag(tag_to_replace):
                note.delTag(tag_to_replace)
                note.addTag(replace_with_tag)
                note.flush()

        self.window().requireReset()
        self.window().progress.finish()
        self.window().reset()


    @util.api()
    def replaceTagsInAllNotes(self, tag_to_replace, replace_with_tag):
        self.window().progress.start()

        collection = self.collection()
        for nid in collection.db.list('select id from notes'):
            note = self.getNote(nid)
            if note.hasTag(tag_to_replace):
                note.delTag(tag_to_replace)
                note.addTag(replace_with_tag)
                note.flush()

        self.window().requireReset()
        self.window().progress.finish()
        self.window().reset()


    @util.api()
    def setEaseFactors(self, cards, easeFactors):
        couldSetEaseFactors = []
        for i, card in enumerate(cards):
            try:
                ankiCard = self.getCard(card)
            except NotFoundError:
                couldSetEaseFactors.append(False)
                continue

            couldSetEaseFactors.append(True)
            ankiCard.factor = easeFactors[i]
            ankiCard.flush()

        return couldSetEaseFactors

    @util.api()
    def setSpecificValueOfCard(self, card, keys,
                               newValues, warning_check=False):
        if isinstance(card, list):
            print("card has to be int, not list")
            return False

        if not isinstance(keys, list) or not isinstance(newValues, list):
            print("keys and newValues have to be lists.")
            return False

        if len(newValues) != len(keys):
            print("Invalid list lengths.")
            return False

        for key in keys:
            if key in ["did", "id", "ivl", "lapses", "left", "mod", "nid",
                       "odid", "odue", "ord", "queue", "reps", "type", "usn"]:
                if warning_check is False:
                    return False

        result = []
        try:
            ankiCard = self.getCard(card)
            for i, key in enumerate(keys):
                setattr(ankiCard, key, newValues[i])
            ankiCard.flush()
            result.append(True)
        except Exception as e:
            result.append([False, str(e)])
        return result


    @util.api()
    def getEaseFactors(self, cards):
        easeFactors = []
        for card in cards:
            try:
                ankiCard = self.getCard(card)
            except NotFoundError:
                easeFactors.append(None)
                continue

            easeFactors.append(ankiCard.factor)

        return easeFactors


    @util.api()
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


    @util.api()
    def unsuspend(self, cards):
        self.suspend(cards, False)


    @util.api()
    def suspended(self, card):
        card = self.getCard(card)
        return card.queue == -1


    @util.api()
    def areSuspended(self, cards):
        suspended = []
        for card in cards:
            try:
                suspended.append(self.suspended(card))
            except NotFoundError:
                suspended.append(None)

        return suspended


    @util.api()
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
                    due.append(date - ivl <= time.time())

        return due


    @util.api()
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



    @util.api()
    def modelNames(self):
        return self.collection().models.allNames()


    @util.api()
    def createModel(self, modelName, inOrderFields, cardTemplates, css = None, isCloze = False):
        # https://github.com/dae/anki/blob/b06b70f7214fb1f2ce33ba06d2b095384b81f874/anki/stdmodels.py
        if len(inOrderFields) == 0:
            raise Exception('Must provide at least one field for inOrderFields')
        if len(cardTemplates) == 0:
            raise Exception('Must provide at least one card for cardTemplates')
        if modelName in self.collection().models.allNames():
            raise Exception('Model name already exists')

        collection = self.collection()
        mm = collection.models

        # Generate new Note
        m = mm.new(modelName)
        if isCloze:
            m['type'] = MODEL_CLOZE

        # Create fields and add them to Note
        for field in inOrderFields:
            fm = mm.newField(field)
            mm.addField(m, fm)

        # Add shared css to model if exists. Use default otherwise
        if (css is not None):
            m['css'] = css

        # Generate new card template(s)
        cardCount = 1
        for card in cardTemplates:
            cardName = 'Card ' + str(cardCount)
            if 'Name' in card:
                cardName = card['Name']

            t = mm.newTemplate(cardName)
            cardCount += 1
            t['qfmt'] = card['Front']
            t['afmt'] = card['Back']
            mm.addTemplate(m, t)

        mm.add(m)
        return m


    @util.api()
    def modelNamesAndIds(self):
        models = {}
        for model in self.modelNames():
            models[model] = int(self.collection().models.byName(model)['id'])

        return models


    @util.api()
    def modelNameFromId(self, modelId):
        model = self.collection().models.get(modelId)
        if model is None:
            raise Exception('model was not found: {}'.format(modelId))
        else:
            return model['name']


    @util.api()
    def modelFieldNames(self, modelName):
        model = self.collection().models.byName(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))
        else:
            return [field['name'] for field in model['flds']]


    @util.api()
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


    @util.api()
    def modelTemplates(self, modelName):
        model = self.collection().models.byName(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))

        templates = {}
        for template in model['tmpls']:
            templates[template['name']] = {'Front': template['qfmt'], 'Back': template['afmt']}

        return templates


    @util.api()
    def modelStyling(self, modelName):
        model = self.collection().models.byName(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))

        return {'css': model['css']}


    @util.api()
    def updateModelTemplates(self, model):
        models = self.collection().models
        ankiModel = models.byName(model['name'])
        if ankiModel is None:
            raise Exception('model was not found: {}'.format(model['name']))

        templates = model['templates']
        for ankiTemplate in ankiModel['tmpls']:
            template = templates.get(ankiTemplate['name'])
            if template:
                qfmt = template.get('Front')
                if qfmt:
                    ankiTemplate['qfmt'] = qfmt

                afmt = template.get('Back')
                if afmt:
                    ankiTemplate['afmt'] = afmt

        self.save_model(models, ankiModel)


    @util.api()
    def updateModelStyling(self, model):
        models = self.collection().models
        ankiModel = models.byName(model['name'])
        if ankiModel is None:
            raise Exception('model was not found: {}'.format(model['name']))

        ankiModel['css'] = model['css']

        self.save_model(models, ankiModel)


    @util.api()
    def findAndReplaceInModels(self, modelName, findText, replaceText, front=True, back=True, css=True):
        if not modelName:
            ankiModel = self.collection().models.allNames()
        else:
            model = self.collection().models.byName(modelName)
            if model is None:
                raise Exception('model was not found: {}'.format(modelName))
            ankiModel = [modelName]
        updatedModels = 0
        for model in ankiModel:
            model = self.collection().models.byName(model)
            checkForText = False
            if css and findText in model['css']:
                checkForText = True
                model['css'] = model['css'].replace(findText, replaceText)
            for tmpls in model.get('tmpls'):
                if front and findText in tmpls['qfmt']:
                    checkForText = True
                    tmpls['qfmt'] = tmpls['qfmt'].replace(findText, replaceText)
                if back and findText in tmpls['afmt']:
                    checkForText = True
                    tmpls['afmt'] = tmpls['afmt'].replace(findText, replaceText)
            self.save_model(self.collection().models, model)
            if checkForText:
                updatedModels += 1
        return updatedModels


    @util.api()
    def modelFieldRename(self, modelName, oldFieldName, newFieldName):
        mm = self.collection().models
        model = mm.byName(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))

        fieldMap = mm.fieldMap(model)
        if oldFieldName not in fieldMap:
            raise Exception('field was not found in {}: {}'.format(modelName, oldFieldName))
        field = fieldMap[oldFieldName][1]

        mm.renameField(model, field, newFieldName)

        self.save_model(mm, model)


    @util.api()
    def modelFieldReposition(self, modelName, fieldName, index):
        mm = self.collection().models
        model = mm.byName(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))

        fieldMap = mm.fieldMap(model)
        if fieldName not in fieldMap:
            raise Exception('field was not found in {}: {}'.format(modelName, fieldName))
        field = fieldMap[fieldName][1]

        mm.repositionField(model, field, index)

        self.save_model(mm, model)


    @util.api()
    def modelFieldAdd(self, modelName, fieldName, index=None):
        mm = self.collection().models
        model = mm.byName(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))

        # only adds the field if it doesn't already exist
        fieldMap = mm.fieldMap(model)
        if fieldName not in fieldMap:
            field = mm.newField(fieldName)
            mm.addField(model, field)

        # repositions, even if the field already exists
        if index is not None:
            fieldMap = mm.fieldMap(model)
            newField = fieldMap[fieldName][1]
            mm.repositionField(model, newField, index)

        self.save_model(mm, model)


    @util.api()
    def modelFieldRemove(self, modelName, fieldName):
        mm = self.collection().models
        model = mm.byName(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))

        fieldMap = mm.fieldMap(model)
        if fieldName not in fieldMap:
            raise Exception('field was not found in {}: {}'.format(modelName, fieldName))
        field = fieldMap[fieldName][1]

        mm.removeField(model, field)

        self.save_model(mm, model)


    @util.api()
    def deckNameFromId(self, deckId):
        deck = self.collection().decks.get(deckId)
        if deck is None:
            raise Exception('deck was not found: {}'.format(deckId))

        return deck['name']


    @util.api()
    def findNotes(self, query=None):
        if query is None:
            return []

        return list(map(int, self.collection().findNotes(query)))


    @util.api()
    def findCards(self, query=None):
        if query is None:
            return []

        return list(map(int, self.collection().findCards(query)))


    @util.api()
    def cardsInfo(self, cards):
        result = []
        for cid in cards:
            try:
                card = self.getCard(cid)
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
                    'question': util.cardQuestion(card),
                    'answer': util.cardAnswer(card),
                    'modelName': model['name'],
                    'ord': card.ord,
                    'deckName': self.deckNameFromId(card.did),
                    'css': model['css'],
                    'factor': card.factor,
                    #This factor is 10 times the ease percentage,
                    # so an ease of 310% would be reported as 3100
                    'interval': card.ivl,
                    'note': card.nid,
                    'type': card.type,
                    'queue': card.queue,
                    'due': card.due,
                    'reps': card.reps,
                    'lapses': card.lapses,
                    'left': card.left,
                    'mod': card.mod,
                })
            except NotFoundError:
                # Anki will give a NotFoundError if the card ID does not exist.
                # Best behavior is probably to add an 'empty card' to the
                # returned result, so that the items of the input and return
                # lists correspond.
                result.append({})

        return result

    @util.api()
    def cardsModTime(self, cards):
        result = []
        for cid in cards:
            try:
                card = self.getCard(cid)
                result.append({
                    'cardId': card.id,
                    'mod': card.mod,
                })
            except NotFoundError:
                # Anki will give a NotFoundError if the card ID does not exist.
                # Best behavior is probably to add an 'empty card' to the
                # returned result, so that the items of the input and return
                # lists correspond.
                result.append({})
        return result


    @util.api()
    def forgetCards(self, cards):
        self.startEditing()
        scids = anki.utils.ids2str(cards)
        self.collection().db.execute('update cards set type=0, queue=0, left=0, ivl=0, due=0, odue=0, factor=0 where id in ' + scids)
        self.stopEditing()


    @util.api()
    def relearnCards(self, cards):
        self.startEditing()
        scids = anki.utils.ids2str(cards)
        self.collection().db.execute('update cards set type=3, queue=1 where id in ' + scids)
        self.stopEditing()


    @util.api()
    def cardReviews(self, deck, startID):
        return self.database().all(
            'select id, cid, usn, ease, ivl, lastIvl, factor, time, type from revlog ''where id>? and cid in (select id from cards where did=?)',
            startID,
            self.decks().id(deck)
        )


    @util.api()
    def reloadCollection(self):
        self.collection().reset()


    @util.api()
    def getLatestReviewID(self, deck):
        return self.database().scalar(
            'select max(id) from revlog where cid in (select id from cards where did=?)',
            self.decks().id(deck)
        ) or 0


    @util.api()
    def insertReviews(self, reviews):
        if len(reviews) > 0:
            sql = 'insert into revlog(id,cid,usn,ease,ivl,lastIvl,factor,time,type) values '
            for row in reviews:
                sql += '(%s),' % ','.join(map(str, row))
            sql = sql[:-1]
            self.database().execute(sql)


    @util.api()
    def notesInfo(self, notes):
        result = []
        for nid in notes:
            try:
                note = self.getNote(nid)
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
            except NotFoundError:
                # Anki will give a NotFoundError if the note ID does not exist.
                # Best behavior is probably to add an 'empty card' to the
                # returned result, so that the items of the input and return
                # lists correspond.
                result.append({})

        return result


    @util.api()
    def deleteNotes(self, notes):
        try:
            self.collection().remNotes(notes)
        finally:
            self.stopEditing()


    @util.api()
    def removeEmptyNotes(self):
        for model in self.collection().models.all():
            if self.collection().models.useCount(model) == 0:
                self.collection().models.rem(model)
        self.window().requireReset()


    @util.api()
    def cardsToNotes(self, cards):
        return self.collection().db.list('select distinct nid from cards where id in ' + anki.utils.ids2str(cards))


    @util.api()
    def guiBrowse(self, query=None):
        browser = aqt.dialogs.open('Browser', self.window())
        browser.activateWindow()

        if query is not None:
            browser.form.searchEdit.lineEdit().setText(query)
            if hasattr(browser, 'onSearch'):
                browser.onSearch()
            else:
                browser.onSearchActivated()

        return self.findCards(query)


    @util.api()
    def guiEditNote(self, note):
        Edit.open_dialog_and_show_note_with_id(note)


    @util.api()
    def guiSelectedNotes(self):
        (creator, instance) = aqt.dialogs._dialogs['Browser']
        if instance is None:
            return []
        return instance.selectedNotes()

    @util.api()
    def guiAddCards(self, note=None):
        if note is not None:
            collection = self.collection()

            deck = collection.decks.byName(note['deckName'])
            if deck is None:
                raise Exception('deck was not found: {}'.format(note['deckName']))

            collection.decks.select(deck['id'])
            savedMid = deck.pop('mid', None)

            model = collection.models.byName(note['modelName'])
            if model is None:
                raise Exception('model was not found: {}'.format(note['modelName']))

            collection.models.setCurrent(model)
            collection.models.update(model)

            ankiNote = anki.notes.Note(collection, model)

            # fill out card beforehand, so we can be sure of the note id
            if 'fields' in note:
                for name, value in note['fields'].items():
                    if name in ankiNote:
                        ankiNote[name] = value

            self.addMediaFromNote(ankiNote, note)

            if 'tags' in note:
                ankiNote.tags = note['tags']

            def openNewWindow():
                nonlocal ankiNote

                addCards = aqt.dialogs.open('AddCards', self.window())

                if savedMid:
                    deck['mid'] = savedMid

                addCards.editor.set_note(ankiNote)

                addCards.activateWindow()

                aqt.dialogs.open('AddCards', self.window())
                addCards.setAndFocusNote(addCards.editor.note)

            currentWindow = aqt.dialogs._dialogs['AddCards'][1]

            if currentWindow is not None:
                currentWindow.closeWithCallback(openNewWindow)
            else:
                openNewWindow()

            return ankiNote.id

        else:
            addCards = aqt.dialogs.open('AddCards', self.window())
            addCards.activateWindow()

            return addCards.editor.note.id


    @util.api()
    def guiReviewActive(self):
        return self.reviewer().card is not None and self.window().state == 'review'


    @util.api()
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

        buttonList = reviewer._answerButtonList()
        return {
            'cardId': card.id,
            'fields': fields,
            'fieldOrder': card.ord,
            'question': util.cardQuestion(card),
            'answer': util.cardAnswer(card),
            'buttons': [b[0] for b in buttonList],
            'nextReviews': [reviewer.mw.col.sched.nextIvlStr(reviewer.card, b[0], True) for b in buttonList],
            'modelName': model['name'],
            'deckName': self.deckNameFromId(card.did),
            'css': model['css'],
            'template': card.template()['name']
        }


    @util.api()
    def guiStartCardTimer(self):
        if not self.guiReviewActive():
            return False

        card = self.reviewer().card
        if card is not None:
            card.startTimer()
            return True

        return False


    @util.api()
    def guiShowQuestion(self):
        if self.guiReviewActive():
            self.reviewer()._showQuestion()
            return True

        return False


    @util.api()
    def guiShowAnswer(self):
        if self.guiReviewActive():
            self.window().reviewer._showAnswer()
            return True

        return False


    @util.api()
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


    @util.api()
    def guiDeckOverview(self, name):
        collection = self.collection()
        if collection is not None:
            deck = collection.decks.byName(name)
            if deck is not None:
                collection.decks.select(deck['id'])
                self.window().onOverview()
                return True

        return False


    @util.api()
    def guiDeckBrowser(self):
        self.window().moveToState('deckBrowser')


    @util.api()
    def guiDeckReview(self, name):
        if self.guiDeckOverview(name):
            self.window().moveToState('review')
            return True

        return False


    @util.api()
    def guiExitAnki(self):
        timer = QTimer()
        timer.timeout.connect(self.window().close)
        timer.start(1000) # 1s should be enough to allow the response to be sent.


    @util.api()
    def guiCheckDatabase(self):
        self.window().onCheckDB()
        return True


    @util.api()
    def addNotes(self, notes):
        results = []
        for note in notes:
            try:
                results.append(self.addNote(note))
            except:
                results.append(None)

        return results


    @util.api()
    def canAddNotes(self, notes):
        results = []
        for note in notes:
            results.append(self.canAddNote(note))

        return results


    @util.api()
    def exportPackage(self, deck, path, includeSched=False):
        collection = self.collection()
        if collection is not None:
            deck = collection.decks.byName(deck)
            if deck is not None:
                exporter = AnkiPackageExporter(collection)
                exporter.did = deck['id']
                exporter.includeSched = includeSched
                exporter.exportInto(path)
                return True

        return False


    @util.api()
    def importPackage(self, path):
        collection = self.collection()
        if collection is not None:
            try:
                self.startEditing()
                importer = AnkiPackageImporter(collection, path)
                importer.run()
            except:
                self.stopEditing()
                raise
            else:
                self.stopEditing()
                return True

        return False


    @util.api()
    def apiReflect(self, scopes=None, actions=None):
        if not isinstance(scopes, list):
            raise Exception('scopes has invalid value')
        if not (actions is None or isinstance(actions, list)):
            raise Exception('actions has invalid value')

        cls = type(self)
        scopes2 = []
        result = {'scopes': scopes2}

        if 'actions' in scopes:
            if actions is None:
                actions = dir(cls)

            methodNames = []
            for methodName in actions:
                if not isinstance(methodName, str):
                    pass
                method = getattr(cls, methodName, None)
                if method is not None and getattr(method, 'api', False):
                    methodNames.append(methodName)

            scopes2.append('actions')
            result['actions'] = methodNames

        return result


#
# Entry
#

# when run inside Anki, `__name__` would be either numeric,
# or, if installed via `link.sh`, `AnkiConnectDev`
if __name__ != "plugin":
    if platform.system() == "Windows" and anki_version == (2, 1, 50):
        util.patch_anki_2_1_50_having_null_stdout_on_windows()

    Edit.register_with_anki()

    ac = AnkiConnect()
    ac.initLogging()
    ac.startWebServer()

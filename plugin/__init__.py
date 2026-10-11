# Copyright 2016-2026 Alex Yatskov
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

required_anki_version = (26, 8, 0)
VERSION_SUFFIXES = ["b", "rc"]

version_string = aqt.appVersion
for suffix in VERSION_SUFFIXES:
    version_string = version_string.replace(suffix, ".")
anki_version = tuple(int(segment) for segment in version_string.split(".") if segment)

# Append to tuple when versions have different number of segments (ie. 25.07 vs 25.07.0)
anki_version += (0,) * (len(required_anki_version) - len(anki_version))
required_anki_version += (0,) * (len(anki_version) - len(required_anki_version))
if anki_version < required_anki_version:
    raise Exception(f"Minimum Anki version supported: {required_anki_version[0]}.{required_anki_version[1]}.{required_anki_version[2]}")

import inspect
import json
from aqt.qt import Qt, QTimer, QMessageBox, QCheckBox
from . import util, web
from .edit import Edit
from .legacy import Legacy, Accepted
from .runtime import Runtime
from .contract import SCHEMA, LEGACY_TARGETS
from .protocol import Deferred, completed
from .web import format_success_reply, format_exception_reply


class AnkiConnect:
    """Compatibility facade; all actions translate to shared API services."""
    def __init__(self):
        self.log = None
        self.timer = None
        self.runtime = Runtime(self)
        self.server = web.WebServer(self.handler_async, self.runtime.dispatcher.request)

    def initLogging(self):
        path = util.setting('apiLogPath')
        if path is not None:
            self.log = open(path, 'w')

    def logEvent(self, name, data):
        if self.log:
            self.log.write('[{}]\n'.format(name))
            json.dump(data, self.log, indent=4, sort_keys=True)
            self.log.write('\n\n')
            self.log.flush()

    def startWebServer(self):
        try:
            self.server.listen()
            self.timer = QTimer()
            self.timer.timeout.connect(self.advance)
            self.timer.start(util.setting('apiPollInterval'))
        except Exception as error:
            QMessageBox.critical(self.window(), 'AnkiConnect', str(error))

    def advance(self):
        self.server.advance()
        if self.runtime.exit_requested and not self.server.clients:
            self.runtime.exit_requested = False
            self.window().close()

    def window(self):
        return aqt.mw

    def collection(self):
        return self.runtime.service().col

    def decks(self):
        return self.collection().decks

    def scheduler(self):
        return self.collection().sched

    def database(self):
        return self.collection().db

    def media(self):
        return self.collection().media

    def reviewer(self):
        return self.window().reviewer

    def getNote(self, noteId):
        return self.collection().get_note(noteId)

    def getCard(self, cardId):
        return self.collection().get_card(cardId)

    def getModel(self, modelName):
        return self.runtime.service().resolve({'name': modelName}, 'noteType')

    def legacy_actions(self):
        return [name for name, method in inspect.getmembers(self, inspect.ismethod) if getattr(method, 'api', False)]

    def resolve_action(self, name, version, params):
        for methodName in self.legacy_actions():
            method = getattr(self, methodName)
            aliases = [(v, alias) for v, alias in getattr(method, 'versions', []) if v <= version]
            alias = max(aliases)[1] if aliases else methodName
            if alias == name:
                bound = inspect.signature(method).bind(**params)
                bound.apply_defaults()
                return methodName, dict(bound.arguments)
        raise Exception('unsupported action')

    def guard_legacy(self, name, params):
        gui_action = name.startswith('gui') and name != 'guiExitAnki'
        if (gui_action or name == 'reloadCollection') and getattr(self.window(), '_background_op_count', 0):
            from .protocol import ApiError
            raise ApiError('busy', 'A collection operation is active.')
        if self.runtime.lifecycle_active and name not in ('version', 'requestPermission', 'apiReflect', 'getProfiles', 'getActiveProfile'):
            from .protocol import ApiError
            raise ApiError('busy', 'Collection lifecycle operation is active.')
        converted = dict(params)
        note = params.get('note')
        if isinstance(note, dict):
            converted['id'] = str(note.get('id'))
        elif note is not None:
            converted['id'] = str(note)
        converted['ids'] = [str(id) for id in (params.get('notes') or [converted.get('id')])]
        if name == 'replaceTagsInAllNotes':
            converted['allNotes'] = True
        for target in LEGACY_TARGETS.get(name, []):
            if target in SCHEMA['x-methods'] and SCHEMA['x-methods'][target]['effect'] in ('write', 'advancedWrite'):
                self.runtime.gui.guard(target, converted)

    def legacy(self, name, params):
        self.guard_legacy(name, params)
        service = None
        if name not in ('version', 'requestPermission', 'apiReflect', 'getProfiles', 'getActiveProfile', 'loadProfile', 'sync', 'guiExitAnki'):
            service = self.runtime.service()
        adapter = Legacy(self, service)
        try:
            value = adapter.call(name, params)
            if isinstance(value, Accepted):
                return value.value
            if isinstance(value, Deferred):
                if not value.done:
                    return value
                if value.error:
                    raise value.error
                return value.value
            return value
        finally:
            if service:
                self.runtime.finish_changes(service)

    def handler(self, request):
        version = request.get('version', 4)
        try:
            name = request.get('action', '')
            if name != 'requestPermission' and request.get('key') != util.setting('apiKey'):
                raise Exception('valid api key must be provided')
            name, params = self.resolve_action(name, version, request.get('params', {}))
            value = self.multi(params['actions']) if name == 'multi' else self.legacy(name, params)
            return format_success_reply(version, value)
        except Exception as error:
            return format_exception_reply(version, error)

    def validate_multi(self, actions, depth=0, state=None):
        """Preflight the entire tree before admitting any executable action."""
        if state is None:
            state = {'count': 0, 'exit': False}
        if depth > 16:
            raise Exception('multi nesting limit exceeded')
        if not isinstance(actions, list):
            raise Exception('multi actions must be an array')
        for item in actions:
            state['count'] += 1
            if state['count'] > 100:
                raise Exception('multi action limit exceeded')
            if not isinstance(item, dict):
                raise Exception('multi actions must be request objects')
            name, params = self.resolve_action(item.get('action', ''), item.get('version', 4), item.get('params', {}))
            if name == 'multi':
                self.validate_multi(params['actions'], depth + 1, state)
            else:
                if state['exit']:
                    raise Exception('guiExitAnki must be the last executable multi action')
                state['exit'] = name == 'guiExitAnki'

    def handler_async(self, request, barrier=False, depth=0):
        version = request.get('version', 4)
        try:
            if depth > 16:
                raise Exception('multi nesting limit exceeded')
            name = request.get('action', '')
            if name != 'requestPermission' and request.get('key') != util.setting('apiKey'):
                raise Exception('valid api key must be provided')
            name, params = self.resolve_action(name, version, request.get('params', {}))
            self.guard_legacy(name, params)
            if name == 'multi':
                actions = params['actions']
                if depth == 0:
                    self.validate_multi(actions)
                pending = Deferred()
                results = []
                def step(index):
                    if index == len(actions):
                        pending.resolve(results)
                    else:
                        self.handler_async(actions[index], True, depth + 1).then(lambda source: advance(index, source))
                def advance(index, source):
                    results.append(source.value)
                    self.runtime.schedule(lambda: step(index + 1))
                step(0)
            elif name.startswith('gui') or name in ('version', 'requestPermission', 'apiReflect', 'getProfiles', 'getActiveProfile', 'loadProfile', 'sync', 'reloadCollection'):
                value = Legacy(self).call(name, params)
                def admitted(value):
                    return value.pending.map(value.project) if isinstance(value, Accepted) and barrier else value.value if isinstance(value, Accepted) else value
                pending = value.map(admitted) if isinstance(value, Deferred) else completed(value).map(admitted)
            else:
                pending = self.runtime.background(lambda service: Legacy(self, service).call(name, params))
            reply = Deferred()
            pending.then(lambda source: reply.resolve(format_exception_reply(version, source.error) if source.error else format_success_reply(version, source.value)))
            return reply
        except Exception as error:
            return completed(format_exception_reply(version, error))

    def permission(self, origin, allowed):
        results = {'permission': 'denied'}
        if allowed:
            results = {'permission': 'granted', 'requireApikey': bool(util.setting('apiKey')), 'version': util.setting('apiVersion')}
        elif origin in util.setting('ignoreOriginList'):
            pass
        else:
            msg = QMessageBox(self.window())
            msg.setWindowTitle('A website wants to access to Anki')
            msg.setText('"{}" requests permission to use Anki through AnkiConnect. Do you want to give it access?'.format(origin))
            msg.setInformativeText("By granting permission, you'll allow the website to modify your collection on your behalf, including the execution of destructive actions such as deck deletion.")
            msg.setWindowIcon(self.window().windowIcon())
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg.setDefaultButton(QMessageBox.StandardButton.No)
            msg.setCheckBox(QCheckBox(text='Ignore further requests from "{}"'.format(origin), parent=msg))
            if hasattr(Qt, 'WindowStaysOnTopHint'):
                WindowOnTopFlag = Qt.WindowStaysOnTopHint
            elif hasattr(Qt, 'WindowType') and hasattr(Qt.WindowType, 'WindowStaysOnTopHint'):
                WindowOnTopFlag = Qt.WindowType.WindowStaysOnTopHint
            msg.setWindowFlag(WindowOnTopFlag, True)
            pending = Deferred()
            def chosen(pressedButton):
                try:
                    value = {'permission': 'denied'}
                    if pressedButton == QMessageBox.StandardButton.Yes:
                        config = aqt.mw.addonManager.getConfig(__name__) or {}
                        config['webCorsOriginList'] = list(util.setting('webCorsOriginList'))
                        config['webCorsOriginList'].append(origin)
                        aqt.mw.addonManager.writeConfig(__name__, config)
                        value = {'permission': 'granted', 'requireApikey': bool(util.setting('apiKey')), 'version': util.setting('apiVersion')}
                    elif origin and pressedButton == QMessageBox.StandardButton.No and msg.checkBox().isChecked():
                        config = aqt.mw.addonManager.getConfig(__name__) or {}
                        config['ignoreOriginList'] = list(util.setting('ignoreOriginList'))
                        config['ignoreOriginList'].append(origin)
                        aqt.mw.addonManager.writeConfig(__name__, config)
                    pending.resolve(value)
                except Exception as error:
                    pending.resolve(error=error)
                finally:
                    msg.deleteLater()
            msg.finished.connect(chosen)
            msg.setWindowModality(Qt.WindowModality.ApplicationModal)
            msg.show()
            return pending
        return results

    @util.api()
    def version(self):
        return self.legacy('version', {})

    @util.api()
    def requestPermission(self, origin, allowed):
        return self.legacy('requestPermission', {'origin': origin, 'allowed': allowed})

    @util.api()
    def getProfiles(self):
        return self.legacy('getProfiles', {})

    @util.api()
    def getActiveProfile(self):
        return self.legacy('getActiveProfile', {})

    @util.api()
    def loadProfile(self, name):
        return self.legacy('loadProfile', {'name': name})

    @util.api()
    def sync(self):
        return self.legacy('sync', {})

    @util.api()
    def multi(self, actions):
        return self.legacy('multi', {'actions': actions})

    @util.api()
    def getNumCardsReviewedToday(self):
        return self.legacy('getNumCardsReviewedToday', {})

    @util.api()
    def getNumCardsReviewedByDay(self):
        return self.legacy('getNumCardsReviewedByDay', {})

    @util.api()
    def getCollectionStatsHTML(self, wholeCollection=True):
        return self.legacy('getCollectionStatsHTML', {'wholeCollection': wholeCollection})

    @util.api()
    def deckNames(self):
        return self.legacy('deckNames', {})

    @util.api()
    def deckNamesAndIds(self):
        return self.legacy('deckNamesAndIds', {})

    @util.api()
    def getDecks(self, cards):
        return self.legacy('getDecks', {'cards': cards})

    @util.api()
    def createDeck(self, deck):
        return self.legacy('createDeck', {'deck': deck})

    @util.api()
    def changeDeck(self, cards, deck):
        return self.legacy('changeDeck', {'cards': cards, 'deck': deck})

    @util.api()
    def deleteDecks(self, decks, cardsToo=False):
        return self.legacy('deleteDecks', {'decks': decks, 'cardsToo': cardsToo})

    @util.api()
    def getDeckConfig(self, deck):
        return self.legacy('getDeckConfig', {'deck': deck})

    @util.api()
    def saveDeckConfig(self, config):
        return self.legacy('saveDeckConfig', {'config': config})

    @util.api()
    def setDeckConfigId(self, decks, configId):
        return self.legacy('setDeckConfigId', {'decks': decks, 'configId': configId})

    @util.api()
    def cloneDeckConfigId(self, name, cloneFrom='1'):
        return self.legacy('cloneDeckConfigId', {'name': name, 'cloneFrom': cloneFrom})

    @util.api()
    def removeDeckConfigId(self, configId):
        return self.legacy('removeDeckConfigId', {'configId': configId})

    @util.api()
    def getDeckStats(self, decks):
        return self.legacy('getDeckStats', {'decks': decks})

    @util.api()
    def storeMediaFile(self, filename, data=None, path=None, url=None, skipHash=None, deleteExisting=True):
        return self.legacy('storeMediaFile', {'filename': filename, 'data': data, 'path': path, 'url': url, 'skipHash': skipHash, 'deleteExisting': deleteExisting})

    @util.api()
    def retrieveMediaFile(self, filename):
        return self.legacy('retrieveMediaFile', {'filename': filename})

    @util.api()
    def getMediaFilesNames(self, pattern='*'):
        return self.legacy('getMediaFilesNames', {'pattern': pattern})

    @util.api()
    def deleteMediaFile(self, filename):
        return self.legacy('deleteMediaFile', {'filename': filename})

    @util.api()
    def getMediaDirPath(self):
        return self.legacy('getMediaDirPath', {})

    @util.api()
    def addNote(self, note):
        return self.legacy('addNote', {'note': note})

    @util.api()
    def canAddNote(self, note):
        return self.legacy('canAddNote', {'note': note})

    @util.api()
    def canAddNoteWithErrorDetail(self, note):
        return self.legacy('canAddNoteWithErrorDetail', {'note': note})

    @util.api()
    def updateNoteFields(self, note):
        return self.legacy('updateNoteFields', {'note': note})

    @util.api()
    def updateNote(self, note):
        return self.legacy('updateNote', {'note': note})

    @util.api()
    def updateNoteModel(self, note):
        return self.legacy('updateNoteModel', {'note': note})

    @util.api()
    def updateNoteTags(self, note, tags):
        return self.legacy('updateNoteTags', {'note': note, 'tags': tags})

    @util.api()
    def getNoteTags(self, note):
        return self.legacy('getNoteTags', {'note': note})

    @util.api()
    def addTags(self, notes, tags, add=True):
        return self.legacy('addTags', {'notes': notes, 'tags': tags, 'add': add})

    @util.api()
    def removeTags(self, notes, tags):
        return self.legacy('removeTags', {'notes': notes, 'tags': tags})

    @util.api()
    def getTags(self):
        return self.legacy('getTags', {})

    @util.api()
    def clearUnusedTags(self):
        return self.legacy('clearUnusedTags', {})

    @util.api()
    def replaceTags(self, notes, tag_to_replace, replace_with_tag):
        return self.legacy('replaceTags', {'notes': notes, 'tag_to_replace': tag_to_replace, 'replace_with_tag': replace_with_tag})

    @util.api()
    def replaceTagsInAllNotes(self, tag_to_replace, replace_with_tag):
        return self.legacy('replaceTagsInAllNotes', {'tag_to_replace': tag_to_replace, 'replace_with_tag': replace_with_tag})

    @util.api()
    def setEaseFactors(self, cards, easeFactors):
        return self.legacy('setEaseFactors', {'cards': cards, 'easeFactors': easeFactors})

    @util.api()
    def setSpecificValueOfCard(self, card, keys, newValues, warning_check=False):
        return self.legacy('setSpecificValueOfCard', {'card': card, 'keys': keys, 'newValues': newValues, 'warning_check': warning_check})

    @util.api()
    def getEaseFactors(self, cards):
        return self.legacy('getEaseFactors', {'cards': cards})

    @util.api()
    def suspend(self, cards, suspend=True):
        return self.legacy('suspend', {'cards': cards, 'suspend': suspend})

    @util.api()
    def unsuspend(self, cards):
        return self.legacy('unsuspend', {'cards': cards})

    @util.api()
    def suspended(self, card):
        return self.legacy('suspended', {'card': card})

    @util.api()
    def areSuspended(self, cards):
        return self.legacy('areSuspended', {'cards': cards})

    @util.api()
    def areDue(self, cards):
        return self.legacy('areDue', {'cards': cards})

    @util.api()
    def getIntervals(self, cards, complete=False):
        return self.legacy('getIntervals', {'cards': cards, 'complete': complete})

    @util.api()
    def modelNames(self):
        return self.legacy('modelNames', {})

    @util.api()
    def createModel(self, modelName, inOrderFields, cardTemplates, css=None, isCloze=False):
        return self.legacy('createModel', {'modelName': modelName, 'inOrderFields': inOrderFields, 'cardTemplates': cardTemplates, 'css': css, 'isCloze': isCloze})

    @util.api()
    def modelNamesAndIds(self):
        return self.legacy('modelNamesAndIds', {})

    @util.api()
    def findModelsById(self, modelIds):
        return self.legacy('findModelsById', {'modelIds': modelIds})

    @util.api()
    def findModelsByName(self, modelNames):
        return self.legacy('findModelsByName', {'modelNames': modelNames})

    @util.api()
    def modelNameFromId(self, modelId):
        return self.legacy('modelNameFromId', {'modelId': modelId})

    @util.api()
    def modelFieldNames(self, modelName):
        return self.legacy('modelFieldNames', {'modelName': modelName})

    @util.api()
    def modelFieldDescriptions(self, modelName):
        return self.legacy('modelFieldDescriptions', {'modelName': modelName})

    @util.api()
    def modelFieldFonts(self, modelName):
        return self.legacy('modelFieldFonts', {'modelName': modelName})

    @util.api()
    def modelFieldsOnTemplates(self, modelName):
        return self.legacy('modelFieldsOnTemplates', {'modelName': modelName})

    @util.api()
    def modelTemplates(self, modelName):
        return self.legacy('modelTemplates', {'modelName': modelName})

    @util.api()
    def modelStyling(self, modelName):
        return self.legacy('modelStyling', {'modelName': modelName})

    @util.api()
    def updateModelTemplates(self, model):
        return self.legacy('updateModelTemplates', {'model': model})

    @util.api()
    def updateModelStyling(self, model):
        return self.legacy('updateModelStyling', {'model': model})

    @util.api()
    def findAndReplaceInModels(self, modelName, findText, replaceText, front=True, back=True, css=True):
        return self.legacy('findAndReplaceInModels', {'modelName': modelName, 'findText': findText, 'replaceText': replaceText, 'front': front, 'back': back, 'css': css})

    @util.api()
    def modelTemplateRename(self, modelName, oldTemplateName, newTemplateName):
        return self.legacy('modelTemplateRename', {'modelName': modelName, 'oldTemplateName': oldTemplateName, 'newTemplateName': newTemplateName})

    @util.api()
    def modelTemplateReposition(self, modelName, templateName, index):
        return self.legacy('modelTemplateReposition', {'modelName': modelName, 'templateName': templateName, 'index': index})

    @util.api()
    def modelTemplateAdd(self, modelName, template):
        return self.legacy('modelTemplateAdd', {'modelName': modelName, 'template': template})

    @util.api()
    def modelTemplateRemove(self, modelName, templateName):
        return self.legacy('modelTemplateRemove', {'modelName': modelName, 'templateName': templateName})

    @util.api()
    def modelFieldRename(self, modelName, oldFieldName, newFieldName):
        return self.legacy('modelFieldRename', {'modelName': modelName, 'oldFieldName': oldFieldName, 'newFieldName': newFieldName})

    @util.api()
    def modelFieldReposition(self, modelName, fieldName, index):
        return self.legacy('modelFieldReposition', {'modelName': modelName, 'fieldName': fieldName, 'index': index})

    @util.api()
    def modelFieldAdd(self, modelName, fieldName, index=None):
        return self.legacy('modelFieldAdd', {'modelName': modelName, 'fieldName': fieldName, 'index': index})

    @util.api()
    def modelFieldRemove(self, modelName, fieldName):
        return self.legacy('modelFieldRemove', {'modelName': modelName, 'fieldName': fieldName})

    @util.api()
    def modelFieldSetFont(self, modelName, fieldName, font):
        return self.legacy('modelFieldSetFont', {'modelName': modelName, 'fieldName': fieldName, 'font': font})

    @util.api()
    def modelFieldSetFontSize(self, modelName, fieldName, fontSize):
        return self.legacy('modelFieldSetFontSize', {'modelName': modelName, 'fieldName': fieldName, 'fontSize': fontSize})

    @util.api()
    def modelFieldSetDescription(self, modelName, fieldName, description):
        return self.legacy('modelFieldSetDescription', {'modelName': modelName, 'fieldName': fieldName, 'description': description})

    @util.api()
    def deckNameFromId(self, deckId):
        return self.legacy('deckNameFromId', {'deckId': deckId})

    @util.api()
    def findNotes(self, query=None):
        return self.legacy('findNotes', {'query': query})

    @util.api()
    def findCards(self, query=None):
        return self.legacy('findCards', {'query': query})

    @util.api()
    def cardsInfo(self, cards):
        return self.legacy('cardsInfo', {'cards': cards})

    @util.api()
    def cardsModTime(self, cards):
        return self.legacy('cardsModTime', {'cards': cards})

    @util.api()
    def forgetCards(self, cards):
        return self.legacy('forgetCards', {'cards': cards})

    @util.api()
    def relearnCards(self, cards):
        return self.legacy('relearnCards', {'cards': cards})

    @util.api()
    def answerCards(self, answers):
        return self.legacy('answerCards', {'answers': answers})

    @util.api()
    def cardReviews(self, deck, startID):
        return self.legacy('cardReviews', {'deck': deck, 'startID': startID})

    @util.api()
    def getReviewsOfCards(self, cards):
        return self.legacy('getReviewsOfCards', {'cards': cards})

    @util.api()
    def setDueDate(self, cards, days):
        return self.legacy('setDueDate', {'cards': cards, 'days': days})

    @util.api()
    def reloadCollection(self):
        return self.legacy('reloadCollection', {})

    @util.api()
    def getLatestReviewID(self, deck):
        return self.legacy('getLatestReviewID', {'deck': deck})

    @util.api()
    def insertReviews(self, reviews):
        return self.legacy('insertReviews', {'reviews': reviews})

    @util.api()
    def notesInfo(self, notes=None, query=None):
        return self.legacy('notesInfo', {'notes': notes, 'query': query})

    @util.api()
    def notesModTime(self, notes):
        return self.legacy('notesModTime', {'notes': notes})

    @util.api()
    def deleteNotes(self, notes):
        return self.legacy('deleteNotes', {'notes': notes})

    @util.api()
    def removeEmptyNotes(self):
        return self.legacy('removeEmptyNotes', {})

    @util.api()
    def cardsToNotes(self, cards):
        return self.legacy('cardsToNotes', {'cards': cards})

    @util.api()
    def guiBrowse(self, query=None, reorderCards=None):
        return self.legacy('guiBrowse', {'query': query, 'reorderCards': reorderCards})

    @util.api()
    def guiEditNote(self, note):
        return self.legacy('guiEditNote', {'note': note})

    @util.api()
    def guiSelectNote(self, note):
        return self.legacy('guiSelectNote', {'note': note})

    @util.api()
    def guiSelectCard(self, card):
        return self.legacy('guiSelectCard', {'card': card})

    @util.api()
    def guiSelectedNotes(self):
        return self.legacy('guiSelectedNotes', {})

    @util.api()
    def guiAddNoteSetData(self, note, append=False):
        return self.legacy('guiAddNoteSetData', {'note': note, 'append': append})

    @util.api()
    def guiAddCards(self, note=None):
        return self.legacy('guiAddCards', {'note': note})

    @util.api()
    def guiReviewActive(self):
        return self.legacy('guiReviewActive', {})

    @util.api()
    def guiCurrentCard(self):
        return self.legacy('guiCurrentCard', {})

    @util.api()
    def guiStartCardTimer(self):
        return self.legacy('guiStartCardTimer', {})

    @util.api()
    def guiShowQuestion(self):
        return self.legacy('guiShowQuestion', {})

    @util.api()
    def guiShowAnswer(self):
        return self.legacy('guiShowAnswer', {})

    @util.api()
    def guiAnswerCard(self, ease):
        return self.legacy('guiAnswerCard', {'ease': ease})

    @util.api()
    def guiPlayAudio(self):
        return self.legacy('guiPlayAudio', {})

    @util.api()
    def guiUndo(self):
        return self.legacy('guiUndo', {})

    @util.api()
    def guiDeckOverview(self, name):
        return self.legacy('guiDeckOverview', {'name': name})

    @util.api()
    def guiDeckBrowser(self):
        return self.legacy('guiDeckBrowser', {})

    @util.api()
    def guiDeckReview(self, name):
        return self.legacy('guiDeckReview', {'name': name})

    @util.api()
    def guiImportFile(self, path=None):
        return self.legacy('guiImportFile', {'path': path})

    @util.api()
    def guiExitAnki(self):
        return self.legacy('guiExitAnki', {})

    @util.api()
    def guiCheckDatabase(self):
        return self.legacy('guiCheckDatabase', {})

    @util.api()
    def addNotes(self, notes):
        return self.legacy('addNotes', {'notes': notes})

    @util.api()
    def canAddNotes(self, notes):
        return self.legacy('canAddNotes', {'notes': notes})

    @util.api()
    def canAddNotesWithErrorDetail(self, notes):
        return self.legacy('canAddNotesWithErrorDetail', {'notes': notes})

    @util.api()
    def exportPackage(self, deck, path, includeSched=False):
        return self.legacy('exportPackage', {'deck': deck, 'path': path, 'includeSched': includeSched})

    @util.api()
    def importPackage(self, path):
        return self.legacy('importPackage', {'path': path})

    @util.api()
    def apiReflect(self, scopes=None, actions=None):
        return self.legacy('apiReflect', {'scopes': scopes, 'actions': actions})

if __name__ != "plugin":
    Edit.register_with_anki()
    ac = AnkiConnect()
    ac.runtime.register_hooks()
    ac.initLogging()
    ac.startWebServer()

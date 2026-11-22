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

required_anki_version = (2, 1, 15)
VERSION_SUFFIXES = ["b", "rc"]


def parse_anki_version(version):
    # Ignore local version labels used by forks, such as "26.09.4+fsrs7".
    version_string = version.split("+")[0]
    for suffix in VERSION_SUFFIXES:
        version_string = version_string.replace(suffix, ".")
    return tuple(int(segment) for segment in version_string.split(".") if segment)


anki_version = parse_anki_version(aqt.appVersion)

# Append to tuple when versions have different number of segments (ie. 25.07 vs 25.07.0)
anki_version += (0,) * (len(required_anki_version) - len(anki_version))
required_anki_version += (0,) * (len(anki_version) - len(required_anki_version))
if anki_version < required_anki_version:
    raise Exception(f"Minimum Anki version supported: {required_anki_version[0]}.{required_anki_version[1]}.{required_anki_version[2]}")

import inspect
import json
import time
from aqt.qt import Qt, QTimer, QMessageBox, QCheckBox
from . import compat, util, web
compat.install_backports()
from .legacy import Legacy, Accepted, legacy_request
from .runtime import Runtime
from .contract import SCHEMA, LEGACY_TARGETS
from .protocol import Deferred, completed
from .web import format_success_reply, format_exception_reply

macos_helper = compat.macos_helper()
Edit = None
if compat.editor_dialog_available():
    from .edit import Edit


# Legacy clients update note types on every sync, often while their own Browser
# preview is open. Once open editors save, these writes leave nothing an editor
# could overwrite: Anki itself permits template, styling, and card edits then.
LEGACY_EDITOR_SAFE = frozenset((
    'createModel', 'findAndReplaceInModels', 'updateModelStyling', 'updateModelTemplates',
    'modelTemplateAdd', 'modelTemplateRemove', 'modelTemplateRename', 'modelTemplateReposition',
    'modelFieldSetDescription', 'modelFieldSetFont', 'modelFieldSetFontSize',
    'setEaseFactors', 'setSpecificValueOfCard', 'insertReviews', 'removeEmptyNotes'))
# Legacy actions wait this long for active collection work before failing busy.
LEGACY_WAIT_SECONDS = 30
LEGACY_LIFECYCLE_EXEMPT = ('version', 'requestPermission', 'apiReflect', 'getProfiles', 'getActiveProfile')
# Field edits change the shape of every note of a type; only its editors conflict.
LEGACY_FIELD_EDITS = frozenset(('modelFieldAdd', 'modelFieldRemove', 'modelFieldRename', 'modelFieldReposition'))
# Lifecycle actions start on a later tick; legacy admission is reserved until they finish.
LEGACY_LIFECYCLE = ('sync', 'loadProfile')
LEGACY_DIRECT = ('version', 'requestPermission', 'apiReflect', 'getProfiles', 'getActiveProfile', 'loadProfile', 'sync', 'reloadCollection')


class AnkiConnect:
    """Compatibility facade; all actions translate to shared API services."""
    def __init__(self):
        self.log = None
        self.timer = None
        self.lifecycle_reserved = 0
        self.runtime = Runtime(self)
        self.server = web.WebServer(self.handler_async, self.runtime.dispatcher.request)

    def initLogging(self):
        path = util.setting('apiLogPath')
        if path is not None:
            self.log = open(path, 'w')

    def logEvent(self, name, data):
        if self.log:
            # Logging must never interrupt the reply callbacks that follow it.
            try:
                self.log.write('[{}]\n{}\n\n'.format(name, json.dumps(data, indent=4, sort_keys=True, default=str)))
                self.log.flush()
            except Exception as error:
                print('AnkiConnect: failed to log {}: {}'.format(name, error))

    def startWebServer(self):
        try:
            self.server.listen()
            self.timer = QTimer()
            self.timer.timeout.connect(self.advance)
            self.timer.start(util.setting('apiPollInterval'))
        except Exception as error:
            QMessageBox.critical(self.window(), 'AnkiConnect', str(error))
            return

        if macos_helper is not None:
            try:
                # Anki's helper retains the activity token until process exit.
                macos_helper.disable_appnap()
            except Exception as error:
                print('AnkiConnect: failed to disable App Nap: {}'.format(error))

    def advance(self):
        self.server.advance()
        if self.runtime.exit_requested and not self.server.clients:
            self.runtime.exit_requested = False
            self.window().close()

    def window(self):
        return aqt.mw

    def reviewer(self):
        return self.window().reviewer

    def legacy_actions(self):
        return [name for name, method in inspect.getmembers(self, inspect.ismethod) if getattr(method, 'api', False)]

    def resolve_action(self, name, params):
        method = getattr(self, name, None) if isinstance(name, str) else None
        if not getattr(method, 'api', False):
            raise Exception('unsupported action')
        signature = inspect.signature(method)
        # Clients often reuse parameter objects across actions. Ignore
        # surplus keys, while preserving the binder's missing-argument errors.
        params = {key: value for key, value in params.items() if key in signature.parameters}
        for key, parameter in signature.parameters.items():
            if params.get(key) is None and parameter.default is not inspect.Parameter.empty:
                params.pop(key, None)
        try:
            bound = signature.bind(**params)
        except TypeError:
            # The declaration's own binder retains the historical public error.
            try:
                method(**params)
            except TypeError as error:
                raise compat.binding_error(error, method) from None
            raise
        bound.apply_defaults()
        return name, Legacy.normalize_params(name, dict(bound.arguments))

    @staticmethod
    def waits_for_collection_work(name):
        return (name.startswith('gui') and name != 'guiExitAnki') or name == 'reloadCollection'

    def lifecycle_busy(self, name):
        return (self.runtime.lifecycle_active or self.lifecycle_reserved > 0) and name not in LEGACY_LIFECYCLE_EXEMPT

    def legacy_busy(self, name):
        if self.lifecycle_busy(name):
            return True
        return self.waits_for_collection_work(name) and bool(compat.background_op_count(self.window()))

    @staticmethod
    def legacy_writes(name):
        return any(target in SCHEMA['x-methods'] and SCHEMA['x-methods'][target]['effect'] in ('write', 'advancedWrite')
                   for target in LEGACY_TARGETS.get(name, []))

    def save_open_editors(self):
        """Commit pending editor input before a write's change notification
        makes open editors reload their notes from the collection."""
        editors = [dialog.editor for _, dialog in aqt.dialogs._dialogs.values()
                   if dialog is not None and compat.saves_editor(getattr(dialog, 'editor', None))]
        if not editors:
            return None
        pending = Deferred()
        remaining = [len(editors)]
        deadline = time.monotonic() + LEGACY_WAIT_SECONDS
        def settled():
            # From 2.1.45 editors write typed fields through a background update_note op.
            return remaining[0] == 0 and not compat.background_op_count(self.window())
        def saved():
            remaining[0] -= 1
            if settled():
                pending.resolve(None)
        def check():
            if pending.done:
                return
            if settled():
                pending.resolve(None)
            elif time.monotonic() < deadline:
                self.runtime.schedule_later(check)
            else:
                from .protocol import ApiError
                pending.resolve(error=ApiError('busy', 'An open editor did not save its note.'))
        for editor in editors:
            compat.editor_save(editor, saved, keepFocus=True)
        if not pending.done:
            self.runtime.schedule_later(check)
        return pending

    def guard_legacy(self, name, params):
        if self.waits_for_collection_work(name) and compat.background_op_count(self.window()):
            from .protocol import ApiError
            raise ApiError('busy', 'A collection operation is active.')
        if self.lifecycle_busy(name):
            from .protocol import ApiError
            raise ApiError('busy', 'Collection lifecycle operation is active.')
        # Editors are guarded by the existing note IDs a write names; new note objects have none.
        note = params.get('note')
        notes = params.get('notes')
        ids = [str(id) for id in notes if not isinstance(id, dict)] if isinstance(notes, list) else []
        note_id = note.get('id') if isinstance(note, dict) else note
        if note_id is not None:
            ids.append(str(note_id))
        converted = {'ids': ids, 'allNotes': name == 'replaceTagsInAllNotes'}
        if name in LEGACY_EDITOR_SAFE:
            return
        if name in LEGACY_FIELD_EDITS:
            self.runtime.gui.guard_note_type(params.get('modelName'))
            return
        for target in LEGACY_TARGETS.get(name, []):
            if target in SCHEMA['x-methods'] and SCHEMA['x-methods'][target]['effect'] in ('write', 'advancedWrite'):
                # Legacy writes save open editors first; see save_open_editors.
                self.runtime.gui.guard(target, converted, saved=True)

    def validate_multi(self, actions, depth=0, state=None):
        """Preflight the entire tree before admitting any executable action."""
        if state is None:
            state = {'exit': False}
        if depth > 16:
            raise Exception('multi nesting limit exceeded')
        if not isinstance(actions, list):
            raise Exception('multi actions must be an array')
        # Legacy clients batch whole vaults; v1's item limit does not apply here.
        for item in actions:
            if not isinstance(item, dict):
                raise Exception('multi actions must be request objects')
            try:
                item = legacy_request(item)
                name, params = self.resolve_action(item.get('action', ''), item.get('params', {}))
            except Exception:
                # Invalid actions have their own error slot and cannot execute.
                continue
            if name == 'multi':
                self.validate_multi(params['actions'], depth + 1, state)
            else:
                if state['exit']:
                    raise Exception('guiExitAnki must be the last executable multi action')
                state['exit'] = name == 'guiExitAnki'

    def handler_async(self, request, barrier=False, depth=0):
        if self.log:
            self.logEvent('request', {**request, 'key': '***'} if isinstance(request, dict) and 'key' in request else request)
        reply = self.dispatch_legacy(request, barrier, depth)
        if self.log:
            reply.then(lambda source: self.logEvent('reply', source.value))
        return reply

    def dispatch_legacy(self, request, barrier, depth, waited=False, saved=False):
        version = 4
        try:
            request = legacy_request(request)
            version = request['version']
            if depth > 16:
                raise Exception('multi nesting limit exceeded')
            name = request.get('action', '')
            if name != 'requestPermission' and util.setting('apiKey') and request.get('key') != util.setting('apiKey'):
                raise Exception('valid api key must be provided')
            name, params = self.resolve_action(name, request.get('params', {}))
            if not waited and self.legacy_busy(name):
                return self.after_collection_work(name, lambda: self.dispatch_legacy(request, barrier, depth, True, saved))
            self.guard_legacy(name, params)
            direct = name.startswith('gui') or name in LEGACY_DIRECT
            if not saved and name != 'multi' and not direct and self.legacy_writes(name):
                saving = self.save_open_editors()
                if saving is not None:
                    # Saving lets other work run, so admission is checked again afterwards.
                    reply = Deferred()
                    saving.then(lambda source: reply.resolve(format_exception_reply(version, source.error)) if source.error else
                                self.dispatch_legacy(request, barrier, depth, False, True).then(lambda final: reply.resolve(final.value)))
                    return reply
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
            elif direct:
                value = Legacy(self).call(name, params)
                if isinstance(value, Accepted) and name in LEGACY_LIFECYCLE:
                    self.reserve_lifecycle(value.pending)
                # Historical sync replied after syncing, so standalone sync waits too.
                def admitted(value):
                    return value.pending.map(value.project) if isinstance(value, Accepted) and (barrier or name == 'sync') else value.value if isinstance(value, Accepted) else value
                pending = value.map(admitted) if isinstance(value, Deferred) else completed(value).map(admitted)
            else:
                pending = self.runtime.background(lambda service: Legacy(self, service).call(name, params))
            reply = Deferred()
            pending.then(lambda source: reply.resolve(format_exception_reply(version, source.error) if source.error else format_success_reply(version, source.value)))
            return reply
        except Exception as error:
            return completed(format_exception_reply(version, error))

    def reserve_lifecycle(self, pending):
        self.lifecycle_reserved += 1
        def release(source):
            self.lifecycle_reserved -= 1
        pending.then(release)

    def after_collection_work(self, name, retry):
        """Queue a legacy action behind active collection or lifecycle work, as
        historical synchronous calls could not interleave with earlier work."""
        pending = Deferred()
        deadline = time.monotonic() + LEGACY_WAIT_SECONDS
        def check():
            # Admission rechecks every guard once collection work has finished.
            if self.legacy_busy(name) and time.monotonic() < deadline:
                self.runtime.schedule_later(check)
            else:
                retry().then(lambda source: pending.resolve(source.value, source.error))
        self.runtime.schedule_later(check)
        return pending

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
            msg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
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
    def version(self): ...

    @util.api()
    def requestPermission(self, origin, allowed): ...

    @util.api()
    def getProfiles(self): ...

    @util.api()
    def getActiveProfile(self): ...

    @util.api()
    def loadProfile(self, name): ...

    @util.api()
    def sync(self): ...

    @util.api()
    def multi(self, actions): ...

    @util.api()
    def getNumCardsReviewedToday(self): ...

    @util.api()
    def getNumCardsReviewedByDay(self): ...

    @util.api()
    def getCollectionStatsHTML(self, wholeCollection=True): ...

    @util.api()
    def deckNames(self): ...

    @util.api()
    def deckNamesAndIds(self): ...

    @util.api()
    def getDecks(self, cards): ...

    @util.api()
    def createDeck(self, deck): ...

    @util.api()
    def changeDeck(self, cards, deck): ...

    @util.api()
    def deleteDecks(self, decks, cardsToo=False): ...

    @util.api()
    def getDeckConfig(self, deck): ...

    @util.api()
    def saveDeckConfig(self, config): ...

    @util.api()
    def setDeckConfigId(self, decks, configId): ...

    @util.api()
    def cloneDeckConfigId(self, name, cloneFrom='1'): ...

    @util.api()
    def removeDeckConfigId(self, configId): ...

    @util.api()
    def getDeckStats(self, decks): ...

    @util.api()
    def storeMediaFile(self, filename, data=None, path=None, url=None, skipHash=None, deleteExisting=True): ...

    @util.api()
    def retrieveMediaFile(self, filename): ...

    @util.api()
    def getMediaFilesNames(self, pattern='*'): ...

    @util.api()
    def deleteMediaFile(self, filename): ...

    @util.api()
    def getMediaDirPath(self): ...

    @util.api()
    def addNote(self, note): ...

    @util.api()
    def canAddNote(self, note): ...

    @util.api()
    def canAddNoteWithErrorDetail(self, note): ...

    @util.api()
    def updateNoteFields(self, note): ...

    @util.api()
    def updateNote(self, note): ...

    @util.api()
    def updateNoteModel(self, note): ...

    @util.api()
    def updateNoteTags(self, note, tags): ...

    @util.api()
    def getNoteTags(self, note): ...

    @util.api()
    def addTags(self, notes, tags, add=True): ...

    @util.api()
    def removeTags(self, notes, tags): ...

    @util.api()
    def getTags(self): ...

    @util.api()
    def clearUnusedTags(self): ...

    @util.api()
    def replaceTags(self, notes, tag_to_replace, replace_with_tag): ...

    @util.api()
    def replaceTagsInAllNotes(self, tag_to_replace, replace_with_tag): ...

    @util.api()
    def setEaseFactors(self, cards, easeFactors): ...

    @util.api()
    def setSpecificValueOfCard(self, card, keys, newValues, warning_check=False): ...

    @util.api()
    def getEaseFactors(self, cards): ...

    @util.api()
    def suspend(self, cards, suspend=True): ...

    @util.api()
    def unsuspend(self, cards): ...

    @util.api()
    def suspended(self, card): ...

    @util.api()
    def areSuspended(self, cards): ...

    @util.api()
    def areDue(self, cards): ...

    @util.api()
    def getIntervals(self, cards, complete=False): ...

    @util.api()
    def modelNames(self): ...

    @util.api()
    def createModel(self, modelName, inOrderFields, cardTemplates, css=None, isCloze=False): ...

    @util.api()
    def modelNamesAndIds(self): ...

    @util.api()
    def findModelsById(self, modelIds): ...

    @util.api()
    def findModelsByName(self, modelNames): ...

    @util.api()
    def modelNameFromId(self, modelId): ...

    @util.api()
    def modelFieldNames(self, modelName): ...

    @util.api()
    def modelFieldDescriptions(self, modelName): ...

    @util.api()
    def modelFieldFonts(self, modelName): ...

    @util.api()
    def modelFieldsOnTemplates(self, modelName): ...

    @util.api()
    def modelTemplates(self, modelName): ...

    @util.api()
    def modelStyling(self, modelName): ...

    @util.api()
    def updateModelTemplates(self, model): ...

    @util.api()
    def updateModelStyling(self, model): ...

    @util.api()
    def findAndReplaceInModels(self, modelName, findText, replaceText, front=True, back=True, css=True): ...

    @util.api()
    def modelTemplateRename(self, modelName, oldTemplateName, newTemplateName): ...

    @util.api()
    def modelTemplateReposition(self, modelName, templateName, index): ...

    @util.api()
    def modelTemplateAdd(self, modelName, template): ...

    @util.api()
    def modelTemplateRemove(self, modelName, templateName): ...

    @util.api()
    def modelFieldRename(self, modelName, oldFieldName, newFieldName): ...

    @util.api()
    def modelFieldReposition(self, modelName, fieldName, index): ...

    @util.api()
    def modelFieldAdd(self, modelName, fieldName, index=None): ...

    @util.api()
    def modelFieldRemove(self, modelName, fieldName): ...

    @util.api()
    def modelFieldSetFont(self, modelName, fieldName, font): ...

    @util.api()
    def modelFieldSetFontSize(self, modelName, fieldName, fontSize): ...

    @util.api()
    def modelFieldSetDescription(self, modelName, fieldName, description): ...

    @util.api()
    def deckNameFromId(self, deckId): ...

    @util.api()
    def findNotes(self, query=None): ...

    @util.api()
    def findCards(self, query=None): ...

    @util.api()
    def cardsInfo(self, cards, fields=None): ...

    @util.api()
    def cardsModTime(self, cards): ...

    @util.api()
    def forgetCards(self, cards): ...

    @util.api()
    def relearnCards(self, cards): ...

    @util.api()
    def answerCards(self, answers): ...

    @util.api()
    def cardReviews(self, deck, startID): ...

    @util.api()
    def getReviewsOfCards(self, cards): ...

    @util.api()
    def setDueDate(self, cards, days): ...

    @util.api()
    def reloadCollection(self): ...

    @util.api()
    def getLatestReviewID(self, deck): ...

    @util.api()
    def insertReviews(self, reviews): ...

    @util.api()
    def notesInfo(self, notes=None, query=None): ...

    @util.api()
    def notesModTime(self, notes): ...

    @util.api()
    def deleteNotes(self, notes): ...

    @util.api()
    def removeEmptyNotes(self): ...

    @util.api()
    def cardsToNotes(self, cards): ...

    @util.api()
    def guiBrowse(self, query=None, reorderCards=None): ...

    @util.api()
    def guiEditNote(self, note): ...

    @util.api()
    def guiSelectNote(self, note): ...

    @util.api()
    def guiSelectCard(self, card): ...

    @util.api()
    def guiSelectedNotes(self): ...

    @util.api()
    def guiAddNoteSetData(self, note, append=False): ...

    @util.api()
    def guiAddCards(self, note=None): ...

    @util.api()
    def guiReviewActive(self): ...

    @util.api()
    def guiCurrentCard(self): ...

    @util.api()
    def guiStartCardTimer(self): ...

    @util.api()
    def guiShowQuestion(self): ...

    @util.api()
    def guiShowAnswer(self): ...

    @util.api()
    def guiAnswerCard(self, ease): ...

    @util.api()
    def guiPlayAudio(self): ...

    @util.api()
    def guiUndo(self): ...

    @util.api()
    def guiDeckOverview(self, name): ...

    @util.api()
    def guiDeckBrowser(self): ...

    @util.api()
    def guiDeckReview(self, name): ...

    @util.api()
    def guiImportFile(self, path=None): ...

    @util.api()
    def guiExitAnki(self): ...

    @util.api()
    def guiCheckDatabase(self): ...

    @util.api()
    def addNotes(self, notes): ...

    @util.api()
    def canAddNotes(self, notes): ...

    @util.api()
    def canAddNotesWithErrorDetail(self, notes): ...

    @util.api()
    def exportPackage(self, deck, path, includeSched=False): ...

    @util.api()
    def importPackage(self, path): ...

    @util.api()
    def apiReflect(self, scopes=None, actions=None): ...

if __name__ != "plugin":
    if Edit is not None:
        Edit.register_with_anki()
    ac = AnkiConnect()
    ac.runtime.register_hooks()
    ac.initLogging()
    ac.startWebServer()

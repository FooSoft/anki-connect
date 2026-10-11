"""Qt adapters. All functions in this module run on the main thread."""
import json
import uuid
import time

from .protocol import ApiError, Deferred, timestamp
from .services import RATINGS, entity_id


class Gui:
    def __init__(self, runtime):
        self.runtime = runtime
        self.editors = {}
        self.operation_id = None

    @property
    def mw(self):
        import aqt
        return aqt.mw

    def service(self):
        return self.runtime.service()

    def execute(self, method, params, operation_id=None):
        params = {key: value for key, value in params.items() if key != 'session'}
        previous, self.operation_id = self.operation_id, operation_id
        try:
            return getattr(self, method.replace('.', '_'))(**params)
        finally:
            self.operation_id = previous

    def cancellable(self, callback):
        if self.operation_id:
            self.runtime.operations.cancellations[self.operation_id] = callback
            self.runtime.operations.records[self.operation_id]['cancellable'] = True

    def operation_state(self):
        key = self.operation_id
        def update(state):
            if key and not self.runtime.operations.completions[key].done:
                self.runtime.operations.records[key].update(state=state, updatedAt=timestamp())
        return update

    def browser(self):
        import aqt
        return aqt.dialogs._dialogs.get('Browser', (None, None))[1]

    def browser_getSelection(self):
        browser = self.browser()
        return {'open': browser is not None,
                'selectedNoteIds': [str(id) for id in browser.selectedNotes()] if browser else [],
                'selectedCardIds': [str(id) for id in browser.selectedCards()] if browser else []}

    def browser_open(self, query=None, sort=None):
        import aqt
        browser = aqt.dialogs.open('Browser', self.mw)
        browser.activateWindow()
        def opened(_):
            if query is not None:
                browser.form.searchEdit.lineEdit().setText(query)
                browser.onSearchActivated()
            if sort:
                from aqt.qt import Qt
                index = browser.table._model.active_column_index(sort['column'])
                if index is None:
                    raise ApiError('invalidParams', 'Browser sort column is not active.')
                direction = Qt.SortOrder.AscendingOrder if sort['direction'] == 'ascending' else Qt.SortOrder.DescendingOrder
                # Set column first, then explicitly apply direction to defeat first-click defaults.
                browser.table._on_sort_column_changed(index, direction)
                browser.table._on_sort_column_changed(index, direction)
            return self.browser_getSelection()
        # Native search/selection saves the editor first. Do not ask it to call
        # saveNow before the webview has installed that function.
        return self.javascript(browser.editor, 'return true;', ready='typeof saveNow === "function"').map(opened)

    def browser_select(self, cardIds=None, noteIds=None):
        browser = self.browser()
        if browser is None:
            raise ApiError('invalidState', 'Browser is not open.')
        if cardIds is None:
            cardIds = [str(card) for id in noteIds for card in self.service().note(id).card_ids()]
        for id in cardIds:
            self.service().card(id)
        browser.table.clear_selection()
        # Current table supports selecting by card IDs in both browser modes.
        from aqt.qt import QItemSelection, QItemSelectionModel
        selection = QItemSelection()
        for id in cardIds:
            row = browser.table._model.get_card_row(entity_id(id))
            if row is not None:
                selection.select(browser.table._model.index(row, 0), browser.table._model.index(row, browser.table._model.columnCount() - 1))
        browser.table._selection_model().select(selection, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        return self.browser_getSelection()

    def add_dialog(self):
        import aqt
        return (aqt.dialogs._dialogs.get('NewAddCards', (None, None))[1] or
                aqt.dialogs._dialogs.get('AddCards', (None, None))[1])

    def register(self, dialog, kind):
        key = next((key for key, value in self.editors.items() if value[0] is dialog), None)
        if key is None:
            key = uuid.uuid4().hex
            self.editors[key] = (dialog, kind, self.runtime.session)
        return key

    def javascript(self, editor, code, ready=None):
        """Await a webview promise through callbacks, without a nested event loop."""
        from aqt.qt import QTimer
        result = Deferred()
        key = '__ankiConnect_' + uuid.uuid4().hex
        session = self.runtime.session
        started = time.monotonic()
        launched = [False]
        ready = ready or 'typeof getNoteInfo === "function" && typeof loadNote === "function"'
        script = '(async () => { ' + code + ' })().then(value => { globalThis[' + json.dumps(key) + '] = {value}; }, error => { globalThis[' + json.dumps(key) + '] = {error: String(error)}; });'
        def poll():
            if result.done:
                return
            if self.runtime.session != session:
                result.resolve(error=ApiError('staleSession', 'Editor session changed.'))
                return
            if time.monotonic() - started > 15:
                result.resolve(error=ApiError('ioError', 'Editor did not respond.'))
                return
            def checked(value):
                if not launched[0]:
                    if value:
                        launched[0] = True
                        editor.web.eval(script)
                    QTimer.singleShot(20, poll)
                elif value is None:
                    QTimer.singleShot(20, poll)
                elif 'error' in value:
                    result.resolve(error=ApiError('ioError', value['error']))
                else:
                    editor.web.eval('delete globalThis[' + json.dumps(key) + '];')
                    result.resolve(value.get('value'))
            try:
                probe = ready if not launched[0] else 'globalThis[' + json.dumps(key) + '] ?? null'
                editor.web.evalWithCallback(probe, checked)
            except RuntimeError as error:
                result.resolve(error=ApiError('notFound', 'Editor closed.'))
        poll()
        return result

    def svelte_record(self, dialog, kind):
        def projected(value):
            model = self.service().resolve({'id': str(value['mid'])}, 'noteType')
            deck = self.service().resolve({'name': value['deck']}, 'deck') if kind == 'add' else None
            fields = dict(zip([field['name'] for field in model['flds']], value['fields']))
            return {'id': self.register(dialog, kind), 'kind': kind, 'variant': 'svelte',
                    'noteId': str(value['id']) if value['id'] and str(value['id']) != '0' and kind != 'add' else None,
                    'noteType': self.service().summary(model), 'deck': self.service().summary(deck) if deck else None,
                    'fields': fields, 'tags': value['tags'], 'dirty': any(fields.values()) or bool(value['tags']),
                    'session': self.runtime.session}
        ready = '(() => { try { return !!getNoteInfo().mid' + (" && !!document.querySelector('.deck-chooser .chooser-button')?.textContent?.trim()" if kind == 'add' else '') + '; } catch { return false; } })()'
        return self.javascript(dialog.editor, "document.activeElement?.blur(); await saveNow(); const info = getNoteInfo(); return {...info, tags: [...document.querySelectorAll('.tag-editor [data-addon-tag]')].map(element => element.dataset.addonTag).filter(Boolean), deck: document.querySelector('.deck-chooser .chooser-button')?.textContent?.trim() ?? null};", ready=ready).map(projected)

    def editor_record(self, dialog, kind):
        key = self.register(dialog, kind)
        editor = dialog.editor
        service = self.service()
        if not hasattr(editor, 'note'):
            return self.svelte_record(dialog, kind)
        note = editor.note
        deck_id = dialog.deck_chooser.selected_deck_id if kind == 'add' else None
        return {'id': key, 'kind': kind, 'variant': 'legacy' if kind == 'add' else 'custom',
                'noteId': str(note.id) if note.id else None, 'noteType': service.summary(note.note_type()),
                'deck': service.summary(service.resolve({'id': str(deck_id)}, 'deck')) if deck_id else None,
                'fields': dict(note.items()), 'tags': list(note.tags), 'dirty': bool(any(note.fields)) if not note.id else False,
                'session': self.runtime.session}

    def editors_openNote(self, noteId):
        from .edit import Edit
        dialog = Edit.open_dialog_and_show_note_with_id(entity_id(noteId))
        return self.editor_record(dialog, 'note')

    def editors_openAdd(self, note=None):
        import aqt
        existing = self.add_dialog()
        def open_dialog(record=None):
            if record and record['dirty'] and note:
                raise ApiError('editorConflict', 'Existing Add draft has unsaved content.')
            from anki.collection import ExperimentFlag
            variant = 'NewAddCards' if self.mw.col.experiment_enabled(ExperimentFlag.SVELTE_EDITOR) else 'AddCards'
            dialog = existing or aqt.dialogs.open(variant, self.mw)
            dialog.activateWindow()
            if not note:
                if not existing and not hasattr(dialog.editor, 'note'):
                    dialog.load_new_note()
                return self.editor_record(dialog, 'add')
            native, deck = self.service().prepare_note(note)
            if hasattr(dialog.editor, 'note'):
                dialog.set_note(native, deck['id'])
                return self.editor_record(dialog, 'add')
            return self.populate_svelte(dialog, native, deck['id'])
        if existing:
            value = self.editor_record(existing, 'add')
            return value.map(open_dialog) if isinstance(value, Deferred) else open_dialog(value)
        return open_dialog()

    def populate_svelte(self, dialog, note, deck_id):
        args = {'nid': None, 'notetypeId': str(note.mid), 'deckId': str(deck_id), 'initial': True, 'focusTo': 0}
        code = 'await loadNote(' + json.dumps(args) + '); setFields(' + json.dumps(list(note.keys())) + ', ' + json.dumps(list(note.fields)) + '); setTags(' + json.dumps(list(note.tags)) + '); await saveNow(); return true;'
        return self.javascript(dialog.editor, code).map(lambda _: self.editor_record(dialog, 'add'))

    def editors_updateDraft(self, editorId, patch, mode='replace'):
        entry = self.editors.get(editorId)
        if not entry or entry[2] != self.runtime.session:
            raise ApiError('notFound', 'Editor not found in this session.')
        dialog, kind, _ = entry
        if kind != 'add' or dialog is not self.add_dialog():
            raise ApiError('invalidState', 'Only the active Add draft can be updated.')
        if not hasattr(dialog.editor, 'note'):
            def update(record):
                if record['dirty'] and ('noteType' in patch or mode == 'replace' and 'fields' in patch):
                    raise ApiError('editorConflict', 'Draft contains unsaved edits.')
                model = self.service().resolve(patch.get('noteType', {'id': record['noteType']['id']}), 'noteType')
                from anki.notes import Note
                note = Note(self.mw.col, model)
                for field in note.keys():
                    note[field] = record['fields'].get(field, '')
                for field, value in patch.get('fields', {}).items():
                    if field not in note:
                        raise ApiError('validationFailed', 'Unknown field: ' + field)
                    note[field] = note[field] + value if mode == 'append' else value
                tags = list(patch.get('tags', record['tags']))
                note.tags = list(dict.fromkeys(record['tags'] + tags)) if mode == 'append' else tags
                deck = self.service().resolve(patch.get('deck', {'id': record['deck']['id']}), 'deck')
                return self.populate_svelte(dialog, note, deck['id'])
            return self.svelte_record(dialog, kind).map(update)
        current = dialog.editor.note
        if any(current.fields) and ('noteType' in patch or (mode == 'replace' and 'fields' in patch)):
            raise ApiError('editorConflict', 'Draft contains unsaved edits.')
        model = self.service().resolve(patch['noteType'], 'noteType') if 'noteType' in patch else current.note_type()
        from anki.notes import Note
        updated = Note(self.mw.col, model)
        for name, value in current.items():
            if name in updated:
                updated[name] = value
        for name, value in patch.get('fields', {}).items():
            if name not in updated:
                raise ApiError('validationFailed', 'Unknown field: ' + name)
            updated[name] = updated[name] + value if mode == 'append' else value
        tags = patch.get('tags', current.tags)
        updated.tags = list(dict.fromkeys(list(current.tags) + list(tags))) if mode == 'append' else list(tags)
        deck = self.service().resolve(patch['deck'], 'deck')['id'] if 'deck' in patch else dialog.deck_chooser.selected_deck_id
        dialog.set_note(updated, deck)
        return self.editor_record(dialog, 'add')

    def reviewer(self):
        reviewer = self.mw.reviewer
        if self.mw.state != 'review' or not reviewer or not reviewer.card:
            raise ApiError('invalidState', 'GUI review is not active.')
        return reviewer

    def reviewer_token(self, reviewer):
        return [reviewer.card.id, reviewer._v3.states.SerializeToString().hex(), self.runtime.generation]

    def reviewer_get(self):
        try:
            reviewer = self.reviewer()
        except ApiError:
            return {'active': False, 'card': None, 'rendered': None, 'side': 'none', 'stateToken': None,
                    'answers': [], 'source': 'reviewer'}
        labels = self.mw.col._backend.describe_next_states(reviewer._v3.states)
        buttons = {button[0] for button in reviewer._answerButtonList()}
        return {'active': True, 'card': self.service().card_record(reviewer.card),
                'rendered': self.service().cards_render(str(reviewer.card.id)),
                'side': reviewer.state if reviewer.state in ('question', 'answer') else 'none',
                'stateToken': self.runtime.token('reviewer', self.reviewer_token(reviewer)),
                'answers': [{'rating': RATINGS[index], 'label': label, 'interval': None}
                            for index, label in enumerate(labels) if index + 1 in buttons], 'source': 'reviewer'}

    def checked_reviewer(self, stateToken):
        reviewer = self.reviewer()
        self.runtime.check_token(stateToken, 'reviewer', self.reviewer_token(reviewer))
        return reviewer

    def reviewer_startTimer(self, stateToken):
        self.checked_reviewer(stateToken).card.start_timer()
        return {'changed': True}

    def reviewer_showQuestion(self, stateToken):
        self.checked_reviewer(stateToken)._showQuestion()
        return {'changed': True}

    def reviewer_showAnswer(self, stateToken):
        self.checked_reviewer(stateToken)._showAnswer()
        return {'changed': True}

    def reviewer_playAudio(self, stateToken):
        self.checked_reviewer(stateToken).replayAudio()
        return {'changed': True}

    def reviewer_answer(self, stateToken, rating):
        from aqt import gui_hooks
        reviewer = self.checked_reviewer(stateToken)
        if reviewer.state != 'answer':
            raise ApiError('invalidState', 'The answer must be visible.')
        ease = RATINGS.index(rating) + 1
        if ease not in {button[0] for button in reviewer._answerButtonList()}:
            raise ApiError('invalidState', 'Rating is not offered.')
        proceed, ease = gui_hooks.reviewer_will_answer_card((True, ease), reviewer, reviewer.card)
        if not proceed:
            raise ApiError('vetoed', 'Reviewer hook vetoed the answer.')
        answer = self.mw.col.sched.build_answer(card=reviewer.card, states=reviewer._v3.states,
                                                rating=reviewer._v3.rating_from_ease(ease))
        card_id = str(reviewer.card.id)
        reviewer.state = 'transition'
        def work(service):
            service.change(service.col.sched.answer_card(answer))
            latest = service.col.db.scalar('select max(id) from revlog where cid=?', int(card_id))
            return {'cardId': card_id, 'reviewId': str(latest) if latest else None,
                    'scheduling': service.scheduling_get(card_id)}
        def after(value):
            reviewer.card.load()
            suspended = reviewer.card.queue < 0
            reviewer._after_answering(ease)
            if self.mw.col.sched.state_is_leech(answer.new_state):
                reviewer.onLeech(suspended)
            return value
        future = self.runtime.background(work, after=after, initiator=reviewer)
        future.then(lambda source: setattr(reviewer, 'state', 'answer') if source.error else None)
        return future

    def application_navigate(self, view, deck=None):
        if deck:
            value = self.service().resolve(deck, 'deck')
            self.mw.col.decks.select(value['id'])
        self.mw.moveToState({'deckBrowser': 'deckBrowser', 'deckOverview': 'overview', 'review': 'review'}[view])
        return {'changed': True}

    def application_exit(self):
        self.runtime.exit_requested = True
        return {'accepted': True}

    def application_importFile(self, path=None):
        from pathlib import Path
        from aqt.qt import QFileDialog, QTimer, Qt
        from aqt.import_export.import_dialog import ImportDialog, AnkiPackageArgs, CsvArgs, JsonFileArgs
        from aqt.import_export.importing import ColpkgImporter
        session = self.runtime.session
        state = self.operation_state()
        if path is None:
            state('waitingForUser')
            path, _ = QFileDialog.getOpenFileName(self.mw, 'Import', '',
                'Import files (*.apkg *.zip *.colpkg *.csv *.txt *.json *.anki-json)')
            if not path:
                raise ApiError('cancelled', 'Import file selection cancelled.')
            state('running')
        self.runtime.capture(session)
        if not Path(path).is_file():
            raise ApiError('notFound', 'Import file not found.')
        if ColpkgImporter.can_import(Path(path).name.lower()):
            return self.import_collection_package(path)
        if any(isinstance(window, ImportDialog) and window.isVisible() for window in self.mw.app.topLevelWidgets()):
            raise ApiError('busy', 'Another import dialog is open.')
        suffix = Path(path).suffix.lower()
        args = AnkiPackageArgs(path) if suffix in ('.apkg', '.zip') else JsonFileArgs(path) if suffix in ('.json', '.anki-json') else CsvArgs(path) if suffix in ('.csv', '.txt') else None
        if args is None:
            raise ApiError('unsupportedCapability', 'Import file format is not supported by this adapter.')
        result = Deferred()
        dialog = ImportDialog(self.mw, args)
        self.runtime.lifecycle_active = True
        state('waitingForUser')
        def finish(value=None, error=None):
            if result.done:
                return
            self.runtime.lifecycle_active = False
            result.resolve(value, error)
        def closed(code):
            if result.done:
                return
            # Wait behind any in-progress native import before reporting cancellation.
            barrier = self.runtime.background(lambda service: service.col.db.scalar('select 1'), expected=session)
            barrier.then(lambda source: finish(error=source.error or ApiError('cancelled', 'Import cancelled.')))
        dialog.finished.connect(closed)
        self.cancellable(dialog.reject)
        def poll():
            if result.done:
                return
            state('running' if self.mw._background_op_count else 'waitingForUser')
            if self.runtime.session != session:
                finish(error=ApiError('staleSession', 'Collection changed during import.'))
                return
            if dialog.windowModality() == Qt.WindowModality.NonModal:
                # Anki changes modality only after native import succeeds and its
                # operation notifications have been queued on the main thread.
                QTimer.singleShot(0, lambda: finish({'completed': True}))
                return
            def error_checked(message):
                if result.done:
                    return
                if message:
                    finish(error=ApiError('ioError', message))
                else:
                    QTimer.singleShot(100, poll)
            if dialog.web is not None:
                # 26.08 renders initial-load failures as a SvelteKit error page,
                # which never releases Anki's queued DOM-ready evaluations.
                dialog.web.page().runJavaScript("""
                    (() => {
                        const importError = document.querySelector('.error-box .error-text')?.textContent;
                        const pageError = document.querySelector('.message')?.textContent;
                        return importError
                            ?? (/^[45]\\d{2}:/.test(pageError ?? '') ? pageError : null);
                    })()
                """, error_checked)
        poll()
        return result

    def import_collection_package(self, path):
        from aqt.operations import QueryOp
        from aqt.import_export.importing import import_collection_package_op
        from aqt.utils import askUser
        self.guard_lifecycle()
        if not askUser('Importing this collection package will replace the current collection. Continue?', defaultno=True):
            raise ApiError('cancelled', 'Collection replacement cancelled.')
        pending = Deferred()
        self.runtime.lifecycle_active = True
        def loaded(error=None):
            try:
                if not self.mw.loadCollection():
                    raise ApiError('ioError', 'Collection could not be reopened after import.')
                self.runtime.invalidate_session()
                self.mw.reset()
                if error:
                    raise error
                pending.resolve({'completed': True})
            except Exception as failure:
                pending.resolve(error=failure)
            finally:
                self.runtime.lifecycle_active = False
        def start_import():
            import_collection_package_op(self.mw, path, loaded).failure(loaded).run_in_background()
        def after_backup(_):
            self.mw.unloadCollection(start_import)
        def backup_failed(error):
            self.runtime.lifecycle_active = False
            pending.resolve(error=error)
        QueryOp(parent=self.mw, op=lambda _: self.mw.create_backup_now(), success=after_backup).failure(backup_failed).with_progress().run_in_background()
        return pending

    def profiles_list(self):
        return [{'name': name} for name in self.mw.pm.profiles()]

    def profiles_getActive(self):
        return {'name': self.mw.pm.name} if self.mw.col else None

    def profiles_switch(self, name):
        if name not in self.mw.pm.profiles():
            raise ApiError('notFound', 'Profile not found.')
        if name == self.mw.pm.name and self.mw.col:
            return self.service().collection_get()
        self.guard_lifecycle()
        pending = Deferred()
        self.runtime.lifecycle_active = True
        def loaded():
            try:
                if not self.mw.col or self.mw.pm.name != name:
                    raise ApiError('ioError', 'Profile did not load.')
                self.runtime.invalidate_session()
                pending.resolve(self.service().collection_get())
            except Exception as error:
                pending.resolve(error=error)
            finally:
                self.runtime.lifecycle_active = False
        def load():
            try:
                self.runtime.invalidate_session()
                self.mw.pm.load(name)
                self.mw.loadProfile(onsuccess=loaded)
                if not self.mw.col:
                    loaded()
            except Exception as error:
                self.runtime.lifecycle_active = False
                pending.resolve(error=error)
        if self.mw.col:
            self.mw.unloadProfile(load)
        else:
            load()
        return pending

    def guard_lifecycle(self):
        import aqt
        if self.mw._background_op_count:
            raise ApiError('busy', 'Anki has an active collection operation.')
        for _, dialog in aqt.dialogs._dialogs.values():
            if dialog is not None and hasattr(dialog, 'editor'):
                raise ApiError('editorConflict', 'Close editors before changing collection lifecycle.')

    def collection_refresh(self, target='windows'):
        if target == 'cachesAndWindows':
            self.mw.col.models._cache.clear()
        self.mw.reset()
        return {'changed': True}

    def collection_sync(self, includeMedia=True):
        from aqt.qt import QTimer
        from aqt import gui_hooks
        auth = self.mw.pm.sync_auth()
        if not auth:
            raise ApiError('authenticationRequired', 'Sync authentication is not configured.')
        self.guard_lifecycle()
        includeMedia = includeMedia and self.mw.pm.media_syncing_enabled()
        pending = Deferred()
        state = self.operation_state()
        self.runtime.lifecycle_active = True
        col = self.mw.col
        self.cancellable(lambda: (col.abort_sync(), col.abort_media_sync()))
        def fail(error):
            from anki.errors import Interrupted
            self.runtime.lifecycle_active = False
            pending.resolve(error=ApiError('cancelled' if isinstance(error, Interrupted) or isinstance(error, ApiError) and error.kind == 'cancelled' else 'ioError', str(error)))
        def done():
            self.runtime.lifecycle_active = False
            self.runtime.invalidate_predictions()
            self.mw._refresh_after_sync()
            pending.resolve({'collectionComplete': True, 'mediaComplete': includeMedia})
        def media():
            if not includeMedia:
                done()
                return
            self.mw.media_syncer.start_monitoring()
            def poll():
                def checked(future):
                    try:
                        status = future.result()
                        if status.active:
                            QTimer.singleShot(250, poll)
                        else:
                            done()
                    except Exception as error:
                        fail(error)
                self.mw.taskman.run_in_background(col.media_sync_status, checked, uses_collection=False)
            poll()
        def full(out, upload):
            state('running')
            gui_hooks.collection_will_temporarily_close(col)
            def work():
                if not upload:
                    self.mw.create_backup_now()
                col.close_for_full_sync()
                col.full_upload_or_download(auth=auth, server_usn=out.server_media_usn if includeMedia else None, upload=upload)
            def finished(future):
                try:
                    self.mw.reopen(after_full_sync=True)
                    self.runtime.invalidate_session()
                    future.result()
                    self.mw.reset()
                    media()
                except Exception as error:
                    fail(error)
            self.mw.taskman.with_progress(work, finished)
        def synced(future):
            try:
                out = future.result()
                col._load_scheduler()
                self.mw.pm.set_host_number(out.host_number)
                if out.new_endpoint:
                    self.mw.pm.set_current_sync_url(out.new_endpoint)
                if out.required in (out.NO_CHANGES, out.NORMAL_SYNC):
                    media()
                else:
                    state('waitingForUser')
                    from aqt.utils import ask_user_dialog
                    directions = [False] if out.required == out.FULL_DOWNLOAD else [True] if out.required == out.FULL_UPLOAD else [True, False]
                    def choice(index):
                        if index < len(directions):
                            full(out, directions[index])
                        else:
                            fail(ApiError('cancelled', 'Full sync cancelled.'))
                    ask_user_dialog('Anki requires a full sync. Choose the authoritative collection.',
                                    callback=choice, buttons=[('Upload' if upload else 'Download') for upload in directions] + ['Cancel'], default_button=len(directions), parent=self.mw)
            except Exception as error:
                fail(error)
        self.mw.taskman.with_progress(lambda: col.sync_collection(auth, includeMedia), synced)
        return pending

    def guard(self, method, params):
        """Reject affected open editors, including changes still pending in JS."""
        import aqt
        if method.startswith(('scheduling.', 'cards.')):
            return
        for _, dialog in aqt.dialogs._dialogs.values():
            if dialog is None or not hasattr(dialog, 'editor'):
                continue
            editor = dialog.editor
            note = getattr(editor, 'note', None)
            note_id = note.id if note is not None else getattr(editor, 'nid', None)
            affected = method.startswith(('noteTypes.', 'collection.', 'packages.', 'advanced.')) or method == 'application.importFile'
            ids = params.get('ids', params.get('noteIds', [params.get('id')]))
            if method.startswith(('notes.', 'tags.')):
                affected = bool(note_id) and (str(note_id) in ids or params.get('allNotes', False))
            if affected:
                raise ApiError('editorConflict', 'Close the affected editor before this API write, even if its content is saved.')

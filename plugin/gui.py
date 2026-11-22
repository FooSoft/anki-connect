"""Qt adapters. All functions in this module run on the main thread."""
import json
import uuid
import time

from . import compat
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
        already_open = self.browser() is not None
        # Start a new browser with the target query, before its editor loads.
        # Existing browsers must save their current note before changing search.
        initial = not already_open and query is not None and compat.browser_opens_with_search()
        browser = aqt.dialogs.open('Browser', self.mw, **({'search': (query,)} if initial else {}))
        browser.activateWindow()
        # Before 2.1.45 searching and sorting save the editor and then change rows
        # asynchronously; these browsers save once and change rows synchronously.
        table = getattr(browser, 'table', None) is not None
        def search():
            browser.form.searchEdit.lineEdit().setText(query)
            if table:
                browser.onSearchActivated()
            else:
                browser._onSearchActivated()
        if not already_open and query is not None and not initial:
            # Before 2.1.41 a new browser searches its default first; the
            # editor's save of any shown note completes before this search.
            if table:
                search()
            else:
                browser.form.searchEdit.lineEdit().setText(query)
                compat.editor_save(browser.editor, browser._onSearchActivated)
        def apply():
            if already_open and query is not None:
                search()
            if sort and not compat.browser_sort(browser, sort['column'], sort['direction'] == 'descending'):
                raise ApiError('invalidParams', 'Browser sort column is not active.')
            return self.browser_getSelection()
        def opened(_):
            if table:
                return apply()
            pending = Deferred()
            def saved():
                try:
                    pending.resolve(apply())
                except Exception as error:
                    pending.resolve(error=error)
            compat.editor_save(browser.editor, saved)
            return pending
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
        # Card rows are found in both browser modes.
        rows = [compat.browser_card_row(browser, entity_id(id)) for id in cardIds]
        compat.browser_select_rows(browser, [row for row in rows if row is not None])
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
        # Chromium 69 of Anki 2.1.15 lacks globalThis and the ?? operator.
        slot = 'window[' + json.dumps(key) + ']'
        script = '(async () => { ' + code + ' })().then(value => { ' + slot + ' = {value}; }, error => { ' + slot + ' = {error: String(error)}; });'
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
                    editor.web.eval('delete ' + slot + ';')
                    result.resolve(value.get('value'))
            try:
                probe = ready if not launched[0] else '(' + slot + ' === undefined ? null : ' + slot + ')'
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
        deck_id = compat.add_dialog_deck_id(dialog) if kind == 'add' else None
        # Before 2.1.28 new notes receive their ID at construction, not when added.
        draft = kind == 'add' or not note.id
        return {'id': key, 'kind': kind, 'variant': 'legacy' if kind == 'add' else 'custom',
                'noteId': None if draft else str(note.id), 'noteType': service.summary(note.note_type()),
                'deck': service.summary(service.resolve({'id': str(deck_id)}, 'deck')) if deck_id else None,
                'fields': dict(note.items()), 'tags': list(note.tags), 'dirty': bool(any(note.fields)) if draft else False,
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
            variant = 'NewAddCards' if compat.svelte_editor_enabled(self.mw.col) else 'AddCards'
            dialog = existing or aqt.dialogs.open(variant, self.mw)
            dialog.activateWindow()
            if not note:
                if not existing and not hasattr(dialog.editor, 'note'):
                    dialog.load_new_note()
                return self.editor_record(dialog, 'add')
            native, deck = self.service().prepare_note(note)
            if hasattr(dialog.editor, 'note'):
                compat.add_dialog_set_note(dialog, native, deck['id'])
                return self.editor_record(dialog, 'add')
            return self.populate_svelte(dialog, native, deck['id'])
        if existing:
            value = self.editor_record(existing, 'add')
            return value.map(open_dialog) if isinstance(value, Deferred) else open_dialog(value)
        return open_dialog()

    def populate_svelte(self, dialog, note, deck_id):
        args = {'nid': None, 'notetypeId': str(note.mid), 'deckId': str(deck_id), 'initial': True, 'focusTo': 0,
                'copyFromNote': {'notetypeId': str(note.mid), 'fields': list(note.fields), 'tags': list(note.tags)}}
        # setTags() updates the chips but does not update Svelte's note state.
        # Native draft loading copies tags into the note that the Add button saves.
        # Keep the copied note out of the initial arguments that Anki reuses
        # after saving, so the next draft does not repeat these fields/tags.
        code = 'const args = ' + json.dumps(args) + '; const copy = args.copyFromNote; copy.notetypeId = BigInt(copy.notetypeId); delete args.copyFromNote; await loadNote(args); await loadNote({copyFromNote: copy}); setFields(' + json.dumps(list(note.keys())) + ', ' + json.dumps(list(note.fields)) + '); await saveNow(); return true;'
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
        deck = self.service().resolve(patch['deck'], 'deck')['id'] if 'deck' in patch else compat.add_dialog_deck_id(dialog)
        compat.add_dialog_set_note(dialog, updated, deck)
        return self.editor_record(dialog, 'add')

    def reviewer(self):
        reviewer = self.mw.reviewer
        if self.mw.state != 'review' or not reviewer or not reviewer.card:
            raise ApiError('invalidState', 'GUI review is not active.')
        return reviewer

    def reviewer_token(self, reviewer):
        card = reviewer.card
        # Without the v3 scheduler, a card's reviews and modification identify its state.
        states = (compat.reviewer_states(reviewer._v3).SerializeToString().hex() if getattr(reviewer, '_v3', None)
                  else '%d:%d:%d' % (card.reps, card.mod, card.queue))
        return [card.id, states, self.runtime.generation]

    def reviewer_ratings(self, reviewer):
        """Ratings by offered ease; v1 learning cards offer Again, Good and sometimes Easy."""
        eases = sorted(button[0] for button in reviewer._answerButtonList())
        names = {4: RATINGS, 3: ['again', 'good', 'easy'], 2: ['again', 'good']}[len(eases)]
        return dict(zip(eases, names))

    def reviewer_get(self):
        try:
            reviewer = self.reviewer()
        except ApiError:
            return {'active': False, 'card': None, 'rendered': None, 'side': 'none', 'stateToken': None,
                    'answers': [], 'source': 'reviewer'}
        ratings = self.reviewer_ratings(reviewer)
        if getattr(reviewer, '_v3', None):
            labels = dict(enumerate(self.mw.col.sched.describe_next_states(compat.reviewer_states(reviewer._v3)), 1))
        else:
            labels = {ease: self.mw.col.sched.nextIvlStr(reviewer.card, ease, True) for ease in ratings}
        return {'active': True, 'card': self.service().card_record(reviewer.card),
                'rendered': self.service().cards_render(str(reviewer.card.id)),
                'side': reviewer.state if reviewer.state in ('question', 'answer') else 'none',
                'stateToken': self.runtime.token('reviewer', self.reviewer_token(reviewer)),
                'answers': [{'rating': rating, 'label': labels[ease], 'interval': None}
                            for ease, rating in ratings.items()], 'source': 'reviewer'}

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
        reviewer = self.checked_reviewer(stateToken)
        if reviewer.state != 'answer':
            raise ApiError('invalidState', 'The answer must be visible.')
        ease = next((ease for ease, name in self.reviewer_ratings(reviewer).items() if name == rating), None)
        if ease is None:
            raise ApiError('invalidState', 'Rating is not offered.')
        if not getattr(reviewer, '_v3', None):
            return self.answer_without_v3(reviewer, ease)
        from aqt import gui_hooks
        proceed, ease = gui_hooks.reviewer_will_answer_card((True, ease), reviewer, reviewer.card)
        if not proceed:
            raise ApiError('vetoed', 'Reviewer hook vetoed the answer.')
        answer = self.mw.col.sched.build_answer(card=reviewer.card, states=compat.reviewer_states(reviewer._v3),
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
                compat.reviewer_leech(reviewer, suspended)
            return value
        future = self.runtime.background(work, after=after, initiator=reviewer)
        future.then(lambda source: setattr(reviewer, 'state', 'answer') if source.error else None)
        return future

    def answer_without_v3(self, reviewer, ease):
        """Answer through the reviewer, which runs hooks and the v1/v2 scheduler on the main thread."""
        card_id = reviewer.card.id
        latest = 'select max(id) from revlog where cid=?'
        before = self.mw.col.db.scalar(latest, card_id)
        reviewer._answerCard(ease)
        review = self.mw.col.db.scalar(latest, card_id)
        if review == before:
            raise ApiError('vetoed', 'Reviewer hook vetoed the answer.')
        return {'cardId': str(card_id), 'reviewId': str(review), 'scheduling': self.service().scheduling_get(str(card_id))}

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
        dialog = compat.import_dialog(self.mw, args)
        self.runtime.lifecycle_active = True
        state('waitingForUser')
        def finish(value=None, error=None):
            if result.done:
                return
            self.runtime.lifecycle_active = False
            result.resolve(value, error)
        dialog_closed = []
        def closed(code):
            # The dialog deletes itself on close; scheduled polls must not touch it.
            dialog_closed.append(code)
            if result.done:
                return
            # Wait behind any in-progress native import before reporting cancellation.
            barrier = self.runtime.background(lambda service: service.col.db.scalar('select 1'), expected=session)
            barrier.then(lambda source: finish(error=source.error or ApiError('cancelled', 'Import cancelled.')))
        dialog.finished.connect(closed)
        self.cancellable(dialog.reject)
        def poll():
            if result.done or dialog_closed:
                return
            state('running' if compat.background_op_count(self.mw) else 'waitingForUser')
            if self.runtime.session != session:
                finish(error=ApiError('staleSession', 'Collection changed during import.'))
                return
            if dialog.windowModality() == Qt.WindowModality.NonModal:
                # Anki changes modality only after native import succeeds and its
                # operation notifications have been queued on the main thread.
                QTimer.singleShot(0, lambda: finish({'completed': True}))
                return
            def error_checked(message):
                if result.done or dialog_closed:
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
        if compat.background_op_count(self.mw):
            raise ApiError('busy', 'Anki has an active collection operation.')
        for _, dialog in aqt.dialogs._dialogs.values():
            if dialog is not None and hasattr(dialog, 'editor'):
                raise ApiError('editorConflict', 'Close editors before changing collection lifecycle.')

    def collection_refresh(self, target='windows'):
        if target == 'cachesAndWindows':
            compat.clear_notetype_cache(self.mw.col)
        self.mw.reset()
        return {'changed': True}

    def collection_sync(self, includeMedia=True):
        from aqt.qt import QTimer
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
            compat.refresh_after_sync(self.mw)
            pending.resolve({'collectionComplete': True, 'mediaComplete': includeMedia})
        def media():
            if not includeMedia:
                done()
                return
            watched = None if compat.collection_syncs_media(col) else compat.watch_media_sync(self.mw.media_syncer)
            compat.start_media_sync(self.mw, col)
            def poll():
                if watched:
                    if self.mw.media_syncer.is_syncing():
                        QTimer.singleShot(250, poll)
                        return
                    error = watched()
                    if error is not None:
                        fail(error)
                    else:
                        done()
                    return
                def checked(future):
                    try:
                        status = future.result()
                        if status.active:
                            QTimer.singleShot(250, poll)
                        else:
                            done()
                    except Exception as error:
                        fail(error)
                compat.run_in_background(self.mw, col.media_sync_status, checked, uses_collection=False)
            poll()
        def full(out, upload):
            state('running')
            compat.collection_will_temporarily_close(col)
            server_usn = compat.field(out, 'server_media_usn') if includeMedia else None
            def work():
                compat.full_sync(self.mw, col, auth, upload, server_usn)
            def finished(future):
                try:
                    compat.reopen_after_full_sync(self.mw)
                    self.runtime.invalidate_session()
                    future.result()
                    self.mw.reset()
                    media()
                except Exception as error:
                    fail(error)
            self.mw.taskman.with_progress(work, finished)
        def synced(future):
            try:
                begin()
                out = future.result()
                col._load_scheduler()
                self.mw.pm.set_host_number(out.host_number)
                if compat.field(out, 'new_endpoint'):
                    self.mw.pm.set_current_sync_url(out.new_endpoint)
                if out.required in (out.NO_CHANGES, out.NORMAL_SYNC):
                    media()
                else:
                    state('waitingForUser')
                    directions = [False] if out.required == out.FULL_DOWNLOAD else [True] if out.required == out.FULL_UPLOAD else [True, False]
                    def choice(index):
                        if index < len(directions):
                            full(out, directions[index])
                        else:
                            fail(ApiError('cancelled', 'Full sync cancelled.'))
                    compat.ask_user('Anki requires a full sync. Choose the authoritative collection.',
                                    choice, [('Upload' if upload else 'Download') for upload in directions] + ['Cancel'], len(directions), self.mw)
            except Exception as error:
                fail(error)
        begin = compat.release_sync_lock(col)
        self.mw.taskman.with_progress(lambda: compat.sync_collection(col, auth, includeMedia), synced)
        return pending

    def guard(self, method, params, saved=False):
        """Reject affected open editors, including changes still pending in JS.

        With saved, the caller saves open editors before writing, so note and tag
        writes skip editors whose hosts reload the changed note afterwards."""
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
                affected = affected and not (saved and compat.reloads_changed_notes(editor, method))
            if affected:
                raise ApiError('editorConflict', 'Close the affected editor before this API write, even if its content is saved.')

    def guard_note_type(self, name):
        """Reject only editors that may show a note of the named note type."""
        import aqt
        for _, dialog in aqt.dialogs._dialogs.values():
            if dialog is None or not hasattr(dialog, 'editor'):
                continue
            editor = dialog.editor
            note = getattr(editor, 'note', None)
            if note is not None:
                try:
                    affected = note.note_type()['name'].casefold() == str(name).casefold()
                except Exception:
                    affected = True
            else:
                # Web editors keep their note type in JavaScript; assume a conflict.
                affected = not hasattr(editor, 'note') or getattr(editor, 'nid', None) is not None
            if affected:
                raise ApiError('editorConflict', 'Close the affected editor before this API write, even if its content is saved.')

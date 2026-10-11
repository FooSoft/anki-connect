#!/usr/bin/env python3
"""Real-GUI smoke checks, run by test.sh/test.ps1 by default; uses disposable Anki profiles.

Run with the pinned environment and a working display:
    python tools/smoke_gui.py [all|editors|browser|custom|reviewer|imports|profiles|colpkg|exit|legacy-exit]

No sync credentials are used. Profiles/files remain in the OS temp directory for diagnostics.
Processes exit after checks to isolate native Qt/WebEngine teardown; application
shutdown is verified separately by the exit scenario.
"""
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Each scenario runs in a fresh process/profile to isolate Qt WebEngine teardown.
scenario = sys.argv[1] if len(sys.argv) > 1 else 'all'
scenarios = ['editors', 'browser', 'custom', 'reviewer', 'imports', 'profiles', 'colpkg', 'exit', 'legacy-exit']
if scenario == 'all':
    import subprocess
    failures = []
    for item in scenarios:
        try:
            code = subprocess.run([sys.executable, __file__, item], timeout=90).returncode
        except subprocess.TimeoutExpired:
            code = 1
            print('GUI scenario timed out: ' + item, flush=True)
        if code:
            failures.append(item)
    print('Failed scenarios: ' + ', '.join(failures) if failures else 'All GUI scenarios passed', flush=True)
    sys.exit(bool(failures))
if scenario not in scenarios:
    raise SystemExit('Choose all or: ' + ', '.join(scenarios))
# Anki's IPC key is normally per user, not per profile. Set it before importing
# aqt so tests never reuse a personal Anki instance or another test process.
os.environ['ANKI_SINGLE_INSTANCE_KEY'] = 'anki-api-test-' + uuid.uuid4().hex
from anki.lang import set_lang
set_lang('en')
from aqt.profiles import ProfileManager
base = Path(tempfile.mkdtemp(prefix='anki-api-gui-'))
pm = ProfileManager(base)
pm.setupMeta()
pm.profiles()
pm.load(pm.profiles()[0])
pm.meta['firstRun'] = False
pm.meta['defaultLang'] = 'en'
# Keep unattended tests offline and free of startup update dialogs.
pm.set_update_check(False)
pm.set_check_for_addon_updates(False)
pm.profile['autoSync'] = False
pm.profile['numBackups'] = 0
pm.save()
pm.db.close()
import aqt
from aqt.qt import QTimer
app = aqt._run(['anki', '-b', str(base), '-p', 'User 1', '-l', 'en'], exec=False)
from plugin import AnkiConnect
from plugin.edit import Edit
from plugin.protocol import Deferred
owner = AnkiConnect()
Edit.register_with_anki()
owner.runtime.register_hooks()
unhandled = []
def exception_hook(kind, error, traceback):
    import traceback as tb
    unhandled.append(error)
    print('UNHANDLED GUI ERROR:', ''.join(tb.format_exception(kind, error, traceback)), flush=True)
sys.excepthook = exception_hook
def wait_until(fn, timeout=30, description='GUI wait'):
    deadline = time.monotonic() + timeout
    while not fn():
        if time.monotonic() > deadline:
            windows = [(type(window).__name__, window.windowTitle())
                       for window in app.topLevelWidgets() if window.isVisible()]
            print('TIMEOUT:', description, 'background operations:', aqt.mw._background_op_count,
                  'visible windows:', windows, flush=True)
            raise TimeoutError(description + ' expired')
        app.processEvents()
        time.sleep(0.01)
def result(value):
    if isinstance(value, Deferred):
        wait_until(lambda: value.done)
        if value.error:
            raise value.error
        return value.value
    return value
def call(method, **params):
    deadline = time.monotonic() + 30
    while True:
        wait_until(lambda: aqt.mw._background_op_count == 0)
        try:
            value = result(owner.runtime.dispatcher.invoke(method, params))
            if isinstance(value, dict) and 'operationId' in value:
                value = result(owner.runtime.operations.completions[value['operationId']])
            return value
        except Exception as error:
            # Browser/editor callbacks can start native work between admission
            # and the queued operation's start. This rejection precedes execution.
            if (getattr(error, 'kind', None) != 'busy'
                    or str(error) != 'A collection operation is active.'
                    or time.monotonic() >= deadline):
                raise
            app.processEvents()
def old(action, **params):
    deadline = time.monotonic() + 30
    while True:
        wait_until(lambda: aqt.mw._background_op_count == 0)
        previous = set(owner.runtime.operations.records)
        reply = result(owner.handler_async({'action': action, 'version': 6, 'params': params}))
        if (reply['error'] == 'A collection operation is active.'
                and time.monotonic() < deadline):
            app.processEvents()
            continue
        assert reply['error'] is None, (action, reply)
        try:
            # Legacy GUI actions may acknowledge admission before completion.
            # Preserve that timing while checking the real operation's outcome.
            for id in owner.runtime.operations.records.keys() - previous:
                result(owner.runtime.operations.completions[id])
            return reply['result']
        except Exception as error:
            if (getattr(error, 'kind', None) != 'busy'
                    or str(error) != 'A collection operation is active.'
                    or time.monotonic() >= deadline):
                raise
            # Like call(), retry only this rejection before GUI execution.
            app.processEvents()
try:
    wait_until(lambda: aqt.mw.col is not None and aqt.mw.state == 'deckBrowser')
    print('PASS loaded disposable profile', base, flush=True)
    print('DESCRIBE', [m for m in owner.runtime.describe()['methods'] if not m['available']], flush=True)
    note = call('notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': 'GUI question', 'Back': 'GUI answer'})
    print('PASS native note', note['noteId'], flush=True)
    if scenario == 'editors':
        from anki.collection import ExperimentFlag
        for svelte in [False, True]:
            aqt.mw.col._experiments[str(ExperimentFlag.SVELTE_EDITOR)] = svelte
            import base64
            open_media = ('open-' + str(svelte) + '.txt').lower()
            assert old('guiAddCards', note={'modelName': 'Basic', 'deckName': 'Default',
                       'fields': {'Front': '', 'Back': ''},
                       'audio': [{'filename': open_media, 'data': base64.b64encode(b'open media').decode(),
                                  'fields': []}]}) == 0
            assert (Path(aqt.mw.col.media.dir()) / open_media).read_bytes() == b'open media'
            empty = call('editors.openAdd')
            assert empty['noteId'] is None and not any(empty['fields'].values()), empty
            draft = call('editors.openAdd', note={'noteType': {'name': 'Basic'}, 'deck': {'name': 'Default'}, 'fields': {'Front': 'Draft question ' + str(svelte), 'Back': 'Draft answer'}, 'tags': ['gui-smoke']})
            assert draft['fields']['Front'] == 'Draft question ' + str(svelte), draft
            assert draft['noteId'] is None, draft
            print('PASS open Add', draft['variant'], flush=True)
            updated = call('editors.updateDraft', editorId=draft['id'], mode='append', patch={'fields': {'Back': ' appended'}, 'tags': ['extra']})
            assert updated['fields']['Back'] == 'Draft answer appended', updated
            import base64
            media_name = ('draft-' + str(svelte) + '.txt').lower()
            assert old('guiAddNoteSetData', note={'fields': {'Back': ' legacy'},
                       'audio': [{'filename': media_name, 'data': base64.b64encode(b'draft media').decode(),
                                  'fields': ['Back']}]}, append=True)
            assert (Path(aqt.mw.col.media.dir()) / media_name).read_bytes() == b'draft media'
            print('PASS update Add', updated['variant'], flush=True)
            dialog = owner.runtime.gui.add_dialog()
            before = aqt.mw.col.note_count()
            if hasattr(dialog.editor, 'note'):
                ready = [False]
                def probe():
                    dialog.editor.web.evalWithCallback('typeof saveNow === "function"', lambda v: ready.__setitem__(0, bool(v)))
                    return ready[0]
                wait_until(probe)
                dialog.add_current_note()
            else:
                result(owner.runtime.gui.javascript(dialog.editor, 'document.querySelectorAll("button").forEach(button => { if (button.textContent.trim() === "Add") button.click(); }); return true;'))
            wait_until(lambda: aqt.mw.col.note_count() == before + 1)
            wait_until(lambda: aqt.mw._background_op_count == 0)
            saved = aqt.mw.col.find_notes('"Draft question ' + str(svelte) + '"')
            assert len(saved) == 1 and aqt.mw.col.get_note(saved[0])['Back'] == 'Draft answer appended legacy[sound:' + media_name + ']'
            print('PASS save Add', draft['variant'], flush=True)
            if not hasattr(dialog.editor, 'note'):
                wait_until(lambda: not any(result(owner.runtime.gui.javascript(dialog.editor, 'return getNoteInfo().fields;'))))
            aqt.dialogs.closeAll(onsuccess=lambda: None)
            def add_closed():
                from aqt.qt import QMessageBox
                # Native Add may still consider its reset draft dirty. The saved
                # note was asserted above; discard only leftover test input.
                for window in app.topLevelWidgets():
                    if isinstance(window, QMessageBox) and window.isVisible():
                        discard = window.button(QMessageBox.StandardButton.Discard)
                        if discard is not None:
                            print('Discarding residual Add draft:', window.text(), flush=True)
                            discard.click()
                return aqt.dialogs.allClosed()
            wait_until(add_closed)
            print('PASS close Add', flush=True)
    if scenario == 'browser':
        call('noteTypes.editStructure', noteType={'name': 'Basic'}, edits=[{'op': 'addTemplate',
             'template': {'name': 'Reverse compatibility', 'questionHtml': '{{Back}}', 'answerHtml': '{{Front}}'}}])
        selection = call('browser.open', query='nid:' + note['noteId'])
        selection = call('browser.select', noteIds=[note['noteId']])
        assert selection['selectedNoteIds'] == [note['noteId']], selection
        siblings = {str(id) for id in aqt.mw.col.get_note(int(note['noteId'])).card_ids()}
        assert set(selection['selectedCardIds']) == siblings
        assert call('browser.getSelection')['selectedNoteIds'] == [note['noteId']]
        assert old('guiSelectCard', card=int(note['cardIds'][0]))
        assert old('guiSelectedNotes') == [int(note['noteId'])]
        # Historical guiSelectNote accepts a CARD ID despite its name.
        selected_card = max(siblings, key=int)
        assert old('guiSelectNote', note=int(selected_card))
        assert call('browser.getSelection')['selectedNoteIds'] == [note['noteId']]
        assert call('browser.getSelection')['selectedCardIds'] == [selected_card]
        print('PASS browser search/selection', flush=True)
        call('notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': 'Second GUI question'})
        browser = owner.runtime.gui.browser()
        expected_cards = set(aqt.mw.col.find_cards(''))
        # Distinct due days avoid relying on native tie-breaking between sibling cards.
        for index, id in enumerate(sorted(expected_cards)):
            call('scheduling.setDueDate', cardIds=[str(id)], days=str(index + 1))
        def browser_items():
            model = browser.table._model
            return list(model.get_items([model.index(row, 0) for row in range(model.rowCount())]))
        ascending = None
        for direction in ['ascending', 'descending', 'ascending', 'descending']:
            call('browser.open', query='', sort={'column': 'cardDue', 'direction': direction})
            assert browser.table._state.sort_column == 'cardDue'
            assert browser.table._state.sort_backwards == (direction == 'descending')
            wait_until(lambda: set(browser_items()) == expected_cards)
            items = browser_items()
            if direction == 'ascending':
                ascending = items
            else:
                assert items == ascending[::-1], (items, ascending)
        print('PASS browser numeric sorting both directions', flush=True)
        legacy_reply = result(owner.handler_async({'action': 'guiBrowse', 'version': 6, 'params': {'query': ''}}))
        assert legacy_reply == {'result': sorted(aqt.mw.col.find_cards('')), 'error': None}, legacy_reply
        print('PASS legacy browser completion', flush=True)
        result(owner.runtime.gui.javascript(owner.runtime.gui.browser().editor, 'await saveNow(); return true;'))
        aqt.dialogs.closeAll(onsuccess=lambda: None)
        wait_until(aqt.dialogs.allClosed)
    if scenario == 'custom':
        editor = call('editors.openNote', noteId=note['noteId'])
        assert editor['noteId'] == note['noteId'], editor
        print('PASS custom editor', flush=True)
        dialog = aqt.dialogs._dialogs[Edit.dialog_registry_tag][1]
        ready = [False]
        def custom_ready():
            dialog.editor.web.evalWithCallback('typeof saveNow === "function"', lambda v: ready.__setitem__(0, bool(v)))
            return ready[0]
        wait_until(custom_ready)
        dialog.editor.web.eval('setFields(["Front", "Back"], ["Edited GUI question", "GUI answer"]);')
        saved = []
        dialog.editor.call_after_note_saved(lambda: saved.append(True))
        wait_until(lambda: bool(saved))
        assert aqt.mw.col.get_note(int(note['noteId']))['Front'] == 'Edited GUI question'
        assert old('guiEditNote', note=int(note['noteId'])) is None
        assert owner.runtime.gui.editors
        print('PASS custom editor save', flush=True)
        aqt.dialogs.closeAll(onsuccess=lambda: None)
        wait_until(aqt.dialogs.allClosed)
    if scenario == 'reviewer':
        call('notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': 'Legacy reviewer question'})
        assert old('guiDeckOverview', name='Default')
        assert aqt.mw.state == 'overview'
        assert old('guiDeckReview', name='Default')
        call('application.navigate', view='review', deck={'name': 'Default'})
        wait_until(lambda: aqt.mw.reviewer.card and aqt.mw.reviewer.state == 'question')
        review = call('reviewer.get')
        assert old('guiReviewActive')
        assert old('guiCurrentCard')['cardId'] == int(review['card']['id'])
        assert call('reviewer.startTimer', stateToken=review['stateToken']) == {'changed': True}
        assert old('guiStartCardTimer')
        call('reviewer.showAnswer', stateToken=review['stateToken'])
        wait_until(lambda: aqt.mw.reviewer.state == 'answer')
        review = call('reviewer.get')
        assert call('reviewer.showQuestion', stateToken=review['stateToken']) == {'changed': True}
        wait_until(lambda: aqt.mw.reviewer.state == 'question')
        assert old('guiShowAnswer')
        wait_until(lambda: aqt.mw.reviewer.state == 'answer')
        assert old('guiShowQuestion')
        wait_until(lambda: aqt.mw.reviewer.state == 'question')
        assert old('guiShowAnswer')
        wait_until(lambda: aqt.mw.reviewer.state == 'answer')
        review = call('reviewer.get')
        # Exercise real reviewer audio plumbing on a silent card. Audible output
        # remains explicitly deferred; no audio device or player assertion here.
        assert call('reviewer.playAudio', stateToken=review['stateToken']) == {'changed': True}
        assert old('guiPlayAudio')
        veto = lambda choice, reviewer, card: (False, choice[1])
        aqt.gui_hooks.reviewer_will_answer_card.append(veto)
        try:
            call('reviewer.answer', stateToken=review['stateToken'], rating='good')
            raise AssertionError('Vetoed answer succeeded')
        except Exception as error:
            assert getattr(error, 'kind', None) == 'vetoed', error
        finally:
            aqt.gui_hooks.reviewer_will_answer_card.remove(veto)
        print('PASS reviewer veto', flush=True)
        answered = call('reviewer.answer', stateToken=review['stateToken'], rating='good')
        assert answered['reviewId'] is not None, answered
        assert aqt.mw.col.db.scalar('select ease from revlog where id=?', int(answered['reviewId'])) == 3
        print('PASS reviewer native answer', flush=True)
        wait_until(lambda: aqt.mw.reviewer.card and aqt.mw.reviewer.state == 'question')
        legacy_card = aqt.mw.reviewer.card.id
        assert old('guiShowAnswer')
        wait_until(lambda: aqt.mw.reviewer.state == 'answer')
        assert old('guiAnswerCard', ease=3)
        assert aqt.mw.col.db.scalar('select ease from revlog where cid=? order by id desc limit 1', legacy_card) == 3
        assert old('guiDeckBrowser') is None
        assert aqt.mw.state == 'deckBrowser'
        call('application.navigate', view='deckBrowser')
    if scenario == 'imports':
        from aqt.import_export.import_dialog import ImportDialog
        csv = base / 'sample.csv'
        csv.write_text('imported front,imported back\n')
        def visible_import(path):
            return next((w for w in app.topLevelWidgets()
                         if isinstance(w, ImportDialog) and w.isVisible()
                         and w.args.path == str(path)), None)
        def import_clicker(dialog):
            clicked = False
            probing = False
            def checked(value):
                nonlocal clicked, probing
                probing = False
                clicked = clicked or bool(value)
            def probe():
                nonlocal probing
                if not clicked and not probing and dialog.web is not None:
                    probing = True
                    # Probe directly rather than accumulating evaluations in
                    # Anki's DOM-ready queue. Permit only one pending probe.
                    dialog.web.page().runJavaScript('(() => {const button = document.querySelector(".import")?.closest("button"); if (!button || button.disabled) return false; button.click(); return true;})()', checked)
                return clicked
            return probe
        def start_import(path, allow_error=False):
            wait_until(lambda: aqt.mw._background_op_count == 0)
            handle = result(owner.runtime.dispatcher.invoke('application.importFile', {'path': str(path)}))
            pending = owner.runtime.operations.completions[handle['operationId']]
            wait_until(lambda: pending.done or visible_import(path), description='Open import ' + path.name)
            if pending.done and not allow_error:
                result(pending)
            dialog = visible_import(path)
            assert dialog is not None, ('Import completed without a dialog', pending.error)
            return handle, dialog
        handle, dialog = start_import(csv)
        # Cancelling before WebChannel initialization tears down its bridge while
        # the page is still loading, producing an unrelated JavaScript error.
        wait_until(lambda: dialog.web._domDone)
        result(owner.runtime.invoke('operations.cancel', {'operationId': handle['operationId']}))
        pending = owner.runtime.operations.completions[handle['operationId']]
        wait_until(lambda: pending.done)
        assert getattr(pending.error, 'kind', None) == 'cancelled', pending.error
        print('PASS import cancellation', flush=True)
        handle, dialog = start_import(csv)
        click_import = import_clicker(dialog)
        try:
            wait_until(lambda: owner.runtime.operations.completions[handle["operationId"]].done or click_import())
        except TimeoutError:
            body = []
            dialog.web.evalWithCallback('document.body.innerText', body.append)
            wait_until(lambda: bool(body))
            print('IMPORT PAGE:', body[0], flush=True)
            print('IMPORT OPERATION:', owner.runtime.operations.get(handle['operationId']), flush=True)
            raise
        result(owner.runtime.operations.completions[handle['operationId']])
        assert aqt.mw.col.find_notes('imported')
        dialog.reject()
        print('PASS import success', flush=True)
        legacy_csv = base / 'legacy.csv'
        legacy_csv.write_text('legacy imported front,legacy imported back\n')
        wait_until(lambda: aqt.mw._background_op_count == 0,
                   description='Settle native work before legacy import')
        print('START legacy import', flush=True)
        legacy_import = owner.handler_async({'action': 'guiImportFile', 'version': 6,
                                             'params': {'path': str(legacy_csv)}}, barrier=True)
        wait_until(lambda: legacy_import.done or visible_import(legacy_csv),
                   description='Open legacy import dialog')
        if legacy_import.done:
            raise AssertionError(('Legacy import completed before opening its dialog', result(legacy_import)))
        dialog = visible_import(legacy_csv)
        print('PASS legacy import dialog opened', flush=True)
        click_import = import_clicker(dialog)
        wait_until(lambda: legacy_import.done or click_import(), description='Click legacy Import button')
        print('WAIT legacy import completion', flush=True)
        wait_until(lambda: legacy_import.done, description='Complete legacy native import')
        assert result(legacy_import) == {'result': None, 'error': None}
        assert aqt.mw.col.find_notes('"legacy imported front"')
        dialog.reject()
        print('PASS legacy import completion', flush=True)
        broken = base / 'broken.apkg'
        broken.write_bytes(b'not a package')
        handle, dialog = start_import(broken, allow_error=True)
        pending = owner.runtime.operations.completions[handle['operationId']]
        click_import = import_clicker(dialog)
        def failed_import_finished():
            if not pending.done:
                click_import()
            return pending.done
        wait_until(failed_import_finished)
        assert getattr(pending.error, 'kind', None) == 'ioError', pending.error
        assert 'invalid Zip archive' in str(pending.error), pending.error
        dialog.reject()
        print('PASS expected invalid-package import failure (dialog closed automatically)', flush=True)
    if scenario == 'profiles':
        import inspect
        from aqt import gui_hooks
        from aqt.qt import QMessageBox
        from plugin import util
        from plugin.web import WebRequest
        import json
        # Use native add-on configuration persistence in this disposable base.
        addon = Path(aqt.mw.addonManager.addonsFolder('plugin'))
        addon.mkdir(exist_ok=True)
        (addon / 'config.json').write_text(json.dumps(util.DEFAULT_CONFIG), encoding='utf-8')
        for protocol, choice, ignore in (('v1', 'yes', False), ('legacy', 'no', True)):
            origin = 'https://permission-' + protocol + '.example'
            body = ({'jsonrpc': '2.0', 'id': 1, 'method': 'access.requestPermission', 'params': {}}
                    if protocol == 'v1' else {'action': 'requestPermission', 'version': 6})
            reply = owner.server.handlerWrapper(WebRequest(b'POST', {b'origin': origin.encode()},
                                                         json.dumps(body).encode(),
                                                         b'/api/v1' if protocol == 'v1' else b'/'))
            assert isinstance(reply, Deferred) and not reply.done
            # Returning here proves the prompt did not enter a nested event loop.
            wait_until(lambda: any(isinstance(w, QMessageBox) and w.isVisible() for w in app.topLevelWidgets()))
            prompt = next(w for w in app.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible())
            prompt.checkBox().setChecked(ignore)
            prompt.button(QMessageBox.StandardButton.Yes if choice == 'yes' else QMessageBox.StandardButton.No).click()
            response = json.loads(result(reply).split(b'\r\n\r\n', 1)[1])
            assert response['result']['permission'] == ('granted' if choice == 'yes' else 'denied')
            key = 'webCorsOriginList' if choice == 'yes' else 'ignoreOriginList'
            assert origin in util.setting(key)
        print('PASS native permission prompts and persistence for both protocols', flush=True)
        # Check real GUI sync dependencies without credentials or network I/O.
        # Signature checks do not certify full-sync or media completion.
        for function, args, kwargs in (
            (aqt.mw.taskman.with_progress, (lambda: None, lambda future: None), {}),
            (aqt.mw.taskman.run_in_background, (aqt.mw.col.media_sync_status, lambda future: None), {'uses_collection': False}),
            (aqt.mw.reopen, (), {'after_full_sync': True}),
            (aqt.mw._refresh_after_sync, (), {}),
            (aqt.mw.create_backup_now, (), {}),
            (aqt.mw.media_syncer.start_monitoring, (), {}),
            (aqt.mw.pm.set_host_number, (0,), {}),
            (aqt.mw.pm.set_current_sync_url, (None,), {}),
            (gui_hooks.collection_will_temporarily_close, (aqt.mw.col,), {}),
        ):
            inspect.signature(function).bind(*args, **kwargs)
        old_session = owner.runtime.session
        assert 'User 1' in [profile['name'] for profile in call('profiles.list')]
        assert call('profiles.getActive')['name'] == 'User 1'
        try:
            call('collection.sync')
            raise AssertionError('Sync without credentials succeeded')
        except Exception as error:
            assert getattr(error, 'kind', None) == 'authenticationRequired', error
        sync_reply = result(owner.handler_async({'action': 'sync', 'version': 6}))
        assert 'auth not configured' in sync_reply['error'], sync_reply
        assert old('getActiveProfile') == 'User 1'
        assert 'User 1' in old('getProfiles')
        aqt.mw.pm.create('Other')
        switched = call('profiles.switch', name='Other')
        assert switched['session'] != old_session
        assert old('loadProfile', name='User 1')
        assert call('profiles.getActive')['name'] == 'User 1'
        assert old('loadProfile', name='missing profile') is False
        assert call('collection.refresh', target='cachesAndWindows') == {'changed': True}
        assert old('reloadCollection') is None
        assert old('guiCheckDatabase')
        created = call('notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': 'Undo GUI note'})
        assert old('guiUndo')
        assert not aqt.mw.col.find_notes('nid:' + created['noteId'])
        print('PASS profile switch', flush=True)
    if scenario == 'colpkg':
        from aqt import utils
        backup_dir = base / 'backups'
        backup_dir.mkdir()
        aqt.mw.col.create_backup(backup_folder=str(backup_dir), force=True, wait_for_completion=True)
        package = next(backup_dir.glob('*.colpkg'))
        original_ask = utils.askUser
        utils.askUser = lambda *args, **kwargs: False
        try:
            call('application.importFile', path=str(package))
            raise AssertionError('Cancelled replacement succeeded')
        except Exception as error:
            assert getattr(error, 'kind', None) == 'cancelled', error
        utils.askUser = lambda *args, **kwargs: True
        previous = owner.runtime.session
        try:
            completed = call('application.importFile', path=str(package))
            assert completed == {'completed': True}, completed
            assert owner.runtime.session != previous
            assert call('notes.get', id=note['noteId'])['fields']['Front'] == 'GUI question'
        finally:
            utils.askUser = original_ask
        print('PASS collection package cancellation/import/reopen/session invalidation', flush=True)
    if scenario in ('exit', 'legacy-exit'):
        import json
        import threading
        import urllib.request
        from plugin import util
        setting = util.setting
        util.setting = lambda name: 0 if name == 'webBindPort' else setting(name)
        owner.startWebServer()
        port = owner.server.sock.getsockname()[1]
        replies = []
        def request_exit():
            try:
                path = '/api/v1' if scenario == 'exit' else '/'
                payload = ({'jsonrpc': '2.0', 'id': 1, 'method': 'application.exit'} if scenario == 'exit'
                           else {'action': 'guiExitAnki', 'version': 6})
                request = urllib.request.Request('http://127.0.0.1:' + str(port) + path,
                    json.dumps(payload).encode(),
                    {'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=15) as response:
                    replies.append(json.load(response))
            except Exception as error:
                replies.append(error)
        thread = threading.Thread(target=request_exit, daemon=True)
        closed = []
        aqt.gui_hooks.profile_will_close.append(lambda: closed.append(True))
        thread.start()
        QTimer.singleShot(30000, lambda: app.exit(1))
        code = app.exec()
        thread.join(timeout=1)
        assert code == 0 and closed and len(replies) == 1, (code, closed, replies)
        assert replies[0]['result'] == ({'accepted': True} if scenario == 'exit' else None), replies
        print('PASS HTTP reply and native exit', flush=True)
    assert not unhandled, unhandled
    print('GUI SMOKE PASSED', flush=True)
except BaseException:
    import traceback
    print(traceback.format_exc(), flush=True)
    os._exit(1)
os._exit(0)

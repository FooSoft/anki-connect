#!/usr/bin/env python3
"""Optional real-GUI smoke checks; always creates disposable Anki profiles.

Run with the pinned environment and a working display:
    python tools/smoke_gui.py [all|editors|browser|custom|reviewer|imports|profiles|colpkg|exit]

No sync credentials are used. Profiles/files are left under /tmp for diagnostics.
Processes exit after checks to isolate native Qt/WebEngine teardown; application
shutdown is verified separately by the exit scenario.
"""
import os
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Each scenario runs in a fresh process/profile to isolate Qt WebEngine teardown.
scenario = sys.argv[1] if len(sys.argv) > 1 else 'all'
scenarios = ['editors', 'browser', 'custom', 'reviewer', 'imports', 'profiles', 'colpkg', 'exit']
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
def wait_until(fn, timeout=30):
    deadline = time.monotonic() + timeout
    while not fn():
        if time.monotonic() > deadline:
            raise TimeoutError('GUI wait expired')
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
    wait_until(lambda: aqt.mw._background_op_count == 0)
    value = result(owner.runtime.dispatcher.invoke(method, params))
    if isinstance(value, dict) and 'operationId' in value:
        value = result(owner.runtime.operations.completions[value['operationId']])
    return value
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
            empty = call('editors.openAdd')
            assert empty['noteId'] is None and not any(empty['fields'].values()), empty
            draft = call('editors.openAdd', note={'noteType': {'name': 'Basic'}, 'deck': {'name': 'Default'}, 'fields': {'Front': 'Draft question ' + str(svelte), 'Back': 'Draft answer'}, 'tags': ['gui-smoke']})
            assert draft['fields']['Front'] == 'Draft question ' + str(svelte), draft
            assert draft['noteId'] is None, draft
            print('PASS open Add', draft['variant'], flush=True)
            updated = call('editors.updateDraft', editorId=draft['id'], mode='append', patch={'fields': {'Back': ' appended'}, 'tags': ['extra']})
            assert updated['fields']['Back'] == 'Draft answer appended', updated
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
            print('PASS save Add', draft['variant'], flush=True)
            if not hasattr(dialog.editor, 'note'):
                wait_until(lambda: not any(result(owner.runtime.gui.javascript(dialog.editor, 'return getNoteInfo().fields;'))))
            aqt.dialogs.closeAll(onsuccess=lambda: None)
            wait_until(aqt.dialogs.allClosed)
            print('PASS close Add', flush=True)
    if scenario == 'browser':
        selection = call('browser.open', query='nid:' + note['noteId'])
        selection = call('browser.select', noteIds=[note['noteId']])
        assert selection['selectedNoteIds'] == [note['noteId']], selection
        print('PASS browser search/selection', flush=True)
        call('notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': 'Second GUI question'})
        browser = owner.runtime.gui.browser()
        ascending = None
        for direction in ['ascending', 'descending', 'ascending', 'descending']:
            call('browser.open', query='', sort={'column': 'cardDue', 'direction': direction})
            assert browser.table._state.sort_column == 'cardDue'
            assert browser.table._state.sort_backwards == (direction == 'descending')
            model = browser.table._model
            items = list(model.get_items([model.index(row, 0) for row in range(model.rowCount())]))
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
        print('PASS custom editor save', flush=True)
        aqt.dialogs.closeAll(onsuccess=lambda: None)
        wait_until(aqt.dialogs.allClosed)
    if scenario == 'reviewer':
        call('application.navigate', view='review', deck={'name': 'Default'})
        wait_until(lambda: aqt.mw.reviewer.card and aqt.mw.reviewer.state == 'question')
        review = call('reviewer.get')
        call('reviewer.showAnswer', stateToken=review['stateToken'])
        wait_until(lambda: aqt.mw.reviewer.state == 'answer')
        review = call('reviewer.get')
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
        print('PASS reviewer native answer', flush=True)
        call('application.navigate', view='deckBrowser')
    if scenario == 'imports':
        from aqt.import_export.import_dialog import ImportDialog
        csv = base / 'sample.csv'
        csv.write_text('imported front,imported back\n')
        def start_import(path):
            wait_until(lambda: aqt.mw._background_op_count == 0)
            handle = result(owner.runtime.dispatcher.invoke('application.importFile', {'path': str(path)}))
            pending = owner.runtime.operations.completions[handle['operationId']]
            wait_until(lambda: pending.done or any(isinstance(w, ImportDialog) and w.isVisible() for w in app.topLevelWidgets()))
            if pending.done:
                result(pending)
            dialog = next(w for w in app.topLevelWidgets() if isinstance(w, ImportDialog) and w.isVisible())
            return handle, dialog
        handle, dialog = start_import(csv)
        result(owner.runtime.invoke('operations.cancel', {'operationId': handle['operationId']}))
        pending = owner.runtime.operations.completions[handle['operationId']]
        wait_until(lambda: pending.done)
        assert getattr(pending.error, 'kind', None) == 'cancelled', pending.error
        print('PASS import cancellation', flush=True)
        handle, dialog = start_import(csv)
        clicked = [False]
        def click_import():
            dialog.web.evalWithCallback('(() => {const button = document.querySelector(".import")?.closest("button"); if (!button) return false; button.click(); return true;})()', lambda v: clicked.__setitem__(0, clicked[0] or bool(v)))
            return clicked[0]
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
        broken = base / 'broken.apkg'
        broken.write_bytes(b'not a package')
        handle, dialog = start_import(broken)
        pending = owner.runtime.operations.completions[handle['operationId']]
        clicked = [False]
        def failed_import_finished():
            if not clicked[0] and not pending.done:
                dialog.web.evalWithCallback('(() => {const button = document.querySelector(".import")?.closest("button"); if (!button) return false; button.click(); return true;})()', lambda v: clicked.__setitem__(0, clicked[0] or bool(v)))
            return pending.done
        wait_until(failed_import_finished)
        assert getattr(pending.error, 'kind', None) == 'ioError', pending.error
        dialog.reject()
        print('PASS import failure', flush=True)
    if scenario == 'profiles':
        old = owner.runtime.session
        aqt.mw.pm.create('Other')
        switched = call('profiles.switch', name='Other')
        assert switched['session'] != old
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
    if scenario == 'exit':
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
                request = urllib.request.Request('http://127.0.0.1:' + str(port) + '/api/v1',
                    json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'application.exit'}).encode(),
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
        assert replies[0]['result'] == {'accepted': True}, replies
        print('PASS HTTP reply and native exit', flush=True)
    assert not unhandled, unhandled
    print('GUI SMOKE PASSED', flush=True)
except BaseException:
    import traceback
    print(traceback.format_exc(), flush=True)
    os._exit(1)
os._exit(0)

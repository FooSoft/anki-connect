#!/usr/bin/env python3
"""Real-GUI smoke checks, run by tools/test.sh/tools/test.ps1 by default; uses disposable Anki profiles.

Run with the pinned environment and a working display:
    python tools/smoke_gui.py [all|editors|browser|browser-startup|custom|reviewer|imports|profiles|colpkg|obsidian|mining-clients|exit|legacy-exit]

No sync credentials are used. Profiles/files remain in the OS temp directory for diagnostics.
Processes exit after checks to isolate native Qt/WebEngine teardown; application
shutdown is verified separately by the exit scenario.
"""
import contextlib
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Each scenario runs in a fresh process/profile to isolate Qt WebEngine teardown.
scenario = sys.argv[1] if len(sys.argv) > 1 else 'all'
scenarios = ['editors', 'browser', 'browser-startup', 'custom', 'reviewer', 'imports', 'profiles', 'colpkg', 'obsidian', 'mining-clients', 'exit', 'legacy-exit']
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
import inspect
import anki.lang
import aqt
if hasattr(anki.lang, 'set_lang'):
    if len(inspect.signature(anki.lang.set_lang).parameters) == 1:
        anki.lang.set_lang('en')
    else:
        # 2.1.22 to 2.1.44 take the catalog folder.
        anki.lang.set_lang('en', aqt.locale_dir())
elif 'locale_dir' in inspect.signature(anki.lang.setLang).parameters:
    anki.lang.setLang('en', aqt.locale_dir())
else:
    anki.lang.setLang('en')
from aqt.profiles import ProfileManager
if hasattr(ProfileManager, '_setDefaultLang'):
    # 2.1.15 opens a first-run language dialog before any QApplication exists.
    ProfileManager._setDefaultLang = lambda self: self.setLang('en')
base = Path(tempfile.mkdtemp(prefix='anki-api-gui-'))
pm = ProfileManager(base)
pm.setupMeta()
pm.profiles()
pm.load(pm.profiles()[0])
pm.meta['firstRun'] = False
pm.meta['defaultLang'] = 'en'
# Keep unattended tests offline and free of startup update dialogs.
if hasattr(pm, 'set_update_check'):
    pm.set_update_check(False)
else:
    pm.meta['updates'] = False
if hasattr(pm, 'set_check_for_addon_updates'):
    pm.set_check_for_addon_updates(False)
pm.profile['autoSync'] = False
pm.profile['numBackups'] = 0
pm.save()
pm.db.close()
import aqt
import aqt.main
from aqt.qt import QEventLoop, QTimer
if not hasattr(ProfileManager, 'set_check_for_addon_updates'):
    # Earlier releases check add-on updates daily, without a setting. From 2.1.66
    # the application update check follows as on_done, unconditionally in 23.10-24.6.
    aqt.main.AnkiQt.maybe_check_for_addon_updates = lambda *args, **kwargs: None
app = aqt._run(['anki', '-b', str(base), '-p', 'User 1', '-l', 'en'], exec=False)


def finish(code):
    # os._exit skips Anki's teardown, which would orphan mpv and leave the profile.
    import shutil
    try:
        aqt.sound.cleanup_audio()
    except Exception:
        pass
    shutil.rmtree(base, ignore_errors=True)
    os._exit(code)


from plugin import AnkiConnect, Edit
from plugin.protocol import Deferred
owner = AnkiConnect()
if Edit is not None:
    Edit.register_with_anki()
owner.runtime.register_hooks()
unhandled = []
def upstream_race(error, traceback):
    """Anki 23.10+ measures the bottom bar while leaving review, racing its re-render."""
    import traceback as tb
    frames = tb.extract_tb(traceback)
    return (isinstance(error, TypeError) and frames and frames[-1].name == 'animate_height'
            and frames[-1].filename.replace('\\', '/').endswith('aqt/toolbar.py'))
def exception_hook(kind, error, traceback):
    import traceback as tb
    if upstream_race(error, traceback):
        print('KNOWN UPSTREAM RACE:', error, flush=True)
        return
    unhandled.append(error)
    print('UNHANDLED GUI ERROR:', ''.join(tb.format_exception(kind, error, traceback)), flush=True)
sys.excepthook = exception_hook
def idle():
    # Before 2.1.45, collection work ran on the main thread without a counter.
    return getattr(aqt.mw, '_background_op_count', 0) == 0
def pump():
    # Qt WebEngine 5.15-6.5 defers browser-side tasks while bare processEvents
    # calls run outside an event loop, stalling pages for seconds or indefinitely.
    loop = QEventLoop()
    QTimer.singleShot(10, loop.quit)
    loop.exec()
def wait_until(fn, timeout=30, description='GUI wait'):
    deadline = time.monotonic() + timeout
    while not fn():
        if time.monotonic() > deadline:
            windows = [(type(window).__name__, window.windowTitle())
                       for window in app.topLevelWidgets() if window.isVisible()]
            print('TIMEOUT:', description, 'background operations:', getattr(aqt.mw, '_background_op_count', None),
                  'visible windows:', windows, flush=True)
            raise TimeoutError(description + ' expired')
        pump()
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
        wait_until(idle)
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
            pump()
def old(action, *, http_v2=False, **params):
    deadline = time.monotonic() + 30
    while True:
        wait_until(idle)
        previous = set(owner.runtime.operations.records)
        request = {'action': action, 'version': 2 if http_v2 else 6, 'params': params}
        if http_v2:
            import json
            from plugin.web import WebRequest
            raw = result(owner.server.handlerWrapper(WebRequest(b'POST', {}, json.dumps(request).encode())))
            # Yomitan parses every version-2 response as JSON, including null.
            value = json.loads(raw.split(b'\r\n\r\n', 1)[1])
            reply = value if isinstance(value, dict) and 'error' in value else {'result': value, 'error': None}
        else:
            reply = result(owner.handler_async(request))
        if (reply['error'] == 'A collection operation is active.'
                and time.monotonic() < deadline):
            pump()
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
            pump()
def v6(action, **params):
    return {'action': action, 'version': 6, 'params': params}
@contextlib.contextmanager
def emacs_http():
    """Serve real HTTP and yield a sender like Emacs clients' curl and url.el: one
    origin-less POST per request, sent as soon as the previous reply arrives."""
    import json
    import threading
    import urllib.request
    from plugin import util
    setting = util.setting
    util.setting = lambda name: 0 if name == 'webBindPort' else setting(name)
    owner.startWebServer()
    port = owner.server.sock.getsockname()[1]
    def send(request):
        replies = []
        def post():
            try:
                with urllib.request.urlopen('http://127.0.0.1:%d' % port, json.dumps(request).encode(), timeout=30) as response:
                    replies.append(json.load(response))
            except BaseException as error:
                replies.append(error)
        thread = threading.Thread(target=post, daemon=True)
        thread.start()
        wait_until(lambda: bool(replies), timeout=35, description='Emacs HTTP request')
        thread.join(timeout=1)
        assert not isinstance(replies[0], BaseException), replies
        return replies[0]
    try:
        yield send
    finally:
        owner.server.close()
        owner.timer.stop()
        util.setting = setting
def supports(step, *methods):
    """Whether this release offers every method; otherwise report why step is skipped."""
    for method in methods:
        reason = owner.runtime.capability_reason(method)
        if reason:
            print('SKIP', step + ':', method, 'is unavailable:', reason, flush=True)
            return False
    return True
def editor_variants():
    """Legacy editor, then the experimental Svelte editor where this release has one."""
    try:
        from anki.collection import ExperimentFlag
    except ImportError:
        return [False]
    return [False, True]
def use_editor(svelte):
    if editor_variants() != [False]:
        from anki.collection import ExperimentFlag
        aqt.mw.col._experiments[str(ExperimentFlag.SVELTE_EDITOR)] = svelte
# Editors of every release define saveNow; getNoteInfo appears with the 26.08 editors.
SAVE_READY = 'typeof saveNow === "function"'
def save_editor(editor):
    result(owner.runtime.gui.javascript(editor, 'await saveNow(); return true;', ready=SAVE_READY))
def page_ready(web, expression):
    """A wait_until probe with at most one recent evaluation; floods crash Qt 6.2-6.5.

    A navigation can drop a pending callback, so a probe is reissued after two seconds.
    """
    state = {'ready': False, 'sent': None}
    def answered(value):
        state['ready'], state['sent'] = state['ready'] or bool(value), None
    def probe():
        if not state['ready'] and (state['sent'] is None or time.monotonic() - state['sent'] > 2):
            state['sent'] = time.monotonic()
            web.evalWithCallback(expression, answered)
        return state['ready']
    return probe
def staged_fields(note_id, values):
    """JavaScript changing the shown fields as typing does, leaving the save to the editor."""
    import json
    names = list(aqt.mw.col.get_note(int(note_id)).keys())
    # Before 26.08 editors set fields from [name, html] pairs and report typing
    # through key:ord:nid:html bridge commands; a later save flushes the shown fields.
    code = ('if (setFields.length > 1) { setFields(' + json.dumps(names) + ', ' + json.dumps(values) + '); } else { '
            + 'setFields(' + json.dumps([list(pair) for pair in zip(names, values)]) + '); '
            + ' '.join('pycmd(' + json.dumps('key:%d:%s:%s' % (ord, note_id, value)) + ');'
                       for ord, value in enumerate(values)) + ' } return true;')
    return code
def browser_rows(browser):
    table = getattr(browser, 'table', None)
    if table is None:
        # Before 2.1.45 the browser listed card IDs only.
        return list(browser.model.cards)
    model = table._model
    return list(model.get_items([model.index(row, 0) for row in range(model.rowCount())]))
def browser_sorting(browser):
    table = getattr(browser, 'table', None)
    if table is None:
        return aqt.mw.col.get_config('sortType'), bool(aqt.mw.col.get_config('sortBackwards', False))
    return table._state.sort_column, table._state.sort_backwards
def current_search(browser):
    if hasattr(browser, 'current_search'):
        return browser.current_search()
    return browser.form.searchEdit.lineEdit().text()
try:
    wait_until(lambda: aqt.mw.col is not None and aqt.mw.state == 'deckBrowser')
    print('PASS loaded disposable profile', base, flush=True)
    print('DESCRIBE', [m for m in owner.runtime.describe()['methods'] if not m['available']], flush=True)
    note = call('notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': 'GUI question', 'Back': 'GUI answer'})
    print('PASS native note', note['noteId'], flush=True)
    if scenario == 'editors':
        for svelte in editor_variants():
            use_editor(svelte)
            import base64
            open_media = ('open-' + str(svelte) + '.txt').lower()
            assert old('guiAddCards', note={'modelName': 'Basic', 'deckName': 'Default',
                       'fields': {' front ': '', 'back': None}, 'tags': None, 'options': None,
                       'audio': [{'filename': open_media, 'data': base64.b64encode(b'open media').decode(),
                                  'fields': []}]}) == 0
            assert (Path(aqt.mw.col.media.dir()) / open_media).read_bytes() == b'open media'
            empty = call('editors.openAdd')
            assert empty['noteId'] is None and not any(empty['fields'].values()), empty
            draft = call('editors.openAdd', note={'noteType': {'name': 'Basic'}, 'deck': {'name': 'Default'}, 'fields': {'Front': 'Draft question ' + str(svelte), 'Back': 'Draft answer'}, 'tags': ['gui-smoke']})
            assert draft['fields']['Front'] == 'Draft question ' + str(svelte), draft
            assert draft['noteId'] is None, draft
            print('PASS open Add', draft['variant'], flush=True)
            for invalid, message in [
                ({'deckName': 'Missing'}, 'Deck "Missing" not found'),
                ({'modelName': 'Missing'}, 'Model "Missing" not found'),
                ({'fields': {'Missing': 'value'}}, 'Field "Missing" not found in current note'),
            ]:
                reply = result(owner.handler_async({'action': 'guiAddNoteSetData', 'version': 6,
                                                    'params': {'note': invalid, 'append': True}}))
                assert reply == {'result': None, 'error': message}, reply
            print('PASS historical draft errors', draft['variant'], flush=True)
            updated = call('editors.updateDraft', editorId=draft['id'], mode='append', patch={'fields': {'Back': ' appended'}, 'tags': ['extra']})
            assert updated['fields']['Back'] == 'Draft answer appended', updated
            import base64
            media_name = ('draft-' + str(svelte) + '.txt').lower()
            assert old('guiAddNoteSetData', note={'fields': {' back ': ' legacy'}, 'tags': ' gui-smoke extra ',
                       'audio': [{'filename': media_name, 'data': base64.b64encode(b'draft media').decode(),
                                  'fields': ' back '}]}, append='true')
            assert (Path(aqt.mw.col.media.dir()) / media_name).read_bytes() == b'draft media'
            print('PASS update Add', updated['variant'], flush=True)
            dialog = owner.runtime.gui.add_dialog()
            before = aqt.mw.col.note_count()
            if hasattr(dialog.editor, 'note'):
                # Draft loads queued before the page was ready replace focused fields, and
                # each replaced field reports a blur with its old text into the shared
                # unsaved note (ID 0 from 2.1.28). Blur the field and wait for the final
                # report so the Add click does not race messages that are still pending.
                save_editor(dialog.editor)
                wait_until(lambda: dialog.editor.note.fields[0] == 'Draft question ' + str(svelte))
                # Before 2.1.45 the Add button called addCards.
                (dialog.add_current_note if hasattr(dialog, "add_current_note") else dialog.addCards)()
            else:
                result(owner.runtime.gui.javascript(dialog.editor, 'document.querySelectorAll("button").forEach(button => { if (button.textContent.trim() === "Add") button.click(); }); return true;'))
            wait_until(lambda: aqt.mw.col.note_count() == before + 1)
            wait_until(idle)
            saved = aqt.mw.col.find_notes('"Draft question ' + str(svelte) + '"')
            assert len(saved) == 1 and aqt.mw.col.get_note(saved[0])['Back'] == 'Draft answer appended legacy[sound:' + media_name + ']'
            assert set(aqt.mw.col.get_note(saved[0]).tags) == {'gui-smoke', 'extra'}
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
        # Historical selection of a missing card clears the selection and succeeds.
        assert old('guiSelectCard', card=999) is True
        assert call('browser.getSelection')['selectedCardIds'] == []
        assert old('guiSelectNote', note=int(selected_card))
        print('PASS browser search/selection', flush=True)
        # anki-editor (Emacs) pushes the note shown in the Browser while its preview is open.
        browser = owner.runtime.gui.browser()
        wait_until(lambda: getattr(browser.editor.note, 'id', None) == int(note['noteId']),
                   description='Browser editor shows the selected note')
        if hasattr(browser, 'onTogglePreview'):
            browser.onTogglePreview()
            wait_until(lambda: getattr(browser, '_previewer', None) or getattr(browser, '_previewWindow', None),
                       description='Browser preview opens')
            # Push while the preview shows the note. Closing it later logs a native JS error
            # in 2.1.45-2.1.49, which look up 'previewButton' but name the button 'preview'.
            preview = getattr(browser._previewer, '_web', None) if hasattr(browser, '_previewer') else getattr(browser, '_previewWeb', None)
            if preview is not None:
                wait_until(page_ready(preview, 'typeof _showQuestion === "function" && !!document.getElementById("qa")'),
                           description='Browser preview page loads')
        result(owner.runtime.gui.javascript(browser.editor, staged_fields(note['noteId'], ['GUI question', 'Typed GUI answer']),
                                            ready=SAVE_READY))
        assert old('updateNoteFields', note={'id': int(note['noteId']), 'fields': {'Front': 'Pushed GUI question'}}) is None
        assert old('multi', actions=[{'action': 'addTags', 'params': {'notes': [int(note['noteId'])], 'tags': 'emacs'}}]) == [None]
        pushed = aqt.mw.col.get_note(int(note['noteId']))
        # The Browser saved typing before the push, then reloaded the pushed note.
        assert (pushed.fields, pushed.tags) == (['Pushed GUI question', 'Typed GUI answer'], ['emacs']), pushed.fields
        wait_until(lambda: browser.editor.note is None or browser.editor.note['Front'] == 'Pushed GUI question',
                   description='Browser editor reloads the pushed note')
        save_editor(browser.editor)
        wait_until(idle)
        saved = aqt.mw.col.get_note(int(note['noteId']))
        assert (saved.fields, saved.tags) == (pushed.fields, pushed.tags), (saved.fields, saved.tags)
        if hasattr(browser, 'onTogglePreview'):
            browser.onTogglePreview()
            wait_until(lambda: not (getattr(browser, '_previewer', None) or getattr(browser, '_previewWindow', None)),
                       description='Browser preview closes')
            wait_until(idle)
        print('PASS legacy push to note shown in Browser preview', flush=True)
        # anki-editor 0.3.4's gui-browse, push and delete commands for a note shown in the Browser.
        emacs = call('notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'},
                     fields={'Front': 'Org question', 'Back': 'Org answer'})
        emacs_id, emacs_cards = int(emacs['noteId']), sorted(int(id) for id in emacs['cardIds'])
        with emacs_http() as http:
            for _ in range(2):
                assert http(v6('guiBrowse', query='nid:%d' % emacs_id)) == {'result': emacs_cards, 'error': None}
            browser = owner.runtime.gui.browser()
            wait_until(lambda: getattr(browser.editor.note, 'id', None) == emacs_id,
                       description='Browser editor shows the browsed note')
            info = http(v6('multi', actions=[v6('notesInfo', notes=[emacs_id])]))['result'][0]['result'][0]
            org = {'id': emacs_id, 'deckName': 'Org::Moved', 'modelName': 'Basic', 'options': {'allowDuplicate': False},
                   'fields': {'Front': 'Org question', 'Back': 'Edited in Org'}, 'tags': ['org']}
            done = {'result': [{'result': None, 'error': None}], 'error': None}
            assert http(v6('multi', actions=[v6('updateNote', note=org)])) == done
            assert http(v6('multi', actions=[v6('changeDeck', deck='Org::Moved', cards=info['cards'])])) == done
            pushed = aqt.mw.col.get_note(emacs_id)
            assert (pushed['Back'], pushed.tags) == ('Edited in Org', ['org'])
            assert {aqt.mw.col.decks.name(card.did) for card in pushed.cards()} == {'Org::Moved'}
            wait_until(lambda: browser.editor.note is None or browser.editor.note['Back'] == 'Edited in Org',
                       description='Browser editor reloads the note pushed from Org')
            assert http(v6('deleteNotes', notes=[emacs_id])) == {'result': None, 'error': None}
            assert not aqt.mw.col.find_notes('nid:%d' % emacs_id)
            wait_until(lambda: getattr(browser.editor.note, 'id', None) != emacs_id,
                       description='Browser editor drops the note deleted from Org')
            wait_until(idle)
            print('PASS Emacs browse, push, move and delete of note shown in Browser', flush=True)
        if editor_variants() != [False]:
            # The 26.08 web editor reloads pushed fields and tags in its page, but cannot load a deleted note.
            import json
            aqt.dialogs.closeAll(onsuccess=lambda: None)
            wait_until(aqt.dialogs.allClosed)
            use_editor(True)
            web_id = int(call('notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'},
                              fields={'Front': 'Web question', 'Back': 'Web answer'})['noteId'])
            def shows(*fields):
                return ('(() => { try { const info = getNoteInfo(); return String(info.id) === "%d" && '
                        'JSON.stringify(info.fields) === %s; } catch { return false; } })()'
                        % (web_id, json.dumps(json.dumps(list(fields), separators=(',', ':')))))
            done = {'result': None, 'error': None}
            with emacs_http() as http:
                http(v6('guiBrowse', query='nid:%d' % web_id))
                browser = owner.runtime.gui.browser()
                result(owner.runtime.gui.javascript(browser.editor, staged_fields(web_id, ['Typed web question', 'Web answer']),
                                                    ready=shows('Web question', 'Web answer')))
                assert http(v6('updateNoteFields', note={'id': web_id, 'fields': {'Back': 'Pushed web answer'}})) == done
                assert http(v6('addTags', notes=[web_id], tags='emacs')) == done
                assert aqt.mw.col.get_note(web_id).fields == ['Typed web question', 'Pushed web answer']
                result(owner.runtime.gui.javascript(browser.editor, 'return true;', ready=shows('Typed web question', 'Pushed web answer')))
                result(owner.runtime.gui.javascript(browser.editor, staged_fields(web_id, ['Retyped web question', 'Pushed web answer'])))
                result(owner.runtime.gui.javascript(browser.editor, 'return true;', ready=shows('Retyped web question', 'Pushed web answer')))
                save_editor(browser.editor)
                wait_until(idle)
                saved = aqt.mw.col.get_note(web_id)
                assert (saved.fields, saved.tags) == (['Retyped web question', 'Pushed web answer'], ['emacs']), saved.fields
                refused = http(v6('deleteNotes', notes=[web_id]))
                assert refused['error'].startswith('Close the affected editor'), refused
                assert aqt.mw.col.find_notes('nid:%d' % web_id)
            aqt.dialogs.closeAll(onsuccess=lambda: None)
            wait_until(aqt.dialogs.allClosed)
            use_editor(False)
            call('browser.open', query='nid:' + note['noteId'])
            print('PASS Emacs push to note shown in the 26.08 web editor', flush=True)
        call('notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': 'Second GUI question'})
        browser = owner.runtime.gui.browser()
        expected_cards = set(aqt.mw.col.find_cards(''))
        executed_hook = getattr(getattr(aqt, 'gui_hooks', None), 'operation_did_execute', None)
        if supports('new-card reposition and undo with open browser', 'scheduling.repositionNewCards', 'collection.undo'):
            before = {id: aqt.mw.col.get_card(id).due for id in expected_cards}
            notifications = []
            def reposition_notified(changes, initiator):
                notifications.append(changes.card)
            if executed_hook is not None:
                executed_hook.append(reposition_notified)
            try:
                assert call('scheduling.repositionNewCards', cardIds=[selected_card],
                            startingFrom=0, shiftExisting=True) == {'changedCount': 1}
                # Before 2.1.45 Anki had no operation notifications.
                assert executed_hook is None or any(notifications), 'Reposition replied before native change notification'
                assert {id: aqt.mw.col.get_card(id).due for id in expected_cards} == {
                    id: 0 if str(id) == selected_card else due + 1 for id, due in before.items()}
                # Collection undo requires closing affected editors first.
                save_editor(browser.editor)
                aqt.dialogs.closeAll(onsuccess=lambda: None)
                wait_until(aqt.dialogs.allClosed)
                notifications.clear()
                call('collection.undo')
                assert executed_hook is None or any(notifications), 'Undo replied before native change notification'
                assert {id: aqt.mw.col.get_card(id).due for id in expected_cards} == before
            finally:
                if executed_hook is not None:
                    executed_hook.remove(reposition_notified)
            print('PASS new-card reposition, shifts, native notifications and undo with open browser', flush=True)
        call('browser.open', query='')
        browser = owner.runtime.gui.browser()
        if supports('browser numeric sorting', 'scheduling.setDueDate'):
            # Distinct due days avoid relying on native tie-breaking between sibling cards.
            for index, id in enumerate(sorted(expected_cards)):
                call('scheduling.setDueDate', cardIds=[str(id)], days=str(index + 1))
            ascending = None
            for direction in ['ascending', 'descending', 'ascending', 'descending']:
                call('browser.open', query='', sort={'column': 'cardDue', 'direction': direction})
                assert browser_sorting(browser) == ('cardDue', direction == 'descending'), browser_sorting(browser)
                wait_until(lambda: set(browser_rows(browser)) == expected_cards)
                items = browser_rows(browser)
                if direction == 'ascending':
                    ascending = items
                else:
                    assert items == ascending[::-1], (items, ascending)
            print('PASS browser numeric sorting both directions', flush=True)
        legacy_reply = result(owner.handler_async({'action': 'guiBrowse', 'version': 6, 'params': {'query': ''}}))
        assert legacy_reply == {'result': sorted(aqt.mw.col.find_cards('')), 'error': None}, legacy_reply
        assert set(old('guiBrowse', http_v2=True, query='nid:' + note['noteId'])) == {
            int(id) for id in siblings}
        print('PASS legacy browser completion', flush=True)
        save_editor(owner.runtime.gui.browser().editor)
        aqt.dialogs.closeAll(onsuccess=lambda: None)
        wait_until(aqt.dialogs.allClosed)
    if scenario == 'browser-startup':
        import json
        from aqt.browser import Browser
        from plugin.web import WebRequest
        other = call('notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'},
                     fields={'Front': 'Unrelated browser startup note'})
        query = 'nid:' + note['noteId']
        expected_cards = {int(id) for id in note['cardIds']}
        # 2.1.41 normalizes the search, which quotes it.
        shown = (query, '"' + query + '"')
        native_javascript = owner.runtime.gui.javascript
        # Browser.search_for and the initial search argument arrived in 2.1.41.
        native_search = getattr(Browser, 'search_for', None)
        searches, gates = [], []
        def record_search(browser, search, *args, **kwargs):
            searches.append(search)
            return native_search(browser, search, *args, **kwargs)
        def pause_readiness(editor, code, ready=None):
            if ready == SAVE_READY:
                gate = Deferred()
                gates.append(gate)
                return gate
            return native_javascript(editor, code, ready)
        def table_cards(browser):
            return set(browser_rows(browser))
        from plugin import compat
        # Before 2.1.41 a new browser first runs its own default search.
        single_search = [['is:current'] * (not compat.browser_opens_with_search()) + [text] for text in shown]
        try:
            if native_search is not None:
                Browser.search_for = record_search
            for svelte in editor_variants():
                use_editor(svelte)
                for protocol in ('v1', 'legacy-v2', 'legacy-v6'):
                    assert owner.runtime.gui.browser() is None
                    wait_until(idle)
                    searches.clear()
                    gates.clear()
                    owner.runtime.gui.javascript = pause_readiness
                    if protocol == 'v1':
                        reply = owner.runtime.dispatcher.request({'jsonrpc': '2.0', 'id': 1,
                            'method': 'browser.open', 'params': {'query': query}})
                        value = result(reply)
                        assert 'result' in value, value
                        handle = value['result']['operationId']
                        pending = owner.runtime.operations.completions[handle]
                    else:
                        reply = owner.server.handlerWrapper(WebRequest(b'POST', {}, json.dumps({
                            'action': 'guiBrowse', 'version': 2 if protocol == 'legacy-v2' else 6,
                            'params': {'query': query}}).encode()))
                        pending = reply
                    wait_until(lambda: bool(gates))
                    browser = owner.runtime.gui.browser()
                    # Search/table effects must precede editor readiness and API completion.
                    assert current_search(browser) in shown, current_search(browser)
                    wait_until(lambda: table_cards(browser) == expected_cards)
                    assert native_search is None or searches in single_search, searches
                    assert not pending.done
                    owner.runtime.gui.javascript = native_javascript
                    result(native_javascript(browser.editor, 'return true;', ready=SAVE_READY))
                    gates[0].resolve(True)
                    value = result(pending)
                    if protocol == 'v1':
                        assert value['selectedNoteIds'] == [note['noteId']], value
                    else:
                        value = json.loads(value.split(b'\r\n\r\n', 1)[1])
                        cards = value if protocol == 'legacy-v2' else value['result']
                        assert set(cards) == expected_cards, value
                    assert native_search is None or searches in single_search, searches
                    # Omitted query preserves the existing search on an open browser.
                    assert old('guiBrowse') == []
                    assert current_search(browser) in shown, current_search(browser)
                    # Stage an editor change, then search elsewhere through the same API.
                    edited = 'Browser edit ' + protocol + ' ' + str(svelte)
                    loaded = ('(() => { try { const info = getNoteInfo(); return String(info.id) === '
                              + json.dumps(note['noteId']) + ' && info.fields.length === 2; } catch { return false; } })()'
                              if svelte else SAVE_READY)
                    if not svelte:
                        wait_until(lambda: getattr(browser.editor.note, 'id', None) == int(note['noteId']),
                                   description='Browser editor shows the searched note')
                    result(native_javascript(browser.editor, staged_fields(note['noteId'], [edited, 'GUI answer']),
                                             ready=loaded))
                    if protocol == 'v1':
                        call('browser.open', query='nid:' + other['noteId'])
                    else:
                        old('guiBrowse', http_v2=protocol == 'legacy-v2', query='nid:' + other['noteId'])
                    wait_until(lambda: table_cards(browser) == {int(id) for id in other['cardIds']})
                    wait_until(idle)
                    assert aqt.mw.col.get_note(int(note['noteId']))['Front'] == edited
                    if svelte:
                        result(native_javascript(browser.editor, 'return true;', ready=loaded.replace(
                            json.dumps(note['noteId']), json.dumps(other['noteId']))))
                    save_editor(browser.editor)
                    aqt.dialogs.closeAll(onsuccess=lambda: None)
                    wait_until(aqt.dialogs.allClosed)
                    print('PASS initial browser query before readiness and existing-editor save',
                          protocol, 'svelte=' + str(svelte), flush=True)
        finally:
            if native_search is not None:
                Browser.search_for = native_search
            owner.runtime.gui.javascript = native_javascript
    if scenario == 'custom' and supports('custom editor', 'editors.openNote'):
        editor = call('editors.openNote', noteId=note['noteId'])
        assert editor['noteId'] == note['noteId'], editor
        print('PASS custom editor', flush=True)
        dialog = aqt.dialogs._dialogs[Edit.dialog_registry_tag][1]
        wait_until(page_ready(dialog.editor.web, SAVE_READY))
        dialog.editor.web.eval('(() => { ' + staged_fields(note['noteId'], ['Edited GUI question', 'GUI answer']) + ' })();')
        saved = []
        dialog.editor.call_after_note_saved(lambda: saved.append(True))
        wait_until(lambda: bool(saved))
        assert aqt.mw.col.get_note(int(note['noteId']))['Front'] == 'Edited GUI question'
        assert old('guiEditNote', note=int(note['noteId'])) is None
        assert old('guiEditNote', http_v2=True, note=int(note['noteId'])) is None
        assert owner.runtime.gui.editors
        print('PASS custom editor save', flush=True)
        # Note-type writes reload open editors; the legacy facade saves them first.
        dialog.editor.web.eval('(() => { ' + staged_fields(note['noteId'], ['Unsaved GUI question', 'GUI answer']) + ' })();')
        name = aqt.mw.col.get_note(int(note['noteId'])).note_type()['name']
        assert old('updateModelStyling', model={'name': name, 'css': '.card { color: navy; }'}) is None
        assert aqt.mw.col.get_note(int(note['noteId']))['Front'] == 'Unsaved GUI question'
        assert aqt.mw.col.models.by_name(name)['css'] == '.card { color: navy; }'
        wait_until(idle)
        assert dialog.editor.note['Front'] == 'Unsaved GUI question'
        executed = []
        def record_op(changes, handler):
            executed.append(handler)
        aqt.gui_hooks.operation_did_execute.append(record_op)
        mod = aqt.mw.col.get_note(int(note['noteId'])).mod
        try:
            assert old('updateModelStyling', model={'name': name, 'css': '.card { color: teal; }'}) is None
            wait_until(idle)
        finally:
            aqt.gui_hooks.operation_did_execute.remove(record_op)
        # A clean editor's save is a no-op rather than an extra note update.
        assert aqt.mw.col.get_note(int(note['noteId'])).mod == mod
        assert dialog.editor not in executed, executed
        print('PASS legacy note-type write saves open editor first', flush=True)
        # Deleting the shown note through the API closes the dialog's own preview.
        doomed = call('notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'},
                      fields={'Front': 'Doomed GUI question', 'Back': 'GUI answer'})
        assert old('guiEditNote', note=int(doomed['noteId'])) is None
        wait_until(lambda: dialog.editor.note is not None and dialog.editor.note.id == int(doomed['noteId']),
                   description='custom editor shows the new note')
        previewer = dialog.show_preview()
        wait_until(lambda: previewer.isVisible(), description='custom preview opens')
        assert old('deleteNotes', notes=[int(doomed['noteId'])]) is None
        wait_until(lambda: not previewer._open, description='custom preview closes after deletion')
        wait_until(lambda: dialog.editor.note is not None and dialog.editor.note.id == int(note['noteId']),
                   description='custom editor returns to the previous note')
        print('PASS deleting the shown note closes the custom preview', flush=True)
        aqt.dialogs.closeAll(onsuccess=lambda: None)
        wait_until(aqt.dialogs.allClosed)
    if scenario == 'reviewer':
        schedulers = ['default']
        # From 2.1.45 to 2.1.66 the v3 scheduler is an option.
        if hasattr(aqt.mw.col, 'v3_scheduler') and not aqt.mw.col.v3_scheduler():
            schedulers.append('v3')
        will_answer = getattr(getattr(aqt, 'gui_hooks', None), 'reviewer_will_answer_card', None)
        for scheduler in schedulers:
            if scheduler == 'v3':
                aqt.mw.col.set_v3_scheduler(True)
            call('notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': 'Legacy reviewer question ' + scheduler})
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
            # Before 2.1.20 there was no answer hook to veto with.
            if will_answer is not None:
                veto = lambda choice, reviewer, card: (False, choice[1])
                will_answer.append(veto)
                try:
                    call('reviewer.answer', stateToken=review['stateToken'], rating='good')
                    raise AssertionError('Vetoed answer succeeded')
                except Exception as error:
                    assert getattr(error, 'kind', None) == 'vetoed', error
                finally:
                    will_answer.remove(veto)
                print('PASS reviewer veto', scheduler, flush=True)
            answered = call('reviewer.answer', stateToken=review['stateToken'], rating='good')
            assert answered['reviewId'] is not None, answered
            # v1 learning cards offer Again, Good and Easy as buttons 1 to 3.
            good = [item['rating'] for item in review['answers']].index('good') + 1
            assert aqt.mw.col.db.scalar('select ease from revlog where id=?', int(answered['reviewId'])) == good
            print('PASS reviewer native answer', scheduler, [item['rating'] for item in review['answers']], flush=True)
            wait_until(lambda: aqt.mw.reviewer.card and aqt.mw.reviewer.state == 'question')
            legacy_card = aqt.mw.reviewer.card.id
            assert old('guiShowAnswer')
            wait_until(lambda: aqt.mw.reviewer.state == 'answer')
            assert old('guiAnswerCard', ease=3)
            assert aqt.mw.col.db.scalar('select ease from revlog where cid=? order by id desc limit 1', legacy_card) == 3
            assert old('guiDeckBrowser') is None
            assert aqt.mw.state == 'deckBrowser'
            call('application.navigate', view='deckBrowser')
        # Emacs reviewers send each step once the previous reply arrives: anki.el reads the
        # card straight after guiDeckReview, anki-study.el snapshots it in a multi with {}
        # params and rates once guiShowAnswer replies, then reads the next card at once.
        for index in range(2):
            call('notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': 'Emacs review ' + str(index)})
        wait_until(idle)
        with emacs_http() as http:
            assert http({'action': 'guiDeckReview', 'version': 5, 'params': {'name': 'Default'}}) == {'result': True, 'error': None}
            current = http({'action': 'guiCurrentCard', 'version': 5})['result']
            assert current and current['buttons'] and len(current['nextReviews']) == len(current['buttons']), current
            snapshot = http(v6('multi', actions=[v6('guiReviewActive'), v6('guiCurrentCard')]))
            assert snapshot == {'result': [{'result': True, 'error': None}, {'result': current, 'error': None}], 'error': None}
            assert http(v6('guiShowAnswer')) == {'result': True, 'error': None}
            assert http(v6('guiAnswerCard', ease=current['buttons'][-1])) == {'result': True, 'error': None}
            following = http(v6('guiCurrentCard'))
            assert following['error'] is None and following['result']['cardId'] != current['cardId'], following
            assert aqt.mw.col.db.scalar('select ease from revlog where cid=? order by id desc limit 1',
                                        current['cardId']) == current['buttons'][-1]
            wait_until(idle)
            assert old('guiDeckBrowser') is None
            assert http(v6('guiCurrentCard')) == {'result': None, 'error': 'Gui review is not currently active.'}
            print('PASS Emacs reviewer requests without waits', flush=True)
    if scenario == 'imports' and supports('imports', 'application.importFile'):
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
            wait_until(idle)
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
        wait_until(idle,
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
            # Offscreen Qt has no window manager to reactivate the main window; 2.1.15
            # would otherwise parent later progress dialogs to the deleted prompt.
            aqt.mw.activateWindow()
            response = json.loads(result(reply).split(b'\r\n\r\n', 1)[1])
            assert response['result']['permission'] == ('granted' if choice == 'yes' else 'denied')
            key = 'webCorsOriginList' if choice == 'yes' else 'ignoreOriginList'
            assert origin in util.setting(key)
        print('PASS native permission prompts and persistence for both protocols', flush=True)
        # Check real GUI sync dependencies without credentials or network I/O.
        # Signature checks do not certify full-sync or media completion.
        if supports('sync dependency signatures', 'collection.sync'):
            from plugin import compat
            gui_hooks = getattr(aqt, 'gui_hooks', None)
            col = aqt.mw.col
            checks = [
                (aqt.mw.taskman.with_progress, (lambda: None, lambda future: None), {}),
                (aqt.mw.pm.set_host_number, (0,), {}),
                (aqt.mw.pm.media_syncing_enabled, (), {}),
                (getattr(aqt.mw, '_refresh_after_sync', None) or aqt.mw.toolbar.redraw, (), {}),
                (aqt.mw.reopen if 'after_full_sync' in inspect.signature(aqt.mw.reopen).parameters else col.reopen,
                 (), {'after_full_sync': True}),
            ]
            if compat.collection_syncs_media(col):
                checks += [
                    (aqt.mw.taskman.run_in_background, (col.media_sync_status, lambda future: None), {'uses_collection': False}),
                    (aqt.mw.media_syncer.start_monitoring, (), {}),
                ]
            else:
                checks += [(aqt.mw.media_syncer.start, (), {}), (aqt.mw.media_syncer.is_syncing, (), {})]
            # Releases add these steps; the plugin uses them where present.
            for owner_object, name, args in ((aqt.mw, 'create_backup_now', ()), (aqt.mw.pm, 'set_current_sync_url', (None,)),
                                             (gui_hooks, 'collection_will_temporarily_close', (col,))):
                if hasattr(owner_object, name):
                    checks.append((getattr(owner_object, name), args, {}))
            for function, args, kwargs in checks:
                inspect.signature(function).bind(*args, **kwargs)
        old_session = owner.runtime.session
        assert 'User 1' in [profile['name'] for profile in call('profiles.list')]
        assert call('profiles.getActive')['name'] == 'User 1'
        expected_sync = 'authenticationRequired' if supports('sync authentication', 'collection.sync') else 'unsupportedCapability'
        try:
            call('collection.sync')
            raise AssertionError('Sync without credentials succeeded')
        except Exception as error:
            assert getattr(error, 'kind', None) == expected_sync, error
        sync_reply = result(owner.handler_async({'action': 'sync', 'version': 6}))
        if expected_sync == 'authenticationRequired':
            assert 'auth not configured' in sync_reply['error'], sync_reply
        else:
            assert sync_reply['error'], sync_reply
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
        if supports('GUI undo', 'collection.undo'):
            created = call('notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': 'Undo GUI note'})
            assert old('guiUndo')
            assert not aqt.mw.col.find_notes('nid:' + created['noteId'])
        print('PASS profile switch', flush=True)
    if scenario == 'colpkg' and supports('collection package import', 'application.importFile'):
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
    if scenario == 'obsidian':
        """multi/createDeck/addNote/notesInfo/getTags/updateNoteFields/deleteNotes/
        storeMediaFile/changeDeck/removeTags/addTags through real HTTP and Qt.
        """
        import json
        import threading
        import urllib.request
        from plugin import util
        from tests_api.test_obsidian import file_requests, phase_one, phase_two, request, parse, source
        setting = util.setting
        overrides = {'webBindPort': 0, 'webCorsOriginList': ['http://localhost', 'app://obsidian.md']}
        util.setting = lambda name: overrides[name] if name in overrides else setting(name)
        owner.startWebServer()
        port = owner.server.sock.getsockname()[1]
        def exchange(payload):
            replies = []
            def send():
                try:
                    req = urllib.request.Request('http://127.0.0.1:' + str(port),
                        json.dumps(payload).encode(), {'Origin': 'app://obsidian.md'})
                    with urllib.request.urlopen(req, timeout=30) as response:
                        assert response.headers['Access-Control-Allow-Origin'] == 'app://obsidian.md'
                        replies.append(json.load(response))
                except BaseException as error:
                    replies.append(error)
            thread = threading.Thread(target=send, daemon=True)
            thread.start()
            wait_until(lambda: bool(replies), timeout=35, description='Obsidian HTTP sync')
            thread.join(timeout=1)
            assert not isinstance(replies[0], BaseException), replies
            return parse(replies[0])
        assert 'Basic' in exchange(request('modelNames'))
        picture = base / 'vault picture.png'
        picture.write_bytes(b'Obsidian GUI media')
        files = [file_requests(new=[source('Obsidian GUI ' + str(i)) for i in range(45)],
                              media=[{'filename': 'picture.png', 'path': str(picture)}])]
        files.extend(file_requests() for _ in range(39))
        first = exchange(phase_one(files))
        ids = [parse(reply) for reply in parse(parse(first[1])[0])]
        assert len(ids) == 45 and len(set(ids)) == 45 and all(type(id) is int for id in ids)
        assert parse(parse(first[6])[0]) == 'picture.png'
        assert (Path(aqt.mw.col.media.dir()) / 'picture.png').read_bytes() == picture.read_bytes()
        files = [file_requests(edits=[{'id': id, 'fields': {'Back': 'edited <img src="picture.png">'},
                                      'tags': ['updated']} for id in ids[:-1]],
                               deleted=[ids[-1]], deck='Obsidian::Moved')]
        first = exchange(phase_one(files))
        infos = [parse(reply) for reply in parse(first[2])]
        second = exchange(phase_two(files, infos, parse(first[3])))
        assert [parse(reply) for reply in parse(second[0])] == [None]
        assert [parse(reply) for reply in parse(second[1])] == [None]
        assert [parse(reply) for reply in parse(parse(second[2])[0])] == [None] * 44
        for id in ids[:-1]:
            actual = aqt.mw.col.get_note(id)
            assert actual['Back'] == 'edited <img src="picture.png">' and actual.tags == ['updated']
            assert all(aqt.mw.col.decks.name(card.did) == 'Obsidian::Moved' for card in actual.cards())
        assert aqt.mw.col.find_notes('nid:' + str(ids[-1])) == []
        assert aqt.mw.col.note_count() == 45  # 44 synced notes plus the scenario's setup note.
        # Native change notifications can queue deck-browser refresh queries.
        # The HTTP reply completes the API work, but those queries may still run.
        wait_until(idle,
                   description='Obsidian native refresh completion')
        owner.server.close()
        owner.timer.stop()
        util.setting = setting
        print('PASS Obsidian nested HTTP sync, native Qt completion, media, edits, deck moves, tags and deletion', flush=True)
    if scenario == 'mining-clients':
        """createDeck/createModel/addNote/updateModelStyling/updateModelTemplates/
        deleteNotes/storeMediaFile through LunaTranslator GET and GSM POST.
        """
        import base64
        import json
        import threading
        import urllib.request
        from plugin import util
        from tests_api.test_lunatranslator import exercise_luna
        setting = util.setting
        util.setting = lambda name: 0 if name == 'webBindPort' else setting(name)
        owner.startWebServer()
        port = owner.server.sock.getsockname()[1]
        def exchange(action, params, method='GET'):
            replies = []
            def send():
                try:
                    payload = {'action': action, 'version': 6, 'params': params}
                    request = urllib.request.Request('http://127.0.0.1:' + str(port),
                        json.dumps(payload).encode(), {'Content-Type': 'application/json'}, method=method)
                    with urllib.request.urlopen(request, timeout=30) as response:
                        replies.append(json.load(response))
                except BaseException as error:
                    replies.append(error)
            thread = threading.Thread(target=send, daemon=True)
            thread.start()
            wait_until(lambda: bool(replies), timeout=35, description='Desktop mining HTTP request')
            thread.join(timeout=1)
            assert not isinstance(replies[0], BaseException), replies
            return replies[0]
        first, deleted, replacement, source = exercise_luna(
            lambda action, **params: exchange(action, params), base)
        assert aqt.mw.col.find_notes('nid:' + str(deleted)) == []
        for id in [first, replacement]:
            assert aqt.mw.col.get_note(id)['word'] == '猫'
        response = exchange('storeMediaFile', {'filename': r'C:\GSM\猫.PNG',
            'data': base64.b64encode(b'GSM screenshot').decode()}, method='POST')
        # Native Anki lowercases new media names from 26.5; earlier releases keep the case.
        wait_until(idle, description='Settle before media case probe')
        lowercases = aqt.mw.col.media.write_data('Case Probe.PNG', b'probe') == 'case probe.png'
        expected_name = '猫.PNG' if os.name == 'nt' else 'CGSM猫.PNG'
        expected_name = expected_name.lower() if lowercases else expected_name
        assert response['error'] is None and os.path.normcase(response['result']) == os.path.normcase(expected_name), response
        assert (Path(aqt.mw.col.media.dir()) / response['result']).read_bytes() == b'GSM screenshot'
        assert exchange('updateModelTemplates', {'model': {'name': source['modelName'], 'templates': {
            'LUNACARDTEMPLATE1': {'Front': '{{#example_sentence}}{{example_sentence}}{{/example_sentence}}'}}}}) == {
                'result': None, 'error': None}
        fallback = exchange('addNote', {'note': {'modelName': source['modelName'],
            'deckName': source['deckName'], 'fields': {'word': 'Conditional fallback'}}}, method='POST')
        assert fallback['error'] is None and type(fallback['result']) is int, fallback
        actual = aqt.mw.col.get_note(fallback['result'])
        assert actual['word'] == 'Conditional fallback' and len(actual.card_ids()) == 1
        # Allow native refresh queries triggered by the final write to complete.
        wait_until(idle,
                   description='Mining clients native refresh completion')
        owner.server.close()
        owner.timer.stop()
        util.setting = setting
        print('PASS LunaTranslator GET model refresh, media and overwrite; GSM full-path media; native fallback card', flush=True)
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
        from plugin import compat
        compat.gui_hook('profile_will_close').append(lambda: closed.append(True))
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
    finish(1)
finish(0)

"""Differences between Anki releases, kept out of the API services.

Prefer feature detection; release numbers only order prereleases and gate
behavior that cannot be detected without side effects.
"""
from collections import namedtuple
from types import SimpleNamespace
import functools
import importlib
import inspect
import re
import sys

import aqt

PRERELEASES = {'a': -3, 'b': -2, 'rc': -1}


def parse_version(text):
    """Order releases so that 26.5b1 < 26.5 < 26.5.1; ignore fork labels such as +fsrs7."""
    found = re.match(r'(\d+(?:\.\d+)*)(?:(a|b|rc)(\d+))?', text.split('+')[0].strip())
    if not found:
        raise ValueError('Unrecognized Anki version: ' + text)
    release = [int(part) for part in found.group(1).split('.')]
    release += [0] * (3 - len(release))
    stage = (PRERELEASES[found.group(2)], int(found.group(3))) if found.group(2) else (0, 0)
    return tuple(release[:3]) + stage


VERSION = parse_version(aqt.appVersion)


def at_least(*release):
    return VERSION >= tuple(release) + (0,) * (3 - len(release)) + (0, 0)


def lookup(root, path):
    value = root
    for part in path.split('.'):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def has(root, path):
    return lookup(root, path) is not None


def editor_dialog_available():
    """The custom editor dialog uses the editor modes and browser table of Anki 2.1.50."""
    import aqt.editor
    return has(aqt.editor, 'EditorMode') and has(aqt.gui_hooks, 'operation_did_execute')


def macos_helper():
    try:
        from aqt._macos_helper import macos_helper as helper
    except ImportError:
        # Anki 2.1.49 and earlier have no App Nap helper.
        return None
    return helper


def on_op_finished(mw, changes, initiator=None):
    """Notify Anki's GUI of a native operation, as CollectionOp does."""
    try:
        from aqt.operations import on_op_finished as finished
    except ImportError:
        finished = None
    if finished:
        finished(mw, changes, initiator)
        return
    if isinstance(changes, LegacyChanges):
        # Releases before 2.1.45 have no change tracking; refresh every screen.
        mw.reset()
        return
    # Anki 2.1.45-2.1.65 inline the same steps in CollectionOp._finish_op.
    mw.update_undo_actions()
    mw.autosave()
    aqt.gui_hooks.operation_did_execute(changes, initiator)
    if mw.col.op_made_changes(changes):
        aqt.gui_hooks.state_did_reset()


class _LegacyHook:
    """A runHook-style hook with the append/remove/call shape of a GUI hook."""

    def __init__(self, name):
        self.name = name

    def append(self, callback):
        from anki.hooks import addHook
        addHook(self.name, callback)

    def remove(self, callback):
        from anki.hooks import remHook
        remHook(self.name, callback)

    def __call__(self, *args):
        from anki.hooks import runHook
        runHook(self.name, *args)


# GUI hooks that releases before 2.1.20 ran by name through anki.hooks.
LEGACY_GUI_HOOKS = {'profile_will_close': 'unloadProfile'}


def gui_hook(name):
    """The named GUI hook, or None when the running release has no equivalent."""
    hook = getattr(getattr(aqt, 'gui_hooks', None), name, None)
    if hook is None and name in LEGACY_GUI_HOOKS:
        return _LegacyHook(LEGACY_GUI_HOOKS[name])
    return hook


def register_collection_close(callback):
    hook = gui_hook('collection_will_temporarily_close')
    if hook is not None:
        # Anki 2.1.50 and earlier close collections only by unloading the profile.
        hook.append(callback)


# Releases before 2.1.45 do not count background operations; count this add-on's own.
_background_ops = [0]


def background_op_count(mw):
    if hasattr(mw, '_increase_background_ops'):
        return mw._background_op_count
    return _background_ops[0]


def increase_background_ops(mw):
    if hasattr(mw, '_increase_background_ops'):
        mw._increase_background_ops()
    else:
        _background_ops[0] += 1


def decrease_background_ops(mw):
    if hasattr(mw, '_decrease_background_ops'):
        mw._decrease_background_ops()
    else:
        _background_ops[0] -= 1


def collection_thread_bound():
    """Whether collections use a Python sqlite3 connection bound to the main thread (before 2.1.24)."""
    import importlib.util
    return importlib.util.find_spec('anki.dbproxy') is None


def run_in_background(mw, task, on_done, uses_collection=True):
    """Run task through Anki's task manager, calling on_done(future) on the main thread.

    Where collections are bound to the main thread, collection work runs there later
    instead, preserving asynchronous completion. Releases before 23.10 cannot mark
    work as independent of the collection.
    """
    import concurrent.futures
    taskman = getattr(mw, 'taskman', None)
    if taskman is None or (uses_collection and collection_thread_bound()):
        def run():
            future = concurrent.futures.Future()
            try:
                future.set_result(task())
            except BaseException as error:
                future.set_exception(error)
            on_done(future)
        if taskman is not None:
            taskman.run_on_main(run)
        else:
            # Anki 2.1.15 has no task manager.
            from aqt.qt import QTimer
            QTimer.singleShot(0, run)
        return
    parameters = inspect.signature(taskman.run_in_background).parameters
    if 'uses_collection' in parameters or any(p.kind == p.VAR_KEYWORD for p in parameters.values()):
        taskman.run_in_background(task, on_done, uses_collection=uses_collection)
    elif uses_collection:
        _run_collection_task(taskman, task, on_done)
    else:
        taskman.run_in_background(task, on_done)


# Collection tasks waiting for the one in progress; the first entry is running.
_collection_tasks = []


def _run_collection_task(taskman, task, on_done):
    """Before 23.10 the task manager runs tasks on several threads at once. Queue
    collection work so one request's reads and writes do not interleave with another's."""
    def finished(future):
        try:
            on_done(future)
        finally:
            _collection_tasks.pop(0)
            if _collection_tasks:
                _start_collection_task(taskman)
    _collection_tasks.append((task, finished))
    if len(_collection_tasks) == 1:
        _start_collection_task(taskman)


def _start_collection_task(taskman):
    import concurrent.futures
    task, finished = _collection_tasks[0]
    try:
        taskman.run_in_background(task, finished)
    except BaseException as error:
        # A task that cannot start must still release the queue.
        future = concurrent.futures.Future()
        future.set_exception(error)
        finished(future)


# Qt dialogs. These run on the main thread.

def svelte_editor_enabled(col):
    """Whether Add opens the experimental Svelte editor of Anki 26.08 and later."""
    try:
        from anki.collection import ExperimentFlag
    except ImportError:
        return False
    return col.experiment_enabled(ExperimentFlag.SVELTE_EDITOR)


def add_dialog_deck_id(dialog):
    chooser = getattr(dialog, 'deck_chooser', None)
    # Before 2.1.45 the deck chooser stored a deck name.
    return chooser.selected_deck_id if chooser is not None else dialog.deckChooser.selectedId()


def add_dialog_set_note(dialog, note, deck_id):
    """AddCards.set_note of 2.1.50: select the note type and deck, then load fields and tags."""
    if hasattr(dialog, 'set_note'):
        dialog.set_note(note, deck_id)
        return
    if hasattr(dialog, 'notetype_chooser'):
        dialog.notetype_chooser.selected_notetype_id = note.mid
        dialog.deck_chooser.selected_deck_id = deck_id
        draft = dialog._new_note()
    else:
        # Before 2.1.45 Add drafts used the collection's current note type.
        col = dialog.mw.col
        col.models.setCurrent(note.note_type())
        dialog.modelChooser.updateModels()
        dialog.deckChooser.setDeckName(col.decks.name(deck_id))
        draft = col.newNote()
    draft.fields = list(note.fields)
    draft.tags = list(note.tags)
    dialog.setAndFocusNote(draft)
    # Before 2.1.50 Add mode keeps the tag box text, which saving copies to the note.
    dialog.editor.tags.setText(' '.join(draft.tags))


def browser_opens_with_search():
    """Whether a new browser applies an initial search before loading its editor (2.1.41)."""
    from aqt.browser import Browser
    opens = inspect.signature(aqt.dialogs.open).parameters.values()
    return ('search' in inspect.signature(Browser.__init__).parameters
            and any(parameter.kind == parameter.VAR_KEYWORD for parameter in opens))


def browser_card_row(browser, card_id):
    table = getattr(browser, 'table', None)
    if table is not None:
        return table._model.get_card_row(card_id)
    # Before 2.1.45 the browser listed only cards, in search order; 2.1.28-2.1.44
    # keep the backend's repeated field, which has no index method.
    try:
        return list(browser.model.cards).index(card_id)
    except ValueError:
        return None


def browser_select_rows(browser, rows):
    from aqt.qt import QItemSelection, QItemSelectionModel
    table = getattr(browser, 'table', None)
    view = browser.form.tableView
    if table is not None:
        table.clear_selection()
    else:
        view.selectionModel().clear()
    model = view.model()
    selection = QItemSelection()
    for row in rows:
        # The Rows flag extends each index across its row.
        selection.select(model.index(row, 0), model.index(row, 0))
    if rows:
        # Before 2.1.45 the browser shows the card at the current index.
        view.selectionModel().setCurrentIndex(model.index(rows[0], 0), QItemSelectionModel.SelectionFlag.NoUpdate)
    view.selectionModel().select(
        selection, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)


def browser_column_exists(col, column):
    if hasattr(col, 'get_browser_column'):
        return col.get_browser_column(column) is not None
    # Before 2.1.45 the browser defined these card columns.
    return column in ('question', 'answer', 'template', 'deck', 'noteFld', 'noteCrt', 'noteMod', 'cardMod',
                      'cardDue', 'cardIvl', 'cardEase', 'cardReps', 'cardLapses', 'noteTags', 'note')


def browser_sort(browser, column, descending):
    """Sort by an active browser column; returns False when the column is not shown.

    Applies the column, then the direction, so that a column's default direction
    on first selection does not decide the result.
    """
    table = getattr(browser, 'table', None)
    if table is not None:
        from aqt.qt import Qt
        index = table._model.active_column_index(column)
        if index is None:
            return False
        order = Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder
        table._on_sort_column_changed(index, order)
        table._on_sort_column_changed(index, order)
        return True
    columns = browser.model.activeCols
    if column not in columns:
        return False
    # Before 2.1.45 unsortable columns open a modal notice; before 2.1.28 there were more.
    unsortable = ('question', 'answer') + (() if at_least(2, 1, 28) else ('template', 'deck', 'note', 'noteTags'))
    if column in unsortable:
        from .protocol import ApiError
        raise ApiError('invalidParams', 'This Anki release cannot sort the browser by ' + column + '.')
    # The native handler reverses rows after an asynchronous editor save; the
    # caller has saved the editor, so set the order and search synchronously.
    col = browser.col
    col.conf['sortType'] = column
    col.conf['sortBackwards'] = descending
    col.setMod()
    browser.search()
    browser.setSortIndicator()
    return True


def editor_save(editor, callback, keepFocus=False):
    """Save the shown note, then call back; 2.1.45 renamed saveNow."""
    (getattr(editor, 'call_after_note_saved', None) or editor.saveNow)(callback, keepFocus=keepFocus)


def saves_editor(editor):
    return callable(getattr(editor, 'call_after_note_saved', None) or getattr(editor, 'saveNow', None))


def reloads_changed_notes(editor, method):
    """Whether a saved editor shows the result of a note write afterwards.

    Browser, Edit Current, and custom editor hosts reload a classic editor's Python
    note from change notifications (from the reset hook before 2.1.45) and drop
    deleted notes. The web editors of 26.08 keep only a note ID; outside Add mode
    their page reloads field and tag changes from the same notifications, but a
    deleted or converted note fails to load there."""
    if getattr(editor, 'note', None) is not None:
        return True
    return (method in ('notes.update', 'tags.add', 'tags.remove', 'tags.replace')
            and hasattr(editor, 'reload_note') and not getattr(editor, 'addMode', False))


def binding_error(error, function):
    """Name methods by their qualified name in argument errors, as Python 3.10+ does."""
    message = str(error)
    if sys.version_info < (3, 10) and message.startswith(function.__name__ + '('):
        return TypeError(function.__qualname__ + message[len(function.__name__):])
    return error


def repeated(field):
    """Whether a protobuf field descriptor is a repeated field, for every protobuf release."""
    if hasattr(field, 'is_repeated'):
        return field.is_repeated
    return field.label == field.LABEL_REPEATED


def deck_config_descriptor():
    """The native preset descriptor, or None before 2.1.28.

    2.1.45 introduced DeckConfig.Config (its module was renamed in 2.1.66);
    2.1.28-2.1.44 describe the same options as backend DeckConfigInner.
    """
    try:
        from anki.deck_config_pb2 import DeckConfig
    except ImportError:
        try:
            from anki.deckconfig_pb2 import DeckConfig
        except ImportError:
            DeckConfig = None
    if DeckConfig is not None:
        return DeckConfig.Config.DESCRIPTOR
    for module in ('anki._backend.backend_pb2', 'anki.backend_pb2'):
        try:
            return importlib.import_module(module).DeckConfigInner.DESCRIPTOR
        except (ImportError, AttributeError):
            pass
    return None


def message(cls, **values):
    """Build a protobuf message, omitting fields this release does not define."""
    known = cls.DESCRIPTOR.fields_by_name
    return cls(**{name: value for name, value in values.items() if name in known and value is not None})


def field(value, name, default=None):
    """Read a protobuf field this release may not define."""
    if not hasattr(value, 'DESCRIPTOR'):
        return getattr(value, name, default)
    return getattr(value, name) if name in value.DESCRIPTOR.fields_by_name else default


# Before 25.07, native rendering marked an empty front only by appending a
# notice that links to one of these help pages and repeating it as the answer.
EMPTY_FRONT_LINKS = ('#front-of-card-is-blank', '#no-cloze-filter-on-cloze-note-type',
                     '/the-front-of-this-card-is-blank', '/no-cloze-found-on-card')


def rendered_empty(output):
    """Whether a partial render has an empty front, as Anki decides when adding cards."""
    if 'is_empty' in output.DESCRIPTOR.fields_by_name:
        return output.is_empty
    answer, question = output.answer_nodes, output.question_nodes
    if not question or question[-1].WhichOneof('value') != 'text':
        return False
    front = question[-1]
    # 2.1.41-2.1.44 replace both sides with the message; earlier releases append it to the question.
    return ((len(answer) == 1 and answer[0] == front
             or re.fullmatch("<div>[^<]*<br><a href='[^']*'>[^<]*</a></div>", front.text) is not None)
            and any(link + "'>" in front.text for link in EMPTY_FRONT_LINKS))


def import_package(col, path):
    """Import an .apkg with notetype merging, scheduling and presets where the release offers options (23.10+)."""
    if not hasattr(col, 'import_anki_package'):
        # Before 2.1.52 Anki imported packages with its Python importer, which clears undo.
        from anki.importing.apkg import AnkiPackageImporter
        import zipfile
        importer = AnkiPackageImporter(col, path)
        try:
            importer.run()
        except zipfile.BadZipFile as error:
            # Report it as the Rust importer does.
            raise OSError('invalid Zip archive: ' + str(error)) from error
        finally:
            if hasattr(importer, 'close'):
                importer.close()
            elif getattr(importer, 'zip', None):
                # Before 2.1.50 the importer left its archive open.
                importer.zip.close()
        try:
            from anki.collection import OpChanges
        except ImportError:
            return LegacyChanges()
        return message(OpChanges, card=True, note=True, deck=True, deck_config=True, notetype=True,
                       tag=True, note_text=True, browser_table=True, study_queues=True, mtime=True)
    from anki import import_export_pb2
    if not hasattr(import_export_pb2, 'ImportAnkiPackageOptions'):
        # 2.1.52-2.1.66 import scheduling and presets and keep conflicting notetypes separate.
        return col.import_anki_package(path)
    options = message(import_export_pb2.ImportAnkiPackageOptions,
                      merge_notetypes=True, with_scheduling=True, with_deck_configs=True)
    return col.import_anki_package(import_export_pb2.ImportAnkiPackageRequest(package_path=path, options=options))


def export_package(col, path, deck_id, scheduling):
    if not hasattr(col, 'export_anki_package'):
        # Before 2.1.52 Anki exported packages with its Python exporter.
        from anki.exporting import AnkiPackageExporter
        exporter = AnkiPackageExporter(col)
        exporter.did, exporter.includeSched, exporter.includeMedia = deck_id, scheduling, True
        exporter.exportInto(path)
        return
    from anki import import_export_pb2
    from anki.collection import DeckIdLimit
    limit = DeckIdLimit(deck_id=deck_id)
    if hasattr(import_export_pb2, 'ExportAnkiPackageOptions'):
        options = import_export_pb2.ExportAnkiPackageOptions(with_scheduling=scheduling, with_media=True, legacy=True)
        return col.export_anki_package(out_path=path, options=options, limit=limit)
    return col.export_anki_package(out_path=path, limit=limit, with_scheduling=scheduling,
                                   with_media=True, legacy_support=True)


try:
    from anki.collection import AddNoteRequest
except ImportError:
    # Collection.add_notes and its request arrived in 23.10.
    AddNoteRequest = namedtuple('AddNoteRequest', 'note deck_id')


def column_sorting(column, kind):
    """A browser column's sort mode for notes or cards; 23.10 split the single mode by kind."""
    name = 'sorting_notes' if kind == 'notes' else 'sorting_cards'
    return getattr(column, name) if name in column.DESCRIPTOR.fields_by_name else column.sorting


def transact(col, op):
    """Apply op atomically; before 23.10 the collection is always inside an open transaction."""
    if hasattr(col.db, 'transact'):
        return col.db.transact(op)
    col.save()
    try:
        op()
    except BaseException:
        col.db.rollback()
        col.db.begin()
        raise
    col.save()


def which(message):
    """The set member of a message's main oneof, which 2.1.66 renamed from value to kind."""
    return message.WhichOneof('kind' if 'kind' in message.DESCRIPTOR.oneofs_by_name else 'value')


def backend_errors():
    """Exception classes raised by the Rust backend; 2.1.55 gave them the BackendError base."""
    import anki.errors
    if hasattr(anki.errors, 'BackendError'):
        return (anki.errors.BackendError,)
    names = ('LocalizedError', 'NotFoundError', 'ExistsError', 'Interrupted', 'UndoEmpty', 'StringError')
    return tuple(getattr(anki.errors, name) for name in names if hasattr(anki.errors, name))


def renders_uncommitted(col):
    """Whether the backend renders unsaved notes; from 2.1.28."""
    return has(col._backend, 'render_uncommitted_card_legacy') or has(col._backend, 'render_uncommitted_card')


def render_uncommitted(col, note, card_ord, template, fill_empty):
    """Render a template against an unsaved note; partial_render (2.1.61+) leaves Python filters unapplied."""
    # Before 2.1.45 the unsuffixed method took the template as JSON bytes.
    render = getattr(col._backend, 'render_uncommitted_card_legacy', None) or col._backend.render_uncommitted_card
    options = {'note': note, 'card_ord': card_ord, 'template': template, 'fill_empty': fill_empty}
    if 'partial_render' in inspect.signature(render).parameters:
        options['partial_render'] = True
    return render(**options)


def _import_dialog_available():
    try:
        from aqt.import_export import import_dialog, importing
    except ImportError:
        return False
    return (all(hasattr(import_dialog, name) for name in ('ImportDialog', 'AnkiPackageArgs', 'CsvArgs', 'JsonFileArgs'))
            and all(hasattr(importing, name) for name in ('ColpkgImporter', 'import_collection_package_op')))


class _ClosedWebView:
    def setFocus(self):
        pass

    def cleanup(self):
        pass


def import_dialog(mw, args):
    """Open Anki's import dialog, tolerating 23.10-24.04's late setup focus callback."""
    from aqt.import_export.import_dialog import ImportDialog
    if at_least(24, 6):
        return ImportDialog(mw, args)

    class Dialog(ImportDialog):
        def reject(self):
            ImportDialog.reject(self)
            # The setup callback focuses self.web and can run after an early close.
            self.web = _ClosedWebView()

    return Dialog(mw, args)


FEATURES = {
    'editorDialog': (lambda: editor_dialog_available(), 'Requires the note editor modes of Anki 2.1.50.'),
    # Earlier importers report through modal dialogs and offer no completion signal.
    'importDialog': (_import_dialog_available, 'Requires the import dialog of Anki 23.10 or later.'),
}


def missing_feature(name):
    """The reason a release feature is unavailable, or None."""
    available, reason = FEATURES[name]
    return None if available() else reason


def scheduling_states(col, card_id):
    """A card's current and next v3 states; 2.1.55 renamed get_next_card_states."""
    backend = col._backend
    if hasattr(backend, 'get_scheduling_states'):
        return backend.get_scheduling_states(card_id)
    return backend.get_next_card_states(card_id)


def reviewer_states(info):
    """The reviewer's v3 card states; 2.1.55 renamed next_states."""
    return info.states if hasattr(info, 'states') else info.next_states


def reviewer_leech(reviewer, suspended):
    """Report a leech; before 25.07 onLeech took an optional card and read its queue."""
    if 'suspended' in inspect.signature(reviewer.onLeech).parameters:
        reviewer.onLeech(suspended)
    else:
        reviewer.onLeech()


def learning_seconds(col, card):
    """The current (re)learning step delay, as rslib reports it in the card's state."""
    backend = col._backend
    if not has(backend, 'get_scheduling_states') and not has(backend, 'get_next_card_states'):
        return _learning_seconds(col, card)
    states = scheduling_states(col, card.id)
    native = states.current.normal
    if which(states.current) == 'filtered' and which(states.current.filtered) == 'rescheduling':
        native = states.current.filtered.rescheduling.original_state
    kind = which(native)
    if kind == 'learning':
        return native.learning.scheduled_secs
    if kind == 'relearning':
        return native.relearning.learning.scheduled_secs
    return None


def _learning_seconds(col, card):
    """Port of rslib 2.1.44 current_card_state for releases without native card states."""
    if card.odid and not col.decks.get(card.did).get('resched', True):
        # Previewing filtered decks report a preview state.
        return None
    config = col.decks.confForDid(card.odid or card.did)
    steps = config['new' if card.type == 1 else 'lapse']['delays']
    index = min(max(len(steps) - card.left % 1000, 0), max(len(steps) - 1, 0))
    return int(steps[index] * 60) if steps else 0


def collection_syncs_media(col):
    """Anki 23.10 syncs media with the collection and reports media status itself."""
    return hasattr(col, 'media_sync_status')


def sync_collection(col, auth, media):
    if collection_syncs_media(col):
        return col.sync_collection(auth, media)
    return col.sync_collection(auth)


def release_sync_lock(col):
    """Before 23.10 Python holds a write transaction that native sync commits first."""
    if 'trx' not in inspect.signature(col.save).parameters:
        return lambda: None
    col.save(trx=False)
    return col.db.begin


def full_sync(mw, col, auth, upload, server_usn):
    """Back up, close, and replace one side; runs in the background like Anki's own sync."""
    if not upload and hasattr(mw, '_close_for_full_download'):
        # 2.1.45-2.1.54 back up by closing and reopening for the download.
        mw._close_for_full_download()
    else:
        if not upload and hasattr(mw, 'create_backup_now'):
            mw.create_backup_now()
        # Before 2.1.40 Anki's own full download took no backup first.
        col.close_for_full_sync()
    if hasattr(col, 'full_upload_or_download'):
        col.full_upload_or_download(auth=auth, server_usn=server_usn, upload=upload)
    else:
        (col.full_upload if upload else col.full_download)(auth)


def reopen_after_full_sync(mw):
    if 'after_full_sync' in inspect.signature(mw.reopen).parameters:
        mw.reopen(after_full_sync=True)
    else:
        mw.col.reopen(after_full_sync=True)


def refresh_after_sync(mw):
    """Redraw the toolbar's sync state; 2.1.41 named this step."""
    if hasattr(mw, '_refresh_after_sync'):
        mw._refresh_after_sync()
    else:
        mw.toolbar.redraw()


def start_media_sync(mw, col):
    """23.10 only monitors the media sync that the collection sync started."""
    if collection_syncs_media(col):
        mw.media_syncer.start_monitoring()
    else:
        mw.media_syncer.start()


def watch_media_sync(syncer):
    """Before 23.10 the media syncer only logs failures and cancellation. Observe its
    next completion; the returned function gives that run's exception, or None."""
    outcome = []
    finished = syncer._on_finished
    native = syncer.__dict__.get('_on_finished', outcome)
    def restore():
        if native is outcome:
            syncer.__dict__.pop('_on_finished', None)
        else:
            syncer._on_finished = native
    def observed(future):
        restore()
        outcome.append(future.exception())
        finished(future)
    syncer._on_finished = observed
    def result():
        restore()
        return outcome[0] if outcome else None
    return result


def collection_will_temporarily_close(col):
    hook = gui_hook('collection_will_temporarily_close')
    if hook is not None:
        hook(col)


def ask_user(text, callback, buttons, default_button, parent):
    """A non-modal button choice; ask_user_dialog exists from 2.1.55."""
    try:
        from aqt.utils import ask_user_dialog
    except ImportError:
        ask_user_dialog = None
    if ask_user_dialog is not None:
        return ask_user_dialog(text, callback=callback, buttons=buttons, default_button=default_button, parent=parent)
    from aqt.qt import QMessageBox
    box = QMessageBox(parent)
    box.setText(text)
    role = getattr(QMessageBox, 'ActionRole', None)
    if role is None:
        role = QMessageBox.ButtonRole.ActionRole
    added = [box.addButton(label, role) for label in buttons]
    box.setDefaultButton(added[default_button])
    box.setEscapeButton(added[default_button])
    box.buttonClicked.connect(lambda button: callback(added.index(button)))
    box.open()
    return box



def _graph_rows(col, search):
    """The searched cards and their reviews, as the 2.1.28 graphs backend returned them."""
    from anki.utils import ids2str
    cids = ids2str(col.find_cards(search))
    revlog = [SimpleNamespace(id=id, review_kind=kind, last_interval=last, taken_millis=taken) for id, kind, last, taken
              in col.db.execute('select id, type, lastIvl, time from revlog where cid in %s order by id' % cids)]
    cards = [SimpleNamespace(queue=queue, ctype=kind, interval=interval) for queue, kind, interval
             in col.db.execute('select queue, type, ivl from cards where id in %s' % cids)]
    return SimpleNamespace(revlog=revlog, cards=cards, next_day_at_secs=col.sched.dayCutoff)


def graphs(col, search):
    """Statistics summaries; before 2.1.56 the backend returned raw rows to the frontend.

    The fallback ports rslib's 2.1.56 today, reviews, and card_counts summaries."""
    if has(col._backend, 'graphs'):
        raw = graphs_response(col, search)
        if 'today' in raw.DESCRIPTOR.fields_by_name:
            return raw
    else:
        raw = _graph_rows(col, search)
    kinds = ('learn', 'young', 'relearn', 'filtered')
    def counts():
        return SimpleNamespace(learn=0, relearn=0, young=0, mature=0, filtered=0)
    count, time, start_of_today = {}, {}, (raw.next_day_at_secs - 86400) * 1000
    today = SimpleNamespace(answer_count=0)
    for review in raw.revlog:
        if review.review_kind == 4:
            continue
        elapsed = review.id // 1000 - raw.next_day_at_secs
        day = -(-elapsed // 86400) if elapsed < 0 else elapsed // 86400
        kind = kinds[review.review_kind]
        if kind == 'young' and review.last_interval >= 21:
            kind = 'mature'
        for totals, value in ((count, 1), (time, review.taken_millis)):
            entry = totals.setdefault(day, counts())
            setattr(entry, kind, getattr(entry, kind) + value)
        if review.id >= start_of_today:
            today.answer_count += 1
    active = SimpleNamespace(newCards=0, learn=0, relearn=0, young=0, mature=0, suspended=0, buried=0)
    for card in raw.cards:
        if card.queue == -1:
            active.suspended += 1
        elif card.queue in (-2, -3):
            active.buried += 1
        else:
            kind = ('newCards', 'learn', 'young', 'relearn')[card.ctype]
            # 2.1.28-2.1.35 name the interval ivl.
            if kind == 'young' and getattr(card, 'interval', getattr(card, 'ivl', 0)) >= 21:
                kind = 'mature'
            setattr(active, kind, getattr(active, kind) + 1)
    return SimpleNamespace(today=today, reviews=SimpleNamespace(count=count, time=time),
                           card_counts=SimpleNamespace(excluding_inactive=active))


def error_message(error):
    """A backend error's details; before 2.1.55 errors held only a localized sentence."""
    message = str(error)
    # Fluent isolates the details argument, as in "Invalid input: \u2068soon\u2069".
    inner = re.fullmatch('[^\u2068]*\u2068(.*)\u2069[^\u2069]*', message, re.S)
    if inner:
        return inner.group(1)
    if not message and type(error).__name__ == 'NotFoundError':
        return 'Not found.'
    return message


def _utility(name, legacy):
    import anki.utils
    function = getattr(anki.utils, name, None)
    return function if function is not None else getattr(anki.utils, legacy)


def strip_html_media(text):
    """Anki's media-preserving HTML stripping; 2.1.50 renamed it and moved it to Rust."""
    return _utility('strip_html_media', 'stripHTMLMedia')(text)


def field_checksum(text):
    return _utility('field_checksum', 'fieldChecksum')(text)


def parsed(value, cls):
    """Before 2.1.50 some backend calls returned serialized messages for the web frontend."""
    if isinstance(value, bytes):
        message = cls()
        message.ParseFromString(value)
        return message
    return value


def graphs_response(col, search):
    try:
        from anki.stats_pb2 import GraphsResponse
    except ImportError:
        # Before 2.1.45 the message lived with the backend; 2.1.41 moved it into anki._backend.
        try:
            from anki._backend.backend_pb2 import GraphsOut as GraphsResponse
        except ImportError:
            from anki.backend_pb2 import GraphsOut as GraphsResponse
    return parsed(col._backend.graphs(search=search, days=0), GraphsResponse)


def _default_map(old, new):
    """Port of rslib's default field/template map: names first, then unused sources in order."""
    unused = {item['name']: item['ord'] for item in old}
    chosen = [unused.pop(item['name'], None) for item in new]
    remaining = iter(sorted(unused.values()))
    return [next(remaining, -1) if index is None else index for index in chosen]


def change_notetype_info(col, old_id, new_id):
    if not has(col.models, 'change_notetype_info'):
        # Before 2.1.45 the plan is built in Python and applied by ModelManager.change.
        old, new = col.models.get(old_id), col.models.get(new_id)
        cloze = old['type'] == 1 or new['type'] == 1
        return SimpleNamespace(input=SimpleNamespace(
            old_notetype_id=old_id, new_notetype_id=new_id, note_ids=[], is_cloze=cloze,
            new_fields=_default_map(old['flds'], new['flds']),
            new_templates=[] if cloze else _default_map(old['tmpls'], new['tmpls'])))
    from anki import notetypes_pb2
    return parsed(col.models.change_notetype_info(old_notetype_id=old_id, new_notetype_id=new_id),
                  notetypes_pb2.ChangeNotetypeInfo)


def change_notetype_of_notes(col, request):
    if has(col.models, 'change_notetype_of_notes'):
        return col.models.change_notetype_of_notes(request)
    old, new = col.models.get(request.old_notetype_id), col.models.get(request.new_notetype_id)
    fields = {source: target for target, source in enumerate(request.new_fields) if source >= 0}
    if request.is_cloze:
        # The legacy change keeps cloze card ordinals and drops those beyond a standard target.
        cards = {item['ord']: item['ord'] for item in old['tmpls']}
    else:
        cards = {item['ord']: None for item in old['tmpls']}
        cards.update({source: target for target, source in enumerate(request.new_templates) if source >= 0})
    # Like the native change, mark the schema modified rather than asking the user.
    col.modSchema(check=False)
    col.models.change(old, list(request.note_ids), new, fields or {0: None}, cards)
    return LegacyChanges()


def day_cutoff(col):
    """The next day's start; v3 schedulers before 2.1.50 name it dayCutoff."""
    cutoff = getattr(col.sched, 'day_cutoff', None)
    return cutoff if cutoff is not None else col.sched.dayCutoff


def deck_total(col, node):
    """Cards whose current deck is the node's deck, as native due counts total them from 2.1.47."""
    total = field(node, 'total_in_deck')
    if total is not None:
        return total
    return col.db.scalar('select count() from cards where did=?', node.deck_id)


def resets_counts():
    try:
        from anki import scheduler_pb2
    except ImportError:
        return False
    return 'reset_counts' in scheduler_pb2.ScheduleCardsAsNewRequest.DESCRIPTOR.fields_by_name


def schedule_cards_as_new(col, card_ids, restore_position, reset_counts, log):
    """Forget cards; before 2.1.50 cards record no original position to restore."""
    forget = getattr(col._backend, 'schedule_cards_as_new', None)
    parameters = inspect.signature(forget).parameters if forget else {}
    if 'card_ids' in parameters:
        # 2.1.39-2.1.49 take keywords; only 2.1.45 and later return OpChanges.
        changes = col._backend.schedule_cards_as_new(card_ids=card_ids, log=log)
        return changes if reports_changes() else None
    if 'message' not in parameters:
        # Before 2.1.39 forgetting writes no review log entry.
        col.sched.forgetCards(list(card_ids))
        return None
    from anki import scheduler_pb2
    request = message(scheduler_pb2.ScheduleCardsAsNewRequest, card_ids=card_ids,
                      restore_position=restore_position, reset_counts=reset_counts, log=log)
    return col._backend.schedule_cards_as_new(request)


class LegacyChanges(SimpleNamespace):
    """Stands in for OpChanges on releases before 2.1.45, which report no changes."""


def reports_changes():
    import anki.collection
    return hasattr(anki.collection, 'OpChanges')


def _require_row(col, table, id):
    # Before 2.1.28 loading a missing note or card failed while unpacking its row.
    if not col.db.scalar('select 1 from %s where id=?' % table, id):
        from anki.errors import NotFoundError
        raise NotFoundError()


def _note(col, note_id):
    from anki.notes import Note
    _require_row(col, 'notes', note_id)
    return Note(col, id=note_id)


def _card(col, card_id):
    _require_row(col, 'cards', card_id)
    return col.getCard(card_id)


def _new_note(col, notetype):
    from anki.notes import Note
    note = Note(col, notetype)
    # Python notes of 2.1.24-2.1.26 take an id when created; native notes have none until added.
    note.id = 0
    return note


def _set_deck(col, card_ids, deck_id):
    """Move cards as the 2.1.15-2.1.37 browser did: return filtered cards home first."""
    col.sched.remFromDyn(list(card_ids))
    col.decks.setDeck(list(card_ids), deck_id)


def _add_note(col, note, deck_id):
    """Port of rslib add_note over the Python card generation of 2.1.24-2.1.26."""
    from anki.utils import timestampID
    note.id = note.id or timestampID(col.db, 'notes')
    templates = col.findTemplates(note)
    if not templates:
        # rslib adds the first card when no template has a non-empty front.
        templates = [dict(note.model()['tmpls'][0], ord=0)]
    note.flush()
    due = col.nextID('pos')
    for template in templates:
        col._newCard(note, template, due, did=deck_id)
    return LegacyChanges(count=len(templates))


def _remove_notes(col, note_ids):
    col.remNotes(list(note_ids))
    return LegacyChanges()


def _deck_due_tree(sched):
    """The due tree of 2.1.24-2.1.26 as native-shaped nodes under a root."""
    def node(value):
        name, did, review, learn, new, children = value
        return SimpleNamespace(deck_id=did, name=name, review_count=review, learn_count=learn, new_count=new,
                               children=[node(child) for child in children])
    return SimpleNamespace(deck_id=0, name='', review_count=0, learn_count=0, new_count=0,
                           children=[node(value) for value in sched.deckDueTree()])


def _trash_media(media, fnames):
    """Move files to media.trash beside the folder, as the Rust backend does from 2.1.22."""
    import os
    folder = media.dir()
    trash = os.path.join(os.path.dirname(folder), 'media.trash')
    os.makedirs(trash, exist_ok=True)
    for fname in fnames:
        path = os.path.join(folder, fname)
        if os.path.exists(path):
            os.replace(path, os.path.join(trash, fname))


def _names_and_ids(items):
    return [SimpleNamespace(id=int(item['id']), name=item['name'])
            for item in sorted(items, key=lambda item: item['name'].casefold())]


def _remove_notetype(models, notetype_id):
    models.rem(models.get(notetype_id))
    return LegacyChanges()


def clear_notetype_cache(col):
    """Drop cached note types; before 2.1.28 the manager held them all without a cache."""
    cache = getattr(col.models, '_cache', None)
    if cache is not None:
        cache.clear()


def _update_note(col, note, **_):
    note.flush()
    return LegacyChanges()


def _update_card(col, card, **_):
    card.flush()
    return LegacyChanges()


def _update_notetype(models, notetype):
    if hasattr(models, 'models'):
        # 2.1.24-2.1.26 save only registered dicts and generate cards for new templates on request.
        notetype['id'] = models.get(notetype['id'])['id']
        nids = _remap_structure(models.col, notetype)
        models.update(notetype)
        models.save(notetype, templates=True)
        if nids:
            models.col.updateFieldCache(nids)
    else:
        models.save(notetype)
    return LegacyChanges()


def _remap_structure(col, notetype):
    """Port of rslib update_notetype: entries keep their old ord, new ones have none."""
    from anki.utils import ids2str, intTime, joinFields, splitFields
    old = col.models.get(notetype['id'])
    nids = col.db.list('select id from notes where mid=?', notetype['id'])
    fields = [field.get('ord') for field in notetype['flds']]
    if fields != list(range(len(old['flds']))):
        col.modSchema(check=False)
        rows = []
        for id, flds in col.db.execute('select id, flds from notes where mid=?', notetype['id']):
            values = splitFields(flds)
            rows.append((joinFields([values[ord] if ord is not None and ord < len(values) else '' for ord in fields]),
                         intTime(), col.usn(), id))
        col.db.executemany('update notes set flds=?, mod=?, usn=? where id=?', rows)
    templates = [template.get('ord') for template in notetype['tmpls']]
    if notetype['type'] == 0 and templates != list(range(len(old['tmpls']))):
        col.modSchema(check=False)
        moved = {ord: index for index, ord in enumerate(templates) if ord is not None}
        cards = 'nid in ' + ids2str(nids)
        col.remCards(col.db.list('select id from cards where %s and ord not in %s' % (cards, ids2str(moved))))
        if moved:
            cases = ' '.join('when %d then %d' % pair for pair in moved.items())
            col.db.execute('update cards set ord=(case ord %s end), mod=?, usn=? where %s' % (cases, cards), intTime(), col.usn())
    for key in ('flds', 'tmpls'):
        for index, value in enumerate(notetype[key]):
            value['ord'] = index
    notetype['sortf'] = min(notetype['sortf'], len(notetype['flds']) - 1)
    return nids


def clear_unused_tags(col):
    """Remove unused tags; before 2.1.45 the count is measured from the tag list."""
    before = set(col.tags.all())
    out = col.tags.clear_unused_tags()
    if out is None:
        out = LegacyChanges(count=len(before - set(col.tags.all())))
    return out


class _CardRecord:
    """A stored card with the protobuf surface of 2.1.24's backend Card message, which older backends lack."""
    FIELDS = ('id', 'note_id', 'deck_id', 'template_idx', 'mtime_secs', 'usn', 'ctype', 'queue', 'due', 'interval',
              'ease_factor', 'reps', 'lapses', 'remaining_steps', 'original_due', 'original_deck_id', 'flags', 'data')
    DESCRIPTOR = SimpleNamespace(fields_by_name=dict.fromkeys(FIELDS))

    def __init__(self, col, card_id):
        _require_row(col, 'cards', card_id)
        row = col.db.first('select id, nid, did, ord, mod, usn, type, queue, due, ivl, factor, reps, lapses, '
                           'left, odue, odid, flags, data from cards where id = ?', card_id)
        self.__dict__.update(zip(self.FIELDS, row))

    def ClearField(self, name):
        setattr(self, name, type(getattr(self, name))())

    def SerializeToString(self):
        return repr([getattr(self, name) for name in self.FIELDS]).encode()

    def __eq__(self, other):
        return isinstance(other, _CardRecord) and vars(self) == vars(other)


def _find_notes(col, query):
    # The Python finder's findNotes returns no notes for an invalid term, where findCards raises.
    import anki.find
    finder = anki.find.Finder(col)
    if finder._where(finder._tokenize(query))[0] is None:
        raise Exception('invalidSearch')
    return col.findNotes(query)


def find_ids(col, kind, query, order=False, reverse=False):
    finder = col.find_notes if kind == 'notes' else col.find_cards
    if order is False and not has(col, 'get_browser_column'):
        # Before 2.1.45 find_notes takes no order.
        return finder(query)
    return finder(query, order=order, reverse=reverse)


def _remove_decks(decks, deck_ids):
    for deck_id in deck_ids:
        decks.rem(deck_id, cardsToo=True)
    return LegacyChanges()


def cloze_numbers(col, note):
    if has(col._backend, 'cloze_numbers_in_note'):
        return col._backend.cloze_numbers_in_note(note._to_backend_note())
    # Before 2.1.41 cloze numbers are read from the field text.
    return sorted({int(number) for text in note.fields for number in re.findall(r'\{\{c(\d+)::', text)})


def set_due_date(col, card_ids, days):
    # The config key arrived in 2.1.45.
    if 'config_key' in inspect.signature(col.sched.set_due_date).parameters:
        return col.sched.set_due_date(card_ids, days, config_key=None)
    return col.sched.set_due_date(card_ids, days)


def deck_search(col, name):
    if has(col, 'build_search_string'):
        from anki.collection import SearchNode
        return col.build_search_string(SearchNode(deck=name))
    # Before 2.1.41 searches are written by hand.
    return 'deck:"' + re.sub(r'([\\"*_])', r'\\\1', name) + '"'


def _add_normal_deck(decks, name):
    return LegacyChanges(id=decks.id(name, create=True))


def _add_notetype(models, notetype):
    models.add(notetype)
    return LegacyChanges(id=notetype['id'])


CLOZE = re.compile(r'\{\{c\d+::')


def _cloze_fields(notetype):
    """Indexes of fields rendered through a cloze filter in the first template."""
    names = set()
    for tag in re.findall(r'\{\{([^}]*)\}\}', notetype['tmpls'][0]['qfmt']):
        parts = tag.strip().split(':')
        if 'cloze' in parts[:-1]:
            names.add(parts[-1])
    return {field['ord'] for field in notetype['flds'] if field['name'] in names}


def _fields_check(note):
    """Port of rslib 2.1.45 note_fields_check: empty, then cloze problems, then duplicates."""
    state = note.dupeOrEmpty()
    if state == 1:
        return 1
    notetype = note.model()
    cloze = notetype['type'] == 1
    fields = _cloze_fields(notetype) if cloze else set()
    has_cloze = False
    for index, text in enumerate(note.fields):
        if CLOZE.search(text):
            if not cloze:
                return 4
            if index not in fields:
                return 5
            has_cloze = True
    if cloze and not has_cloze:
        return 3
    return state


# Modern names that releases before 2.1.45 expose under older spellings.
@functools.lru_cache(maxsize=None)
def release():
    """The running Anki release, for rules that no API exposes."""
    try:
        from anki.buildinfo import version
    except ImportError:
        from anki import version  # Before 2.1.20.
    return tuple(int(part) for part in re.findall(r'\d+', version.split('+')[0])[:3])


@functools.lru_cache(maxsize=None)
def field_name_rules():
    """The characters rslib removes from field names and strips from their start.

    2.1.36 added '"' to the removed characters and 2.1.41 began stripping leading "#", "^" and "/"."""
    removed = re.compile(r'[:{}"]' if release() >= (2, 1, 36) else r'[:{}]')
    leading = re.compile(r'^[\s#/^]+' if release() >= (2, 1, 41) else r'^\s+')
    return removed, leading


def _set_due_date(sched, card_ids, days, config_key=None):
    """Before 2.1.41 Anki rescheduled to a day range, also setting the interval and starting ease."""
    match = re.fullmatch(r'\s*(\d+)(?:\s*-\s*(\d+))?\s*!?\s*', days)
    if not match:
        from anki.errors import InvalidInput
        raise InvalidInput(days)
    low = int(match.group(1))
    high = int(match.group(2) or low)
    sched.reschedCards(list(card_ids), min(low, high), max(low, high))


# 2.1.28 made the client a context manager that closes its session.
_HTTP_CLIENT_BACKPORTS = {
    '__enter__': lambda client: client,
    '__exit__': lambda client, *args: client.session.close(),
}


_SCHEDULER_BACKPORTS = {
    'set_due_date': _set_due_date,
    'suspend_cards': lambda sched, ids: sched.suspendCards(list(ids)),
    'unsuspend_cards': lambda sched, ids: sched.unsuspendCards(list(ids)),
    'rebuild_filtered_deck': lambda sched, deck_id: sched.rebuildDyn(deck_id),
    'empty_filtered_deck': lambda sched, deck_id: sched.emptyDyn(deck_id),
    'deck_due_tree': _deck_due_tree,
}


BACKPORTS = {
    'anki.collection.Collection': {
        'get_note': _note,
        'get_card': _card,
        'note_count': lambda col: col.noteCount(),
        'card_count': lambda col: col.cardCount(),
        'new_note': _new_note,
        'update_note': _update_note,
        'update_card': _update_card,
        '_load_scheduler': lambda col: col._loadScheduler(),
        'set_user_flag_for_cards': lambda col, flag, card_ids: col.setUserFlag(flag, list(card_ids)),
        'set_deck': _set_deck,
        'fix_integrity': lambda col: col.fixIntegrity(),
        'add_note': _add_note,
        'remove_notes': _remove_notes,
        'get_config': lambda col, key, default=None: col.conf.get(key, default),
        # Before 2.1.24 the Python finder searched and could not reverse its order.
        'find_cards': lambda col, query, order=False, reverse=False: (
            lambda ids: ids[::-1] if reverse else ids)(col.findCards(query, order)),
        'find_notes': _find_notes,
        # 2.1.28-2.1.40 sync through the backend directly.
        'sync_collection': lambda col, auth: col.backend.sync_collection(auth),
        'full_upload': lambda col, auth: col.backend.full_upload(auth),
        'full_download': lambda col, auth: col.backend.full_download(auth),
        'abort_sync': lambda col: col.backend.abort_sync() and None,
        'abort_media_sync': lambda col: col.backend.abort_media_sync() and None,
    },
    'anki.notes.Note': {
        'fields_check': _fields_check,
        'note_type': lambda note: note.model(),
        '_to_backend_note': lambda note: note.to_backend_note(),
        '_field_index': lambda note, name: note._fieldOrd(name),
        'has_tag': lambda note, tag: note.hasTag(tag),
        'add_tag': lambda note, tag: note.addTag(tag),
        'remove_tag': lambda note, tag: note.delTag(tag),
        'joined_fields': lambda note: note.joinedFields(),
        'card_ids': lambda note: note.col.db.list('select id from cards where nid=? order by ord', note.id),
    },
    'anki.cards.Card': {
        # Before 2.1.20 cards rendered through q() and a(), both prefixed with the CSS.
        'question': lambda card, reload=False, browser=False: card.q(reload, browser),
        'answer': lambda card: card.a(),
        'note_type': lambda card: card.model(),
        'start_timer': lambda card: card.startTimer(),
        'time_limit': lambda card: card.timeLimit(),
        'time_taken': lambda card: card.timeTaken(),
        'user_flag': lambda card: card.userFlag(),
        # The stored card; callers compare freshly loaded cards.
        '_to_backend_card': lambda card: (card.col._backend.get_card(card.id) if has(card.col._backend, 'get_card')
                                          else _CardRecord(card.col, card.id)),
    },
    'anki.schedv2.Scheduler': _SCHEDULER_BACKPORTS,
    # Before 2.1.21 the v1 scheduler did not subclass the v2 one.
    'anki.sched.Scheduler': _SCHEDULER_BACKPORTS,
    'anki.media.MediaManager': {
        # Before 2.1.22 Python managed the media folder.
        'write_data': lambda media, fname, data: media.writeData(fname, data),
        'trash_files': _trash_media,
    },
    'anki.httpclient.HttpClient': _HTTP_CLIENT_BACKPORTS,
    'anki.sync.AnkiRequestsClient': _HTTP_CLIENT_BACKPORTS,
    'anki.tags.TagManager': {
        # Registering all notes rebuilds the tag list before 2.1.41.
        'clear_unused_tags': lambda tags: tags.registerNotes(),
        'bulk_add': lambda tags, note_ids, tags_text: tags.bulkAdd(list(note_ids), tags_text),
    },
    'anki.models.ModelManager': {
        'by_name': lambda models, name: models.byName(name),
        'add_dict': _add_notetype,
        'update_dict': _update_notetype,
        'use_count': lambda models, notetype: models.useCount(notetype),
        'all_names_and_ids': lambda models: _names_and_ids(models.all()),
        'new_field': lambda models, name: models.newField(name),
        'add_field': lambda models, notetype, field: models.addField(notetype, field),
        'rename_field': lambda models, notetype, field, name: models.renameField(notetype, field, name),
        'new_template': lambda models, name: models.newTemplate(name),
        'add_template': lambda models, notetype, template: models.addTemplate(notetype, template),
        'remove': _remove_notetype,
    },
    'anki.decks.DeckManager': {
        'by_name': lambda decks, name: decks.byName(name),
        'add_normal_deck_with_name': _add_normal_deck,
        'remove': _remove_decks,
        'new_filtered': lambda decks, name: decks.newDyn(name),
        'id_for_name': lambda decks, name: decks.id(name, create=False),
        # Missing presets fall back to Default, as the Rust backend does from 2.1.24.
        'get_config': lambda decks, conf_id: decks.dconf.get(str(conf_id)) or decks.dconf['1'],
        'all_config': lambda decks: decks.allConf(),
        'all_names_and_ids': lambda decks, skip_empty_default=False, include_filtered=True: _names_and_ids(
            deck for deck in decks.all() if include_filtered or not deck['dyn']),
    },
}


def _to_json_bytes(value):
    import json
    return json.dumps(value, separators=(',', ':')).encode('utf8')


def _rsbackend(name):
    def load():
        import importlib.util
        if importlib.util.find_spec('anki.rsbackend') is None:
            return None  # Before 2.1.20 Anki had no Rust backend.
        import anki.rsbackend
        return getattr(anki.rsbackend, name, None)
    return load


# Module names the plugin imports, with loaders for their earlier homes.
MODULE_BACKPORTS = {
    'anki.errors': {
        'NotFoundError': _rsbackend('NotFoundError'),
        'InvalidInput': _rsbackend('InvalidInput'),
        'Interrupted': _rsbackend('Interrupted'),
    },
    'anki.sync': {
        'SyncAuth': _rsbackend('SyncAuth'),
        'SyncOutput': _rsbackend('SyncOutput'),
    },
    'anki.utils': {
        'to_json_bytes': lambda: _to_json_bytes,
    },
}


def http_client():
    """Anki's HTTP client, which was anki.sync.AnkiRequestsClient before 2.1.20."""
    try:
        from anki.httpclient import HttpClient
    except ImportError:
        from anki.sync import AnkiRequestsClient as HttpClient
    return HttpClient()


def collection_class():
    """The collection class; before 2.1.28 it was private and opened by anki.storage.Collection()."""
    import anki.collection
    return getattr(anki.collection, 'Collection', None) or anki.collection._Collection


def install_backports():
    """Add modern collection methods to releases that lack them, never replacing native ones."""
    import importlib
    import importlib.util
    for path, methods in BACKPORTS.items():
        module, name = path.rsplit('.', 1)
        if importlib.util.find_spec(module) is None:
            continue
        cls = getattr(importlib.import_module(module), name, None)
        if cls is None and path == 'anki.collection.Collection':
            cls = collection_class()
        if cls is None:
            continue
        for method, function in methods.items():
            if not hasattr(cls, method):
                setattr(cls, method, function)
    for path, names in MODULE_BACKPORTS.items():
        module = importlib.import_module(path)
        for name, load in names.items():
            if not hasattr(module, name):
                value = load()
                if value is None and path == 'anki.errors':
                    # Nothing native raises it there, but backports may.
                    value = type(name, (Exception,), {})
                if value is not None:
                    setattr(module, name, value)
    if importlib.util.find_spec('anki._backend') is None:
        # Before 2.1.41 the collection named its backend col.backend. Later
        # releases assign _backend per instance, so this property must not exist there.
        # Before 2.1.20 there is no backend, and backend capabilities are absent.
        collection_class()._backend = property(lambda col: getattr(col, 'backend', None))

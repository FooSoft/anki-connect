"""Shared dispatcher, Qt admission and serialized native operation completion."""
import copy
import hashlib
import json
import time
import uuid

from . import compat
from .contract import SCHEMA
from .gui import Gui
from .protocol import ApiError, Deferred, Dispatcher, Operations, completed
from .services import Services


GUI_METHODS = {'collection.refresh', 'collection.sync', 'profiles.list', 'profiles.getActive',
               'profiles.switch', 'application.navigate', 'application.exit', 'application.importFile'}
GUI_METHODS.update(name for name in SCHEMA['x-methods'] if name.startswith(('browser.', 'editors.', 'reviewer.')))

# Collection paths each method needs; "a|b" accepts either name. Scheduler paths
# such as sched.build_answer exist only while the v3 scheduler is active.
NATIVE_REQUIREMENTS = {
    'notes.create': ('add_note', '_backend.render_uncommitted_card_legacy|_backend.render_uncommitted_card|findTemplates'),
    'notes.createMany': ('add_note', '_backend.render_uncommitted_card_legacy|_backend.render_uncommitted_card|findTemplates'),
    'notes.validate': ('_backend.render_uncommitted_card_legacy|_backend.render_uncommitted_card|findTemplates',),
    'notes.update': ('update_note',),
    'cards.move': ('set_deck',),
    'scheduling.getQueue': ('sched.get_queued_cards',),
    'scheduling.predict': ('_backend.get_scheduling_states|_backend.get_next_card_states',
                           '_backend.describe_next_states', 'sched.build_answer'),
    'scheduling.answer': ('sched.build_answer', 'sched.answer_card'),
    'scheduling.answerMany': ('sched.build_answer', 'sched.answer_card'),
    'scheduling.repositionNewCards': ('sched.reposition_new_cards',),
    'scheduling.setDueDate': ('sched.set_due_date',),
    'deckPresets.get': ('_backend.get_deck_config',),
    'deckPresets.create': ('decks.get_deck_configs_for_update', 'decks.update_deck_configs'),
    'deckPresets.update': ('decks.get_deck_configs_for_update', 'decks.update_deck_configs'),
    'deckPresets.assign': ('decks.get_deck_configs_for_update', 'decks.update_deck_configs'),
    'deckPresets.delete': ('decks.get_deck_configs_for_update', 'decks.update_deck_configs'),
    'media.store': ('media.write_data', 'media.trash_files'),
    'collection.checkIntegrity': ('fix_integrity',),
    'collection.undo': ('undo', 'undo_status'),
    # Before 2.1.28 Python synced over HTTP itself; there is no backend sync to drive.
    'collection.sync': ('_backend.sync_collection',),
}
REQUIREMENT_REASONS = {
    '_backend.sync_collection': 'Requires the native sync of Anki 2.1.28 or later.',
}
# Release features without a collection path; see compat.FEATURES.
FEATURE_REQUIREMENTS = {
    'editors.openNote': ('editorDialog',),
    'application.importFile': ('importDialog',),
}


def clear_editor_history():
    if compat.editor_dialog_available():
        from .edit import history
        history.note_ids.clear()


class Runtime:
    def __init__(self, owner, schedule=None):
        from aqt.qt import QTimer
        self.owner = owner
        self.schedule = schedule or (lambda callback: QTimer.singleShot(0, callback))
        # Polling delay for work that waits for active collection operations.
        self.schedule_later = lambda callback: QTimer.singleShot(25, callback)
        self.operations = Operations(self.schedule)
        self.dispatcher = Dispatcher(self)
        self.gui = Gui(self)
        self._collection = None
        self._session = None
        self.profile_name = None
        self.tokens = {}
        self.cursors = {}
        self.generation = 0
        self.exit_requested = False
        self.full_reset_required = False
        self.active_reviewer_card = None
        self.lifecycle_active = False
        self.media_recovered_session = None

    @property
    def mw(self):
        import aqt
        return aqt.mw

    @property
    def session(self):
        col = self.mw.col if self.mw else None
        if col is not self._collection:
            clear_editor_history()
            self._collection = col
            self._session = uuid.uuid4().hex if col else None
            self.profile_name = self.mw.pm.name if col else None
            self.tokens.clear()
            self.cursors.clear()
            self.gui.editors.clear()
        return self._session

    def invalidate_session(self, *args):
        self._collection = None
        self._session = None
        self.tokens.clear()
        self.cursors.clear()
        self.gui.editors.clear()
        clear_editor_history()

    def register_hooks(self):
        compat.gui_hook('profile_will_close').append(self.invalidate_session)
        compat.register_collection_close(self.invalidate_session)

    def service(self):
        session = self.session
        if session is None:
            raise ApiError('collectionUnavailable', 'Collection is not available.')
        return Services(self, self._collection, session)

    def capture(self, expected=None):
        session = self.session
        if session is None:
            raise ApiError('collectionUnavailable', 'Collection is not available.')
        if expected is not None and expected != session:
            raise ApiError('staleSession', 'Collection session changed.')
        return self._collection, session

    def invalidate_predictions(self):
        self.generation += 1

    def token(self, kind, value):
        if len(self.tokens) >= 1000:
            oldest = min(self.tokens, key=lambda key: self.tokens[key][3])
            self.tokens.pop(oldest)
        key = uuid.uuid4().hex
        digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        self.tokens[key] = (kind, digest, self._session, time.monotonic())
        return key

    def check_token(self, key, kind, value):
        token = self.tokens.get(key)
        digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        if not token or token[:3] != (kind, digest, self._session) or time.monotonic() - token[3] > 600:
            raise ApiError('conflict', 'Prediction/conversion token is stale.')

    def page(self, ids, method, params, session):
        params = dict(params)
        cursor = params.pop('cursor', None)
        limit = params.get('limit', 100)
        now = time.monotonic()
        self.cursors = {key: value for key, value in self.cursors.items() if now - value['created'] <= 600}
        if cursor:
            state = self.cursors.get(cursor)
            if not state or state['session'] != session:
                raise ApiError('staleCursor', 'Cursor expired or collection changed.')
            if state['method'] != method or state['params'] != params:
                raise ApiError('invalidParams', 'Cursor query parameters changed.')
            self.cursors.pop(cursor)
        else:
            if len(self.cursors) >= 100 or len(ids) > 1000000:
                raise ApiError('busy', 'Search snapshot capacity exceeded.')
            state = {'ids': ids, 'offset': 0, 'created': now, 'session': session, 'method': method, 'params': params}
        start = state['offset']
        selected = state['ids'][start:start + limit]
        next_offset = start + limit
        if next_offset < len(state['ids']):
            next_cursor = uuid.uuid4().hex
            self.cursors[next_cursor] = {**state, 'offset': next_offset}
        else:
            next_cursor = None
        if method == 'notes.search' or method == 'notes.findEmpty':
            selected = [id for id in selected if self._collection.db.scalar('select 1 from notes where id=?', id)]
        elif method == 'cards.search':
            selected = [id for id in selected if self._collection.db.scalar('select 1 from cards where id=?', id)]
        return {'ids': [str(id) for id in selected], 'nextCursor': next_cursor}

    def capability_reason(self, method, col=None):
        if method in ('api.describe', 'api.execute', 'operations.get', 'operations.cancel', 'access.requestPermission', 'media.store'):
            handler = True
        else:
            adapter = self.gui if method in GUI_METHODS else Services
            handler = callable(getattr(adapter, method.replace('.', '_'), None))
        if not handler:
            return 'No adapter for ' + method
        for name in FEATURE_REQUIREMENTS.get(method, ()):
            reason = compat.missing_feature(name)
            if reason:
                return reason
        if col is None:
            col = self.mw.col if self.mw else None
        if col:
            for path in NATIVE_REQUIREMENTS.get(method, ()):
                if not any(callable(compat.lookup(col, choice)) for choice in path.split('|')):
                    if path.startswith('sched.') and hasattr(col, 'v3_scheduler') and not col.v3_scheduler():
                        return 'Requires the v3 scheduler; enable it in Anki preferences.'
                    if path.startswith('sched.') and not hasattr(col, 'v3_scheduler'):
                        return 'Requires the v3 scheduler of Anki 2.1.45 or later.'
                    return REQUIREMENT_REASONS.get(path, 'Native capability missing: ' + path)
        return None

    def require_capability(self, method):
        reason = self.capability_reason(method)
        if reason:
            raise ApiError('unsupportedCapability', reason)

    def describe(self):
        import aqt
        methods = []
        for name in SCHEMA['x-methods']:
            reason = self.capability_reason(name)
            methods.append({'name': name, 'available': reason is None, 'reason': reason})
        return {'apiMajor': 1, 'ankiVersion': aqt.appVersion, 'schema': copy.deepcopy(SCHEMA),
                'methods': methods, 'limits': copy.deepcopy(SCHEMA['x-limits'])}

    def finish_changes(self, service, initiator=None):
        changes, service.changes = service.changes, []
        legacy = [change for change in changes if isinstance(change, compat.LegacyChanges)]
        # Untracked changes refresh every screen, so one notification covers them all.
        for change in [change for change in changes if not isinstance(change, compat.LegacyChanges)] + legacy[:1]:
            compat.on_op_finished(self.mw, change, initiator)
        if self.full_reset_required:
            self.full_reset_required = False
            self.mw.reset()

    def direct(self, method, params):
        meta = SCHEMA['x-methods'][method]
        if method in GUI_METHODS:
            if meta['scope'] == 'collection':
                self.capture(params.get('session'))
            return self.gui.execute(method, params)
        service = self.service()
        if self.lifecycle_active:
            raise ApiError('busy', 'Collection lifecycle operation is active.')
        if meta['effect'] in ('write', 'advancedWrite'):
            self.gui.guard(method, params)
        try:
            return service.execute(method, params)
        finally:
            self.finish_changes(service)

    def background(self, work, expected=None, after=None, initiator=None):
        col, session = self.capture(expected)
        service = Services(self, col, session)
        result = Deferred()
        # A GUI/background operation could otherwise unload the captured collection.
        compat.increase_background_ops(self.mw)
        reviewer = self.mw.reviewer
        self.active_reviewer_card = reviewer.card.id if reviewer and reviewer.card and self.mw.state == 'review' else None
        def task():
            from .media import MediaTransaction
            if self._collection is not col or self._session != session:
                raise ApiError('staleSession', 'Collection changed before execution.')
            # Restore interrupted journals before a session's first collection work.
            if self.media_recovered_session != session:
                self.media_recovered_session = session
                MediaTransaction.recover(service)
            return work(service)
        def finished(future):
            compat.decrease_background_ops(self.mw)
            try:
                value = future.result()
                if after:
                    value = after(value)
                self.finish_changes(service, initiator)
                result.resolve(value)
            except Exception as error:
                # Successful prefixes still need post-write notification on failure.
                try:
                    self.finish_changes(service, initiator)
                finally:
                    result.resolve(error=error)
        compat.run_in_background(self.mw, task, finished)
        return result

    def invoke(self, method, params):
        self.require_capability(method)
        if method == 'api.describe':
            return completed(self.describe())
        if method == 'operations.get':
            return completed(self.operations.get(params['operationId']))
        if method == 'operations.cancel':
            return completed(self.operations.cancel(params['operationId']))
        if method == 'api.execute':
            session = self.session
            for command in params['commands']:
                if command['method'] in ('api.execute', 'application.exit', 'profiles.switch'):
                    raise ApiError('invalidParams', 'This command is not allowed inside api.execute.')
                self.dispatcher.params(command['method'], command.get('params', {}))
            return completed(self.operations.submit(method, session, lambda key: self.execute_commands(params['commands'], session, key)))
        meta = SCHEMA['x-methods'][method]
        if self.lifecycle_active and meta['scope'] == 'collection':
            raise ApiError('busy', 'Collection lifecycle operation is active.')
        if meta['scope'] == 'collection':
            _, session = self.capture(params.get('session'))
        else:
            session = self.session
        if meta['effect'] in ('write', 'advancedWrite'):
            self.gui.guard(method, params)
        if method in GUI_METHODS and meta['scope'] == 'collection' and compat.background_op_count(self.mw):
            raise ApiError('busy', 'A collection operation is active.')
        def start(key=None):
            self.require_capability(method)
            if self.lifecycle_active and (meta['scope'] == 'collection' or meta['effect'] == 'lifecycle'):
                raise ApiError('busy', 'Collection lifecycle operation is active.')
            if meta['effect'] in ('write', 'advancedWrite'):
                self.gui.guard(method, params)
            if meta['scope'] == 'collection':
                self.capture(session)
                if method in GUI_METHODS and compat.background_op_count(self.mw):
                    raise ApiError('busy', 'A collection operation is active.')
            if method in GUI_METHODS:
                value = self.gui.execute(method, params, operation_id=key)
                return value if isinstance(value, Deferred) else completed(value)
            if method == 'media.store':
                return self.acquire_media(params, session)
            return self.background(lambda service: service.execute(method, params), session)
        if meta['completion'] == 'operation':
            return completed(self.operations.submit(method, session, start))
        return start()

    def await_value(self, future):
        def resolve(value):
            if isinstance(value, dict) and 'operationId' in value and value.get('method') in SCHEMA['x-methods']:
                return self.operations.completions[value['operationId']]
            return value
        return future.map(resolve)

    def execute_commands(self, commands, session, operation_id=None):
        result = Deferred()
        items = []
        cancelled = [False]
        if operation_id:
            self.operations.cancellations[operation_id] = lambda: cancelled.__setitem__(0, True)
            self.operations.records[operation_id]['cancellable'] = True
        def step(index):
            if cancelled[0]:
                result.resolve(error=ApiError('cancelled', 'Sequence cancelled between commands.', {'items': items}))
                return
            if index == len(commands):
                result.resolve({'items': items})
                return
            command = commands[index]
            name = command['method']
            try:
                params = dict(command.get('params', {}))
                if SCHEMA['x-methods'][name]['scope'] == 'collection':
                    params.setdefault('session', session)
                pending = self.await_value(self.dispatcher.invoke(name, params))
            except Exception as error:
                pending = completed(error=error)
            def finish(source):
                from .protocol import error_record
                items.append({'index': index, 'method': name, **({'error': error_record(source.error)} if source.error else {'result': source.value})})
                self.schedule(lambda: step(index + 1))
            pending.then(finish)
        step(0)
        return result

    def acquire_media(self, params, session):
        import base64
        from . import util
        from .protocol import completed
        result = Deferred()
        limit = SCHEMA['x-limits']['maxMediaBytes']
        source = params['source']
        def read():
            if 'data' in source:
                return base64.b64decode(source['data'], validate=True)
            if 'path' in source:
                with open(source['path'], 'rb') as file:
                    return file.read(limit + 1)
            # Anki's HTTP client applies the configured timeout. Limit acquisition,
            # including HTTP redirects, before any native media mutation.
            return util.download(source['url'], limit)
        def done(future):
            try:
                data = future.result()
                if len(data) > limit:
                    raise ApiError('invalidParams', 'Media exceeds the configured size limit.')
                self.capture(session)
                self.background(lambda service: service.store_bytes(params['filename'], data, params.get('collision', 'rename'), params.get('skipIfHash')), session).then(lambda source: result.resolve(source.value, source.error))
            except Exception as error:
                result.resolve(error=error if isinstance(error, ApiError) else ApiError('ioError', str(error)))
        compat.run_in_background(self.mw, read, done, uses_collection=False)
        return result

    def permission(self, context):
        # The facade owns the persisted user-facing permission flow, shared by both APIs.
        from . import util
        value = self.owner.permission(context.get('origin', ''), context.get('allowed', False))
        pending = value if isinstance(value, Deferred) else completed(value)
        return pending.map(lambda value: {'permission': value['permission'], 'requireApiKey': bool(util.setting('apiKey'))})

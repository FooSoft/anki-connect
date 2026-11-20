"""Legacy argument translation and result projection over shared domain services."""
import copy
import html
import os
import re
from datetime import datetime

from .protocol import ApiError, Deferred
from .services import RATINGS, KINDS, PRESET_ENUMS, MEDIA_ILLEGAL_CHARACTERS, LEGACY_SKIP_CLOZE, entity_id


def integer(value):
    """Accept decimal strings without rounding numbers or interpreting truthiness."""
    if isinstance(value, str) and re.fullmatch(r'[+-]?[0-9]{1,19}', value.strip()):
        return int(value)
    if type(value) is float and value.is_integer() and abs(value) <= 9007199254740991:
        return int(value)
    return value


def legacy_request(request):
    """Normalize only the legacy envelope, shared by HTTP and nested dispatch."""
    if not isinstance(request, dict):
        raise ApiError('invalidParams', 'Legacy requests must be objects.')
    request = dict(request)
    version = integer(request.get('version')) if request.get('version') is not None else 4
    if type(version) is not int:
        raise ApiError('invalidParams', 'version must be an integer.')
    request['version'] = version
    params = request.get('params')
    if params is None or params == []:
        params = {}
    if not isinstance(params, dict):
        raise ApiError('invalidParams', 'params must be an object.')
    request['params'] = dict(params)
    return request


class Accepted:
    def __init__(self, value, pending, project=lambda value: value):
        self.value, self.pending, self.project = value, pending, project


class Legacy:
    def __init__(self, owner, service=None):
        self.owner, self.runtime = owner, owner.runtime
        self.service = service
        self.media_transaction = None

    @staticmethod
    def boolean(value, default, label):
        if value is None:
            return default
        if isinstance(value, str):
            value = {'true': True, 'false': False, '1': True, '0': False}.get(value.strip().lower(), value)
        if type(value) is int and value in (0, 1):
            value = bool(value)
        if type(value) is not bool:
            raise ApiError('invalidParams', label + ' must be boolean')
        return value

    @staticmethod
    def array(value):
        return [] if value is None else value if isinstance(value, list) else [value]

    @staticmethod
    def identifier(value):
        value = integer(value)
        # Queries and direct native calls also consume legacy IDs, so validate
        # before constructing a search or allowing Qt guards to inspect them.
        if type(value) is not int:
            raise ApiError('invalidParams', 'Expected a positive signed 64-bit decimal ID.')
        entity_id(str(value))
        return value

    @classmethod
    def normalize_params(cls, name, params):
        """Keep coercion at the compatibility boundary, before guards and services."""
        p = dict(params)
        note_lists = name in ('addNotes', 'canAddNotes', 'canAddNotesWithErrorDetail')
        for key in ('cards', 'notes', 'decks', 'modelIds', 'modelNames', 'easeFactors',
                    'keys', 'newValues', 'answers', 'inOrderFields', 'cardTemplates'):
            if key in p and not (name == 'notesInfo' and key == 'notes' and p[key] is None):
                p[key] = cls.array(p[key])
        for key in ('cards', 'modelIds', 'notes'):
            if key in p and p[key] is not None and not (key == 'notes' and note_lists):
                p[key] = [cls.identifier(value) for value in p[key]]
        for key in ('card', 'note', 'deckId', 'modelId', 'configId', 'cloneFrom', 'ease', 'index', 'fontSize', 'startID'):
            if key in p:
                p[key] = integer(p[key])
        if 'easeFactors' in p:
            p['easeFactors'] = [integer(value) for value in p['easeFactors']]
        if name == 'setDueDate' and type(p.get('days')) is int:
            p['days'] = str(p['days'])
        defaults = {'cardsToo': False, 'deleteExisting': True, 'add': True, 'warning_check': False,
                    'suspend': True, 'complete': False, 'isCloze': False, 'front': True, 'back': True,
                    'append': False, 'includeSched': False, 'wholeCollection': True}
        if name == 'findAndReplaceInModels':
            defaults['css'] = True
        for key, default in defaults.items():
            if key in p:
                p[key] = cls.boolean(p[key], default, key)
        if name == 'cardsInfo' and p.get('fields') is not None:
            p['fields'] = cls.array(p['fields'])
        if name == 'apiReflect':
            if p.get('scopes') is None:
                p['scopes'] = []
            for key in ('scopes', 'actions'):
                if isinstance(p.get(key), str):
                    p[key] = cls.array(p[key])
        if isinstance(p.get('note'), dict):
            p['note'] = cls.normalize_note(p['note'])
        if note_lists and 'notes' in p:
            p['notes'] = [cls.normalize_note(note) if isinstance(note, dict) else note for note in p['notes']]
        if name == 'answerCards':
            p['answers'] = [{**answer, **{key: integer(answer[key]) for key in ('cardId', 'ease') if key in answer}}
                            if isinstance(answer, dict) else answer for answer in p['answers']]
        return p

    @classmethod
    def normalize_note(cls, note):
        note = dict(note)
        if 'id' in note:
            note['id'] = integer(note['id'])
        # Null optional settings mean the same thing as omitted settings.
        if note.get('options') is None:
            note['options'] = {}
        options = note['options']
        if isinstance(options, dict):
            options = note['options'] = dict(options)
            scoped = options.get('duplicateScopeOptions')
            if scoped is None:
                scoped = {}
            if isinstance(scoped, dict):
                scoped = dict(scoped)
            options['duplicateScopeOptions'] = scoped
        for kind in ('audio', 'video', 'picture'):
            if note.get(kind):
                entries = []
                for entry in cls.array(note[kind]):
                    if isinstance(entry, dict):
                        entry = dict(entry)
                        # Historical attachments passed a missing flag through as falsy and renamed on collision.
                        entry['deleteExisting'] = cls.boolean(entry.get('deleteExisting'), False, 'deleteExisting')
                    entries.append(entry)
                note[kind] = entries
        return note

    @staticmethod
    def field_name(name, names):
        if name in names:
            return name
        matches = [value for value in names if isinstance(name, str) and value.lower() == name.strip().lower()]
        if len(matches) > 1:
            raise ApiError('compatibilityError', 'Ambiguous field name.')
        return matches[0] if matches else None

    @classmethod
    def fields(cls, values, names):
        if values is None:
            values = {}
        if not isinstance(values, dict):
            raise ApiError('invalidParams', 'Fields must be provided as a dictionary')
        result = {}
        for key, value in values.items():
            actual = cls.field_name(key, names)
            if actual is not None:
                value = '' if value is None else value
                if actual in values and key != actual:
                    continue
                if actual in result and result[actual] != value:
                    raise ApiError('compatibilityError', 'Ambiguous field name.')
                result[actual] = value
        return result

    @classmethod
    def media_targets(cls, entry, fields):
        return list(dict.fromkeys(actual for field in cls.array(entry.get('fields'))
                                  if (actual := cls.field_name(field, fields)) is not None))

    def s(self, method, **params):
        if self.service is None:
            self.service = self.runtime.service()
        notes = [params['note']] if isinstance(params.get('note'), dict) else params.get('notes', [])
        flags = [isinstance(note, dict) and note.get(LEGACY_SKIP_CLOZE) for note in notes]
        if any(flags):
            params = dict(params)
            stripped = [{key: value for key, value in note.items() if key != LEGACY_SKIP_CLOZE} for note in notes]
            params.update({'note': stripped[0]} if 'note' in params else {'notes': stripped})
        try:
            validated = self.runtime.dispatcher.params(method, params)
            # Reattach legacy-only options after public schema validation.
            for note, flag in zip([validated['note']] if 'note' in validated and any(flags) else validated.get('notes', []), flags):
                if flag:
                    note[LEGACY_SKIP_CLOZE] = True
            return self.service.execute(method, validated)
        except ApiError as error:
            if error.kind == 'notFound':
                # Resolve only on failure, so a missing entity keeps its legacy
                # wording without disguising unrelated service failures.
                source = params.get('note', params)
                for key, kind in (('noteType', 'noteType'), ('deck', 'deck')):
                    if key in source:
                        self.resolve(source[key], kind)
                if method in ('notes.get', 'notes.update'):
                    raise ApiError(error.kind, 'Note was not found: ' + params['id'], error.details) from error
                if method == 'cards.get':
                    raise ApiError(error.kind, 'Card was not found: ' + params['id'], error.details) from error
            if error.kind == 'validationFailed' and error.details:
                message = self.validation_error(error.details)
                if message:
                    raise ApiError(error.kind, message, error.details) from error
            if method == 'noteTypes.create' and error.kind == 'conflict':
                raise ApiError(error.kind, 'Model name already exists', error.details) from error
            raise

    def resolve(self, reference, kind):
        try:
            return self.service.resolve(reference, kind)
        except ApiError as error:
            if error.kind == 'notFound':
                label = 'model' if kind == 'noteType' else 'deck'
                value = reference.get('name', reference.get('id'))
                raise ApiError(error.kind, label + ' was not found: ' + str(value), error.details) from error
            raise

    @staticmethod
    def validation_error(validation):
        messages = {
            'emptyFirstField': 'cannot create note because it is empty',
            'duplicate': 'cannot create note because it is a duplicate',
            'emptyQuestions': 'The field values you have provided would make an empty question on all cards.',
            'missingCloze': 'cannot create note for unknown reason',
            'notClozeNoteType': 'cannot create note for unknown reason',
            'notClozeField': 'cannot create note for unknown reason',
        }
        # Legacy note creation reported the first failure. In particular, an
        # empty first field must not be mistaken for a duplicate by clients.
        issues = validation.get('issues', [])
        if issues:
            return messages.get(issues[0]['type'], issues[0]['message'])
        for item in validation.get('items', []):
            details = item.get('error', {}).get('data', {}).get('details', item)
            message = Legacy.validation_error(details)
            if message:
                return message
        return None

    def ids(self, values):
        return [str(value) for value in values]

    def ref(self, name):
        return {'name': name}

    def unwrap(self, value, missing=False):
        values = []
        for item in value['items']:
            if 'error' in item:
                if missing and item['error'].get('data', {}).get('type') == 'notFound':
                    values.append(None)
                else:
                    error = item['error']
                    raise ApiError(error.get('data', {}).get('type', 'internalError'), error['message'],
                                   error.get('data', {}).get('details'))
            else:
                values.append(item['result'])
        return values

    def all_pages(self, method, **params):
        result, cursor = [], None
        while True:
            page = self.s(method, **params, **({'cursor': cursor} if cursor else {}))
            result.extend(page.get('ids', page.get('items', [])))
            cursor = page['nextCursor']
            if not cursor:
                return result

    def native_search(self, kind, query):
        # Unlike paginated v1 searches, legacy results keep Anki's native order.
        if self.service is None:
            self.service = self.runtime.service()
        col = self.service.col
        try:
            return [int(id) for id in (col.find_notes if kind == 'notes' else col.find_cards)(query)]
        except Exception as error:
            raise ApiError('invalidSearch', str(error)) from error

    def model(self, name=None, id=None):
        # Compatibility projections are snapshots, never a writable alternate service.
        if self.service is None:
            self.service = self.runtime.service()
        return self.resolve({'id': str(id)} if id is not None else self.ref(name), 'noteType')

    @staticmethod
    def normalize_tags(tags):
        if tags is None:
            return []
        entries = [tags] if isinstance(tags, str) else tags
        if not isinstance(entries, list) or any(tag is not None and not isinstance(tag, str) for tag in entries):
            raise ApiError('invalidParams', 'Must provide tags as a list of strings')
        # Use Anki's whitespace-separated tag convention for both input forms.
        return list(dict.fromkeys(tag for entry in entries if entry is not None for tag in entry.split()))

    def created_note(self, source, pure=False):
        source = self.normalize_note(source)
        model = self.model(source['modelName'])
        self.resolve(self.ref(source['deckName']), 'deck')
        # Native notes have every model field, including omitted media targets.
        fields = {field['name']: '' for field in model['flds']}
        fields.update(self.fields(source.get('fields'), fields))
        options = source.get('options', {})
        scoped = options.get('duplicateScopeOptions', {})
        for key, values, label in (('allowDuplicate', options, 'allowDuplicate'),
                                   ('checkChildren', scoped, 'duplicateScopeOptions.checkChildren'),
                                   ('checkAllModels', scoped, 'duplicateScopeOptions.checkAllModels')):
            if key in values:
                values[key] = self.boolean(values[key], False, 'option parameter "' + label + '"')
        scope = 'deck' if options.get('duplicateScope') == 'deck' else 'collection'
        duplicates = {'allow': options.get('allowDuplicate', False), 'scope': scope,
                      'includeChildren': scoped.get('checkChildren', False),
                      'acrossNoteTypes': scoped.get('checkAllModels', False)}
        # The historical deck/all-model duplicate path checked only the first
        # field, while the default path used Anki's full field check.
        skip_cloze = scope == 'deck' or duplicates['acrossNoteTypes']
        if scope == 'deck':
            deck_name = scoped.get('deckName')
            duplicates['deck'] = self.ref(source['deckName'] if deck_name is None else deck_name)
            if deck_name is not None:
                try:
                    self.service.resolve(duplicates['deck'], 'deck')
                except ApiError as error:
                    if error.kind != 'notFound':
                        raise
                    # Historically, a missing scope deck cannot contain duplicates.
                    duplicates = {'allow': True}
        data = {'noteType': self.ref(source['modelName']), 'deck': self.ref(source['deckName']),
                'fields': fields, 'tags': self.normalize_tags(source.get('tags')), 'duplicates': duplicates,
                # Legacy creation lets Anki generate its fallback card. Rendering
                # a blank template is not the same as a native add returning 0.
                'rejectEmptyQuestions': False}
        if skip_cloze:
            data[LEGACY_SKIP_CLOZE] = True
        if pure:
            self.attachments(data['fields'], source, pure=True)
        return data

    def acquire(self, params):
        import base64
        from . import util
        sources = [key for key in ('data', 'path', 'url') if params.get(key)]
        if not sources:
            raise ApiError('invalidParams', 'You must provide a "data", "path", or "url" field.')
        key = sources[0]
        if key == 'data':
            data = base64.b64decode(params[key])
        elif key == 'path':
            with open(params[key], 'rb') as file:
                data = file.read(67108865)
        else:
            data = util.download(params[key], 67108864)
        if len(data) > 67108864:
            raise ApiError('invalidParams', 'Media exceeds the size limit.')
        return data

    def install(self, entry, data, transaction=None):
        from .media import MediaTransaction
        if transaction is None:
            if self.service is None:
                self.service = self.runtime.service()
            if self.media_transaction is None:
                self.media_transaction = MediaTransaction(self.service)
            transaction = self.media_transaction
        skip = {'algorithm': 'md5', 'digest': entry['skipHash']} if entry.get('skipHash') else None
        return transaction.install(self.media_name(entry['filename']), data, skip,
                                   'replace' if entry.get('deleteExisting', True) else 'rename')

    def media_name(self, filename):
        # Anki's old writeData wrapper took the host-platform basename, then
        # the native writer stripped illegal characters. GSM passes full paths.
        # Sanitize before journaling; every destination is still a basename.
        return self.service.media_filename(MEDIA_ILLEGAL_CHARACTERS.sub('', os.path.basename(filename)))

    def stage_media(self, source, pure=False):
        """Acquire every attachment before any install; failures become field text."""
        staged = []
        for kind in ('audio', 'video', 'picture'):
            for entry in self.array(source.get(kind)):
                if not entry:
                    continue
                try:
                    staged.append((kind, entry, None if pure else self.acquire(entry), None))
                except Exception as error:
                    if isinstance(error, ApiError) and str(error) == 'Media exceeds the size limit.':
                        raise
                    staged.append((kind, entry, None, error))
        return staged

    def apply_media(self, fields, staged, filename):
        # Historical attachments append references and errors in entry order.
        for kind, entry, data, error in staged:
            if error is None:
                name = filename(entry, data)
                if name is None:
                    continue
                escaped = html.escape(name, quote=True)
                content = '<img src="' + escaped + '">' if kind == 'picture' else '[sound:' + escaped + ']'
            else:
                content = html.escape(str(error), quote=False)
            for field in self.media_targets(entry, fields):
                fields[field] += content

    def attachments(self, fields, source, pure=False):
        self.apply_media(fields, self.stage_media(source, pure),
                         lambda entry, data: entry['filename'] if pure else self.install(entry, data))

    def store_media(self, params):
        return self.install(params, self.acquire(params))

    def prepare_gui_media(self, fields, source):
        session = self.runtime.session
        def prepare(service):
            self.service = service
            self.attachments(fields, source)
        return self.runtime.background(prepare, expected=session)

    def validate(self, source):
        try:
            result = self.s('notes.validate', note=self.created_note(source, pure=True))
            if not result['valid']:
                return {'canAdd': False, 'error': self.validation_error(result)}
            return {'canAdd': True}
        except Exception as error:
            return {'canAdd': False, 'error': str(error)}

    def add_notes(self, sources, atomic):
        prepared = [self.created_note(source, pure=True) for source in sources]
        validation = self.unwrap(self.s('notes.validateMany', notes=prepared))
        if any(not value['valid'] for value in validation):
            raise ApiError('validationFailed', self.validation_error({'items': validation}), {'items': validation})
        # Acquire every attachment before installing any file. Back up only
        # destinations this request owns; never scan or restore unrelated media.
        staged = [self.stage_media(source) for source in sources]
        from .media import MediaTransaction
        transaction = MediaTransaction(self.service)
        try:
            filenames = {id(entry): self.install(entry, data, transaction)
                         for items in staged for _, entry, data, error in items if error is None}
            for source, data, items in zip(sources, prepared, staged):
                data['fields'] = self.created_note(source)['fields']
                self.apply_media(data['fields'], items, lambda entry, _: filenames[id(entry)])
            values = self.unwrap(self.s('notes.createMany', notes=prepared, atomic=atomic))
            transaction.commit()
            return [int(value['noteId']) for value in values]
        except Exception as error:
            if transaction.committed:
                raise
            failures = transaction.rollback()
            if failures:
                raise ApiError('ioError', 'Media restoration failed.', {'failures': failures, 'cause': str(error)}) from error
            raise

    def record(self, kind, id, fields=None):
        if kind == 'cards':
            return self.card_info(id, fields)
        value = self.s(kind + '.get', id=str(id))
        model = self.model(id=value['noteType']['id'])
        return {'noteId': int(id), 'profile': self.runtime.profile_name, 'tags': value['tags'],
                'fields': {field['name']: {'value': value['fields'][field['name']], 'order': index} for index, field in enumerate(model['flds'])},
                'modelName': model['name'], 'mod': int(datetime.fromisoformat(value['modifiedAt'].replace('Z', '+00:00')).timestamp()),
                'cards': [int(id) for id in value['cardIds']]}

    def card_info(self, id, fields=None):
        if self.service is None:
            self.service = self.runtime.service()
        card = self.service.card(str(id))
        result = {'cardId': card.id, 'fieldOrder': card.ord, 'ord': card.ord,
                'factor': card.factor, 'interval': card.ivl, 'note': card.nid, 'type': card.type, 'queue': card.queue,
                'due': card.due, 'reps': card.reps, 'lapses': card.lapses, 'left': card.left, 'mod': card.mod,
                'flags': card.flags}
        requested = None if fields is None else set(fields)
        if requested is None or requested & {'fields', 'modelName', 'css'}:
            note = card.note()
            model = self.model(id=note.mid)
            if requested is None or 'fields' in requested:
                result['fields'] = {field['name']: {'value': note.fields[index], 'order': index} for index, field in enumerate(model['flds'])}
            if requested is None or 'modelName' in requested:
                result['modelName'] = model['name']
            if requested is None or 'css' in requested:
                result['css'] = model['css']
        if requested is None or 'deckName' in requested:
            result['deckName'] = self.resolve({'id': str(card.did)}, 'deck')['name']
        if requested is None or requested & {'question', 'answer'}:
            rendered = self.s('cards.render', id=str(id))
            result.update(question=rendered['questionHtml'], answer=rendered['answerHtml'])
        if requested is None or 'nextReviews' in requested:
            prediction = self.s('scheduling.predict', cardId=str(id))
            result['nextReviews'] = [item['label'] for item in prediction['answers']]
        return result if requested is None else {key: value for key, value in result.items() if key in requested}

    def gui_call(self, name, p, draft_fields=None):
        runtime = self.runtime
        gui = runtime.gui
        def call(method, **params):
            value = gui.execute(method, params)
            return value
        def accepted(method, value, final=lambda value: value, **params):
            pending = runtime.await_value(runtime.invoke(method, runtime.dispatcher.params(method, params)))
            return Accepted(value, pending, final)
        if name == 'getProfiles':
            return [value['name'] for value in gui.profiles_list()]
        if name == 'getActiveProfile':
            value = gui.profiles_getActive()
            return value['name'] if value else None
        if name == 'loadProfile':
            if p['name'] not in self.owner.window().pm.profiles():
                return False
            return accepted('profiles.switch', True, lambda value: True, name=p['name'])
        if name == 'sync':
            if not self.owner.window().pm.sync_auth():
                raise ApiError('authenticationRequired', 'sync: auth not configured')
            return accepted('collection.sync', None, lambda value: None)
        if name == 'reloadCollection':
            call('collection.refresh', target='cachesAndWindows')
            return None
        if name == 'guiBrowse':
            sort = p['reorderCards']
            if sort is not None:
                if not isinstance(sort, dict):
                    raise ApiError('invalidParams', 'reorderCards should be a dict: ' + str(sort))
                if 'columnId' not in sort or 'order' not in sort:
                    raise ApiError('invalidParams', 'Must provide a "columnId" and a "order" property"')
                if sort['order'] not in ('ascending', 'descending'):
                    raise ApiError('invalidParams', 'invalid card order: ' + str(sort['order']))
                if self.service is None:
                    self.service = runtime.service()
                if self.service.col.get_browser_column(sort['columnId']) is None:
                    raise ApiError('invalidParams', 'invalid columnId: ' + str(sort['columnId']))
                sort = {'column': sort['columnId'], 'direction': sort['order']}
            value = call('browser.open', query=p['query'], sort=sort)
            if isinstance(value, Deferred):
                pending = Deferred()
                def translate(source):
                    error = source.error
                    if isinstance(error, ApiError) and str(error) == 'Browser sort column is not active.':
                        error = ApiError('invalidParams', 'invalid columnId: ' + str(p['reorderCards']['columnId']))
                    pending.resolve(source.value, error)
                value.then(translate)
                value = pending
            def project(_):
                return [] if p['query'] is None else self.native_search('cards', p['query'])
            return value.map(project) if isinstance(value, Deferred) else project(value)
        if name in ('guiSelectNote', 'guiSelectCard'):
            if not gui.browser():
                return False
            try:
                call('browser.select', cardIds=[str(p.get('card', p.get('note')))])
            except Exception as error:
                from anki.errors import NotFoundError
                if not isinstance(error, NotFoundError) and getattr(error, 'kind', None) != 'notFound':
                    raise
                # Historically a missing card only cleared the selection.
                call('browser.select', cardIds=[])
            return True
        if name == 'guiSelectedNotes':
            return [int(id) for id in call('browser.getSelection')['selectedNoteIds']]
        if name == 'guiEditNote':
            return accepted('editors.openNote', None, lambda value: None, noteId=str(p['note']))
        if name == 'guiAddCards':
            if p['note']:
                self.s('decks.get', deck=self.ref(p['note']['deckName']))
            note = self.created_note(p['note']) if p['note'] else None
            session = runtime.session
            def open_add(_=None):
                runtime.capture(session)
                if note:
                    note.pop('duplicates', None)
                    note.pop('rejectEmptyQuestions', None)
                    note.pop(LEGACY_SKIP_CLOZE, None)
                return accepted('editors.openAdd', 0, lambda value: int(value['noteId'] or 0), **({'note': note} if note else {}))
            if note and any(p['note'].get(kind) for kind in ('audio', 'video', 'picture')):
                return self.prepare_gui_media(note['fields'], p['note']).map(open_add)
            return open_add()
        if name == 'guiAddNoteSetData':
            dialog = gui.add_dialog()
            if dialog is None:
                return {'error': 'Add Note dialog is not open', 'code': 1}
            source = copy.deepcopy(p['note'])
            if self.service is None:
                self.service = runtime.service()
            for key, kind, label in [('deckName', 'deck', 'Deck'), ('modelName', 'noteType', 'Model')]:
                if key in source:
                    try:
                        self.resolve(self.ref(source[key]), kind)
                    except ApiError as error:
                        if error.kind == 'notFound':
                            raise ApiError(error.kind, '{} "{}" not found'.format(label, source[key])) from error
                        raise
            if 'fields' in source:
                names = draft_fields
                if names is None:
                    if 'modelName' in source or hasattr(dialog.editor, 'note'):
                        model = self.model(source['modelName']) if 'modelName' in source else dialog.editor.note.note_type()
                        names = [value['name'] for value in model['flds']]
                    else:
                        # Svelte keeps the selected note type in the webview.
                        # Read its draft asynchronously before matching field keys.
                        return gui.editor_record(dialog, 'add').map(
                            lambda record: self.gui_call(name, p, list(record['fields'])))
                for field in source['fields'] or {}:
                    if self.field_name(field, names) is None:
                        raise ApiError('notFound', 'Field "' + field + '" not found in current note')
                source['fields'] = self.fields(source['fields'], names)
            patch = {key: value for key, value in source.items() if key in ('fields', 'tags')}
            if 'tags' in patch:
                patch['tags'] = self.normalize_tags(patch['tags'])
            for old, new in [('deckName', 'deck'), ('modelName', 'noteType')]:
                if old in source:
                    patch[new] = self.ref(source[old])
            editor_id = gui.register(dialog, 'add')
            session = runtime.session
            def update(_=None):
                runtime.capture(session)
                return call('editors.updateDraft', editorId=editor_id, patch=patch,
                            mode='append' if p['append'] else 'replace')
            value = (self.prepare_gui_media(patch['fields'], source).map(update)
                     if 'fields' in patch and any(source.get(kind) for kind in ('audio', 'video', 'picture'))
                     else update())
            if isinstance(value, Deferred):
                pending = Deferred()
                def finished(source):
                    error = source.error
                    if isinstance(error, ApiError) and str(error).startswith('Unknown field: '):
                        error = ApiError(error.kind, 'Field "' + str(error).removeprefix('Unknown field: ') + '" not found in current note')
                    pending.resolve(True if error is None else None, error)
                value.then(finished)
                return pending
            return True
        if name in ('guiReviewActive', 'guiCurrentCard', 'guiStartCardTimer', 'guiShowQuestion',
                    'guiShowAnswer', 'guiPlayAudio', 'guiAnswerCard') and self.owner.reviewer() is None:
            raise ApiError('invalidState', 'reviewer is not available')
        if name == 'guiReviewActive':
            return call('reviewer.get')['active']
        if name == 'guiCurrentCard':
            value = call('reviewer.get')
            if not value['active']:
                raise ApiError('invalidState', 'Gui review is not currently active.')
            record = self.record('cards', value['card']['id'])
            keep = ('cardId', 'fields', 'fieldOrder', 'question', 'answer', 'modelName', 'deckName', 'css')
            return {**{key: record[key] for key in keep}, 'buttons': [RATINGS.index(item['rating']) + 1 for item in value['answers']],
                    'nextReviews': [item['label'] for item in value['answers']], 'template': gui.reviewer().card.template()['name']}
        if name in ('guiStartCardTimer', 'guiShowQuestion', 'guiShowAnswer', 'guiPlayAudio', 'guiAnswerCard'):
            value = call('reviewer.get')
            if not value['active']:
                return False
            method = {'guiStartCardTimer': 'reviewer.startTimer', 'guiShowQuestion': 'reviewer.showQuestion',
                      'guiShowAnswer': 'reviewer.showAnswer', 'guiPlayAudio': 'reviewer.playAudio', 'guiAnswerCard': 'reviewer.answer'}[name]
            if name == 'guiAnswerCard':
                ease = p['ease']
                if value['side'] != 'answer' or type(ease) is not int or ease not in [RATINGS.index(item['rating']) + 1 for item in value['answers']]:
                    return False
                return accepted(method, True, lambda value: True, stateToken=value['stateToken'], rating=RATINGS[ease - 1])
            call(method, stateToken=value['stateToken'])
            return True
        if name in ('guiUndo', 'guiCheckDatabase'):
            return accepted('collection.undo' if name == 'guiUndo' else 'collection.checkIntegrity', True, lambda value: True)
        if name == 'guiImportFile':
            return accepted('application.importFile', None, lambda value: None, **({'path': p['path']} if p['path'] else {}))
        if name == 'guiExitAnki':
            call('application.exit')
            return None
        if name in ('guiDeckOverview', 'guiDeckReview', 'guiDeckBrowser'):
            if name != 'guiDeckBrowser':
                try:
                    self.s('decks.get', deck=self.ref(p['name']))
                except ApiError:
                    return False
            call('application.navigate', view={'guiDeckOverview': 'deckOverview', 'guiDeckReview': 'review', 'guiDeckBrowser': 'deckBrowser'}[name],
                 **({'deck': self.ref(p['name'])} if name != 'guiDeckBrowser' else {}))
            return None if name == 'guiDeckBrowser' else True
        raise ApiError('methodNotFound', 'Unknown GUI action.')

    def call(self, name, p):
        """Run one action with parameters already bound by AnkiConnect.resolve_action."""
        def success(value):
            if self.media_transaction:
                self.media_transaction.commit()
                self.media_transaction = None
            return value
        def failure(error):
            if self.media_transaction and not self.media_transaction.committed:
                failures = self.media_transaction.rollback()
                self.media_transaction = None
                if failures:
                    raise ApiError('ioError', 'Media restoration failed.', {'failures': failures}) from error
            raise error
        def cleanup(value=None, error=None):
            if self.media_transaction and name.startswith('gui'):
                try:
                    return self.runtime.background(lambda service: failure(error) if error else success(value),
                                                   expected=self.service.session)
                except Exception:
                    # A profile switch can close the pinned collection before
                    # cleanup admission. Retain its journal for recovery there.
                    self.media_transaction._active.discard(self.media_transaction.path)
                    self.media_transaction = None
                    raise
            return failure(error) if error else success(value)
        def wrapped(value):
            if isinstance(value, Accepted):
                return Accepted(value.value, wrapped(value.pending), value.project)
            if isinstance(value, Deferred):
                pending = Deferred()
                def finish(source):
                    try:
                        output = cleanup(error=source.error) if source.error else wrapped(source.value)
                        if isinstance(output, Deferred):
                            output.then(lambda final: pending.resolve(final.value, final.error))
                        else:
                            pending.resolve(output)
                    except Exception as error:
                        pending.resolve(error=error)
                value.then(finish)
                return pending
            return cleanup(value)
        try:
            return wrapped(self.dispatch(name, p))
        except Exception as error:
            return cleanup(error=error)

    def dispatch(self, name, p):
        from . import util
        if name == 'version':
            return util.setting('apiVersion')
        if name == 'requestPermission':
            return self.owner.permission(p['origin'], p['allowed'])
        if name == 'apiReflect':
            if not isinstance(p['scopes'], list):
                raise ApiError('invalidParams', 'scopes has invalid value')
            if not (p['actions'] is None or isinstance(p['actions'], list)):
                raise ApiError('invalidParams', 'actions has invalid value')
            if 'actions' not in p['scopes']:
                return {'scopes': []}
            names = p['actions'] if p['actions'] is not None else self.owner.legacy_actions()
            return {'scopes': ['actions'], 'actions': [name for name in names if name in self.owner.legacy_actions()]}
        if name.startswith('gui') or name in ('getProfiles', 'getActiveProfile', 'loadProfile', 'sync', 'reloadCollection'):
            return self.gui_call(name, p)
        if name in ('deckNames', 'deckNamesAndIds', 'modelNames', 'modelNamesAndIds'):
            values = self.s('decks.list' if name.startswith('deck') else 'noteTypes.list')
            return {value['name']: int(value['id']) for value in values} if name.endswith('AndIds') else [value['name'] for value in values]
        if name in ('deckNameFromId', 'modelNameFromId'):
            return self.s('decks.get' if name == 'deckNameFromId' else 'noteTypes.get',
                          **({'deck': {'id': str(p['deckId'])}} if name == 'deckNameFromId' else {'noteType': {'id': str(p['modelId'])}}))['name']
        if name == 'createDeck':
            return int(self.s('decks.create', name=p['deck'])['id'])
        if name == 'getDecks':
            result = {}
            for id in p['cards']:
                card = self.s('cards.get', id=str(id))
                result.setdefault(card['deck']['name'], []).append(id)
            return result
        if name == 'changeDeck':
            target = self.s('decks.create', name=p['deck'])
            # Historical bulk writes ignored card IDs that do not exist.
            self.unwrap(self.s('cards.move', ids=self.ids(p['cards']), deck={'id': target['id']}), missing=True)
            return None
        if name == 'deleteDecks':
            if not p['cardsToo']:
                raise ApiError('invalidParams', "Since Anki 2.1.28 it's not possible to delete decks without deleting cards as well")
            existing = {value['name'] for value in self.s('decks.list')}
            self.unwrap(self.s('decks.delete', decks=[self.ref(name) for name in p['decks'] if name in existing], deleteCards=True))
            return None
        if name == 'getDeckStats':
            # Native due-tree nodes: leaf names and each deck's own card total.
            wanted = {int(self.s('decks.create', name=deck)['id']) for deck in p['decks']}
            result = {}
            def collect(node):
                if node.deck_id in wanted:
                    result[str(node.deck_id)] = {'deck_id': node.deck_id, 'name': node.name, 'new_count': node.new_count,
                                                 'learn_count': node.learn_count, 'review_count': node.review_count,
                                                 'total_in_deck': node.total_in_deck}
                for child in node.children:
                    collect(child)
            collect(self.service.col.sched.deck_due_tree())
            return result
        if name == 'getDeckConfig':
            try:
                deck = self.s('decks.get', deck=self.ref(p['deck']))
                return copy.deepcopy(self.service.col.decks.get_config(int(deck['presetId'])))
            except ApiError as error:
                if error.kind == 'notFound':
                    return False
                raise
        if name in ('saveDeckConfig', 'setDeckConfigId', 'cloneDeckConfigId', 'removeDeckConfigId'):
            try:
                if name == 'setDeckConfigId':
                    refs = [self.ref(deck) for deck in p['decks']]
                    for ref in refs:
                        self.s('decks.get', deck=ref)
                    self.unwrap(self.s('deckPresets.assign', decks=refs, preset={'id': str(p['configId'])}))
                    return True
                if name == 'cloneDeckConfigId':
                    return int(self.s('deckPresets.create', name=p['name'], cloneFrom={'id': str(p['cloneFrom'])})['id'])
                if name == 'removeDeckConfigId':
                    self.s('deckPresets.delete', preset={'id': str(p['configId'])}, replacement={'id': '1'})
                    return True
                settings = self.preset_patch(p['config'])
                self.s('deckPresets.update', preset={'id': str(p['config']['id'])}, name=p['config']['name'], settings=settings)
                return True
            except Exception:
                return False
        if name == 'storeMediaFile':
            return self.store_media(p)
        if name == 'retrieveMediaFile':
            try:
                return self.s('media.get', filename=os.path.basename(p['filename']))['data']
            except ApiError as error:
                if error.kind == 'notFound':
                    return False
                raise
        if name == 'getMediaFilesNames':
            return self.s('media.list', pattern=p['pattern'])
        if name == 'deleteMediaFile':
            try:
                self.s('media.delete', filename=p['filename'])
            except ApiError as error:
                if error.kind != 'notFound':
                    raise
            return None
        if name == 'getMediaDirPath':
            return self.s('media.getDirectory')['path']
        if name in ('canAddNote', 'canAddNoteWithErrorDetail', 'canAddNotes', 'canAddNotesWithErrorDetail'):
            sources = p.get('notes', [p.get('note')])
            result = [self.validate(source) for source in sources]
            if not name.endswith('WithErrorDetail'):
                result = [item['canAdd'] for item in result]
            return result if name.startswith('canAddNotes') else result[0]
        if name in ('addNote', 'addNotes'):
            if name == 'addNotes':
                prepared, indices, errors = [], [], {}
                for index, source in enumerate(p['notes']):
                    try:
                        prepared.append(self.created_note(source, pure=True))
                        indices.append(index)
                    except Exception as error:
                        errors[index] = str(error)
                _, failures = self.service.prepare_notes(prepared)
                for failure in failures:
                    errors[indices[failure['index']]] = self.validation_error({'items': [failure]}) or failure['error']['message']
                if errors:
                    raise ApiError('validationFailed', str([errors[index] for index in sorted(errors)]), {'items': failures})
            try:
                values = self.add_notes(p.get('notes', [p.get('note')]), True)
            except Exception as error:
                if name == 'addNotes':
                    items = error.details.get('items', []) if isinstance(error, ApiError) and error.details else []
                    errors = [self.validation_error({'items': [item]}) or item.get('error', {}).get('message', str(error))
                              for item in items]
                    raise ApiError(getattr(error, 'kind', 'internalError'), str(errors or [str(error)]),
                                   getattr(error, 'details', None)) from error
                raise
            return values if name == 'addNotes' else values[0]
        if name in ('updateNote', 'updateNoteFields', 'updateNoteTags'):
            source = p['note']
            source = {'id': source, 'tags': p['tags']} if name == 'updateNoteTags' else copy.deepcopy(source)
            patch = {}
            if 'fields' in source or any(source.get(kind) for kind in ('audio', 'video', 'picture')):
                current = self.s('notes.get', id=str(source['id']))
                patch['fields'] = self.fields(source.get('fields'), current['fields'])
                # Attachments may target a field omitted from the text patch.
                for kind in ('audio', 'video', 'picture'):
                    for entry in self.array(source.get(kind)):
                        if entry:
                            for field in self.media_targets(entry, current['fields']):
                                patch['fields'].setdefault(field, current['fields'][field])
            if name != 'updateNoteFields' and 'tags' in source:
                patch['tags'] = self.normalize_tags(source['tags'])
            if not patch:
                raise ApiError('invalidParams', 'Must provide a "fields" or "tags" property.')
            self.runtime.dispatcher.params('notes.update', {'id': str(source['id']), 'patch': patch})
            if 'fields' in patch:
                self.attachments(patch['fields'], source)
            self.s('notes.update', id=str(source['id']), patch=patch)
            return None
        if name == 'updateNoteModel':
            source = p['note']
            if not source.get('id'):
                raise ApiError('invalidParams', 'Note ID is required')
            if not source.get('modelName'):
                raise ApiError('invalidParams', 'Model name is required')
            if not source.get('fields') or not isinstance(source['fields'], dict):
                raise ApiError('invalidParams', 'Fields must be provided as a dictionary')
            original = self.s('notes.get', id=str(source['id']))
            try:
                target = self.s('noteTypes.get', noteType=self.ref(source['modelName']))
            except ApiError as error:
                if error.kind == 'notFound':
                    raise ApiError(error.kind, "Model '" + source['modelName'] + "' not found", error.details) from error
                raise
            plan = self.s('notes.planConversion', source={'id': original['noteType']['id']}, target={'id': target['id']})
            fields = {item['name']: '' for item in target['fields']}
            fields.update(self.fields(source['fields'], fields))
            # Historical conversion replaced tags; omitted or null tags clear them.
            patch = {'fields': fields, 'tags': self.normalize_tags(source.get('tags'))}
            # Validate content before conversion can change cards or review history.
            self.runtime.dispatcher.params('notes.update', {'id': str(source['id']), 'patch': patch})
            old = self.model(id=original['noteType']['id'])
            for key, mapping in [('flds', plan['fields']), ('tmpls', plan['templates'])]:
                names = [[item['name'] for item in old[key] if item['name'].lower() == entry['target'].lower()]
                         for entry in mapping]
                for matches in names:
                    if len(matches) > 1 or (key == 'tmpls' and not matches and len(old[key]) > 1):
                        raise ApiError('compatibilityError', 'Explicit conversion mappings are required.')
                # Raw mid assignment kept cards by ordinal. A lone source template without a
                # namesake keeps Anki's positional mapping instead of losing its cards.
                if key == 'tmpls' and not any(names):
                    continue
                for entry, matches in zip(mapping, names):
                    entry['source'] = matches[0] if matches else None
            self.s('notes.convert', ids=[str(source['id'])], target={'id': target['id']}, fields=plan['fields'], templates=plan['templates'], planToken=plan['token'])
            self.s('notes.update', id=str(source['id']), patch=patch)
            return None
        if name == 'getNoteTags':
            return self.s('notes.get', id=str(p['note']))['tags']
        if name in ('addTags', 'removeTags'):
            tags = self.normalize_tags(p['tags'])
            method = 'tags.remove' if name == 'removeTags' or not p.get('add', True) else 'tags.add'
            self.unwrap(self.s(method, noteIds=self.ids(p['notes']), tags=tags), missing=True)
            return None
        if name == 'getTags':
            return self.s('tags.list')
        if name == 'clearUnusedTags':
            self.s('tags.deleteUnused')
            return None
        if name in ('replaceTags', 'replaceTagsInAllNotes'):
            ids = self.ids(p['notes']) if name == 'replaceTags' else None
            if ids is not None:
                ids = [value['id'] for value in self.unwrap(self.s('notes.getMany', ids=ids), missing=True) if value]
            self.s('tags.replace', **{'from': p['tag_to_replace'], 'to': p['replace_with_tag']},
                   **({'noteIds': ids} if name == 'replaceTags' else {'allNotes': True}))
            return None
        if name in ('findNotes', 'findCards'):
            return [] if p['query'] is None else self.native_search('notes' if name == 'findNotes' else 'cards', p['query'])
        if name in ('notesInfo', 'cardsInfo', 'notesModTime', 'cardsModTime'):
            fields = p.get('fields') if name == 'cardsInfo' else None
            if fields is not None and (not isinstance(fields, list) or not all(isinstance(field, str) for field in fields)):
                raise ApiError('invalidParams', 'fields must be a list of card record field names.')
            kind = 'notes' if name.startswith('notes') else 'cards'
            ids = p.get(kind)
            if name == 'notesInfo' and p['query'] is not None:
                ids = self.native_search('notes', p['query'])
            if ids is None:
                raise ApiError('invalidParams', 'Must provide either "notes" or a "query"')
            result = []
            for id in ids:
                try:
                    if name.endswith('ModTime'):
                        native = self.service.note(str(id)) if kind == 'notes' else self.service.card(str(id))
                        result.append({'noteId' if kind == 'notes' else 'cardId': int(id), 'mod': native.mod})
                    else:
                        result.append(self.record(kind, id, fields))
                except Exception as error:
                    from anki.errors import NotFoundError
                    if isinstance(error, NotFoundError) or isinstance(error, ApiError) and error.kind == 'notFound':
                        result.append({})
                    else:
                        raise
            return result
        if name == 'deleteNotes':
            self.unwrap(self.s('notes.delete', ids=self.ids(p['notes'])), missing=True)
            return None
        if name == 'removeEmptyNotes':
            # Historically this silently deleted every unused note type. Sync
            # clients call it routinely, so it now succeeds without deleting.
            return None
        if name == 'cardsToNotes':
            values = self.unwrap(self.s('cards.getMany', ids=self.ids(p['cards'])), missing=True)
            return list(dict.fromkeys(int(value['noteId']) for value in values if value))
        if name in ('suspend', 'unsuspend'):
            for id in p['cards']:
                self.s('cards.get', id=str(id))
            values = self.unwrap(self.s('cards.setSuspended', ids=self.ids(p['cards']), suspended=False if name == 'unsuspend' else p['suspend']))
            return None if name == 'unsuspend' else any(value['changed'] for value in values)
        if name in ('suspended', 'areSuspended'):
            if name == 'suspended':
                return self.s('cards.get', id=str(p['card']))['scheduling']['queue'] == 'suspended'
            ids = [p['card']] if name == 'suspended' else p['cards']
            values = self.unwrap(self.s('cards.getMany', ids=self.ids(ids)), missing=name != 'suspended')
            result = [value['scheduling']['queue'] == 'suspended' if value else None for value in values]
            return result[0] if name == 'suspended' else result
        if name == 'areDue':
            result = []
            for id in p['cards']:
                if self.all_pages('cards.search', query='cid:{} is:new'.format(id)):
                    result.append(True)
                else:
                    # Historical queries depend on the latest review, including
                    # their IndexError when the card has no review history.
                    import time
                    date, ivl = self.service.col.db.all('select id/1000.0, ivl from revlog where cid = ?', id)[-1]
                    result.append(bool(self.all_pages('cards.search', query='cid:{} is:due'.format(id)))
                                  if ivl >= -1200 else date - ivl <= time.time())
            return result
        if name == 'getIntervals':
            result = []
            for id in p['cards']:
                if self.all_pages('cards.search', query='cid:{} is:new'.format(id)):
                    result.append(0)
                else:
                    intervals = self.service.col.db.list('select ivl from revlog where cid = ?', id)
                    result.append(intervals if p['complete'] else intervals[-1])
            return result
        if name in ('getEaseFactors', 'setEaseFactors'):
            if name == 'getEaseFactors':
                return [value['scheduling']['sm2EasePermille'] if value else None
                        for value in self.unwrap(self.s('cards.getMany', ids=self.ids(p['cards'])), missing=True)]
            result = []
            for index, id in enumerate(p['cards']):
                try:
                    self.s('cards.get', id=str(id))
                except ApiError as error:
                    if error.kind != 'notFound':
                        raise
                    result.append(False)
                    continue
                self.s('advanced.cards.update', cardId=str(id), patch={'sm2EasePermille': p['easeFactors'][index]})
                result.append(True)
            return result
        if name == 'setSpecificValueOfCard':
            return self.expert_card(p)
        if name in ('forgetCards', 'setDueDate', 'relearnCards', 'answerCards'):
            if name == 'forgetCards':
                self.unwrap(self.s('scheduling.reset', cardIds=self.ids(p['cards'])), missing=True)
                return None
            if name == 'setDueDate':
                self.unwrap(self.s('scheduling.setDueDate', cardIds=self.ids(p['cards']), days=p['days']), missing=True)
                return True
            if name == 'relearnCards':
                for id in p['cards']:
                    card = self.s('cards.get', id=str(id))
                    if card['scheduling']['queue'] != 'review' or card['homeDeck']:
                        raise ApiError('invalidState', 'Relearning requires an unfiltered active review card.')
                answers = [{'cardId': id, 'ease': 1} for id in p['cards']]
            else:
                answers = p['answers']
            if any(answer['ease'] not in (1, 2, 3, 4) for answer in answers):
                raise ApiError('invalidParams', 'Invalid ease.')
            result = []
            for answer in answers:
                try:
                    prediction = self.s('scheduling.predict', cardId=str(answer['cardId']))
                    self.s('scheduling.answer', cardId=str(answer['cardId']), rating=RATINGS[answer['ease'] - 1], stateToken=prediction['stateToken'])
                    result.append(True)
                except Exception as error:
                    from anki.errors import NotFoundError
                    # Missing and unanswerable cards fail individually, so one
                    # suspended or on-screen card cannot abort a partial batch.
                    if isinstance(error, NotFoundError) or isinstance(error, ApiError) and (error.kind == 'notFound' or name == 'answerCards' and error.kind == 'invalidState'):
                        result.append(False)
                    else:
                        raise
            return result if name == 'answerCards' else None
        if name.startswith('model') or name in ('createModel', 'findModelsById', 'findModelsByName', 'updateModelTemplates', 'updateModelStyling', 'findAndReplaceInModels'):
            return self.model_action(name, p)
        if name in ('getNumCardsReviewedToday', 'getNumCardsReviewedByDay', 'getCollectionStatsHTML'):
            if name == 'getNumCardsReviewedToday':
                return self.s('statistics.getToday')['count']
            if name == 'getNumCardsReviewedByDay':
                return [[value['day'], value['count']] for value in self.s('statistics.getReviewDays')]
            deck = None if p['wholeCollection'] else {'id': str(self.service.col.decks.selected())}
            return self.s('statistics.getHtml', **({'deck': deck} if deck else {}))['html']
        if name == 'getLatestReviewID':
            self.s('decks.create', name=p['deck'])
            return int(self.s('reviews.getLatestId', deck=self.ref(p['deck']))['id'] or 0)
        if name in ('cardReviews', 'getReviewsOfCards'):
            if name == 'cardReviews':
                self.s('decks.create', name=p['deck'])
                params = {'deck': self.ref(p['deck']), **({'afterId': str(p['startID'])} if p['startID'] else {})}
            else:
                values = self.unwrap(self.s('cards.getMany', ids=self.ids(p['cards'])), missing=True)
                params = {'cardIds': [value['id'] for value in values if value]}
            reviews = self.all_pages('reviews.list', **params)
            if name == 'cardReviews':
                return [[int(row['id']), int(row['cardId']), row['syncSequence'], RATINGS.index(row['rating']) + 1 if row['rating'] else 0,
                         self.signed(row['interval']), self.signed(row['previousInterval']), row['factor']['value'], row['elapsedMs'], KINDS.index(row['kind'])] for row in reviews]
            result = {str(id): [] for id in p['cards']}
            for row in reviews:
                result[row['cardId']].append({'id': int(row['id']), 'usn': row['syncSequence'], 'ease': RATINGS.index(row['rating']) + 1 if row['rating'] else 0,
                                              'ivl': self.signed(row['interval']), 'lastIvl': self.signed(row['previousInterval']), 'factor': row['factor']['value'], 'time': row['elapsedMs'], 'type': KINDS.index(row['kind'])})
            return result
        if name == 'insertReviews':
            values = []
            from .services import interval
            for row in p['reviews']:
                if not isinstance(row, (list, tuple)) or len(row) != 9 or not all(type(value) is int for value in row):
                    raise ApiError('invalidParams', 'Review rows require nine integers.')
                id, cid, usn, ease, ivl, last, factor, elapsed, kind = row
                if not 0 <= ease <= 4 or not 0 <= kind <= 5:
                    raise ApiError('invalidParams', 'Invalid review rating/kind.')
                values.append({'id': str(id), 'cardId': str(cid), 'rating': RATINGS[ease - 1] if ease else None,
                               'interval': interval(ivl), 'previousInterval': interval(last), 'factor': {'encoding': 'unknown', 'value': factor},
                               'elapsedMs': elapsed, 'kind': KINDS[kind]})
            if values:
                self.s('advanced.reviews.import', reviews=values)
            return None
        if name == 'importPackage':
            with open(p['path'], 'rb'):
                pass
            self.s('packages.import', path=p['path'])
            return True
        if name == 'exportPackage':
            try:
                self.s('packages.export', deck=self.ref(p['deck']), path=p['path'], includeScheduling=p['includeSched'])
                return True
            except ApiError as error:
                if error.kind == 'notFound':
                    return False
                raise
        raise ApiError('methodNotFound', 'Unsupported legacy action: ' + name)

    def signed(self, value):
        return -value['value'] if value['unit'] == 'seconds' else value['value']

    def expert_card(self, p):
        protected = {'did', 'id', 'ivl', 'lapses', 'left', 'mod', 'nid', 'odid', 'odue', 'ord', 'queue', 'reps', 'type', 'usn'}
        if type(p['card']) is not int or not isinstance(p['keys'], list) or not isinstance(p['newValues'], list) or len(p['keys']) != len(p['newValues']):
            return False
        if not p['warning_check'] and protected.intersection(p['keys']):
            return False
        if len(set(p['keys'])) != len(p['keys']):
            raise ApiError('compatibilityError', 'Duplicate card keys.')
        mapping = {'factor': 'sm2EasePermille', 'ivl': 'intervalDays', 'reps': 'repetitions', 'lapses': 'lapses', 'custom_data': 'customData'}
        if any(key not in {*mapping, 'did', 'flags'} for key in p['keys']):
            raise ApiError('compatibilityError', 'Use native scheduling commands for protected state.')
        if any(key in p['keys'] for key in ('did', 'flags')) and len(p['keys']) != 1:
            raise ApiError('compatibilityError', 'Separate deck/flag edits from metadata edits.')
        try:
            self.s('cards.get', id=str(p['card']))
            values = dict(zip(p['keys'], p['newValues']))
            if 'did' in values:
                self.unwrap(self.s('cards.move', ids=[str(p['card'])], deck={'id': str(values['did'])}))
            elif 'flags' in values:
                self.unwrap(self.s('cards.setFlags', ids=[str(p['card'])], flag=values['flags']))
            else:
                self.s('advanced.cards.update', cardId=str(p['card']), patch={mapping[key]: value for key, value in values.items()})
            return [True]
        except Exception as error:
            return [[False, str(error)]]

    def preset_patch(self, data):
        baseline = self.service.col.decks.get_config(int(data['id']))
        settings = {}
        paths = {'newPerDay': ('new', 'perDay'), 'reviewsPerDay': ('rev', 'perDay'), 'learnStepsMinutes': ('new', 'delays'),
                 'relearnStepsMinutes': ('lapse', 'delays'), 'initialEase': ('new', 'initialFactor'),
                 'easyMultiplier': ('rev', 'ease4'), 'hardMultiplier': ('rev', 'hardFactor'),
                 'lapseMultiplier': ('lapse', 'mult'), 'intervalMultiplier': ('rev', 'ivlFct'),
                 'maximumIntervalDays': ('rev', 'maxIvl'), 'minimumLapseIntervalDays': ('lapse', 'minInt'),
                 'leechThreshold': ('lapse', 'leechFails'), 'buryNew': ('new', 'bury'), 'buryReviews': ('rev', 'bury')}
        handled = {'id', 'name', 'mod', 'usn'}
        groups = {}
        for public, (group, key) in paths.items():
            groups.setdefault(group, set()).add(key)
            if key in data.get(group, {}) and data[group][key] != baseline[group][key]:
                value = data[group][key]
                settings[public] = value / 1000 if public == 'initialEase' else value
        enums = {'newMix': 'newMix', 'interdayLearningMix': 'dayLearningMix', 'reviewOrder': 'reviewOrder',
                 'newSortOrder': 'newSortOrder', 'newGatherPriority': 'newGatherOrder',
                 'questionAction': 'questionAction', 'answerAction': 'answerAction'}
        for old, public in enums.items():
            handled.add(old)
            if old in data and data[old] != baseline.get(old):
                settings[public] = PRESET_ENUMS[public][1][data[old]]
        # Anki ignores these obsolete keys and the unused third graduating interval;
        # historical README configs still send them.
        groups['new'].update(('ints', 'order', 'separate'))
        groups['rev'].update(('fuzz', 'minSpace'))
        groups['lapse'].add('leechAction')
        if 'ints' in data.get('new', {}) and data['new']['ints'][:2] != baseline['new']['ints'][:2]:
            if len(data['new']['ints']) not in (2, 3):
                raise ApiError('compatibilityError', 'Unsupported graduating interval metadata.')
            settings['graduatingGoodDays'], settings['graduatingEasyDays'] = data['new']['ints'][:2]
        if 'order' in data.get('new', {}) and data['new']['order'] != baseline['new']['order']:
            settings['newInsertOrder'] = {0: 'random', 1: 'due'}[data['new']['order']]
        if 'leechAction' in data.get('lapse', {}) and data['lapse']['leechAction'] != baseline['lapse']['leechAction']:
            settings['leechAction'] = PRESET_ENUMS['leechAction'][1][data['lapse']['leechAction']]
        mapping = {'newPerDayMinimum': 'newPerDayMinimum',
                   'maxTaken': 'answerTimeLimitSeconds', 'timer': 'showTimer', 'autoplay': 'disableAutoplay',
                   'desiredRetention': 'desiredRetention', 'ignoreRevlogsBeforeDate': 'ignoreReviewsBefore',
                   'buryInterdayLearning': 'buryDayLearning', 'fsrsWeights': 'fsrsParameters4',
                   'fsrsParams5': 'fsrsParameters5', 'fsrsParams6': 'fsrsParameters6',
                   'easyDaysPercentages': 'easyDaysPercentages', 'stopTimerOnAnswer': 'stopTimerOnAnswer',
                   'secondsToShowQuestion': 'questionDisplaySeconds', 'secondsToShowAnswer': 'answerDisplaySeconds',
                   'waitForAudio': 'waitForAudio', 'sm2Retention': 'historicalRetention', 'weightSearch': 'parameterSearch',
                   'replayq': 'skipQuestionOnAnswerReplay'}
        for old, public in mapping.items():
            handled.add(old)
            if old in data and data[old] != baseline.get(old):
                settings[public] = not data[old] if old in ('autoplay', 'replayq') else bool(data[old]) if old == 'timer' else data[old]
        for group, keys in groups.items():
            handled.add(group)
            for key, value in data.get(group, {}).items():
                if key not in keys and value != baseline.get(group, {}).get(key):
                    raise ApiError('compatibilityError', 'Unsupported preset setting: ' + group + '.' + key)
        for key, value in data.items():
            if key not in handled and value != baseline.get(key):
                raise ApiError('compatibilityError', 'Unsupported preset setting: ' + key)
        return settings

    def model_action(self, name, p):
        ref = self.ref(p.get('modelName', ''))
        if name in ('findModelsById', 'findModelsByName'):
            return [self.model(id=id) for id in p['modelIds']] if name == 'findModelsById' else [self.model(name=value) for value in p['modelNames']]
        if name == 'createModel':
            if not p['inOrderFields']:
                raise ApiError('invalidParams', 'Must provide at least one field for inOrderFields')
            if not p['cardTemplates']:
                raise ApiError('invalidParams', 'Must provide at least one card for cardTemplates')
            if self.service.col.models.by_name(p['modelName']) is not None:
                raise ApiError('conflict', 'Model name already exists')
            templates = [{'name': template.get('Name', 'Card ' + str(index + 1)), 'questionHtml': template['Front'], 'answerHtml': template['Back']}
                         for index, template in enumerate(p['cardTemplates'])]
            # Historical createModel kept Anki's new-model CSS and LaTeX defaults.
            defaults = self.service.col.models.new(p['modelName'])
            css = p['css'] if p['css'] is not None else defaults['css']
            value = self.s('noteTypes.create', name=p['modelName'], fields=[{'name': value} for value in p['inOrderFields']],
                           templates=templates, kind='cloze' if p['isCloze'] else 'normal', css=css,
                           latexHeader=defaults['latexPre'], latexFooter=defaults['latexPost'])
            return self.model(id=value['id'])
        if name in ('modelFieldNames', 'modelFieldDescriptions', 'modelFieldFonts', 'modelTemplates', 'modelStyling', 'modelFieldsOnTemplates'):
            model = self.s('noteTypes.get', noteType=ref)
            if name == 'modelFieldNames':
                return [value['name'] for value in model['fields']]
            if name == 'modelFieldDescriptions':
                return [value['description'] for value in model['fields']]
            if name == 'modelFieldFonts':
                return {value['name']: {'font': value['fontFamily'], 'size': value['fontSize']} for value in model['fields']}
            if name == 'modelTemplates':
                return {value['name']: {'Front': value['questionHtml'], 'Back': value['answerHtml']} for value in model['templates']}
            if name == 'modelStyling':
                return {'css': model['css']}
            return {value['templateName']: [value['questionFields'], [field for field in value['answerFields'] if field not in value['questionFields']]]
                    for value in self.s('noteTypes.getTemplateUsage', noteType=ref)}
        if name == 'updateModelStyling':
            self.s('noteTypes.update', noteType=self.ref(p['model']['name']), patch={'css': p['model']['css']})
            return None
        if name == 'findAndReplaceInModels':
            targets = [new for old, new in [('front', 'question'), ('back', 'answer'), ('css', 'css')] if p[old]]
            if not targets:
                return 0
            return self.s('noteTypes.replaceText', find=p['findText'], replace=p['replaceText'], targets=targets,
                          **({'noteTypes': [ref]} if p['modelName'] else {'allNoteTypes': True}))['changedCount']
        edits = []
        if name == 'updateModelTemplates':
            ref = self.ref(p['model']['name'])
            model = self.s('noteTypes.get', noteType=ref)
            for template in model['templates']:
                value = p['model']['templates'].get(template['name'], {})
                patch = {new: value[old] for old, new in [('Front', 'questionHtml'), ('Back', 'answerHtml')] if value.get(old)}
                if patch:
                    edits.append({'op': 'updateTemplate', 'name': template['name'], 'patch': patch})
        elif name in ('modelTemplateRename', 'modelFieldRename'):
            kind = 'Template' if 'Template' in name else 'Field'
            edits = [{'op': 'update' + kind, 'name': p['old' + kind + 'Name'], 'patch': {'name': p['new' + kind + 'Name']}}]
        elif name in ('modelTemplateReposition', 'modelFieldReposition'):
            kind = 'Template' if 'Template' in name else 'Field'
            edits = [{'op': 'move' + kind, 'name': p[kind.lower() + 'Name'], 'index': p['index']}]
        elif name in ('modelTemplateRemove', 'modelFieldRemove'):
            kind = 'Template' if 'Template' in name else 'Field'
            edits = [{'op': 'remove' + kind, 'name': p[kind.lower() + 'Name']}]
        elif name == 'modelTemplateAdd':
            value = p['template']
            data = {'name': value['Name'], 'questionHtml': value['Front'], 'answerHtml': value['Back']}
            model = self.s('noteTypes.get', noteType=ref)
            if value['Name'] in [template['name'] for template in model['templates']]:
                edits = [{'op': 'updateTemplate', 'name': value['Name'], 'patch': data}]
            else:
                edits = [{'op': 'addTemplate', 'template': data}]
        elif name == 'modelFieldAdd':
            model = self.s('noteTypes.get', noteType=ref)
            if p['fieldName'] not in [field['name'] for field in model['fields']]:
                edits.append({'op': 'addField', 'field': {'name': p['fieldName']}})
            if p['index'] is not None:
                edits.append({'op': 'moveField', 'name': p['fieldName'], 'index': p['index']})
        elif name in ('modelFieldSetFont', 'modelFieldSetFontSize', 'modelFieldSetDescription'):
            key, source = {'modelFieldSetFont': ('fontFamily', 'font'), 'modelFieldSetFontSize': ('fontSize', 'fontSize'),
                           'modelFieldSetDescription': ('description', 'description')}[name]
            edits = [{'op': 'updateField', 'name': p['fieldName'], 'patch': {key: p[source]}}]
        else:
            raise ApiError('methodNotFound', 'Unknown note type action.')
        if edits:
            model = self.model(p.get('modelName', p.get('model', {}).get('name')))
            names = {'field': {value['name'] for value in model['flds']},
                     'template': {value['name'] for value in model['tmpls']}}
            for edit in edits:
                kind = 'field' if edit['op'].endswith('Field') else 'template'
                if edit['op'].startswith('add'):
                    names[kind].add(edit[kind]['name'])
                    continue
                if edit['name'] not in names[kind]:
                    raise ApiError('notFound', kind + ' was not found in ' + model['name'] + ': ' + edit['name'])
                if edit['op'].startswith('move'):
                    # Anki's historical list insertion placed large indexes last.
                    edit['index'] = min(edit['index'], len(names[kind]) - 1)
            if name in ('modelFieldSetFont', 'modelFieldSetFontSize', 'modelFieldSetDescription'):
                key, expected, label = {'modelFieldSetFont': ('font', str, 'a string'),
                                        'modelFieldSetFontSize': ('fontSize', int, 'an integer'),
                                        'modelFieldSetDescription': ('description', str, 'a string')}[name]
                if not isinstance(p[key], expected):
                    raise ApiError('invalidParams', key + ' should be ' + label + ': ' + str(p[key]))
            self.s('noteTypes.editStructure', noteType=ref, edits=edits)
        return True if name == 'modelFieldSetDescription' else None

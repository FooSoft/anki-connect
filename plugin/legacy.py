"""Legacy argument translation and result projection over shared domain services."""
import copy
import html
import os
from datetime import datetime

from .protocol import ApiError, Deferred
from .services import RATINGS, KINDS, PRESET_ENUMS


class Accepted:
    def __init__(self, value, pending, project=lambda value: value):
        self.value, self.pending, self.project = value, pending, project


class Legacy:
    def __init__(self, owner, service=None):
        self.owner, self.runtime = owner, owner.runtime
        self.service = service
        self.media_transaction = None

    def s(self, method, **params):
        if self.service is None:
            self.service = self.runtime.service()
        return self.service.execute(method, self.runtime.dispatcher.params(method, params))

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
                    raise ApiError(error.get('data', {}).get('type', 'internalError'), error['message'])
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

    def model(self, name=None, id=None):
        # Compatibility projections are snapshots, never a writable alternate service.
        if self.service is None:
            self.service = self.runtime.service()
        service = self.service
        return service.resolve({'id': str(id)} if id is not None else self.ref(name), 'noteType')

    def created_note(self, source, pure=False):
        source = copy.deepcopy(source)
        model = self.model(source['modelName'])
        fields = {}
        for key, value in source['fields'].items():
            matches = [field['name'] for field in model['flds'] if field['name'].lower() == key.lower()]
            if len(matches) > 1:
                raise ApiError('compatibilityError', 'Ambiguous field name.')
            if matches:
                fields[matches[0]] = value
        options = source.get('options', {})
        scope = options.get('duplicateScope') or 'collection'
        if scope not in ('collection', 'deck'):
            raise ApiError('invalidParams', 'Unknown duplicate scope.')
        scoped = options.get('duplicateScopeOptions', {})
        duplicates = {'allow': options.get('allowDuplicate', False), 'scope': scope,
                      'includeChildren': scoped.get('checkChildren', False),
                      'acrossNoteTypes': scoped.get('checkAllModels', False)}
        if scope == 'deck':
            duplicates['deck'] = self.ref(scoped.get('deckName', source['deckName']))
        data = {'noteType': self.ref(source['modelName']), 'deck': self.ref(source['deckName']),
                'fields': fields, 'tags': list(source.get('tags', [])), 'duplicates': duplicates}
        if pure:
            self.attachments(data['fields'], source, pure=True)
        return data

    def acquire(self, params):
        import base64
        import urllib.request
        from . import util
        sources = [key for key in ('data', 'path', 'url') if params.get(key) is not None]
        if len(sources) != 1:
            raise ApiError('invalidParams', 'Provide exactly one of data, path, or url.')
        key = sources[0]
        if key == 'data':
            data = base64.b64decode(params[key], validate=True)
        elif key == 'path':
            with open(params[key], 'rb') as file:
                data = file.read(67108865)
        else:
            with urllib.request.urlopen(params[key], timeout=util.setting('webTimeout') / 1000) as response:
                data = response.read(67108865)
        if len(data) > 67108864:
            raise ApiError('invalidParams', 'Media exceeds the size limit.')
        return data

    def install(self, entry, data):
        from .media import MediaTransaction
        if self.service is None:
            self.service = self.runtime.service()
        if self.media_transaction is None:
            self.media_transaction = MediaTransaction(self.service)
        skip = {'algorithm': 'md5', 'digest': entry['skipHash']} if entry.get('skipHash') else None
        return self.media_transaction.install(entry['filename'], data, skip,
                    'replace' if entry.get('deleteExisting', True) else 'rename')

    def attachments(self, fields, source, pure=False):
        staged = []
        for kind in ('audio', 'video', 'picture'):
            entries = source.get(kind) or []
            entries = entries if isinstance(entries, list) else [entries]
            for entry in entries:
                if entry:
                    staged.append((kind, entry, None if pure else self.acquire(entry)))
        for kind, entry, data in staged:
            filename = entry['filename'] if pure else self.install(entry, data)
            if filename is None:
                continue
            escaped = html.escape(filename, quote=True)
            content = '<img src="' + escaped + '">' if kind == 'picture' else '[sound:' + escaped + ']'
            for field in entry.get('fields', []):
                if field in fields:
                    fields[field] += content

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
                return {'canAdd': False, 'error': '; '.join(issue['message'] for issue in result['issues'])}
            return {'canAdd': True}
        except Exception as error:
            return {'canAdd': False, 'error': str(error)}

    def add_notes(self, sources, atomic):
        prepared = [self.created_note(source, pure=True) for source in sources]
        validation = self.unwrap(self.s('notes.validateMany', notes=prepared))
        if any(not value['valid'] for value in validation):
            raise ApiError('validationFailed', 'One or more notes failed validation.', {'items': validation})
        # Acquire every attachment before installing any file. Back up only
        # destinations this request owns; never scan or restore unrelated media.
        staged = []
        import base64
        import urllib.request
        from . import util
        for source in sources:
            for kind in ('audio', 'video', 'picture'):
                entries = source.get(kind) or []
                entries = entries if isinstance(entries, list) else [entries]
                for entry in entries:
                    if not entry:
                        continue
                    filename = self.service.media_filename(entry['filename'])
                    if 'data' in entry:
                        data = base64.b64decode(entry['data'], validate=True)
                    elif 'path' in entry:
                        with open(entry['path'], 'rb') as file:
                            data = file.read(67108865)
                    elif 'url' in entry:
                        with urllib.request.urlopen(entry['url'], timeout=util.setting('webTimeout') / 1000) as response:
                            data = response.read(67108865)
                    else:
                        raise ApiError('invalidParams', 'Attachment needs data, path, or url.')
                    if len(data) > 67108864:
                        raise ApiError('invalidParams', 'Media is too large.')
                    staged.append((entry, filename, data))
        from .media import MediaTransaction
        transaction = MediaTransaction(self.service)
        filenames = {}
        try:
            for entry, filename, data in staged:
                skip = {'algorithm': 'md5', 'digest': entry['skipHash']} if entry.get('skipHash') else None
                filenames[id(entry)] = transaction.install(filename, data, skip)
            for source, data in zip(sources, prepared):
                data['fields'] = self.created_note(source)['fields']
                for kind in ('audio', 'video', 'picture'):
                    entries = source.get(kind) or []
                    entries = entries if isinstance(entries, list) else [entries]
                    for entry in entries:
                        if not entry or filenames[id(entry)] is None:
                            continue
                        filename = html.escape(filenames[id(entry)], quote=True)
                        content = '<img src="' + filename + '">' if kind == 'picture' else '[sound:' + filename + ']'
                        for field in entry.get('fields', []):
                            if field in data['fields']:
                                data['fields'][field] += content
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

    def record(self, kind, id):
        value = self.s(kind + '.get', id=str(id))
        model = self.model(id=value['noteType']['id']) if kind == 'notes' else self.model(id=self.service.card(str(id)).note().mid)
        if kind == 'notes':
            return {'noteId': int(id), 'profile': self.runtime.profile_name, 'tags': value['tags'],
                    'fields': {field['name']: {'value': value['fields'][field['name']], 'order': index} for index, field in enumerate(model['flds'])},
                    'modelName': model['name'], 'mod': int(datetime.fromisoformat(value['modifiedAt'].replace('Z', '+00:00')).timestamp()),
                    'cards': [int(id) for id in value['cardIds']]}
        card = self.service.card(str(id))
        rendered = self.s('cards.render', id=str(id))
        prediction = self.s('scheduling.predict', cardId=str(id))
        return {'cardId': card.id, 'fields': {field['name']: {'value': card.note().fields[index], 'order': index} for index, field in enumerate(model['flds'])},
                'fieldOrder': card.ord, 'question': rendered['questionHtml'], 'answer': rendered['answerHtml'],
                'modelName': model['name'], 'ord': card.ord, 'deckName': value['deck']['name'], 'css': model['css'],
                'factor': card.factor, 'interval': card.ivl, 'note': card.nid, 'type': card.type, 'queue': card.queue,
                'due': card.due, 'reps': card.reps, 'lapses': card.lapses, 'left': card.left, 'mod': card.mod,
                'nextReviews': [item['label'] for item in prediction['answers']], 'flags': card.flags}

    def gui_call(self, name, p):
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
            sort = {'column': sort['columnId'], 'direction': sort['order']} if sort else None
            value = call('browser.open', query=p['query'], sort=sort)
            def project(_):
                return [] if p['query'] is None else [int(id) for id in self.all_pages('cards.search', query=p['query'])]
            return value.map(project) if isinstance(value, Deferred) else project(value)
        if name in ('guiSelectNote', 'guiSelectCard'):
            if not gui.browser():
                return False
            call('browser.select', cardIds=[str(p.get('card', p.get('note')))])
            return True
        if name == 'guiSelectedNotes':
            return [int(id) for id in call('browser.getSelection')['selectedNoteIds']]
        if name == 'guiEditNote':
            return accepted('editors.openNote', None, lambda value: None, noteId=str(p['note']))
        if name == 'guiAddCards':
            note = self.created_note(p['note']) if p['note'] else None
            session = runtime.session
            def open_add(_=None):
                runtime.capture(session)
                if note:
                    note.pop('duplicates', None)
                return accepted('editors.openAdd', 0, lambda value: int(value['noteId'] or 0), **({'note': note} if note else {}))
            if note and any(p['note'].get(kind) for kind in ('audio', 'video', 'picture')):
                return self.prepare_gui_media(note['fields'], p['note']).map(open_add)
            return open_add()
        if name == 'guiAddNoteSetData':
            dialog = gui.add_dialog()
            if dialog is None:
                return {'error': 'Add Note dialog is not open', 'code': 1}
            source = copy.deepcopy(p['note'])
            patch = {key: value for key, value in source.items() if key in ('fields', 'tags')}
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
            return value.map(lambda value: True) if isinstance(value, Deferred) else True
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
        if name == 'multi':
            return [self.owner.handler(action) for action in p['actions']]
        if name == 'version':
            return util.setting('apiVersion')
        if name == 'requestPermission':
            return self.owner.permission(p['origin'], p['allowed'])
        if name == 'apiReflect':
            if not isinstance(p['scopes'], list) or not (p['actions'] is None or isinstance(p['actions'], list)):
                raise ApiError('invalidParams', 'Invalid reflection arguments.')
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
            self.unwrap(self.s('cards.move', ids=self.ids(p['cards']), deck={'id': target['id']}))
            return None
        if name == 'deleteDecks':
            if not p['cardsToo']:
                raise ApiError('invalidParams', 'Since Anki 2.1.28 it is not possible to delete decks without deleting cards.')
            existing = {value['name'] for value in self.s('decks.list')}
            self.unwrap(self.s('decks.delete', decks=[self.ref(name) for name in p['decks'] if name in existing], deleteCards=True))
            return None
        if name == 'getDeckStats':
            result = {}
            for deck in p['decks']:
                value = self.s('decks.getCounts', deck=self.ref(deck))
                result[value['deckId']] = {'deck_id': int(value['deckId']), 'name': deck, 'new_count': value['new'],
                                           'learn_count': value['learning'], 'review_count': value['review'], 'total_in_deck': value['total']}
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
                    return all(value['changed'] or True for value in self.unwrap(self.s('deckPresets.assign', decks=refs, preset={'id': str(p['configId'])})))
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
            values = self.add_notes(p.get('notes', [p.get('note')]), True)
            return values if name == 'addNotes' else values[0]
        if name in ('updateNote', 'updateNoteFields', 'updateNoteTags'):
            source = p['note']
            source = {'id': source, 'tags': p['tags']} if name == 'updateNoteTags' else copy.deepcopy(source)
            patch = {}
            if 'fields' in source:
                current = self.s('notes.get', id=str(source['id']))
                patch['fields'] = {key: value for key, value in source['fields'].items() if key in current['fields']}
            if name != 'updateNoteFields' and 'tags' in source:
                patch['tags'] = [source['tags']] if isinstance(source['tags'], str) else list(source['tags'])
            if not patch:
                raise ApiError('invalidParams', 'Must provide a fields or tags property.')
            self.runtime.dispatcher.params('notes.update', {'id': str(source['id']), 'patch': patch})
            if 'fields' in patch:
                self.attachments(patch['fields'], source)
            self.s('notes.update', id=str(source['id']), patch=patch)
            return None
        if name == 'updateNoteModel':
            source = p['note']
            original = self.s('notes.get', id=str(source['id']))
            target = self.s('noteTypes.get', noteType=self.ref(source['modelName']))
            plan = self.s('notes.planConversion', source={'id': original['noteType']['id']}, target={'id': target['id']})
            old = self.model(id=original['noteType']['id'])
            for key, mapping in [('flds', plan['fields']), ('tmpls', plan['templates'])]:
                for entry in mapping:
                    matches = [item['name'] for item in old[key] if item['name'].lower() == entry['target'].lower()]
                    if len(matches) > 1 or (key == 'tmpls' and not matches and len(old[key]) > 1):
                        raise ApiError('compatibilityError', 'Explicit conversion mappings are required.')
                    entry['source'] = matches[0] if matches else None
            self.s('notes.convert', ids=[str(source['id'])], target={'id': target['id']}, fields=plan['fields'], templates=plan['templates'], planToken=plan['token'])
            fields = {item['name']: '' for item in target['fields']}
            for name, value in source['fields'].items():
                actual = next((field for field in fields if field.lower() == name.lower()), None)
                if actual:
                    fields[actual] = value
            self.s('notes.update', id=str(source['id']), patch={'fields': fields, **({'tags': source['tags']} if 'tags' in source else {})})
            return None
        if name == 'getNoteTags':
            return self.s('notes.get', id=str(p['note']))['tags']
        if name in ('addTags', 'removeTags'):
            tags = self.service.col.tags.split(p['tags']) if isinstance(p['tags'], str) else list(p['tags'])
            method = 'tags.remove' if name == 'removeTags' or not p.get('add', True) else 'tags.add'
            self.unwrap(self.s(method, noteIds=self.ids(p['notes']), tags=tags))
            return None
        if name == 'getTags':
            return self.s('tags.list')
        if name == 'clearUnusedTags':
            self.s('tags.deleteUnused')
            return None
        if name in ('replaceTags', 'replaceTagsInAllNotes'):
            self.s('tags.replace', **{'from': p['tag_to_replace'], 'to': p['replace_with_tag']},
                   **({'noteIds': self.ids(p['notes'])} if name == 'replaceTags' else {'allNotes': True}))
            return None
        if name in ('findNotes', 'findCards'):
            return [] if p['query'] is None else [int(id) for id in self.all_pages('notes.search' if name == 'findNotes' else 'cards.search', query=p['query'])]
        if name in ('notesInfo', 'cardsInfo', 'notesModTime', 'cardsModTime'):
            kind = 'notes' if name.startswith('notes') else 'cards'
            ids = p.get(kind)
            if name == 'notesInfo' and p['query'] is not None:
                ids = self.all_pages('notes.search', query=p['query'])
            if ids is None:
                raise ApiError('invalidParams', 'Must provide notes or query.')
            result = []
            for id in ids:
                try:
                    if name.endswith('ModTime'):
                        native = self.service.note(str(id)) if kind == 'notes' else self.service.card(str(id))
                        result.append({'noteId' if kind == 'notes' else 'cardId': int(id), 'mod': native.mod})
                    else:
                        result.append(self.record(kind, id))
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
            raise ApiError('compatibilityError', 'Use notes.findEmpty with explicit criteria, then notes.delete.')
        if name == 'cardsToNotes':
            values = self.unwrap(self.s('cards.getMany', ids=self.ids(p['cards'])), missing=True)
            return list(dict.fromkeys(int(value['noteId']) for value in values if value))
        if name in ('suspend', 'unsuspend'):
            values = self.unwrap(self.s('cards.setSuspended', ids=self.ids(p['cards']), suspended=False if name == 'unsuspend' else p['suspend']))
            return any(value['changed'] for value in values)
        if name in ('suspended', 'areSuspended'):
            ids = [p['card']] if name == 'suspended' else p['cards']
            values = self.unwrap(self.s('cards.getMany', ids=self.ids(ids)), missing=name != 'suspended')
            result = [value['scheduling']['queue'] == 'suspended' if value else None for value in values]
            return result[0] if name == 'suspended' else result
        if name == 'areDue':
            result = []
            for id in p['cards']:
                card = self.s('cards.get', id=str(id))
                value = self.s('scheduling.getDue', cardId=str(id))
                result.append(value['dueNow'] or (card['scheduling']['queue'] == 'new' and value['available']))
            return result
        if name == 'getIntervals':
            result = []
            for id in p['cards']:
                state = self.s('scheduling.get', cardId=str(id))
                if state['type'] == 'new':
                    result.append(0)
                elif p['complete']:
                    result.append([self.signed(review['interval']) for review in self.all_pages('reviews.list', cardIds=[str(id)], includeManual=False)])
                else:
                    result.append(-state['learningIntervalSeconds'] if state['learningIntervalSeconds'] is not None else state['intervalDays'])
            return result
        if name in ('getEaseFactors', 'setEaseFactors'):
            if name == 'getEaseFactors':
                return [value['scheduling']['sm2EasePermille'] for value in self.unwrap(self.s('cards.getMany', ids=self.ids(p['cards'])))]
            if len(p['cards']) != len(p['easeFactors']):
                raise ApiError('invalidParams', 'Card/ease arrays must have equal lengths.')
            result = []
            for id, factor in zip(p['cards'], p['easeFactors']):
                try:
                    self.s('advanced.cards.update', cardId=str(id), patch={'sm2EasePermille': factor})
                    result.append(True)
                except Exception:
                    result.append(False)
            return result
        if name == 'setSpecificValueOfCard':
            return self.expert_card(p)
        if name in ('forgetCards', 'setDueDate', 'relearnCards', 'answerCards'):
            if name == 'forgetCards':
                self.unwrap(self.s('scheduling.reset', cardIds=self.ids(p['cards'])))
                return None
            if name == 'setDueDate':
                self.unwrap(self.s('scheduling.setDueDate', cardIds=self.ids(p['cards']), days=p['days']))
                return True
            if name == 'relearnCards':
                for id in p['cards']:
                    card = self.s('cards.get', id=str(id))
                    if card['scheduling']['queue'] != 'review' or card['homeDeck']:
                        raise ApiError('invalidState', 'Relearning requires an unfiltered active review card.')
                answers = [{'cardId': id, 'ease': 1} for id in p['cards']]
            else:
                answers = p['answers']
            result = []
            for answer in answers:
                try:
                    if answer['ease'] not in (1, 2, 3, 4):
                        raise ApiError('invalidParams', 'Invalid ease.')
                    prediction = self.s('scheduling.predict', cardId=str(answer['cardId']))
                    self.s('scheduling.answer', cardId=str(answer['cardId']), rating=RATINGS[answer['ease'] - 1], stateToken=prediction['stateToken'])
                    result.append(True)
                except Exception as error:
                    from anki.errors import NotFoundError
                    if isinstance(error, NotFoundError) or isinstance(error, ApiError) and error.kind == 'notFound':
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
            return int(self.s('reviews.getLatestId', deck=self.ref(p['deck']))['id'] or 0)
        if name in ('cardReviews', 'getReviewsOfCards'):
            params = {'deck': self.ref(p['deck']), **({'afterId': str(p['startID'])} if p['startID'] else {})} if name == 'cardReviews' else {'cardIds': self.ids(p['cards'])}
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
        groups['new'].update(('ints', 'order'))
        groups['lapse'].add('leechAction')
        if 'ints' in data.get('new', {}) and data['new']['ints'] != baseline['new']['ints']:
            if len(data['new']['ints']) != 3 or data['new']['ints'][2] != baseline['new']['ints'][2]:
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
            templates = [{'name': template.get('Name', 'Card ' + str(index + 1)), 'questionHtml': template['Front'], 'answerHtml': template['Back']}
                         for index, template in enumerate(p['cardTemplates'])]
            css = p['css'] if p['css'] is not None else self.service.col.models.new(p['modelName'])['css']
            value = self.s('noteTypes.create', name=p['modelName'], fields=[{'name': value} for value in p['inOrderFields']],
                           templates=templates, kind='cloze' if p['isCloze'] else 'normal', css=css)
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
            self.s('noteTypes.editStructure', noteType=ref, edits=edits)
        return True if name == 'modelFieldSetDescription' else None

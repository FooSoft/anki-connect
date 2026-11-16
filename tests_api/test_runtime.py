from pathlib import Path
from types import SimpleNamespace
import pytest
from jsonschema import Draft202012Validator
from anki.collection import Collection
from plugin import AnkiConnect
from plugin.contract import SCHEMA
from plugin.protocol import Dispatcher, ApiError, Operations, completed
from plugin.services import Services
from plugin.legacy import Legacy


@pytest.fixture
def native(tmp_path):
    from anki.lang import set_lang
    set_lang('en')
    col = Collection(str(tmp_path / 'collection.anki2'))
    owner = AnkiConnect()
    runtime = owner.runtime
    runtime._collection, runtime._session, runtime.profile_name = col, 'test-session', 'test'
    runtime.active_reviewer_card = None
    service = Services(runtime, col, 'test-session')
    try:
        yield owner, service
    finally:
        col.close()


def call(service, method, **params):
    dispatcher = Dispatcher(service.runtime)
    value = service.execute(method, dispatcher.params(method, params))
    validator = Draft202012Validator({**SCHEMA, 'oneOf': [SCHEMA['x-methods'][method].get('operationResult', SCHEMA['x-methods'][method]['result'])]})
    errors = list(validator.iter_errors(value))
    if errors:
        leaves = errors[0].context or errors
        pytest.fail('; '.join(str(list(error.path)) + ': ' + error.message for error in leaves))
    return value


def test_native_collection_round_trip(native):
    owner, service = native
    deck = call(service, 'decks.create', name='Test')
    types = call(service, 'noteTypes.list')
    basic = next(value for value in types if value['name'] == 'Basic')
    note = {'noteType': {'id': basic['id']}, 'deck': {'id': deck['id']}, 'fields': {'Front': 'one', 'Back': 'two'}}
    assert call(service, 'notes.validate', note=note)['valid']
    created = call(service, 'notes.create', **note)
    id = created['noteId']
    assert call(service, 'notes.get', id=id)['fields']['Front'] == 'one'
    call(service, 'notes.update', id=id, patch={'fields': {'Back': 'three'}})
    card_id = call(service, 'notes.get', id=id)['cardIds'][0]
    call(service, 'cards.get', id=card_id)
    call(service, 'cards.render', id=card_id)
    call(service, 'cards.setFlags', ids=[card_id], flag=3)
    prediction = call(service, 'scheduling.predict', cardId=card_id)
    call(service, 'scheduling.answer', cardId=card_id, stateToken=prediction['stateToken'], rating='good')
    call(service, 'reviews.list', cardIds=[card_id])
    call(service, 'statistics.getToday')
    call(service, 'statistics.getReviewDays')
    call(service, 'statistics.getSummary', deck={'id': deck['id']})


def test_scheduler_queue_preserves_native_order_without_consuming_cards(native):
    owner, service = native
    created = [call(service, 'notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'},
                    fields={'Front': str(index)}) for index in range(3)]
    expected = [note['cardIds'][0] for note in created[:2]]

    first = call(service, 'scheduling.getQueue', fetchLimit=2)
    second = call(service, 'scheduling.getQueue', fetchLimit=2)
    default = call(service, 'scheduling.getQueue')

    assert first == second
    assert default['cards'] == first['cards'][:1]
    assert first['cards'] == [{'cardId': id, 'queue': 'new'} for id in expected]
    assert first['newCount'] == 3
    assert first['learningCount'] == first['reviewCount'] == 0
    assert service.col.db.scalar('select count() from revlog') == 0


def test_legacy_forwards(native):
    owner, service = native
    legacy = Legacy(owner, service)
    legacy.call('createDeck', {'deck': 'Test'})
    note = {'modelName': 'Basic', 'deckName': 'Test', 'fields': {'Front': 'alpha', 'Back': 'beta'}}
    assert legacy.call('canAddNote', {'note': note})
    id = legacy.call('addNote', {'note': note})
    assert legacy.call('notesInfo', {'notes': [id], 'query': None})[0]['fields']['Front']['value'] == 'alpha'
    assert legacy.call('canAddNote', {'note': note}) is False
    cards = legacy.call('findCards', {'query': 'deck:Test'})
    assert legacy.call('cardsInfo', {'cards': cards})[0]['cardId'] == cards[0]


def test_operations_completion_and_cancel():
    tasks = []
    operations = Operations(tasks.append)
    handle = operations.submit('test', None, lambda key: completed({'changed': True}))
    assert operations.get(handle['operationId'])['state'] == 'queued'
    tasks.pop(0)()
    assert operations.get(handle['operationId'])['state'] == 'succeeded'
    second = operations.submit('test', None, lambda key: pytest.fail('cancelled task ran'))
    assert operations.cancel(second['operationId']) == {'requested': True}
    tasks.pop(0)()
    assert operations.get(second['operationId'])['state'] == 'cancelled'


def test_dispatcher_validation_and_notifications():
    invoked = []
    runtime = SimpleNamespace(invoke=lambda method, params: invoked.append(method) or completed({}))
    dispatcher = Dispatcher(runtime)
    bad = dispatcher.request({'jsonrpc': '2.0', 'id': 1, 'method': 'notes.get', 'params': {'id': 1}})
    assert bad.value['error']['data']['type'] == 'invalidParams'
    notification = dispatcher.request({'jsonrpc': '2.0', 'method': 'decks.create', 'params': {'name': 'X'}})
    assert notification.value is None
    assert not invoked


def test_bulk_atomic_validation_and_media_ownership(native, tmp_path, monkeypatch):
    owner, service = native
    legacy = Legacy(owner, service)
    legacy.call('createDeck', {'deck': 'Test'})
    existing = service.store_bytes('existing.txt', b'original', 'replace')
    service.store_bytes('unrelated.txt', b'keep')
    source = {'modelName': 'Basic', 'deckName': 'Test', 'fields': {'Front': 'a', 'Back': 'b'},
              'audio': [{'filename': 'existing.txt', 'data': 'aW5jb21pbmc=', 'fields': ['Back']}]}
    def fail_after_media_install(*args):
        assert (Path(service.col.media.dir()) / 'existing.txt').read_bytes() == b'incoming'
        raise RuntimeError('native note write failed')
    with monkeypatch.context() as patch:
        patch.setattr(service.col, 'add_notes', fail_after_media_install)
        with pytest.raises(RuntimeError, match='native note write failed'):
            legacy.add_notes([source], True)
    assert (Path(service.col.media.dir()) / 'existing.txt').read_bytes() == b'original'
    assert (Path(service.col.media.dir()) / 'unrelated.txt').read_bytes() == b'keep'
    assert not service.col.find_notes('')
    note = legacy.created_note(source)
    with pytest.raises(ApiError):
        call(service, 'notes.createMany', notes=[note, note], atomic=True)
    assert not service.col.find_notes('')


def test_structures_presets_tags_and_decks(native):
    owner, service = native
    model = call(service, 'noteTypes.create', name='Test Type', fields=[{'name': 'F'}, {'name': 'B'}],
                 templates=[{'name': 'Card', 'questionHtml': '{{F}}', 'answerHtml': '{{B}}'}])
    call(service, 'noteTypes.get', noteType={'id': model['id']})
    call(service, 'noteTypes.editStructure', noteType={'id': model['id']}, edits=[{'op': 'updateField', 'name': 'F', 'patch': {'name': 'Front'}}])
    call(service, 'noteTypes.getTemplateUsage', noteType={'id': model['id']})
    call(service, 'noteTypes.replaceText', find='{{B}}', replace='{{Front}}', noteTypes=[{'id': model['id']}])
    deck = call(service, 'decks.create', name='Test')
    call(service, 'decks.getCounts', deck={'id': deck['id']})
    preset = call(service, 'deckPresets.create', name='Preset')
    call(service, 'deckPresets.get', preset={'id': preset['id']})
    call(service, 'deckPresets.update', preset={'id': preset['id']}, settings={'newPerDay': 30})
    call(service, 'deckPresets.assign', decks=[{'id': deck['id']}], preset={'id': preset['id']})
    note = call(service, 'notes.create', noteType={'id': model['id']}, deck={'id': deck['id']}, fields={'Front': 'X'})
    call(service, 'tags.add', noteIds=[note['noteId']], tags=['a'])
    call(service, 'tags.replace', noteIds=[note['noteId']], **{'from': 'a', 'to': 'b'})
    call(service, 'tags.remove', noteIds=[note['noteId']], tags=['b'])
    call(service, 'tags.deleteUnused')
    call(service, 'deckPresets.delete', preset={'id': preset['id']}, replacement={'id': '1'})
    call(service, 'notes.delete', ids=[note['noteId']])
    call(service, 'noteTypes.deleteUnused', noteTypes=[{'id': model['id']}])
    call(service, 'decks.delete', decks=[{'id': deck['id']}], deleteCards=True)


def test_historical_reviews_transaction_and_sync_flags(native):
    owner, service = native
    note = call(service, 'notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': 'history'})
    card = note['cardIds'][0]
    before = service.card(card)._to_backend_card().SerializeToString()
    review = {'id': '100', 'cardId': card, 'rating': 'good', 'interval': {'value': 4, 'unit': 'days'},
              'previousInterval': {'value': 1, 'unit': 'days'}, 'factor': {'encoding': 'legacySm2EasePermille', 'value': 2500},
              'elapsedMs': 500, 'kind': 'review'}
    assert call(service, 'advanced.reviews.import', reviews=[review]) == {'changedCount': 1}
    assert service.col.db.scalar('select usn from revlog where id=100') == -1
    assert service.card(card)._to_backend_card().SerializeToString() == before
    with pytest.raises(ApiError):
        call(service, 'advanced.reviews.import', reviews=[{**review, 'id': '101'}, review])
    assert not service.col.db.scalar('select 1 from revlog where id=101')


def test_search_cursor_query_binding_and_deleted_ids(native):
    owner, service = native
    ids = [call(service, 'notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': str(index)})['noteId'] for index in range(3)]
    page = call(service, 'notes.search', query='', limit=1)
    with pytest.raises(ApiError) as error:
        call(service, 'notes.search', query='tag:x', limit=1, cursor=page['nextCursor'])
    assert error.value.kind == 'invalidParams'
    assert page['nextCursor'] in owner.runtime.cursors
    call(service, 'notes.delete', ids=[ids[1]])
    second = call(service, 'notes.search', query='', limit=1, cursor=page['nextCursor'])
    assert second['ids'] == []
    with pytest.raises(ApiError) as error:
        call(service, 'notes.search', query='', limit=1, cursor=page['nextCursor'])
    assert error.value.kind == 'staleCursor'
    final = call(service, 'notes.search', query='', limit=1, cursor=second['nextCursor'])
    assert final == {'ids': [ids[2]], 'nextCursor': None}
    assert not owner.runtime.cursors


@pytest.mark.parametrize('action', ['findCards', 'findNotes'])
def test_legacy_large_search_releases_snapshot(native, action):
    from anki.collection import AddNoteRequest
    owner, service = native
    model = service.col.models.by_name('Basic')
    notes = []
    for index in range(10001):
        note = service.col.new_note(model)
        note['Front'] = str(index)
        notes.append(AddNoteRequest(note=note, deck_id=1))
    service.col.add_notes(notes)
    expected = sorted(service.col.find_cards('') if action == 'findCards' else service.col.find_notes(''))
    legacy = Legacy(owner, service)
    for _ in range(2):
        assert legacy.call(action, {'query': ''}) == expected
        assert not owner.runtime.cursors


def test_search_cursor_capacity_preserves_other_snapshots(native):
    owner, service = native
    for index in range(3):
        call(service, 'notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': str(index)})
    pages = [call(service, 'notes.search', query='', limit=1) for _ in range(100)]
    with pytest.raises(ApiError) as error:
        call(service, 'notes.search', query='', limit=1)
    assert error.value.kind == 'busy'
    second = call(service, 'notes.search', query='', limit=1, cursor=pages[0]['nextCursor'])
    assert len(owner.runtime.cursors) == 100
    assert all(page['nextCursor'] in owner.runtime.cursors for page in pages[1:])
    call(service, 'notes.search', query='', limit=1, cursor=second['nextCursor'])
    assert len(owner.runtime.cursors) == 99
    assert call(service, 'notes.search', query='', limit=1)['nextCursor']


def test_legacy_signatures_and_reflection(native, monkeypatch):
    from plugin import util
    owner, service = native
    monkeypatch.setattr(util, 'setting', lambda key: util.DEFAULT_CONFIG[key])
    handle = lambda request: owner.handler_async(request).value
    reflected = handle({'action': 'apiReflect', 'version': 6, 'params': {'scopes': ['actions']}})
    assert len(reflected['result']['actions']) == 122
    assert handle({'action': 'version'}) == 6
    assert handle({'action': 'version', 'version': 6}) == {'result': 6, 'error': None}
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'apiKey', 'secret')
    assert handle({'action': 'version', 'version': 4})['error'] == 'valid api key must be provided'
    assert handle({'action': 'version', 'key': 'secret'}) == 6
    # Declarations bind like the historical methods but never execute directly.
    with pytest.raises(TypeError, match=r"AnkiConnect\.addNote\(\) missing 1 required positional argument: 'note'"):
        owner.addNote()
    with pytest.raises(NotImplementedError):
        owner.version()


def test_http_routing_auth_cors_and_notifications(monkeypatch):
    import json
    from plugin import util
    from plugin.web import WebServer, WebRequest, WebClient
    monkeypatch.setattr(util, 'setting', lambda key: util.DEFAULT_CONFIG[key])
    calls = []
    server = WebServer(lambda request: completed({'result': 6, 'error': None}),
                       lambda request, context: calls.append((request, context)) or completed(None))
    req = WebRequest(b'POST', {}, b'{"jsonrpc":"2.0","method":"collection.get"}', b'/api/v1')
    assert b'204 No Content' in server.handlerWrapper(req).value
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'apiKey', 'secret')
    assert b'401 Unauthorized' in server.handlerWrapper(req)
    req.headers[b'authorization'] = b'Bearer secret'
    assert b'204 No Content' in server.handlerWrapper(req).value
    req.headers[b'origin'] = b'https://unknown.example'
    assert b'403 Forbidden' in server.handlerWrapper(req)
    assert len(calls) == 2
    before = list(util.DEFAULT_CONFIG['webCorsOriginList'])
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'webCorsOrigin', 'https://old.example')
    server.allowOrigin(req)
    assert before == util.DEFAULT_CONFIG['webCorsOriginList']
    client = WebClient(None, None)
    partial = b'POST /api/v1 HTTP/1.1\r\nContent-Length: 5\r\n\r\n{}'
    assert client.parseRequest(partial) == (None, 0)
    parsed, _ = client.parseRequest(partial + b'   ')
    assert parsed.path == b'/api/v1'


def test_conversion_preserves_cards_and_native_undo(native):
    owner, service = native
    created = call(service, 'notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': 'convert', 'Back': 'answer'})
    target = call(service, 'noteTypes.create', name='Target', fields=[{'name': 'Q'}, {'name': 'A'}],
                  templates=[{'name': 'Card', 'questionHtml': '{{Q}}', 'answerHtml': '{{A}}'}])
    plan = call(service, 'notes.planConversion', source={'name': 'Basic'}, target={'id': target['id']})
    result = call(service, 'notes.convert', ids=[created['noteId']], target={'id': target['id']},
                  fields=[{'target': 'Q', 'source': 'Front'}, {'target': 'A', 'source': 'Back'}],
                  templates=[{'target': 'Card', 'source': 'Card 1'}], planToken=plan['token'])
    assert result['changedCount'] == 1
    converted = call(service, 'notes.get', id=created['noteId'])
    assert converted['fields'] == {'Q': 'convert', 'A': 'answer'}
    assert converted['cardIds'] == created['cardIds']
    call(service, 'collection.undo')
    assert call(service, 'notes.get', id=created['noteId'])['noteType']['name'] == 'Basic'


def test_answer_many_and_filtered_home_history(native):
    owner, service = native
    notes = [call(service, 'notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': str(index)}) for index in range(2)]
    predictions = [call(service, 'scheduling.predict', cardId=note['cardIds'][0]) for note in notes]
    outcome = call(service, 'scheduling.answerMany', answers=[{'cardId': prediction['cardId'], 'stateToken': prediction['stateToken'], 'rating': 'good'} for prediction in predictions])
    assert all('result' in item for item in outcome['items']), outcome
    call(service, 'scheduling.reset', cardIds=[note['cardIds'][0] for note in notes])
    call(service, 'scheduling.setDueDate', cardIds=[notes[0]['cardIds'][0]], days='2')
    call(service, 'scheduling.getDue', cardId=notes[0]['cardIds'][0])


def test_legacy_preset_changes_use_native_updates(native):
    owner, service = native
    legacy = Legacy(owner, service)
    config = legacy.call('getDeckConfig', {'deck': 'Default'})
    config['new']['bury'] = True
    config['new']['order'] = 0
    config['rev']['perDay'] = 99
    assert legacy.call('saveDeckConfig', {'config': config})
    updated = legacy.call('getDeckConfig', {'deck': 'Default'})
    assert updated['new']['bury'] is True
    assert updated['new']['order'] == 0
    assert updated['rev']['perDay'] == 99
    updated['unsupported'] = 'new value'
    assert legacy.call('saveDeckConfig', {'config': updated}) is False


def test_packages_native_export_import(native, tmp_path):
    owner, service = native
    call(service, 'notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': 'package'})
    path = str(tmp_path / 'test.apkg')
    assert call(service, 'packages.export', deck={'name': 'Default'}, path=path)['path'] == path
    assert call(service, 'packages.import', path=path) == {'completed': True}


@pytest.fixture
def admitted(native, monkeypatch):
    import aqt
    import concurrent.futures
    from plugin import util
    owner, service = native
    work_queue, timers, notifications = [], [], []
    mw = SimpleNamespace(col=service.col, pm=SimpleNamespace(name='test'), reviewer=None, state='deckBrowser',
                         _background_op_count=0, addonManager=SimpleNamespace(getConfig=lambda module: util.DEFAULT_CONFIG))
    def increase(): mw._background_op_count += 1
    def decrease(): mw._background_op_count -= 1
    mw._increase_background_ops, mw._decrease_background_ops = increase, decrease
    def background(task, on_done, **kwargs):
        def run():
            future = concurrent.futures.Future()
            try: future.set_result(task())
            except Exception as error: future.set_exception(error)
            on_done(future)
        work_queue.append(run)
    mw.taskman = SimpleNamespace(run_in_background=background)
    mw.reset = lambda: notifications.append('reset')
    monkeypatch.setattr(aqt, 'mw', mw)
    monkeypatch.setattr(aqt.operations, 'on_op_finished', lambda mw, change, initiator: notifications.append(change))
    owner.runtime.schedule = timers.append
    owner.runtime.operations.schedule = timers.append
    owner.runtime.session
    def drain():
        while timers or work_queue:
            (work_queue if work_queue else timers).pop(0)()
    return owner, service, drain, work_queue, notifications


def test_http_multi_observes_completed_native_writes(admitted):
    owner, service, drain, work, notifications = admitted
    pending = owner.handler_async({'action': 'multi', 'version': 6, 'params': {'actions': [
        {'action': 'createDeck', 'version': 6, 'params': {'deck': 'Barrier'}},
        {'action': 'deckNames', 'version': 6}]}})
    assert not pending.done
    assert len(work) == 1
    drain()
    assert pending.done
    first, second = pending.value['result']
    assert first['error'] is None
    assert 'Barrier' in second['result']
    assert notifications


def test_execute_operation_waits_and_continues_after_errors(admitted):
    owner, service, drain, work, notifications = admitted
    request = {'jsonrpc': '2.0', 'id': 'test', 'method': 'api.execute', 'params': {'commands': [
        {'method': 'decks.create', 'params': {'name': 'Sequence'}},
        {'method': 'notes.get', 'params': {'id': '999'}},
        {'method': 'decks.list'}]}}
    response = owner.runtime.dispatcher.request(request)
    operation_id = response.value['result']['operationId']
    assert owner.runtime.operations.get(operation_id)['state'] == 'queued'
    drain()
    operation = owner.runtime.operations.get(operation_id)
    assert operation['state'] == 'succeeded'
    items = operation['result']['items']
    assert items[1]['error']['data']['type'] == 'notFound'
    assert any(deck['name'] == 'Sequence' for deck in items[2]['result'])
    assert notifications


def test_media_rollback_removes_repeated_renamed_installs(native):
    from plugin.media import MediaTransaction
    _, service = native
    directory = Path(service.col.media.dir())
    (directory / 'shared.txt').write_bytes(b'old')
    transaction = MediaTransaction(service)
    first = transaction.install('shared.txt', b'new', collision='rename')
    # A batch can attach the same renamed content more than once.
    assert transaction.install('shared.txt', b'new', collision='rename') == first != 'shared.txt'
    assert transaction.rollback() == []
    assert sorted(path.name for path in directory.iterdir()) == ['shared.txt']
    assert (directory / 'shared.txt').read_bytes() == b'old'


def test_recoverable_media_journal_and_owned_rollback(native):
    from plugin.media import MediaTransaction
    owner, service = native
    service.store_bytes('owned.txt', b'original')
    service.store_bytes('unrelated.txt', b'keep')
    transaction = MediaTransaction(service)
    transaction.install('owned.txt', b'new')
    transaction.install('new.txt', b'new file')
    MediaTransaction._active.discard(transaction.path)
    MediaTransaction.recover(service)
    directory = Path(service.col.media.dir())
    assert (directory / 'owned.txt').read_bytes() == b'original'
    assert not (directory / 'new.txt').exists()
    assert (directory / 'unrelated.txt').read_bytes() == b'keep'
    conflicted = MediaTransaction(service)
    conflicted.install('owned.txt', b'new')
    (directory / 'owned.txt').write_bytes(b'external change')
    MediaTransaction._active.discard(conflicted.path)
    failures = MediaTransaction.recover(service)
    assert [failure['filename'] for failure in failures] == ['owned.txt']
    assert (directory / 'owned.txt').read_bytes() == b'external change'
    # The journal and its backup are kept aside, but never block later work.
    assert not conflicted.path.exists()
    assert conflicted.path.with_suffix('.unresolved').is_dir()
    assert MediaTransaction.recover(service) == []
    assert service.store_bytes('owned.txt', b'later', collision='replace')['filename'] == 'owned.txt'
    assert (directory / 'owned.txt').read_bytes() == b'later'


def test_media_recovery_runs_once_per_session(admitted, monkeypatch):
    from plugin.media import MediaTransaction
    owner, service, drain, work, notifications = admitted
    recovered = []
    monkeypatch.setattr(MediaTransaction, 'recover', lambda *args: recovered.append(args) or [])
    for _ in range(2):
        future = owner.runtime.background(lambda service: 'done')
        drain()
        assert future.value == 'done'
    assert len(recovered) == 1
    owner.runtime.invalidate_session()
    owner.runtime.background(lambda service: None)
    drain()
    assert len(recovered) == 2


def test_text_replacement_is_one_native_undo(native):
    owner, service = native
    for name in ['First', 'Second']:
        call(service, 'noteTypes.create', name=name, fields=[{'name': 'F'}],
             templates=[{'name': 'Card', 'questionHtml': '{{F}} old', 'answerHtml': '{{F}}'}])
    call(service, 'noteTypes.replaceText', find='old', replace='new', noteTypes=[{'name': 'First'}, {'name': 'Second'}])
    call(service, 'collection.undo')
    for name in ['First', 'Second']:
        assert 'old' in call(service, 'noteTypes.get', noteType={'name': name})['templates'][0]['questionHtml']


def test_cloze_native_validation_and_conversion(native):
    owner, service = native
    assert call(service, 'notes.validate', note={'noteType': {'name': 'Cloze'}, 'deck': {'name': 'Default'},
                                               'fields': {'Text': '{{c1::one}} and {{c2::two}}'}})['valid']
    created = call(service, 'notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'}, fields={'Front': 'convert to cloze'})
    plan = call(service, 'notes.planConversion', source={'name': 'Basic'}, target={'name': 'Cloze'})
    call(service, 'notes.convert', ids=[created['noteId']], target={'name': 'Cloze'},
         fields=plan['fields'], templates=plan['templates'], planToken=plan['token'])
    assert call(service, 'notes.get', id=created['noteId'])['noteType']['name'] == 'Cloze'


def test_v1_replacement_restores_original_after_native_failure(admitted, monkeypatch):
    import base64
    owner, service, drain, work, notifications = admitted
    service.store_bytes('replace.txt', b'original')
    original_write = service.col.media.write_data
    def fail_incoming(filename, data):
        if data == b'incoming':
            raise OSError('simulated native write failure after trash')
        return original_write(filename, data)
    monkeypatch.setattr(service.col.media, 'write_data', fail_incoming)
    response = owner.runtime.dispatcher.request({'jsonrpc': '2.0', 'id': 1, 'method': 'media.store',
        'params': {'filename': 'replace.txt', 'source': {'data': base64.b64encode(b'incoming').decode()}, 'collision': 'replace'}})
    drain()
    operation = owner.runtime.operations.get(response.value['result']['operationId'])
    assert operation['state'] == 'failed'
    assert operation['error']['data']['type'] == 'ioError'
    assert operation['error']['data']['details']['rollbackFailures'] == []
    assert (Path(service.col.media.dir()) / 'replace.txt').read_bytes() == b'original'
    assert not list((Path(service.col.media.dir()).parent / '.anki-connect-media-journal').iterdir())


def test_nested_multi_preflights_exit_limits_and_shapes(admitted):
    owner, service, drain, work, notifications = admitted
    nested = lambda actions: {'action': 'multi', 'version': 6, 'params': {'actions': actions}}
    exit_request = {'action': 'guiExitAnki', 'version': 6}
    create = {'action': 'createDeck', 'version': 6, 'params': {'deck': 'Must not exist'}}
    too_deep = {'action': 'version'}
    for _ in range(18):
        too_deep = nested([too_deep])
    for actions in ([create, nested([exit_request]), {'action': 'version'}],
                    [create, too_deep], [create, nested([None])],
                    [create, {'action': 'multi', 'params': {'actions': {}}}]):
        response = owner.handler_async(nested(actions))
        assert response.done and response.value['error']
        assert not work and not owner.runtime.exit_requested
    assert service.col.decks.id_for_name('Must not exist') is None
    response = owner.handler_async(nested([{'action': 'version'}, nested([exit_request])]))
    drain()
    assert response.value['error'] is None
    assert owner.runtime.exit_requested


def test_new_per_day_minimum_round_trip(native):
    owner, service = native
    preset = call(service, 'deckPresets.update', preset={'id': '1'}, settings={'newPerDayMinimum': 7})
    assert preset['settings']['newPerDayMinimum'] == 7
    legacy = Legacy(owner, service)
    config = legacy.call('getDeckConfig', {'deck': 'Default'})
    assert config['newPerDayMinimum'] == 7
    config['newPerDayMinimum'] = 11
    assert legacy.call('saveDeckConfig', {'config': config})
    assert call(service, 'deckPresets.get', preset={'id': '1'})['settings']['newPerDayMinimum'] == 11


def test_template_usage_respects_native_token_rules(native):
    owner, service = native
    call(service, 'noteTypes.create', name='Usage', fields=[{'name': 'F'}, {'name': 'G'}],
         templates=[{'name': 'Normal', 'questionHtml': '<!-- {{G}} -->{{#G}}{{text:F}}{{/G}}',
                     'answerHtml': '{{=<% %>=}}<%^F%><%G%><%/F%><!-- <%F%> -->'}])
    assert call(service, 'noteTypes.getTemplateUsage', noteType={'name': 'Usage'}) == [
        {'templateName': 'Normal', 'questionFields': ['G', 'F'], 'answerFields': ['F', 'G']}]


def test_discovery_and_dispatch_agree_on_missing_native_capability(admitted, monkeypatch):
    owner, service, drain, work, notifications = admitted
    monkeypatch.setattr(service.col, 'export_anki_package', None)
    methods = {item['name']: item for item in owner.runtime.describe()['methods']}
    assert not methods['packages.export']['available']
    assert 'export_anki_package' in methods['packages.export']['reason']
    with pytest.raises(ApiError, match='export_anki_package') as error:
        owner.runtime.invoke('packages.export', {})
    assert error.value.kind == 'unsupportedCapability'
    assert not work


def test_unload_hook_invalidates_same_collection_identity(admitted):
    from aqt import gui_hooks
    from plugin.edit import history
    owner, service, drain, work, notifications = admitted
    runtime = owner.runtime
    runtime.register_hooks()
    previous = runtime.session
    runtime.tokens['old'] = None
    runtime.cursors['old'] = None
    history.note_ids.append(123)
    try:
        gui_hooks.collection_will_temporarily_close(service.col)
        assert runtime.session != previous
        assert not runtime.tokens and not runtime.cursors and not history.note_ids
    finally:
        gui_hooks.profile_will_close.remove(runtime.invalidate_session)
        gui_hooks.collection_will_temporarily_close.remove(runtime.invalidate_session)


def test_execute_cancel_preserves_completed_outcomes(admitted):
    owner, service, drain, work, notifications = admitted
    runtime = owner.runtime
    handle = runtime.invoke('api.execute', {'commands': [
        {'method': 'decks.create', 'params': {'name': 'Committed prefix'}},
        {'method': 'decks.create', 'params': {'name': 'Cancelled suffix'}}]}).value
    runtime.operations.schedule.__self__.pop(0)()
    work.pop(0)()
    runtime.operations.cancel(handle['operationId'])
    drain()
    record = runtime.operations.get(handle['operationId'])
    assert record['state'] == 'cancelled'
    assert record['error']['data']['details']['items'][0]['result']['name'] == 'Committed prefix'
    assert service.col.decks.id_for_name('Cancelled suffix') is None


def test_bundled_contract_and_adapters_match_source():
    import json
    from plugin.contract import LEGACY_TARGETS
    from plugin.gui import Gui
    from plugin.runtime import GUI_METHODS
    root = Path(__file__).resolve().parents[1]
    assert SCHEMA == json.loads((root / 'api-v1.schema.json').read_text(encoding='utf-8'))
    assert set(LEGACY_TARGETS) == set(AnkiConnect().legacy_actions())
    for targets in LEGACY_TARGETS.values():
        assert all(target in SCHEMA['x-methods'] for target in targets)
    specials = {'api.describe', 'api.execute', 'access.requestPermission', 'operations.get', 'operations.cancel', 'media.store'}
    for name in SCHEMA['x-methods'].keys() - specials:
        assert callable(getattr(Gui if name in GUI_METHODS else Services, name.replace('.', '_'), None)), name


def test_queued_gui_operation_rechecks_collection_work(admitted, monkeypatch):
    import aqt
    owner, service, drain, work, notifications = admitted
    invoked = []
    monkeypatch.setattr(owner.runtime.gui, 'execute', lambda *args, **kwargs: invoked.append(args))
    handle = owner.runtime.invoke('editors.openAdd', {}).value
    aqt.mw._background_op_count = 1
    drain()
    record = owner.runtime.operations.get(handle['operationId'])
    assert record['state'] == 'failed'
    assert record['error']['data']['type'] == 'busy'
    assert not invoked


def test_stale_queued_work_does_not_recover_media(admitted, monkeypatch):
    from plugin.media import MediaTransaction
    owner, service, drain, work, notifications = admitted
    recovered = []
    monkeypatch.setattr(MediaTransaction, 'recover', lambda *args: recovered.append(args))
    future = owner.runtime.background(lambda service: pytest.fail('stale work executed'))
    owner.runtime.invalidate_session()
    drain()
    assert future.error.kind == 'staleSession'
    assert not recovered


def test_operation_rejects_invalid_terminal_result():
    tasks = []
    operations = Operations(tasks.append)
    handle = operations.submit('media.store', None, lambda key: completed({'filename': 123}))
    tasks.pop(0)()
    record = operations.get(handle['operationId'])
    assert record['state'] == 'failed'
    assert record['error']['data']['type'] == 'internalError'
    assert 'result' not in record


def test_missing_addon_configuration_uses_shipped_defaults(admitted, monkeypatch):
    import aqt
    from plugin import util
    monkeypatch.setattr(aqt.mw.addonManager, 'getConfig', lambda module: None)
    assert util.setting('webBindAddress') == util.DEFAULT_CONFIG['webBindAddress']
    assert util.setting('apiKey') is None
    monkeypatch.setattr(aqt.mw.addonManager, 'getConfig', lambda module: {'webBindPort': 9876})
    assert util.setting('webBindPort') == 9876
    assert util.setting('webBacklog') == util.DEFAULT_CONFIG['webBacklog']


def test_legacy_browser_reply_waits_for_gui_initialization(admitted, monkeypatch):
    from plugin.protocol import Deferred
    owner, service, drain, work, notifications = admitted
    browser_ready = Deferred()
    monkeypatch.setattr(owner.runtime.gui, 'execute', lambda *args, **kwargs: browser_ready)
    reply = owner.handler_async({'action': 'guiBrowse', 'version': 6, 'params': {'query': ''}})
    assert not reply.done
    browser_ready.resolve({})
    assert reply.value == {'result': [], 'error': None}


def test_note_type_delete_unused_reports_items_and_removes_type(native):
    owner, service = native
    model = call(service, 'noteTypes.create', name='Disposable', fields=[{'name': 'Front'}],
                 templates=[{'name': 'Card', 'questionHtml': '{{Front}}', 'answerHtml': '{{Front}}'}])
    note = call(service, 'notes.create', noteType={'id': model['id']}, deck={'name': 'Default'}, fields={'Front': 'x'})
    in_use = call(service, 'noteTypes.deleteUnused', noteTypes=[{'id': model['id']}])
    assert in_use['items'][0]['error']['data']['type'] == 'conflict'
    assert service.col.models.get(int(model['id'])) is not None
    call(service, 'notes.delete', ids=[note['noteId']])
    deleted = call(service, 'noteTypes.deleteUnused', noteTypes=[{'name': 'Disposable'}])
    assert deleted == {'items': [{'index': 0, 'result': {'changed': True}}]}
    assert service.col.models.get(int(model['id'])) is None

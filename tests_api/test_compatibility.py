"""Compatibility workflows against real Anki collections, not mocked services."""
import base64
import hashlib
import inspect
from pathlib import Path
import time

import pytest

from plugin.legacy import Legacy
from plugin.protocol import ApiError
from tests_api.test_runtime import admitted, call, native


def old(native, action, **params):
    owner, service = native
    arguments = inspect.signature(getattr(owner, action)).bind(**params)
    arguments.apply_defaults()
    return Legacy(owner, service).call(action, dict(arguments.arguments))


def note_input(front, **extra):
    return {'noteType': {'name': 'Basic'}, 'deck': {'name': 'Default'},
            'fields': {'Front': front, 'Back': 'answer'}, **extra}


def legacy_note(front):
    return {'modelName': 'Basic', 'deckName': 'Default', 'fields': {'Front': front, 'Back': 'answer'}}


def test_v1_bulk_reads_validation_and_atomic_creation(native):
    owner, service = native
    inputs = [note_input('first'), note_input('second')]
    checks = call(service, 'notes.validateMany', notes=inputs)['items']
    assert all(item['result']['valid'] for item in checks)
    created = call(service, 'notes.createMany', notes=inputs, atomic=True)['items']
    ids = [item['result']['noteId'] for item in created]
    cards = [item['result']['cardIds'][0] for item in created]
    records = call(service, 'notes.getMany', ids=[ids[1], '999', ids[0]])['items']
    assert records[0]['result']['fields']['Front'] == 'second'
    assert records[1]['error']['data']['type'] == 'notFound'
    assert records[2]['result']['id'] == ids[0]
    records = call(service, 'cards.getMany', ids=[cards[0], '999'])['items']
    assert records[0]['result']['noteId'] == ids[0]
    assert records[1]['error']['data']['type'] == 'notFound'
    assert not call(service, 'notes.validateMany', notes=[inputs[0]])['items'][0]['result']['valid']
    partial = call(service, 'notes.createMany', notes=[note_input('third'), inputs[0]])['items']
    assert 'result' in partial[0] and partial[1]['error']['data']['type'] == 'validationFailed'
    assert service.col.note_count() == 3
    assert set(call(service, 'cards.search', query='note:Basic')['ids']) == {
        str(id) for id in service.col.find_cards('note:Basic')}


@pytest.mark.parametrize('rating,ease', [('again', 1), ('hard', 2), ('good', 3), ('easy', 4)])
def test_scheduler_rating_matches_native_review_history(native, rating, ease):
    owner, service = native
    created = call(service, 'notes.create', **note_input(rating))
    card = created['cardIds'][0]
    prediction = call(service, 'scheduling.predict', cardId=card)
    answered = call(service, 'scheduling.answer', cardId=card, rating=rating, stateToken=prediction['stateToken'])
    assert service.col.db.scalar('select ease from revlog where id=?', int(answered['reviewId'])) == ease
    assert call(service, 'reviews.list', cardIds=[card])['items'][0]['rating'] == rating


def test_v1_empty_notes_and_native_tag_registry(native):
    owner, service = native
    created = call(service, 'notes.create', **note_input('will become empty', tags=['keep']))
    call(service, 'notes.update', id=created['noteId'], patch={'fields': {'Front': '', 'Back': ''}})
    for criterion in ('allFieldsEmpty', 'allQuestionsEmpty'):
        assert call(service, 'notes.findEmpty', criterion=criterion)['ids'] == [created['noteId']]
    assert call(service, 'notes.findEmpty', criterion='noCards')['ids'] == []
    assert 'keep' in call(service, 'tags.list')
    call(service, 'notes.delete', ids=[created['noteId']])
    call(service, 'tags.deleteUnused')
    assert 'keep' not in call(service, 'tags.list')


def test_v1_move_suspend_and_advanced_card_metadata(native):
    owner, service = native
    created = call(service, 'notes.create', **note_input('move'))
    card = created['cardIds'][0]
    deck = call(service, 'decks.create', name='Destination')
    moved = call(service, 'cards.move', ids=[card, card, '999'], deck={'id': deck['id']})['items']
    assert moved[0]['result']['changed'] and moved[1]['result']['changed']
    assert moved[2]['error']['data']['type'] == 'notFound'
    assert service.col.get_card(int(card)).did == int(deck['id'])
    assert call(service, 'cards.setSuspended', ids=[card], suspended=True)['items'][0]['result']['changed']
    assert call(service, 'scheduling.get', cardId=card)['queue'] == 'suspended'
    assert not call(service, 'cards.setSuspended', ids=[card], suspended=True)['items'][0]['result']['changed']
    call(service, 'cards.setSuspended', ids=[card], suspended=False)
    assert call(service, 'scheduling.get', cardId=card)['queue'] == 'new'
    patch = {'sm2EasePermille': 2300, 'repetitions': 9, 'lapses': 2, 'customData': '{"x":1}'}
    updated = call(service, 'advanced.cards.update', cardId=card, patch=patch)
    assert updated['scheduling']['sm2EasePermille'] == 2300
    stored = service.col.get_card(int(card))
    assert (stored.reps, stored.lapses, stored.custom_data) == (9, 2, '{"x":1}')
    with pytest.raises(ApiError, match='JSON object'):
        call(service, 'advanced.cards.update', cardId=card, patch={'customData': '[]'})
    with pytest.raises(ApiError, match='Coupled scheduler'):
        call(service, 'advanced.cards.update', cardId=card, patch={'remainingSteps': 1})


def test_v1_deck_rename_and_preset_listing(native):
    owner, service = native
    deck = call(service, 'decks.create', name='Original')
    renamed = call(service, 'decks.update', deck={'id': deck['id']}, name='Renamed')
    assert renamed['id'] == deck['id'] and renamed['name'] == 'Renamed'
    assert call(service, 'decks.get', deck={'name': 'Renamed'}) == renamed
    assert service.col.decks.by_name('Original') is None
    with pytest.raises(ApiError, match='name exists'):
        call(service, 'decks.update', deck={'id': deck['id']}, name='Default')
    presets = call(service, 'deckPresets.list')
    assert any(preset['id'] == '1' for preset in presets)


@pytest.mark.parametrize('public,value,native_field,native_name', [
    ('newInsertOrder', 'random', 'new_card_insert_order', 'NEW_CARD_INSERT_ORDER_RANDOM'),
    ('newGatherOrder', 'deck', 'new_card_gather_priority', 'NEW_CARD_GATHER_PRIORITY_DECK'),
    ('newGatherOrder', 'deckThenRandomNotes', 'new_card_gather_priority', 'NEW_CARD_GATHER_PRIORITY_DECK_THEN_RANDOM_NOTES'),
    ('newGatherOrder', 'lowestPosition', 'new_card_gather_priority', 'NEW_CARD_GATHER_PRIORITY_LOWEST_POSITION'),
    ('newGatherOrder', 'highestPosition', 'new_card_gather_priority', 'NEW_CARD_GATHER_PRIORITY_HIGHEST_POSITION'),
    ('newGatherOrder', 'randomNotes', 'new_card_gather_priority', 'NEW_CARD_GATHER_PRIORITY_RANDOM_NOTES'),
    ('newGatherOrder', 'randomCards', 'new_card_gather_priority', 'NEW_CARD_GATHER_PRIORITY_RANDOM_CARDS'),
    ('newSortOrder', 'templateThenRandom', 'new_card_sort_order', 'NEW_CARD_SORT_ORDER_TEMPLATE_THEN_RANDOM'),
    ('newMix', 'afterReviews', 'new_mix', 'REVIEW_MIX_AFTER_REVIEWS'),
    ('dayLearningMix', 'beforeReviews', 'interday_learning_mix', 'REVIEW_MIX_BEFORE_REVIEWS'),
    ('reviewOrder', 'day', 'review_order', 'REVIEW_CARD_ORDER_DAY'),
    ('reviewOrder', 'dayThenDeck', 'review_order', 'REVIEW_CARD_ORDER_DAY_THEN_DECK'),
    ('reviewOrder', 'deckThenDay', 'review_order', 'REVIEW_CARD_ORDER_DECK_THEN_DAY'),
    ('reviewOrder', 'intervalAscending', 'review_order', 'REVIEW_CARD_ORDER_INTERVALS_ASCENDING'),
    ('reviewOrder', 'intervalDescending', 'review_order', 'REVIEW_CARD_ORDER_INTERVALS_DESCENDING'),
    ('reviewOrder', 'easeAscending', 'review_order', 'REVIEW_CARD_ORDER_EASE_ASCENDING'),
    ('reviewOrder', 'easeDescending', 'review_order', 'REVIEW_CARD_ORDER_EASE_DESCENDING'),
    ('reviewOrder', 'retrievabilityAscending', 'review_order', 'REVIEW_CARD_ORDER_RETRIEVABILITY_ASCENDING'),
    ('reviewOrder', 'retrievabilityDescending', 'review_order', 'REVIEW_CARD_ORDER_RETRIEVABILITY_DESCENDING'),
    ('reviewOrder', 'relativeOverdueness', 'review_order', 'REVIEW_CARD_ORDER_RELATIVE_OVERDUENESS'),
    ('reviewOrder', 'random', 'review_order', 'REVIEW_CARD_ORDER_RANDOM'),
    ('reviewOrder', 'added', 'review_order', 'REVIEW_CARD_ORDER_ADDED'),
    ('reviewOrder', 'reverseAdded', 'review_order', 'REVIEW_CARD_ORDER_REVERSE_ADDED'),
    ('leechAction', 'suspend', 'leech_action', 'LEECH_ACTION_SUSPEND'),
    ('questionAction', 'showReminder', 'question_action', 'QUESTION_ACTION_SHOW_REMINDER'),
    ('answerAction', 'hard', 'answer_action', 'ANSWER_ACTION_ANSWER_HARD'),
])
def test_preset_enums_match_native_semantics(native, public, value, native_field, native_name):
    owner, service = native
    updated = call(service, 'deckPresets.update', preset={'id': '1'}, settings={public: value})
    assert updated['settings'][public] == value
    config = service.col._backend.get_deck_config(1).config
    descriptor = config.DESCRIPTOR.fields_by_name[native_field].enum_type
    assert getattr(config, native_field) == descriptor.values_by_name[native_name].number


def test_v1_note_type_metadata_and_rendering(native):
    owner, service = native
    model = call(service, 'noteTypes.create', name='Metadata', fields=[{'name': 'Q'}, {'name': 'A'}],
                 templates=[{'name': 'Card', 'questionHtml': '{{Q}}', 'answerHtml': '{{A}}'}])
    updated = call(service, 'noteTypes.update', noteType={'id': model['id']},
                   patch={'name': 'Renamed Type', 'css': '.card { color: red; }', 'sortField': 'A',
                          'latexHeader': 'header', 'latexFooter': 'footer', 'latexSvg': True})
    assert (updated['name'], updated['sortField'], updated['latexSvg']) == ('Renamed Type', 'A', True)
    native_model = service.col.models.get(int(model['id']))
    assert native_model['sortf'] == 1 and native_model['latexPre'] == 'header'
    assert native_model['latexPost'] == 'footer'
    created = call(service, 'notes.create', noteType={'id': model['id']}, deck={'name': 'Default'},
                   fields={'Q': 'question', 'A': 'response'})
    rendered = call(service, 'cards.render', id=created['cardIds'][0])
    assert 'question' in rendered['questionHtml'] and 'response' in rendered['answerHtml']
    assert rendered['css'] == updated['css']


def test_v1_integrity_stats_and_latest_review(native):
    owner, service = native
    assert call(service, 'collection.get')['session'] == 'test-session'
    assert call(service, 'reviews.getLatestId')['id'] is None
    created = call(service, 'notes.create', **note_input('stats'))
    card = created['cardIds'][0]
    prediction = call(service, 'scheduling.predict', cardId=card)
    answer = call(service, 'scheduling.answer', cardId=card, rating='good', stateToken=prediction['stateToken'])
    assert call(service, 'reviews.getLatestId', cardIds=[card])['id'] == answer['reviewId']
    selected = service.col.decks.selected()
    report = call(service, 'statistics.getHtml', deck={'name': 'Default'})
    assert report['format'] == 'legacyReport' and '<' in report['html']
    assert service.col.decks.selected() == selected
    assert call(service, 'statistics.getToday')['count'] >= 1
    assert call(service, 'statistics.getSummary')['noteCount'] == 1
    assert call(service, 'collection.checkIntegrity')['problems'] == []
    assert service.col.note_count() == 1


@pytest.mark.parametrize('filename,expected', [
    ('simple.txt', 'simple.txt'),
    ('cafe\u0301.txt', 'caf\u00e9.txt'),
    ('a[]<>:"?*^|\r\nb.txt', 'ab.txt'),
    ('space and_\U0001f600.txt', 'space and_\U0001f600.txt'),
])
@pytest.mark.parametrize('api', ['v1', 'legacy'])
def test_media_filename_native_round_trip(admitted, api, filename, expected):
    owner, service, drain, work, notifications = admitted
    data = base64.b64encode(b'filename compatibility').decode()
    assert service.media_filename(filename) == expected
    if api == 'v1':
        response = owner.runtime.dispatcher.request({
            'jsonrpc': '2.0', 'id': 1, 'method': 'media.store',
            'params': {'filename': filename, 'source': {'data': data}}})
        drain()
        record = owner.runtime.operations.get(response.value['result']['operationId'])
        assert record['state'] == 'succeeded'
        actual = record['result']['filename']
    else:
        actual = old((owner, service), 'storeMediaFile', filename=filename, data=data)
    assert actual == expected
    path = Path(service.col.media.dir()) / actual
    assert path.read_bytes() == b'filename compatibility'
    if api == 'v1':
        assert call(service, 'media.get', filename=filename)['data'] == data
        assert call(service, 'media.delete', filename=filename) == {'changed': True}
    else:
        assert old((owner, service), 'retrieveMediaFile', filename=filename) == data
        old((owner, service), 'deleteMediaFile', filename=filename)
    assert not path.exists()


@pytest.mark.parametrize('filename', ['.', '..', '../escape.txt', 'dir/file.txt',
                                     'dir\\file.txt', 'escape\0.txt', '/absolute.txt'])
def test_media_filename_rejects_paths(native, filename):
    owner, service = native
    with pytest.raises(ApiError) as caught:
        service.store_bytes(filename, b'outside the media directory')
    assert caught.value.kind == 'invalidParams'


def test_v1_media_storage_completion_and_native_files(admitted, tmp_path):
    owner, service, drain, work, notifications = admitted
    def request(method, params):
        response = owner.runtime.dispatcher.request({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
        drain()
        return response.value
    source = tmp_path / 'incoming'
    source.write_bytes(b'first')
    response = request('media.store', {'filename': 'compatibility.txt', 'source': {'path': str(source)}})
    handle = response['result']['operationId']
    record = request('operations.get', {'operationId': handle})['result']
    assert record['state'] == 'succeeded' and record['result']['filename'] == 'compatibility.txt'
    assert call(service, 'media.get', filename='compatibility.txt')['data'] == base64.b64encode(b'first').decode()
    assert call(service, 'media.list', pattern='compatibility*') == ['compatibility.txt']
    assert Path(call(service, 'media.getDirectory')['path']) == Path(service.col.media.dir()).resolve()
    response = request('media.store', {'filename': 'compatibility.txt', 'collision': 'replace',
                                     'source': {'data': base64.b64encode(b'replaced').decode()}})
    record = request('operations.get', {'operationId': response['result']['operationId']})['result']
    assert record['state'] == 'succeeded'
    assert (Path(service.col.media.dir()) / 'compatibility.txt').read_bytes() == b'replaced'
    response = request('media.store', {'filename': 'compatibility.txt', 'collision': 'error', 'source': {'path': str(source)}})
    record = request('operations.get', {'operationId': response['result']['operationId']})['result']
    assert record['state'] == 'failed' and record['error']['data']['type'] == 'conflict'
    assert call(service, 'media.delete', filename='compatibility.txt') == {'changed': True}
    assert call(service, 'media.list', pattern='compatibility*') == []
    with pytest.raises(ApiError):
        call(service, 'media.get', filename='compatibility.txt')


def test_discovery_permissions_and_operation_endpoints(admitted, monkeypatch):
    from plugin import util
    owner, service, drain, work, notifications = admitted
    monkeypatch.setattr(util, 'setting', lambda key: util.DEFAULT_CONFIG[key])
    description = owner.runtime.dispatcher.request({'jsonrpc': '2.0', 'id': 1, 'method': 'api.describe'}).value['result']
    assert description['ankiVersion'] and all(method['available'] for method in description['methods'])
    permission = owner.runtime.dispatcher.request({'jsonrpc': '2.0', 'id': 1, 'method': 'access.requestPermission'},
                                                  {'origin': 'http://localhost', 'allowed': True}).value['result']
    assert permission == {'permission': 'granted', 'requireApiKey': False}
    assert old((owner, service), 'requestPermission', origin='http://localhost', allowed=True)['permission'] == 'granted'
    response = owner.runtime.dispatcher.request({'jsonrpc': '2.0', 'id': 1, 'method': 'api.execute',
                                                'params': {'commands': [{'method': 'decks.create', 'params': {'name': 'Cancelled'}}]}})
    id = response.value['result']['operationId']
    cancelled = owner.runtime.dispatcher.request({'jsonrpc': '2.0', 'id': 2, 'method': 'operations.cancel',
                                                 'params': {'operationId': id}}).value['result']
    assert cancelled == {'requested': True}
    drain()
    status = owner.runtime.dispatcher.request({'jsonrpc': '2.0', 'id': 3, 'method': 'operations.get',
                                              'params': {'operationId': id}}).value['result']
    assert status['state'] == 'cancelled' and service.col.decks.by_name('Cancelled') is None


def test_legacy_note_validation_updates_tags_and_deletion(native):
    owner, service = native
    sources = [legacy_note('first'), legacy_note('second')]
    assert old(native, 'canAddNotes', notes=sources) == [True, True]
    assert old(native, 'canAddNotesWithErrorDetail', notes=sources) == [{'canAdd': True}, {'canAdd': True}]
    assert old(native, 'canAddNoteWithErrorDetail', note=sources[0]) == {'canAdd': True}
    ids = old(native, 'addNotes', notes=sources)
    assert len(ids) == 2 and all(isinstance(id, int) for id in ids)
    assert not old(native, 'canAddNoteWithErrorDetail', note=sources[0])['canAdd']
    old(native, 'updateNoteFields', note={'id': ids[0], 'fields': {'Back': 'changed'}})
    old(native, 'updateNote', note={'id': ids[1], 'fields': {'Back': 'changed too'}, 'tags': ['initial']})
    old(native, 'updateNoteTags', note=ids[0], tags=['start'])
    assert service.col.get_note(ids[0])['Back'] == 'changed'
    assert service.col.get_note(ids[1])['Back'] == 'changed too'
    old(native, 'addTags', notes=ids, tags='added extra')
    assert set(old(native, 'getNoteTags', note=ids[0])) == {'start', 'added', 'extra'}
    old(native, 'removeTags', notes=ids, tags='extra')
    old(native, 'replaceTags', notes=[ids[0]], tag_to_replace='added', replace_with_tag='renamed')
    old(native, 'replaceTagsInAllNotes', tag_to_replace='renamed', replace_with_tag='final')
    assert set(old(native, 'getNoteTags', note=ids[0])) == {'start', 'final'}
    assert 'final' in old(native, 'getTags')
    assert old(native, 'findNotes', query='tag:final') == [ids[0]]
    assert old(native, 'findNotes') == []
    assert old(native, 'notesModTime', notes=ids)[0]['mod'] == service.col.get_note(ids[0]).mod
    old(native, 'deleteNotes', notes=[*ids, 999])
    old(native, 'clearUnusedTags')
    assert service.col.note_count() == 0 and old(native, 'getTags') == []
    with pytest.raises(ApiError, match='explicit criteria'):
        old(native, 'removeEmptyNotes')


def test_legacy_decks_configs_and_card_projections(native):
    owner, service = native
    id = old(native, 'addNote', note=legacy_note('decks'))
    card = service.col.get_note(id).card_ids()[0]
    did = old(native, 'createDeck', deck='Destination')
    assert old(native, 'deckNameFromId', deckId=did) == 'Destination'
    assert old(native, 'deckNamesAndIds')['Destination'] == did
    old(native, 'changeDeck', cards=[card], deck='Destination')
    assert old(native, 'getDecks', cards=[card]) == {'Destination': [card]}
    assert old(native, 'getDeckStats', decks=['Destination'])[str(did)]['total_in_deck'] == 1
    assert old(native, 'cardsToNotes', cards=[card, card, 999]) == [id]
    assert old(native, 'cardsModTime', cards=[card])[0]['mod'] == service.col.get_card(card).mod
    config = old(native, 'cloneDeckConfigId', name='Clone')
    assert old(native, 'setDeckConfigId', decks=['Destination'], configId=config)
    assert old(native, 'getDeckConfig', deck='Destination')['id'] == config
    assert old(native, 'removeDeckConfigId', configId=config)
    assert old(native, 'getDeckConfig', deck='Destination')['id'] == 1
    old(native, 'deleteDecks', decks=['Destination'], cardsToo=True)
    assert service.col.decks.by_name('Destination') is None and service.col.note_count() == 0


def test_legacy_scheduling_metadata_and_reviews(native):
    owner, service = native
    id = old(native, 'addNote', note=legacy_note('schedule'))
    card = service.col.get_note(id).card_ids()[0]
    assert old(native, 'areDue', cards=[card]) == [True]
    assert old(native, 'getIntervals', cards=[card]) == [0]
    assert old(native, 'suspend', cards=[card])
    assert old(native, 'suspended', card=card)
    assert old(native, 'areSuspended', cards=[card, 999]) == [True, None]
    assert old(native, 'unsuspend', cards=[card])
    assert not old(native, 'suspended', card=card)
    assert old(native, 'setEaseFactors', cards=[card], easeFactors=[2400]) == [True]
    assert old(native, 'getEaseFactors', cards=[card]) == [2400]
    assert old(native, 'setSpecificValueOfCard', card=card, keys=['flags'], newValues=[4]) == [True]
    assert service.col.get_card(card).flags & 7 == 4
    assert old(native, 'answerCards', answers=[{'cardId': card, 'ease': 3}, {'cardId': 999, 'ease': 3}]) == [True, False]
    assert old(native, 'getReviewsOfCards', cards=[card])[str(card)]
    rows = old(native, 'cardReviews', deck='Default', startID=0)
    assert len(rows) == 1 and rows[0][1] == card
    assert old(native, 'getLatestReviewID', deck='Default') == rows[0][0]
    assert len(old(native, 'getIntervals', cards=[card], complete=True)[0]) == 1
    old(native, 'setDueDate', cards=[card], days='0')
    assert service.col.get_card(card).queue == 2
    lapses = service.col.get_card(card).lapses
    old(native, 'relearnCards', cards=[card])
    assert service.col.get_card(card).lapses == lapses + 1
    assert service.col.db.scalar('select ease from revlog where cid=? order by id desc limit 1', card) == 1
    old(native, 'forgetCards', cards=[card])
    assert service.col.get_card(card).type == 0
    historical_id = int(time.time() * 1000) - 86400000
    old(native, 'insertReviews', reviews=[[historical_id, card, 0, 3, 4, -60, 2500, 500, 1]])
    stored = old(native, 'getReviewsOfCards', cards=[card])[str(card)]
    assert next(row for row in stored if row['id'] == historical_id)['lastIvl'] == -60
    assert service.col.db.scalar('select usn from revlog where id=?', historical_id) == -1
    assert old(native, 'getNumCardsReviewedToday') >= 1
    assert old(native, 'getNumCardsReviewedByDay')
    assert '<' in old(native, 'getCollectionStatsHTML')


def test_legacy_media_and_packages(native, tmp_path):
    owner, service = native
    data = base64.b64encode(b'original').decode()
    assert old(native, 'storeMediaFile', filename='legacy.txt', data=data) == 'legacy.txt'
    assert old(native, 'retrieveMediaFile', filename='legacy.txt') == data
    assert old(native, 'getMediaFilesNames', pattern='legacy*') == ['legacy.txt']
    assert Path(old(native, 'getMediaDirPath')) == Path(service.col.media.dir()).resolve()
    assert old(native, 'storeMediaFile', filename='skip.txt', data=data,
               skipHash=hashlib.md5(b'original').hexdigest()) is None
    assert not (Path(service.col.media.dir()) / 'skip.txt').exists()
    old(native, 'deleteMediaFile', filename='legacy.txt')
    old(native, 'deleteMediaFile', filename='legacy.txt')
    assert old(native, 'retrieveMediaFile', filename='legacy.txt') is False
    id = old(native, 'addNote', note=legacy_note('package round trip'))
    path = str(tmp_path / 'legacy.apkg')
    assert old(native, 'exportPackage', deck='Default', path=path)
    assert Path(path).stat().st_size > 0
    old(native, 'deleteNotes', notes=[id])
    assert old(native, 'importPackage', path=path)
    assert service.col.note_count() == 1
    assert service.col.get_note(service.col.find_notes('')[0])['Front'] == 'package round trip'


def test_legacy_note_type_structure_and_conversion(native):
    owner, service = native
    model = old(native, 'createModel', modelName='Legacy Type', inOrderFields=['Front', 'Back'],
                cardTemplates=[{'Name': 'One', 'Front': '{{Front}}', 'Back': '{{Back}}'}], css='old css')
    assert 'Legacy Type' in old(native, 'modelNames')
    assert old(native, 'modelNamesAndIds')['Legacy Type'] == model['id']
    assert old(native, 'modelNameFromId', modelId=model['id']) == 'Legacy Type'
    assert old(native, 'findModelsById', modelIds=[model['id']])[0]['name'] == 'Legacy Type'
    assert old(native, 'findModelsByName', modelNames=['Legacy Type'])[0]['id'] == model['id']
    assert old(native, 'modelFieldNames', modelName='Legacy Type') == ['Front', 'Back']
    old(native, 'modelFieldAdd', modelName='Legacy Type', fieldName='Extra', index=1)
    old(native, 'modelFieldSetFont', modelName='Legacy Type', fieldName='Extra', font='Arial')
    old(native, 'modelFieldSetFontSize', modelName='Legacy Type', fieldName='Extra', fontSize=24)
    assert old(native, 'modelFieldSetDescription', modelName='Legacy Type', fieldName='Extra', description='description')
    assert old(native, 'modelFieldFonts', modelName='Legacy Type')['Extra'] == {'font': 'Arial', 'size': 24}
    assert old(native, 'modelFieldDescriptions', modelName='Legacy Type')[1] == 'description'
    old(native, 'modelFieldRename', modelName='Legacy Type', oldFieldName='Extra', newFieldName='Renamed')
    old(native, 'modelFieldReposition', modelName='Legacy Type', fieldName='Renamed', index=2)
    assert old(native, 'modelFieldNames', modelName='Legacy Type') == ['Front', 'Back', 'Renamed']
    old(native, 'modelFieldRemove', modelName='Legacy Type', fieldName='Renamed')
    old(native, 'modelTemplateAdd', modelName='Legacy Type', template={'Name': 'Two', 'Front': '{{Back}}', 'Back': '{{Front}}'})
    old(native, 'modelTemplateRename', modelName='Legacy Type', oldTemplateName='Two', newTemplateName='Renamed')
    old(native, 'modelTemplateReposition', modelName='Legacy Type', templateName='Renamed', index=0)
    assert list(old(native, 'modelTemplates', modelName='Legacy Type')) == ['Renamed', 'One']
    old(native, 'modelTemplateRemove', modelName='Legacy Type', templateName='Renamed')
    old(native, 'updateModelTemplates', model={'name': 'Legacy Type', 'templates': {'One': {'Front': '{{Front}} changed'}}})
    assert 'changed' in old(native, 'modelTemplates', modelName='Legacy Type')['One']['Front']
    old(native, 'updateModelStyling', model={'name': 'Legacy Type', 'css': 'new css'})
    assert old(native, 'modelStyling', modelName='Legacy Type') == {'css': 'new css'}
    assert old(native, 'modelFieldsOnTemplates', modelName='Legacy Type') == {'One': [['Front'], ['Back']]}
    assert old(native, 'findAndReplaceInModels', modelName='Legacy Type', findText='changed', replaceText='replaced') == 1
    assert 'replaced' in old(native, 'modelTemplates', modelName='Legacy Type')['One']['Front']
    id = old(native, 'addNote', note=legacy_note('conversion'))
    old(native, 'updateNoteModel', note={'id': id, 'modelName': 'Legacy Type', 'fields': {'Front': 'converted', 'Back': 'answer'}})
    converted = service.col.get_note(id)
    assert converted.mid == model['id'] and converted['Front'] == 'converted'


def test_sync_native_interfaces_without_credentials(native):
    """Offline dependency checks for collection.sync and legacy sync, not a completed sync."""
    from anki.sync import SyncAuth, SyncOutput

    owner, service = native
    col = service.col
    # Bind the exact call shapes used by Gui.collection_sync without making
    # network requests or closing the collection for a full upload/download.
    auth = SyncAuth()
    for include_media in (False, True):
        inspect.signature(col.sync_collection).bind(auth, include_media)
    for upload in (False, True):
        for server_usn in (None, 0):
            inspect.signature(col.full_upload_or_download).bind(
                auth=auth, server_usn=server_usn, upload=upload)
    inspect.signature(col.close_for_full_sync).bind()
    inspect.signature(col._load_scheduler).bind()
    output = SyncOutput()
    for field in ('host_number', 'new_endpoint', 'server_media_usn', 'required'):
        assert field in output.DESCRIPTOR.fields_by_name
    for state in ('NO_CHANGES', 'NORMAL_SYNC', 'FULL_UPLOAD', 'FULL_DOWNLOAD'):
        assert isinstance(getattr(output, state), int)
    # These calls enter the real Rust backend and are harmless while idle.
    assert not col.media_sync_status().active
    assert col.abort_sync() is None
    assert col.abort_media_sync() is None
    assert not col.media_sync_status().active
    col._load_scheduler()
    assert col.sched is not None


@pytest.mark.parametrize('method', ['notes.search', 'cards.search'])
@pytest.mark.parametrize('direction', ['ascending', 'descending'])
def test_search_uses_native_browser_sort_columns(native, method, direction):
    owner, service = native
    created = [call(service, 'notes.create', **note_input(front))
               for front in ('zebra', 'apple', 'mango')]
    key = 'noteId' if method == 'notes.search' else 'cardIds'
    ids = [note[key] if key == 'noteId' else note[key][0] for note in created]
    expected = [ids[1], ids[2], ids[0]]
    if direction == 'descending':
        expected.reverse()
    sort = {'column': 'noteFld', 'direction': direction}
    page = call(service, method, query='note:Basic', sort=sort, limit=2)
    assert page['ids'] == expected[:2]
    assert call(service, method, query='note:Basic', sort=sort, limit=2,
                cursor=page['nextCursor'])['ids'] == expected[2:]
    with pytest.raises(ApiError, match='sort column'):
        call(service, method, query='', sort={'column': 'missingColumn', 'direction': direction})

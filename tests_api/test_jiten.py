"""Jiten's legacy import requests, upstream 7eac4d44ef10.

Exercises native responses and controlled HTTP admission; Jiten's frontend and
server-side vocabulary import are not launched.
"""
import base64

import pytest

from plugin.services import Services
from plugin.legacy import Legacy
from plugin import compat, util
from tests_api.test_gsm import exchange
from tests_api.test_runtime import admitted, call, native


JITEN_FIELDS = ['cardId', 'due', 'queue', 'type', 'interval', 'factor', 'reps',
                'lapses', 'mod', 'flags', 'fields', 'modelName', 'deckName']


def invoke(owner, drain, action, **params):
    reply = exchange(owner, drain, {'action': action, 'version': 6, 'params': params})
    assert reply['error'] is None, reply
    return reply['result']


@pytest.mark.parametrize('fields', [None, [], ['cardId', 'fields'],
                                  ['question'], ['answer', 'css', 'nextReviews'],
                                  ['unknown', 'cardId', 'cardId']])
def test_cards_info_field_projection_preserves_legacy_values(admitted, fields):
    owner, service, drain, _, _ = admitted
    note = call(service, 'notes.create', noteType={'name': 'Basic'}, deck={'name': 'Default'},
                fields={'Front': '猫', 'Back': 'ねこ'})
    card = int(call(service, 'notes.get', id=note['noteId'])['cardIds'][0])
    full = invoke(owner, drain, 'cardsInfo', cards=[card, 999, card])
    filtered = invoke(owner, drain, 'cardsInfo', cards=[card, 999, card], fields=fields)
    expected = full if fields is None else [{key: value for key, value in record.items() if key in fields} for record in full]
    assert filtered == expected
    # GUI forwarders construct the adapter before it has a collection service.
    assert Legacy(owner).record('cards', card, fields) == expected[0]
    assert invoke(owner, drain, 'cardsInfo', cards=[], fields=fields) == []


@pytest.mark.parametrize('fields', [1, {}, [1], [None]])
def test_cards_info_rejects_invalid_field_filters(admitted, fields):
    owner, _, drain, _, _ = admitted
    reply = exchange(owner, drain, {'action': 'cardsInfo', 'version': 6,
                                  'params': {'cards': [], 'fields': fields}})
    assert reply == {'result': None, 'error': 'fields must be a list of card record field names.'}


def test_jiten_large_filtered_import_and_review_pages(admitted, monkeypatch):
    owner, service, drain, _, _ = admitted
    model = service.col.models.by_name('Basic')
    notes = []
    for index in range(2000):
        note = service.col.new_note(model)
        note['Front'], note['Back'] = '猫' + str(index), 'ねこ'
        notes.append(compat.AddNoteRequest(note=note, deck_id=1))
    service.add_notes(notes)
    cards = invoke(owner, drain, 'findCards', query='deck:"Default"')
    assert len(cards) == 2000
    before = service.col.db.all('select * from cards order by id')
    tokens = dict(owner.runtime.tokens)
    execute = Services.execute
    def selective(self, method, params):
        assert method not in ('cards.render', 'scheduling.predict'), method
        return execute(self, method, params)
    monkeypatch.setattr(Services, 'execute', selective)
    assert invoke(owner, drain, 'cardsInfo', cards=[], fields=JITEN_FIELDS) == []
    records = invoke(owner, drain, 'cardsInfo', cards=cards, fields=JITEN_FIELDS)
    assert [record['cardId'] for record in records] == cards
    for index, record in enumerate(records):
        assert set(record) == set(JITEN_FIELDS)
        assert record['fields']['Front'] == {'value': '猫' + str(index), 'order': 0}
        assert record['modelName'] == 'Basic' and record['deckName'] == 'Default'
    assert owner.runtime.tokens == tokens
    assert service.col.db.all('select * from cards order by id') == before

    # Over 100 default-sized review pages used to exhaust the cursor table too.
    rows = [(100000 + index * 6 + review, card, -1, 3, 10, 5, 2500, 1000, 1)
            for index, card in enumerate(cards) for review in range(6)]
    service.col.db.executemany('insert into revlog values (?,?,?,?,?,?,?,?,?)', rows)
    assert invoke(owner, drain, 'getReviewsOfCards', cards=[]) == {}
    for ids in [cards, [str(card) for card in cards]]:
        reviews = invoke(owner, drain, 'getReviewsOfCards', cards=ids)
        assert set(reviews) == {str(card) for card in cards}
        for index, card in enumerate(cards):
            assert reviews[str(card)] == [dict(zip(
                ['id', 'usn', 'ease', 'ivl', 'lastIvl', 'factor', 'time', 'type'],
                [100000 + index * 6 + review, -1, 3, 10, 5, 2500, 1000, 1])) for review in range(6)]
        assert not owner.runtime.cursors


def test_jiten_versioned_media_batch(admitted):
    owner, service, drain, _, _ = admitted
    data = base64.b64encode(b'Jiten audio').decode()
    filename = invoke(owner, drain, 'storeMediaFile', filename='jiten.mp3', data=data)
    replies = invoke(owner, drain, 'multi', actions=[
        {'action': 'retrieveMediaFile', 'version': 6, 'params': {'filename': name}}
        for name in [filename, 'missing.mp3']])
    assert replies == [{'result': data, 'error': None}, {'result': False, 'error': None}]


@pytest.mark.parametrize('api_key', [None, 'jiten-key'])
def test_jiten_field_probe_with_browser_origin_and_key(admitted, monkeypatch, api_key):
    owner, _, drain, _, _ = admitted
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'webCorsOriginList', ['https://jiten.moe'])
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'apiKey', api_key)
    headers = {b'origin': b'https://jiten.moe'}
    payload = {'action': 'cardsInfo', 'version': 6, 'params': {'cards': [], 'fields': JITEN_FIELDS}}
    if api_key:
        payload['key'] = api_key
    assert exchange(owner, drain, payload, headers) == {'result': [], 'error': None}

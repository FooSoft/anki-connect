"""GameSentenceMiner legacy contracts, upstream c3499a03093e.

Reviewed GameSentenceMiner/anki.py, anki_setup.py, util/cron/anki_card_sync.py,
anki_word_sync.py and GSM_Overlay/hachidori/{anki,anki-index,anki-mining}.js.
Desktop POSTs omit Origin/key; the overlay uses version-6 nested envelopes and
keys on every child. The desktop media helper passes full paths as filenames.
GSM's OCR/recording/database and overlay UI are not launched here.
"""
import base64
import json
import os
from pathlib import Path

import pytest

from plugin import util
from plugin.web import WebRequest
from tests_api.test_cors import response_parts
from tests_api.test_runtime import admitted, call, native, native_media_name


def exchange(owner, drain, payload, headers=None):
    pending = owner.server.handlerWrapper(WebRequest(b'POST', headers or {
        b'content-type': b'application/json'}, json.dumps(payload).encode()))
    drain()
    status, _, body = response_parts(pending)
    assert status == b'HTTP/1.1 200 OK'
    reply = json.loads(body)
    assert set(reply) == {'result', 'error'}
    return reply


@pytest.mark.parametrize('filename,base', [
    ('/tmp/GSM/猫 AUDIO.MP3', '猫 AUDIO.MP3'),
    (r'C:\Users\user\AppData\GSM\猫 AUDIO.MP3',
     '猫 AUDIO.MP3' if os.name == 'nt' else 'CUsersuserAppDataGSM猫 AUDIO.MP3'),
])
def test_gsm_full_path_media_names_keep_native_legacy_normalization(admitted, filename, base):
    """storeMediaFile normalizes GSM's full path inside the media directory."""
    owner, service, drain, _, _ = admitted
    # Native Anki lowercases new media names from 26.5; earlier releases keep the case.
    expected = os.path.normcase(native_media_name(base))
    data = base64.b64encode(b'GSM captured audio').decode()
    reply = exchange(owner, drain, {'action': 'storeMediaFile', 'version': 6,
                                   'params': {'filename': filename, 'data': data}})
    # Native writes may retain requested case on Windows when reusing a file.
    assert reply['error'] is None and os.path.normcase(reply['result']) == expected
    assert (Path(service.col.media.dir()) / reply['result']).read_bytes() == b'GSM captured audio'
    repeated = exchange(owner, drain, {'action': 'storeMediaFile', 'version': 6,
        'params': {'filename': filename, 'data': data, 'deleteExisting': False}})
    assert repeated['error'] is None and os.path.normcase(repeated['result']) == expected
    assert (Path(service.col.media.dir()) / repeated['result']).read_bytes() == b'GSM captured audio'


def test_gsm_desktop_enrichment_polling_and_native_review_sync(admitted):
    """addNote/findNotes/notesInfo/findCards/cardsInfo/storeMediaFile/updateNoteFields/
    addTags/removeTags/getReviewsOfCards keep numeric IDs and nested field values.
    """
    owner, service, drain, _, _ = admitted
    def invoke(action, **params):
        reply = exchange(owner, drain, {'action': action, 'version': 6, 'params': params})
        assert reply['error'] is None, reply
        return reply['result']

    # A Yomitan-created note is detected and enriched by the desktop poller.
    id = invoke('addNote', note={'modelName': 'Basic', 'deckName': 'Default',
                               'fields': {'Front': '猫', 'Back': '猫がいる。'}, 'tags': ['overlay']})
    assert type(id) is int
    assert invoke('findNotes', query='added:1') == [id]
    assert invoke('findNotes', query='Front:_*') == [id]
    infos = invoke('notesInfo', notes=[id, 999])
    assert infos[0]['fields']['Front'] == {'value': '猫', 'order': 0}
    assert type(infos[0]['mod']) is int and infos[1] == {}
    cards = invoke('findCards', query='nid:' + str(id))
    assert infos[0]['cards'] == cards
    prediction = call(service, 'scheduling.predict', cardId=str(cards[0]))
    answer = call(service, 'scheduling.answer', cardId=str(cards[0]),
                  stateToken=prediction['stateToken'], rating='good', elapsedMs=1500)
    before = service.col.get_card(cards[0])._to_backend_card()
    audio = invoke('storeMediaFile', filename=r'C:\GSM\猫.MP3', data=base64.b64encode(b'voice').decode())
    image = invoke('storeMediaFile', filename='/tmp/GSM/猫.PNG', data=base64.b64encode(b'image').decode())
    fields = {'Back': '猫がいる。<br>[sound:' + audio + ']<img src="' + image + '">'}
    assert invoke('updateNoteFields', note={'id': id, 'fields': fields}) is None
    assert invoke('addTags', notes=[id], tags='Game::Test mined') is None
    assert invoke('removeTags', notes=[id], tags='overlay') is None
    saved = invoke('notesInfo', notes=[id])[0]
    assert saved['noteId'] == id and saved['fields']['Back']['value'] == fields['Back']
    assert set(saved['tags']) == {'Game::Test', 'mined'} and saved['cards'] == cards
    card_info = invoke('cardsInfo', cards=[*cards, 999])
    assert card_info[1] == {}
    for field in ['cardId', 'note', 'queue', 'type', 'due', 'interval', 'factor', 'reps', 'lapses']:
        assert type(card_info[0][field]) is int, field
    reviews = invoke('getReviewsOfCards', cards=[*cards, 999])
    assert reviews['999'] == []
    review = reviews[str(cards[0])][0]
    assert set(review) == {'id', 'usn', 'ease', 'ivl', 'lastIvl', 'factor', 'time', 'type'}
    assert review['id'] == int(answer['reviewId']) and review['ease'] == 3
    assert review['time'] == 1500 and all(type(value) is int for value in review.values())
    after = service.col.get_card(cards[0])._to_backend_card()
    for card in [before, after]:
        card.ClearField('mtime_secs')
        card.ClearField('usn')
    assert before == after


@pytest.mark.parametrize('api_key', [None, 'overlay-key'])
def test_gsm_overlay_discovery_and_index_keep_nested_envelopes(admitted, monkeypatch, api_key):
    """multi/deckNames/modelNames/modelFieldNames/modelNamesAndIds/findNotes/
    canAddNotesWithErrorDetail/notesInfo keep GSM's overlay discovery contracts.
    """
    owner, service, drain, _, _ = admitted
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'apiKey', api_key)
    headers = {b'origin': b'chrome-extension://gsm-overlay', b'content-type': b'application/json'}
    def request(action, **params):
        payload = {'action': action, 'version': 6, 'params': params}
        if api_key:
            payload['key'] = api_key
        return payload

    actions = [request('deckNames'), request('modelNames'), request('modelFieldNames', modelName='Basic')]
    reply = exchange(owner, drain, request('multi', actions=actions), headers)
    assert reply['error'] is None
    children = reply['result']
    assert len(children) == 3 and all(set(child) == {'result', 'error'} for child in children)
    assert all(child['error'] is None for child in children)
    assert 'Default' in children[0]['result'] and 'Basic' in children[1]['result']
    assert children[2]['result'] == ['Front', 'Back']
    actions[-1] = request('modelFieldNames', modelName='Missing')
    speculative = exchange(owner, drain, request('multi', actions=actions), headers)
    assert speculative['error'] is None
    assert speculative['result'][2] == {'result': None, 'error': 'model was not found: Missing'}
    models = exchange(owner, drain, request('modelNamesAndIds'), headers)['result']
    assert models['Basic'] == int(service.col.models.by_name('Basic')['id'])
    actions = [request('findNotes', query='mid:' + str(models['Basic'])),
               request('findNotes', query='mid:' + str(models['Basic']) + ' prop:ivl>=21')]
    assert exchange(owner, drain, request('multi', actions=actions), headers)['result'] == [
        {'result': [], 'error': None}, {'result': [], 'error': None}]
    note = {'modelName': 'Basic', 'deckName': 'Default', 'fields': {'Front': '猫', 'Back': ''}}
    assert exchange(owner, drain, request('canAddNotesWithErrorDetail', notes=[note]), headers)['result'] == [
        {'canAdd': True}]


def test_gsm_five_hundred_note_and_card_cache_batches_are_not_truncated(admitted):
    """addNotes/findNotes/notesInfo/cardsInfo retain GSM's 500-item cache batches."""
    owner, service, drain, _, _ = admitted
    def invoke(action, **params):
        reply = exchange(owner, drain, {'action': action, 'version': 6, 'params': params})
        assert reply['error'] is None, reply
        return reply['result']
    notes = [{'modelName': 'Basic', 'deckName': 'Default', 'fields': {'Front': str(index)}}
             for index in range(500)]
    ids = invoke('addNotes', notes=notes)
    assert len(ids) == 500 and len(set(ids)) == 500
    assert invoke('findNotes', query='Front:_*') == sorted(ids)
    infos = invoke('notesInfo', notes=ids)
    assert [info['noteId'] for info in infos] == ids
    assert [info['fields']['Front']['value'] for info in infos] == [str(index) for index in range(500)]
    cards = [info['cards'][0] for info in infos]
    assert [info['cardId'] for info in invoke('cardsInfo', cards=cards)] == cards
    assert service.col.note_count() == 500

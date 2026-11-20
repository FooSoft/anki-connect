"""asbplayer/asbplayer common/anki/anki.ts and common/src/fetcher.ts.

Version-6 POSTs have no Content-Type override, optional body key, and exact
result/error envelopes. Test browser origin admission/private-network preflight,
native mining, stored-media updates and the lookup/status projection contracts.
Controlled admission does not launch the asbplayer webapp or browser extensions.
"""
import base64
import json
from pathlib import Path

import pytest

from plugin import util
from plugin.web import WebRequest
from tests_api.test_cors import response_parts
from tests_api.test_runtime import admitted, native, native_media_name


@pytest.mark.parametrize('origin', [b'https://app.asbplayer.dev', b'chrome-extension://asbplayer'])
@pytest.mark.parametrize('api_key', [None, 'asb-key'])
def test_asbplayer_browser_fetch_mining_media_update_and_status(admitted, monkeypatch, origin, api_key):
    """version/deckNames/modelNames/modelFieldNames/createDeck/addNote/findNotes/
    notesInfo/findCards/cardsInfo/notesModTime/cardsModTime/areSuspended/
    storeMediaFile/updateNoteFields/addTags keep the version-6 mining contracts.
    """
    owner, service, drain, _, _ = admitted
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'apiKey', api_key)
    allowed = ['http://localhost', origin.decode()]
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'webCorsOriginList', allowed)
    headers = {b'origin': origin, b'content-type': b'text/plain;charset=UTF-8'}

    status, cors, body = response_parts(owner.server.handlerWrapper(WebRequest(b'OPTIONS', {
        b'origin': origin, b'access-control-request-method': b'POST',
        b'access-control-request-private-network': b'true',
    }, b'')))
    assert status == b'HTTP/1.1 200 OK' and body == b''
    assert cors[b'Access-Control-Allow-Origin'] == origin
    assert cors[b'Access-Control-Allow-Private-Network'] == b'true'

    def invoke(action, **params):
        request = {'action': action, 'version': 6}
        if params:
            request['params'] = params
        if api_key:
            request['key'] = api_key
        pending = owner.server.handlerWrapper(WebRequest(b'POST', headers, json.dumps(request).encode()))
        drain()
        status, cors, body = response_parts(pending)
        assert status == b'HTTP/1.1 200 OK' and cors[b'Access-Control-Allow-Origin'] == origin
        reply = json.loads(body)
        assert set(reply) == {'result', 'error'} and reply['error'] is None, reply
        return reply['result']

    assert invoke('version') == 6
    assert 'Default' in invoke('deckNames') and 'Basic' in invoke('modelNames')
    assert invoke('modelFieldNames', modelName='Basic') == ['Front', 'Back']
    assert type(invoke('createDeck', deck='asbplayer')) is int
    source = {'deckName': 'asbplayer', 'modelName': 'Basic', 'tags': ['asbplayer'],
              'options': {'allowDuplicate': True, 'duplicateScope': 'deck',
                          'duplicateScopeOptions': {'deckName': 'asbplayer', 'checkChildren': False}},
              'fields': {'Front': '猫がいる。', 'Back': '<span>cat</span>'}}
    note = invoke('addNote', note=source)
    assert type(note) is int and invoke('findNotes', query='added:1') == [note]
    assert invoke('findNotes', query='"Front:*猫*"') == [note]
    info = invoke('notesInfo', notes=[note])[0]
    assert info['noteId'] == note and info['fields']['Back']['value'] == '<span>cat</span>'
    cards = invoke('findCards', query='nid:' + str(note))
    assert info['cards'] == cards and all(type(id) is int for id in cards)
    assert invoke('cardsInfo', cards=cards)[0]['note'] == note
    assert invoke('areSuspended', cards=cards) == [False]
    assert invoke('notesModTime', notes=[note])[0]['noteId'] == note
    assert invoke('cardsModTime', cards=cards)[0]['cardId'] == cards[0]
    before = service.col.get_card(cards[0])._to_backend_card()
    # Update modes store media first and consume the normalized returned name.
    filename = invoke('storeMediaFile', filename='ASB Screenshot.PNG',
                      data=base64.b64encode(b'asb picture').decode())
    assert filename == native_media_name('ASB Screenshot.PNG')
    assert (Path(service.col.media.dir()) / filename).read_bytes() == b'asb picture'
    edited = {**source, 'id': note, 'fields': {'Back': '<span>updated</span><img src="' + filename + '">'}}
    assert invoke('updateNoteFields', note=edited) is None
    assert invoke('addTags', notes=[note], tags='mined 日本語') is None
    updated = invoke('notesInfo', notes=[note])[0]
    assert updated['fields']['Front']['value'] == source['fields']['Front']
    assert updated['fields']['Back']['value'] == edited['fields']['Back']
    assert set(updated['tags']) == {'asbplayer', 'mined', '日本語'}
    assert updated['cards'] == cards
    after = service.col.get_card(cards[0])._to_backend_card()
    for card in [before, after]:
        # 2.1.28-2.1.35 name the modification time mtime.
        for name in ('mtime_secs', 'mtime', 'usn'):
            if name in card.DESCRIPTOR.fields_by_name:
                card.ClearField(name)
    assert before == after and service.col.note_count() == 1


def test_asbplayer_unconfigured_origin_can_preflight_but_cannot_mutate(admitted, monkeypatch):
    owner, service, drain, _, _ = admitted
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'webCorsOriginList', ['http://localhost'])
    headers = {b'origin': b'https://app.asbplayer.dev'}
    status, cors, _ = response_parts(owner.server.handlerWrapper(WebRequest(b'OPTIONS', {
        **headers, b'access-control-request-method': b'POST',
    }, b'')))
    assert status == b'HTTP/1.1 200 OK'
    assert cors[b'Access-Control-Allow-Origin'] == headers[b'origin']
    request = {'action': 'createDeck', 'version': 6, 'params': {'deck': 'Not allowed'}}
    response = owner.server.handlerWrapper(WebRequest(b'POST', headers, json.dumps(request).encode()))
    drain()
    assert response_parts(response)[0] == b'HTTP/1.1 403 Forbidden'
    assert service.col.decks.id_for_name('Not allowed') is None

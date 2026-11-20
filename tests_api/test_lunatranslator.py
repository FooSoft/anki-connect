"""LunaTranslator's desktop mining flow, reviewed at upstream 210ae899e69b.

Sources: HIllya51/LunaTranslator src/LunaTranslator/myutils/ankiconnect.py,
gui/showword.py (AnkiWindow), and defaultconfig/static_data.json. The client
uses GET with a JSON body, no Origin or API key, version 6, exactly two reply
keys, and exact model-exists/duplicate error strings. Custom scripts may change
fields and add video. The Windows application itself is not launched here.
"""
import json
import os
import socket
from pathlib import Path

from plugin import util
from plugin.web import WebClient
from tests_api.test_runtime import admitted, native, native_media_name


FIELDS = ['word', 'rubytextHtml', 'example_sentence', 'audio_for_word',
          'audio_for_example_sentence', 'screenshot', 'remarks', 'dictionaryInfo',
          'dictionaryContent', 'luna_reserved_1', 'luna_reserved_2', 'luna_reserved_3',
          'user_custom_1', 'user_custom_2', 'user_custom_3']


def exercise_luna(invoke, directory):
    """Replay first add, model refresh, duplicate handling, and overwrite."""
    def success(action, **params):
        reply = invoke(action, **params)
        assert set(reply) == {'result', 'error'} and reply['error'] is None, reply
        return reply['result']

    deck, model = 'Luna::日本語', 'modelofluna'
    assert type(success('createDeck', deck=deck)) is int
    template = {'Name': 'LUNACARDTEMPLATE1', 'Front': '{{ word }}{{rubytextHtml}}',
                'Back': '{{FrontSide}}<hr>{{example_sentence}}{{dictionaryContent}}'}
    params = dict(modelName=model, inOrderFields=FIELDS, css='.card { color: black; }',
                  isCloze=False, cardTemplates=[template])
    assert success('createModel', **params)['name'] == model
    fields = {field: '' for field in FIELDS}
    fields.update(word='猫', rubytextHtml='<ruby>猫<rt>ねこ</rt></ruby>',
                  example_sentence='猫がいる。', remarks='A cat',
                  dictionaryContent='<div>cat &amp; feline</div>')
    media = {}
    for kind, field, suffix in [('audio', 'audio_for_word', '.mp3'),
                                ('audio', 'audio_for_example_sentence', '.wav'),
                                ('picture', 'screenshot', '.PNG'),
                                ('video', 'user_custom_1', '.mp4')]:
        path = directory / ('source ' + field + suffix)
        path.write_bytes(field.encode())
        media.setdefault(kind, []).append({'filename': field + suffix,
                                           'path': str(path), 'fields': [field]})
    note = {'deckName': deck, 'modelName': model, 'fields': fields,
            'options': {'allowDuplicate': True}, 'tags': ['luna', '日本語'], **media}
    first = success('addNote', note=note)
    assert type(first) is int
    # Every add attempts createModel; this exact message triggers refresh.
    assert invoke('createModel', **params) == {'result': None, 'error': 'Model name already exists'}
    assert success('updateModelStyling', model={'name': model, 'css': '.card { color: blue; }'}) is None
    assert success('updateModelTemplates', model={'name': model, 'templates': {
        'LUNACARDTEMPLATE1': {'Front': '{{word}} {{example_sentence}}',
                              'Back': '{{FrontSide}} {{remarks}}'}}}) is None
    blocked = {**note, 'options': {'allowDuplicate': False}}
    assert invoke('addNote', note=blocked) == {
        'result': None, 'error': 'cannot create note because it is a duplicate'}
    second = success('addNote', note=note)
    assert type(second) is int and second != first
    # Same-word overwrite deletes the last note before adding its replacement.
    assert success('deleteNotes', notes=[second]) is None
    replacement = success('addNote', note=note)
    return first, second, replacement, note


def socket_invoke(owner, drain, action, **params):
    """Real HTTP parsing and socket delivery with controlled Qt admission."""
    payload = json.dumps({'action': action, 'version': 6, 'params': params}).encode()
    transport, peer = socket.socketpair()
    transport.setblocking(False)
    peer.settimeout(2)
    client = WebClient(transport, owner.server.handlerWrapper)
    try:
        peer.sendall(b'GET / HTTP/1.1\r\nHost: 127.0.0.1:8765\r\nContent-Type: application/json\r\n'
                     + b'Content-Length: ' + str(len(payload)).encode() + b'\r\n\r\n' + payload)
        assert client.advance()
        drain()
        for _ in range(10):
            if not client.advance():
                break
        assert client.sock is None
        response = b''
        for chunk in iter(lambda: peer.recv(65536), b''):
            response += chunk
        head, body = response.split(b'\r\n\r\n', 1)
        assert head.startswith(b'HTTP/1.1 200 OK')
        assert b'Content-Length: ' + str(len(body)).encode() in head
        reply = json.loads(body)
        assert set(reply) == {'result', 'error'}
        return reply
    finally:
        client.close()
        peer.close()


def test_luna_desktop_get_mining_model_refresh_media_and_overwrite(admitted, tmp_path):
    """createDeck/createModel/addNote/updateModelStyling/updateModelTemplates/deleteNotes
    through GET; assert persisted IDs, native model, media and card effects.
    """
    owner, service, drain, _, notifications = admitted
    first, deleted, replacement, source = exercise_luna(
        lambda action, **params: socket_invoke(owner, drain, action, **params), tmp_path)
    assert service.col.find_notes('') == sorted([first, replacement])
    assert not service.col.find_notes('nid:' + str(deleted))
    model = service.col.models.by_name('modelofluna')
    assert [f['name'] for f in model['flds']] == FIELDS
    assert model['css'] == '.card { color: blue; }'
    assert model['tmpls'][0]['qfmt'] == '{{word}} {{example_sentence}}'
    assert model['tmpls'][0]['afmt'] == '{{FrontSide}} {{remarks}}'
    for id in [first, replacement]:
        note = service.col.get_note(id)
        assert note['word'] == '猫' and note['dictionaryContent'] == source['fields']['dictionaryContent']
        assert set(note.tags) == {'luna', '日本語'} and len(note.card_ids()) == 1
        assert service.col.decks.name(note.cards()[0].did) == source['deckName']
        for kind, entries in ((kind, source[kind]) for kind in ('audio', 'picture', 'video')):
            for entry in entries:
                field = entry['fields'][0]
                name = os.path.normcase(native_media_name(entry['filename']))
                # Native writes may retain requested case when reusing a file on Windows.
                assert name in os.path.normcase(note[field])
                assert (Path(service.col.media.dir()) / name).read_bytes() == field.encode()
    assert notifications and owner.window()._background_op_count == 0


def test_luna_client_without_key_retains_authentication_error(admitted, monkeypatch):
    owner, service, drain, _, _ = admitted
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'apiKey', 'secret')
    assert socket_invoke(owner, drain, 'createDeck', deck='Unauthorized') == {
        'result': None, 'error': 'valid api key must be provided'}
    assert service.col.decks.id_for_name('Unauthorized') is None

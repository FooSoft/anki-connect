"""Obsidian_to_Anki 3.6.0's complete legacy HTTP request flow.

Reviewed against ObsidianToAnki/Obsidian_to_Anki main.ts, src/anki.ts,
src/file.ts and src/files-manager.ts. Preserve the two sync phases' per-file
nesting, empty requests, version-6 envelopes and numeric IDs. Native disposable
collections/media use controlled Qt scheduling; Obsidian's parser/UI is not run.
"""
import base64
import json
from pathlib import Path

import pytest

from plugin import util
from plugin.web import WebRequest
from tests_api.test_runtime import admitted, call, native


def request(action, **params):
    return {'action': action, 'version': 6, 'params': params}


def multi(actions):
    return request('multi', actions=actions)


def file_requests(new=(), edits=(), deleted=(), deck='Obsidian', media=()):
    return {'new': list(new), 'edits': list(edits), 'deleted': list(deleted),
            'deck': deck, 'media': list(media)}


def phase_one(files):
    return multi([
        multi([multi([request('createDeck', deck=n['deckName']) for n in f['new']]) for f in files]),
        multi([multi([request('addNote', note=n) for n in f['new']]) for f in files]),
        multi([request('notesInfo', notes=[n['id'] for n in f['edits']]) for f in files]),
        request('getTags'),
        multi([multi([request('updateNoteFields', note={'id': n['id'], 'fields': n['fields']})
                      for n in f['edits']]) for f in files]),
        multi([request('deleteNotes', notes=f['deleted']) for f in files]),
        multi([request('storeMediaFile', **media) for f in files for media in f['media']]),
    ])


def phase_two(files, infos, tags):
    return multi([
        multi([request('changeDeck', cards=[c for n in info for c in n['cards']], deck=f['deck'])
               for f, info in zip(files, infos)]),
        multi([request('removeTags', notes=[n['id'] for n in f['edits']], tags=' '.join(tags))
               for f in files if f['edits']]),
        multi([multi([request('addTags', notes=[n['id']], tags=' '.join(n['tags']))
                      for n in f['edits']]) for f in files]),
    ])


def parse(reply):
    # src/anki.ts requires precisely these two fields at every nested level.
    assert set(reply) == {'result', 'error'}
    assert reply['error'] is None, reply
    return reply['result']


def exchange(admitted, payload):
    owner, _, drain, _, _ = admitted
    pending = owner.server.handlerWrapper(WebRequest(b'POST', {
        b'origin': b'app://obsidian.md',
    }, json.dumps(payload).encode()))
    drain()
    raw = pending.value if hasattr(pending, 'value') else pending
    headers, body = raw.split(b'\r\n\r\n', 1)
    assert headers.startswith(b'HTTP/1.1 200 OK\r\n')
    assert b'Access-Control-Allow-Origin: app://obsidian.md\r\n' in headers + b'\r\n'
    assert b'Content-Length: ' + str(len(body)).encode() in headers
    return json.loads(body)


@pytest.fixture
def obsidian(admitted, monkeypatch):
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'webCorsOriginList', ['http://localhost', 'app://obsidian.md'])
    return admitted


def source(front, deck='Obsidian'):
    return {'modelName': 'Basic', 'deckName': deck, 'fields': {'Front': front, 'Back': 'answer'},
            'tags': ['Obsidian_to_Anki', 'folder::tag']}


def test_obsidian_single_file_bulk_add(obsidian):
    """multi/createDeck/addNote/notesInfo/getTags/deleteNotes/changeDeck sync."""
    _, service, _, _, _ = obsidian
    count = 300
    files = [file_requests(new=[source('card ' + str(i)) for i in range(count)])]
    result = parse(exchange(obsidian, phase_one(files)))
    ids = [parse(reply) for reply in parse(parse(result[1])[0])]
    assert len(ids) == count and len(set(ids)) == count
    assert all(type(id) is int for id in ids)
    assert service.col.note_count() == count
    assert [service.col.get_note(id)['Front'] for id in ids] == ['card ' + str(i) for i in range(count)]
    assert set(parse(result[3])) == {'Obsidian_to_Anki', 'folder::tag'}
    infos = [parse(reply) for reply in parse(result[2])]
    assert infos == [[]]
    second = parse(exchange(obsidian, phase_two(files, infos, parse(result[3]))))
    assert [parse(reply) for reply in parse(second[0])] == [None]
    assert parse(second[1]) == []
    assert [parse(reply) for reply in parse(second[2])] == [[]]


def test_obsidian_vault_add_edit_move_tags_delete_and_media(obsidian, tmp_path):
    """modelNames/modelFieldNames then multi/createDeck/addNote/notesInfo/getTags,
    updateNoteFields/deleteNotes/storeMediaFile/changeDeck/removeTags/addTags.
    """
    _, service, _, _, notifications = obsidian
    models = parse(exchange(obsidian, request('modelNames')))
    fields = {name: parse(exchange(obsidian, request('modelFieldNames', modelName=name))) for name in models}
    assert fields['Basic'] == ['Front', 'Back'] and fields['Cloze'] == ['Text', 'Back Extra']
    media = tmp_path / 'vault with spaces' / 'picture.png'
    media.parent.mkdir()
    media.write_bytes(b'obsidian picture bytes')
    files = []
    for i in range(20):
        deck = 'Obsidian::Folder ' + str(i)
        notes = [source(f'file {i} card {j}', deck) for j in range(5)]
        notes.append({'modelName': 'Cloze', 'deckName': deck, 'tags': ['Obsidian_to_Anki'],
                      'fields': {'Text': f'file {i}: {{{{c1::one}}}} {{{{c2::two}}}}', 'Back Extra': 'context'}})
        files.append(file_requests(new=notes, deck=deck))
    files[0]['media'] = [{'filename': 'picture.png', 'path': str(media)},
                         {'filename': 'audio.mp3', 'data': base64.b64encode(b'obsidian audio').decode()}]
    result = parse(exchange(obsidian, phase_one(files)))
    ids_by_file = [[parse(reply) for reply in parse(file_reply)] for file_reply in parse(result[1])]
    assert service.col.note_count() == 120 and service.col.card_count() == 140
    assert [parse(reply) for reply in parse(result[6])] == ['picture.png', 'audio.mp3']
    assert (Path(service.col.media.dir()) / 'picture.png').read_bytes() == media.read_bytes()
    assert (Path(service.col.media.dir()) / 'audio.mp3').read_bytes() == b'obsidian audio'
    for f, ids in zip(files, ids_by_file):
        assert len(ids) == len(f['new']) and all(type(id) is int for id in ids)
        for note, id in zip(f['new'], ids):
            actual = service.col.get_note(id)
            assert dict(actual.items()) == note['fields']
            assert set(actual.tags) == set(note['tags'])
            assert all(service.col.decks.name(c.did) == f['deck'] for c in actual.cards())
    # Resync existing IDs must preserve scheduling and review history.
    reviewed = service.col.get_note(ids_by_file[0][0]).cards()[0]
    prediction = call(service, 'scheduling.predict', cardId=str(reviewed.id))
    call(service, 'scheduling.answer', cardId=str(reviewed.id), stateToken=prediction['stateToken'], rating='good')
    scheduling = service.col.get_card(reviewed.id)._to_backend_card()
    reviews = service.col.db.all('select * from revlog where cid=?', reviewed.id)
    doomed = parse(exchange(obsidian, request('addNote', note=source('delete me'))))
    unrelated = parse(exchange(obsidian, request('addNote', note=source('outside vault'))))
    files = [file_requests(edits=[{'id': id, 'fields': {
        **note['fields'], ('Back' if note['modelName'] == 'Basic' else 'Back Extra'):
        '<b>edited</b> <img src="picture.png"> [sound:audio.mp3] '
        '<a href="obsidian://open?vault=My%20Vault&amp;file=Note.md">source</a>'},
        'tags': ['Obsidian_to_Anki', 'updated::tag']} for id, note in zip(ids, f['new'])],
        deck='Obsidian::Moved') for f, ids in zip(files, ids_by_file)]
    files[0]['deleted'] = [doomed]
    result = parse(exchange(obsidian, phase_one(files)))
    infos = [parse(reply) for reply in parse(result[2])]
    for i, (f, info) in enumerate(zip(files, infos)):
        assert [n['noteId'] for n in info] == [n['id'] for n in f['edits']]
        for record in info:
            assert set(record) >= {'noteId', 'modelName', 'tags', 'fields', 'cards'}
            assert all(type(id) is int for id in record['cards'])
        assert [parse(reply) for reply in parse(parse(result[4])[i])] == [None] * 6
    second = parse(exchange(obsidian, phase_two(files, infos, parse(result[3]))))
    assert [parse(reply) for reply in parse(second[0])] == [None] * 20
    assert [parse(reply) for reply in parse(second[1])] == [None] * 20
    assert [[parse(reply) for reply in parse(f)] for f in parse(second[2])] == [[None] * 6] * 20
    for f in files:
        for edit in f['edits']:
            actual = service.col.get_note(edit['id'])
            assert dict(actual.items()) == edit['fields'] and set(actual.tags) == set(edit['tags'])
            assert all(service.col.decks.name(c.did) == f['deck'] for c in actual.cards())
    assert service.col.find_notes('nid:' + str(doomed)) == []
    assert set(service.col.get_note(unrelated).tags) == {'Obsidian_to_Anki', 'folder::tag'}
    assert service.col.note_count() == 121
    after = service.col.get_card(reviewed.id)._to_backend_card()
    assert after.deck_id != scheduling.deck_id
    for key in ('deck_id', 'mtime_secs', 'usn'):
        after.ClearField(key)
        scheduling.ClearField(key)
    assert after == scheduling
    assert service.col.db.all('select * from revlog where cid=?', reviewed.id) == reviews
    assert notifications


def test_obsidian_changed_empty_files(obsidian):
    """Empty multi/notesInfo/getTags/deleteNotes/changeDeck vault requests."""
    _, service, _, _, _ = obsidian
    files = [file_requests() for _ in range(40)]
    result = parse(exchange(obsidian, phase_one(files)))
    assert [parse(reply) for reply in parse(result[1])] == [[]] * 40
    infos = [parse(reply) for reply in parse(result[2])]
    assert infos == [[]] * 40
    second = parse(exchange(obsidian, phase_two(files, infos, parse(result[3]))))
    assert [parse(reply) for reply in parse(second[0])] == [None] * 40
    assert service.col.note_count() == 0


def test_obsidian_nested_item_failures_preserve_order_and_successes(obsidian, tmp_path):
    """addNote and storeMediaFile failures are item errors inside multi."""
    _, service, _, _, _ = obsidian
    notes = [source('duplicate'), source('duplicate'), source('after duplicate')]
    files = [file_requests(new=notes, media=[{'filename': 'missing.png', 'path': str(tmp_path / 'missing')},
        {'filename': 'good.png', 'data': base64.b64encode(b'good').decode()}])]
    result = parse(exchange(obsidian, phase_one(files)))
    adds = parse(parse(result[1])[0])
    assert type(parse(adds[0])) is int and type(parse(adds[2])) is int
    assert adds[1] == {'result': None, 'error': 'cannot create note because it is a duplicate'}
    assert [service.col.get_note(parse(adds[i]))['Front'] for i in (0, 2)] == ['duplicate', 'after duplicate']
    assert service.col.note_count() == 2
    media = parse(result[6])
    assert set(media[0]) == {'result', 'error'} and media[0]['result'] is None and media[0]['error']
    assert parse(media[1]) == 'good.png'
    assert (Path(service.col.media.dir()) / 'good.png').read_bytes() == b'good'


@pytest.mark.parametrize('version', [2, 6])
def test_obsidian_sync_empty_tags_cloze_report(obsidian, version):
    owner, service, _, _, _ = obsidian
    fields = {'oid': 'undefined', 'Text': '{{c1:: placeholder}}', 'Extra': '',
              'Breadcrumb': '<a href="obsidian://vault/Pharmacy/Introduction.md">Pharmacy</a>',
              'Config': '', 'Tobedefinedlater': '', 'Tobedefinedlater2': ''}
    parse(exchange(obsidian, request('createDeck', deck='Math')))
    parse(exchange(obsidian, request('createModel', modelName='ObsidianAnkiSyncModel',
        inOrderFields=list(fields), isCloze=True,
        cardTemplates=[{'Name': 'Cloze', 'Front': '{{cloze:Text}}', 'Back': '{{cloze:Text}}'}])))
    note = {'modelName': 'ObsidianAnkiSyncModel', 'deckName': 'Math', 'fields': fields,
            'tags': ['', 'Pharmacy', 'ObsidianAnkiSync', 'replaceblock'],
            'options': {'allowDuplicate': True}}
    payload = {**request('addNotes', notes=[note]), 'version': version}
    reply = exchange(obsidian, payload)
    ids = parse(reply) if version == 6 else reply
    assert len(ids) == 1 and type(ids[0]) is int
    actual = service.col.get_note(ids[0])
    assert dict(actual.items()) == fields
    assert set(actual.tags) == {'Pharmacy', 'ObsidianAnkiSync', 'replaceblock'}
    assert service.col.decks.name(actual.cards()[0].did) == 'Math'
    assert len(actual.card_ids()) == 1
    assert note['tags'][0] == ''

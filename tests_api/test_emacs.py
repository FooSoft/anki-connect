"""Emacs clients' legacy HTTP request shapes.

Reviewed against anki-editor/anki-editor 0.3.4 anki-editor.el (version 6, one
multi per push phase), louietan/anki-editor 0.3.3 and meedstrom/inline-anki
(version 5 with versionless multi items), Elilif/emacs-anki-helper (tag strings),
lujun9972/anki-connect.el (IDs passed through as given) and sdobrau/emacs-anki
(deck config round trip). Requests carry no Origin, as curl and url.el send them.
Editor and reviewer interplay runs in tools/smoke_gui.py browser and reviewer.
"""
import base64
import json

from plugin.web import WebRequest
from tests_api.test_runtime import admitted, native


def send(admitted, payload):
    owner, _, drain, _, _ = admitted
    pending = owner.server.handlerWrapper(WebRequest(b'POST', {
        b'content-type': b'application/x-www-form-urlencoded'}, json.dumps(payload).encode()))
    drain()
    raw = pending.value if hasattr(pending, 'value') else pending
    headers, body = raw.split(b'\r\n\r\n', 1)
    assert headers.startswith(b'HTTP/1.1 200 OK\r\n')
    return json.loads(body)


def v6(action, **params):
    return {'action': action, 'version': 6, **({'params': params} if params else {})}


def item(action, **params):
    return {'action': action, **({'params': params} if params else {})}


def ok(result):
    return {'result': result, 'error': None}


def org_note(id=0, deck='Org', front='Org question', back='Org answer', tags=()):
    # anki-editor-api--note: id 0 for new notes, JSON false, tags as a vector.
    return {'id': id, 'deckName': deck, 'modelName': 'Basic', 'fields': {'Front': front, 'Back': back},
            'options': {'allowDuplicate': False}, 'tags': list(tags)}


def test_anki_editor_push_create_update_move_media_and_delete(admitted):
    _, service, _, _, _ = admitted
    created = send(admitted, v6('multi', actions=[v6('createDeck', deck='Org'), v6('addNote', note=org_note(tags=['emacs']))]))
    deck_id, note_id = [reply['result'] for reply in created['result']]
    assert created == ok([ok(deck_id), ok(note_id)]) and type(note_id) is int
    duplicate = send(admitted, v6('multi', actions=[v6('addNote', note=org_note())]))
    assert duplicate == ok([{'result': None, 'error': 'cannot create note because it is a duplicate'}])
    info = send(admitted, v6('multi', actions=[v6('notesInfo', notes=[note_id])]))['result'][0]['result'][0]
    assert (info['noteId'], info['tags'], info['fields']['Back']) == (note_id, ['emacs'], {'value': 'Org answer', 'order': 1})
    name = 'picture-0a1b.png'
    assert send(admitted, v6('retrieveMediaFile', filename=name)) == ok(False)
    assert send(admitted, v6('storeMediaFile', filename=name, data=base64.b64encode(b'org picture').decode())) == ok(name)
    assert send(admitted, v6('retrieveMediaFile', filename=name)) == ok(base64.b64encode(b'org picture').decode())
    # Protected tags from notesInfo merge into the pushed tags; deckName is moved by changeDeck.
    update = org_note(note_id, 'Org::Moved', back='<img src="%s">' % name, tags=['emacs', 'edited'])
    assert send(admitted, v6('multi', actions=[v6('updateNote', note=update)])) == ok([ok(None)])
    note = service.col.get_note(note_id)
    assert (note['Back'], sorted(note.tags)) == ('<img src="%s">' % name, ['edited', 'emacs'])
    assert {service.col.decks.name(card.did) for card in note.cards()} == {'Org'}
    assert send(admitted, v6('multi', actions=[v6('changeDeck', deck='Org::Moved', cards=info['cards'])])) == ok([ok(None)])
    assert {service.col.decks.name(card.did) for card in service.col.get_note(note_id).cards()} == {'Org::Moved'}
    assert send(admitted, v6('findNotes', query='')) == ok([note_id])
    assert send(admitted, v6('deleteNotes', notes=[note_id])) == ok(None)
    # A stale ANKI_NOTE_ID: notesInfo yields an empty record and the update fails per item.
    stale = send(admitted, v6('multi', actions=[v6('notesInfo', notes=[note_id]), v6('updateNote', note=update)]))
    assert stale == ok([ok([{}]), {'result': None, 'error': 'Note was not found: %d' % note_id}])


def test_version_5_multi_items_without_version_reply_bare(admitted):
    _, service, _, _, _ = admitted
    note = {'id': -1, 'deckName': 'Org', 'modelName': 'Basic', 'fields': {'Front': 'Inline', 'Back': 'one'}, 'tags': ['old']}
    created = send(admitted, {'action': 'multi', 'version': 5, 'params': {'actions': [
        item('createDeck', deck='Org'), item('addNote', note=note), item('addNote', note=note)]}})
    deck_id, note_id, duplicate = created['result']
    assert created == ok([deck_id, note_id, {'result': None, 'error': 'cannot create note because it is a duplicate'}])
    assert type(deck_id) is int and type(note_id) is int
    # updateNoteFields ignores the tags inline-anki and anki-editor 0.3.3 also send.
    edit = {**note, 'id': note_id, 'fields': {'Front': 'Inline', 'Back': 'two'}, 'tags': ['ignored']}
    updated = send(admitted, {'action': 'multi', 'version': 5, 'params': {'actions': [
        item('updateNoteFields', note=edit), item('notesInfo', notes=[note_id]),
        item('addTags', notes=[note_id], tags='new other'), item('removeTags', notes=[note_id], tags='old')]}})
    assert updated['error'] is None and updated['result'][0] is None and updated['result'][2:] == [None, None]
    assert updated['result'][1][0]['tags'] == ['old'] and updated['result'][1][0]['fields']['Back']['value'] == 'two'
    assert sorted(service.col.get_note(note_id).tags) == ['new', 'other']
    cards = send(admitted, {'action': 'findCards', 'version': 5, 'params': {'query': 'nid:%d' % note_id}})['result']
    assert send(admitted, {'action': 'suspend', 'version': 5, 'params': {'cards': cards}}) == ok(True)
    assert all(card.queue == -1 for card in service.col.get_note(note_id).cards())
    assert send(admitted, {'action': 'unsuspend', 'version': 5, 'params': {'cards': cards}}) == ok(None)
    assert all(card.queue == 0 for card in service.col.get_note(note_id).cards())


def test_tag_strings_and_ids_passed_through(admitted):
    _, service, _, _, _ = admitted
    send(admitted, v6('createDeck', deck='Org'))
    note = {'deckName': 'Org', 'modelName': 'Basic', 'fields': {'Front': 'Helper', 'Back': ''}, 'tags': 'one two',
            'options': {'allowDuplicate': False, 'duplicateScope': 'deck'}}
    note_id = send(admitted, v6('addNote', note=note))['result']
    assert sorted(service.col.get_note(note_id).tags) == ['one', 'two']
    assert send(admitted, v6('updateNote', note={'id': str(note_id), 'fields': {'Front': 'Edited'}, 'tags': 'three'})) == ok(None)
    assert (service.col.get_note(note_id)['Front'], service.col.get_note(note_id).tags) == ('Edited', ['three'])
    assert send(admitted, v6('updateNote', note={'id': note_id, 'fields': {'Front': 'Again'}, 'tags': ''})) == ok(None)
    assert service.col.get_note(note_id).tags == []
    assert send(admitted, v6('notesInfo', notes=[str(note_id)]))['result'][0]['noteId'] == note_id


def test_deck_config_round_trip_without_mod_and_usn(admitted):
    _, service, _, _, _ = admitted
    config = send(admitted, {'action': 'getDeckConfig', 'version': 6, 'params': {'deck': 'Default'}})['result']
    muted = {key: value for key, value in config.items() if key not in ('mod', 'usn')}
    muted['autoplay'] = not config['autoplay']
    assert send(admitted, {'action': 'saveDeckConfig', 'version': 6, 'params': {'config': muted}}) == ok(True)
    assert send(admitted, v6('getDeckConfig', deck='Default'))['result']['autoplay'] is not config['autoplay']

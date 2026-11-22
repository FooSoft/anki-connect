"""Forgiving legacy inputs against real collections and controlled Qt admission."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugin import compat, util
from plugin.web import WebRequest
from tests_api.test_runtime import admitted, native
from tests_api.test_yomitan import exchange


def invoke(admitted, action, **params):
    owner, _, drain, _, _ = admitted
    request = {'action': action, 'version': '6', 'params': {**params, 'clientMetadata': 'ignored'}}
    before = copy.deepcopy(request)
    result = exchange(owner, drain, request)
    assert request == before
    assert result['error'] is None, result
    return result['result']


def note(front='question', **kwargs):
    return {'modelName': 'Basic', 'deckName': 'Default', 'fields': {'Front': front, 'Back': 'answer'}, **kwargs}


@pytest.mark.parametrize('version', [None, '2', '4', ' 6 ', 6, 6.0])
@pytest.mark.parametrize('params', [None, [], {'unused': True}])
def test_envelope_normalization_preserves_reply_versions(admitted, version, params):
    owner, service, drain, _, _ = admitted
    request = {'action': 'deckNames', 'version': version, 'params': params}
    before = copy.deepcopy(request)
    expected = ['Default'] if version in (None, '2', '4') else {'result': ['Default'], 'error': None}
    assert exchange(owner, drain, request) == expected
    assert request == before and service.col.note_count() == 0


def test_scalar_lists_ids_fields_tags_and_scheduling(admitted):
    owner, service, _, _, notifications = admitted
    source = note(fields={' front ': 'original', 'back': None, 'unknown': 'ignored'}, tags=' alpha\tbeta::child  alpha ',
                  options={'allowDuplicate': 'false', 'duplicateScopeOptions': None})
    assert invoke(admitted, 'canAddNotes', notes=source) == [True]
    id = invoke(admitted, 'addNotes', notes=source)[0]
    unrelated = invoke(admitted, 'addNote', note=note('unrelated'))
    card = service.col.get_note(id).card_ids()[0]
    assert service.col.get_note(id).fields == ['original', '']
    assert set(service.col.get_note(id).tags) == {'alpha', 'beta::child'}
    assert invoke(admitted, 'notesInfo', notes=' 00' + str(id))[0]['noteId'] == id
    assert invoke(admitted, 'cardsInfo', cards=str(card), fields='note') == [{'note': id}]
    assert invoke(admitted, 'getDecks', cards=str(card)) == {'Default': [card]}
    assert invoke(admitted, 'cardsToNotes', cards=float(card)) == [id]
    assert invoke(admitted, 'updateNoteFields', note={'id': str(id), 'fields': {'FRONT': 'changed', ' Back ': 'answer'}}) is None
    assert service.col.get_note(id).fields == ['changed', 'answer']
    assert invoke(admitted, 'addTags', notes=str(id), tags=[' alpha ', 'beta::child'], add='false') is None
    assert service.col.get_note(id).tags == []
    assert invoke(admitted, 'updateNote', note={'id': str(id), 'tags': 'one two'}) is None
    assert set(service.col.get_note(id).tags) == {'one', 'two'}
    assert invoke(admitted, 'setEaseFactors', cards=str(card), easeFactors='2700') == [True]
    assert invoke(admitted, 'getEaseFactors', cards=str(card)) == [2700]
    assert invoke(admitted, 'suspend', cards=str(card), suspend='true') is True
    assert invoke(admitted, 'suspend', cards=str(card), suspend='false') is True
    assert invoke(admitted, 'areSuspended', cards=str(card)) == [False]
    assert invoke(admitted, 'setDueDate', cards=str(card), days=3) is True
    assert service.col.get_card(card).queue == 2
    reviews = service.col.db.scalar('select count(*) from revlog where cid = ?', card)
    assert invoke(admitted, 'answerCards', answers={'cardId': str(card), 'ease': '4'}) == [True]
    assert service.col.db.scalar('select count(*) from revlog where cid = ?', card) == reviews + 1
    assert service.col.db.scalar('select ease from revlog where cid = ? order by id desc limit 1', card) == 4
    assert invoke(admitted, 'deleteNotes', notes=str(id)) is None
    assert service.col.note_count() == 1 and service.col.get_note(unrelated)['Front'] == 'unrelated'
    assert notifications and owner.window()._background_op_count == 0


@pytest.mark.parametrize('tags,expected', [(None, set()), ('', set()),
    (['', None, '  ', 'alpha beta', 'beta', '日本語'], {'alpha', 'beta', '日本語'})])
def test_tags_and_null_options_are_consistent(admitted, tags, expected):
    _, service, _, _, _ = admitted
    id = invoke(admitted, 'addNote', note=note(tags=tags, options=None))
    assert set(service.col.get_note(id).tags) == expected
    for action, params in [('updateNote', {'note': {'id': id, 'tags': tags}}),
                           ('updateNoteTags', {'note': id, 'tags': tags}),
                           ('updateNoteModel', {'note': note('converted', id=id, tags=tags)})]:
        service.col.tags.bulk_add([id], 'old')
        assert invoke(admitted, action, **params) is None
        assert set(service.col.get_note(id).tags) == expected
    assert invoke(admitted, 'addTags', notes=id, tags=None) is None
    assert set(service.col.get_note(id).tags) == expected


def test_duplicate_booleans_and_null_defaults(admitted):
    _, service, _, _, _ = admitted
    source = note(options={'allowDuplicate': 'false', 'duplicateScope': 'deck',
                          'duplicateScopeOptions': {'checkChildren': '0', 'checkAllModels': 0}})
    invoke(admitted, 'addNote', note=source)
    assert invoke(admitted, 'canAddNoteWithErrorDetail', note=source) == {
        'canAdd': False, 'error': 'cannot create note because it is a duplicate'}
    source['options']['allowDuplicate'] = 'true'
    invoke(admitted, 'addNote', note=source)
    source['fields']['Front'] = 'different'
    source['options'] = {'allowDuplicate': None, 'duplicateScopeOptions': {
        'checkChildren': None, 'checkAllModels': 'false'}}
    assert invoke(admitted, 'canAddNote', note=source) is True
    assert invoke(admitted, 'getMediaFilesNames', pattern=None) == []
    assert invoke(admitted, 'apiReflect', scopes='actions', actions='addNote') == {
        'scopes': ['actions'], 'actions': ['addNote']}
    assert invoke(admitted, 'apiReflect', scopes=None) == {'scopes': []}
    assert service.col.note_count() == 2


@pytest.mark.parametrize('kind', ['audio', 'video', 'picture'])
def test_media_targets_and_string_false_preserve_existing_files(admitted, kind):
    _, service, _, _, _ = admitted
    service.store_bytes('existing.txt', b'original', 'replace')
    id = invoke(admitted, 'addNote', note=note())
    entry = {'filename': 'existing.txt', 'data': 'bmV3', 'deleteExisting': 'false',
             'fields': ['back', 'Back', ' Back ', 'unknown']}
    assert invoke(admitted, 'updateNoteFields', note={'id': str(id), kind: entry}) is None
    directory = Path(service.col.media.dir())
    assert (directory / 'existing.txt').read_bytes() == b'original'
    created = [path for path in directory.iterdir() if path.name != 'existing.txt' and path.is_file()]
    assert len(created) == 1 and created[0].read_bytes() == b'new'
    markup = '<img src="' + created[0].name + '">' if kind == 'picture' else '[sound:' + created[0].name + ']'
    assert service.col.get_note(id).fields == ['question', 'answer' + markup]
    # Scalar media targets use the same matching during pure eligibility and creation.
    source = note('creation', **{kind: {**entry, 'filename': 'created.txt', 'fields': ' back '}})
    assert invoke(admitted, 'canAddNote', note=source) is True
    assert not (directory / 'created.txt').exists()
    created_id = invoke(admitted, 'addNote', note=source)
    created_markup = '<img src="created.txt">' if kind == 'picture' else '[sound:created.txt]'
    assert service.col.get_note(created_id)['Back'] == 'answer' + created_markup
    assert (directory / 'created.txt').read_bytes() == b'new'


@pytest.mark.parametrize('flag', ['omitted', None, True])
def test_attachment_collisions_rename_unless_replacement_is_requested(admitted, flag):
    """de6e6e1 passed a missing attachment flag through as falsy; only storeMediaFile defaulted to replace."""
    _, service, _, _, _ = admitted
    service.store_bytes('shared.mp3', b'original', 'replace')
    entry = {'filename': 'shared.mp3', 'data': 'bmV3', 'fields': ['Back']}
    if flag != 'omitted':
        entry['deleteExisting'] = flag
    id = invoke(admitted, 'addNote', note=note(audio=[entry]))
    directory = Path(service.col.media.dir())
    stored = service.col.get_note(id)['Back'][len('answer[sound:'):-1]
    assert (directory / stored).read_bytes() == b'new'
    assert (directory / 'shared.mp3').read_bytes() == (b'new' if flag is True else b'original')
    assert (stored == 'shared.mp3') is (flag is True)


def test_exact_field_names_win_and_ambiguous_updates_leave_notes_unchanged(admitted):
    owner, service, drain, _, _ = admitted
    id = invoke(admitted, 'addNote', note=note(fields={'front': 'ignored', 'Front': 'exact', 'Back': None}))
    assert service.col.get_note(id).fields == ['exact', '']
    assert invoke(admitted, 'updateNoteFields', note={'id': id, 'fields': {'Front': 'exact update', 'front': 'ignored'}}) is None
    pending = owner.handler_async({'action': 'updateNoteFields', 'version': 6, 'params': {
        'note': {'id': id, 'fields': {'front': 'one', 'FRONT': 'another'}}}})
    drain()
    assert pending.value == {'result': None, 'error': 'Ambiguous field name.'}
    assert service.col.get_note(id).fields == ['exact update', '']


def test_scalar_model_inputs_and_integer_parameters(admitted):
    _, service, _, _, _ = admitted
    model = invoke(admitted, 'createModel', modelName='One field', inOrderFields='Question', isCloze='false',
                   cardTemplates={'Name': 'One', 'Front': '{{Question}}', 'Back': '{{Question}}'})
    assert model['type'] == 0
    assert invoke(admitted, 'findModelsById', modelIds=str(model['id']))[0]['name'] == 'One field'
    assert invoke(admitted, 'findModelsByName', modelNames='One field')[0]['id'] == model['id']
    assert invoke(admitted, 'modelFieldSetFontSize', modelName='One field', fieldName='Question', fontSize='24') is None
    assert service.col.models.by_name('One field')['flds'][0]['size'] == 24


def test_normalized_ids_still_block_affected_editors(admitted, monkeypatch):
    import aqt
    owner, service, drain, work, _ = admitted
    id = invoke(admitted, 'addNote', note=note())
    saves = []
    def save(callback, keepFocus=False):
        saves.append(service.col.get_note(id).fields[:])
        callback()
    # 26.08 web editors keep only the note ID and cannot load a deleted or converted note.
    editor = SimpleNamespace(nid=id, reload_note=lambda: None, call_after_note_saved=save, addMode=False)
    monkeypatch.setattr(aqt.dialogs, '_dialogs', {'Browser': (None, SimpleNamespace(editor=editor))})
    adding = SimpleNamespace(nid=id, reload_note=lambda: None, call_after_note_saved=save, addMode=True)
    for editors, action, params in [
            ({}, 'deleteNotes', {'notes': str(id)}),
            ({}, 'updateNoteModel', {'note': {'id': ' 00' + str(id), 'modelName': 'Basic (and reversed card)',
                                              'fields': {'Front': 'bad'}}}),
            ({'AddCards': (None, SimpleNamespace(editor=adding))}, 'addTags', {'notes': str(id), 'tags': 'bad'})]:
        monkeypatch.setitem(aqt.dialogs._dialogs, 'AddCards', editors.get('AddCards', (None, None)))
        pending = owner.handler_async({'action': action, 'version': '6', 'params': params})
        drain()
        assert pending.value['error'].startswith('Close the affected editor')
        assert not work
    monkeypatch.delitem(aqt.dialogs._dialogs, 'AddCards')
    assert service.col.get_note(id).fields == ['question', 'answer']
    assert service.col.get_note(id).tags == []
    assert service.col.get_note(id).note_type()['name'] == 'Basic'
    # The web editor reloads field and tag writes, which run after it saves.
    assert invoke(admitted, 'updateNoteFields', note={'id': ' 00' + str(id), 'fields': {'front': 'pushed'}}) is None
    assert invoke(admitted, 'addTags', notes=str(id), tags='emacs') is None
    assert invoke(admitted, 'replaceTagsInAllNotes', tag_to_replace='emacs', replace_with_tag='org') is None
    assert saves == [['question', 'answer'], ['pushed', 'answer'], ['pushed', 'answer']]
    assert (service.col.get_note(id).fields, service.col.get_note(id).tags) == (['pushed', 'answer'], ['org'])
    # New notes and other notes do not touch the open editor.
    other = invoke(admitted, 'addNote', note=note('other'))
    invoke(admitted, 'addNotes', notes=[note('third')])
    assert invoke(admitted, 'updateNoteTags', note=other, tags='ok') is None
    assert service.col.get_note(other).tags == ['ok']


def test_legacy_note_writes_save_then_pass_reloading_editors(admitted, monkeypatch):
    # anki-editor (Emacs) pushes notes still shown in the Browser and its preview.
    # The Browser saves its editor first and reloads the note after the write.
    import aqt
    owner, service, drain, work, _ = admitted
    id = invoke(admitted, 'addNote', note=note())
    saves = []
    def save(callback, keepFocus=False):
        saves.append(service.col.get_note(id).fields[:])
        callback()
    editor = SimpleNamespace(note=service.col.get_note(id), call_after_note_saved=save)
    monkeypatch.setattr(aqt.dialogs, '_dialogs', {'Browser': (None, SimpleNamespace(editor=editor))})
    assert invoke(admitted, 'updateNoteFields', note={'id': ' 00' + str(id), 'fields': {'front': 'pushed'}}) is None
    assert invoke(admitted, 'multi', actions=[
        {'action': 'updateNote', 'params': {'note': {'id': id, 'fields': {'Back': 'pushed answer'}, 'tags': ['emacs']}}},
        {'action': 'addTags', 'params': {'notes': [id], 'tags': 'added'}},
        {'action': 'removeTags', 'params': {'notes': [id], 'tags': 'emacs'}}]) == [None, None, None]
    # Each write ran after the editor saved, never before.
    assert saves == [['question', 'answer'], ['pushed', 'answer'], ['pushed', 'pushed answer'], ['pushed', 'pushed answer']]
    assert service.col.get_note(id).fields == ['pushed', 'pushed answer']
    assert service.col.get_note(id).tags == ['added']


def test_legacy_note_type_writes_only_block_editors_of_changed_fields(admitted, monkeypatch):
    # logseq-anki-sync and Obsidian-Anki-Sync update templates on every sync,
    # often while their own Browser preview remains open.
    import aqt
    owner, service, drain, work, _ = admitted
    id = invoke(admitted, 'addNote', note=note())
    card = service.col.get_note(id).card_ids()[0]
    dialog = SimpleNamespace(editor=SimpleNamespace(note=service.col.get_note(id)))
    monkeypatch.setattr(aqt.dialogs, '_dialogs', {'Browser': (None, dialog)})
    model = invoke(admitted, 'createModel', modelName='Synced', inOrderFields=['Q', 'A'], css='.a{}',
                   cardTemplates=[{'Name': 'One', 'Front': '{{Q}}', 'Back': '{{A}}'}])
    for action, params in [
            ('updateModelTemplates', {'model': {'name': 'Basic', 'templates': {'Card 1': {'Front': '{{Front}}!'}}}}),
            ('updateModelStyling', {'model': {'name': 'Basic', 'css': '.card{}'}}),
            ('modelTemplateAdd', {'modelName': 'Synced', 'template': {'Name': 'Two', 'Front': '{{A}}', 'Back': '{{Q}}'}}),
            ('modelFieldSetFontSize', {'modelName': 'Basic', 'fieldName': 'Back', 'fontSize': 30}),
            ('modelFieldAdd', {'modelName': 'Synced', 'fieldName': 'Extra'}),
            ('setEaseFactors', {'cards': [card], 'easeFactors': [2600]}),
            ('removeEmptyNotes', {})]:
        assert invoke(admitted, action, **params) in (None, [True])
    assert service.col.models.by_name('Basic')['tmpls'][0]['qfmt'] == '{{Front}}!'
    assert [field['name'] for field in service.col.models.get(model['id'])['flds']] == ['Q', 'A', 'Extra']
    assert service.col.models.by_name('Synced') is not None
    # Field structure changes still conflict with editors of that note type.
    for params in [{'modelName': 'Basic', 'fieldName': 'Extra'}, {'modelName': 'basic', 'fieldName': 'Extra'}]:
        pending = owner.handler_async({'action': 'modelFieldAdd', 'version': 6, 'params': params})
        drain()
        assert pending.value['error'].startswith('Close the affected editor')
        assert not work
    assert len(service.col.models.by_name('Basic')['flds']) == 2
    # Web editors do not expose their note type to Python.
    monkeypatch.setattr(aqt.dialogs, '_dialogs', {'NewAddCards': (None, SimpleNamespace(editor=SimpleNamespace(nid=None)))})
    pending = owner.handler_async({'action': 'modelFieldAdd', 'version': 6, 'params': {'modelName': 'Synced', 'fieldName': 'More'}})
    drain()
    assert pending.value['error'].startswith('Close the affected editor')


# Editors before 2.1.45 name the save method saveNow.
@pytest.mark.parametrize('save', ['call_after_note_saved', 'saveNow'])
def test_legacy_writes_wait_for_open_editors_to_save(admitted, monkeypatch, save):
    # Change notifications reload open editors from the collection, so typing
    # not yet sent to Python would be lost to a template sync or a Yomitan add.
    import aqt
    import plugin
    owner, service, drain, work, _ = admitted
    saves = []
    editor = SimpleNamespace(note=None, **{save: lambda callback, keepFocus=False: saves.append((callback, keepFocus))})
    monkeypatch.setattr(aqt.dialogs, '_dialogs', {'Browser': (None, SimpleNamespace(editor=editor)), 'AddCards': (None, None)})
    for action, params in [('updateModelStyling', {'model': {'name': 'Basic', 'css': '.saved{}'}}),
                           ('addNote', {'note': note()})]:
        pending = owner.handler_async({'action': action, 'version': 6, 'params': params})
        assert not pending.done and not work and len(saves) == 1 and saves[0][1] is True
        saves.pop()[0]()
        drain()
        assert pending.value['error'] is None
    assert service.col.models.by_name('Basic')['css'] == '.saved{}' and service.col.note_count() == 1
    assert invoke(admitted, 'deckNames') == ['Default'] and not saves
    monkeypatch.setattr(plugin, 'LEGACY_WAIT_SECONDS', 0)
    pending = owner.handler_async({'action': 'addNote', 'version': 6, 'params': {'note': note('unsaved')}})
    drain()
    assert pending.value == {'result': None, 'error': 'An open editor did not save its note.'}
    assert service.col.note_count() == 1


def test_legacy_gui_actions_wait_for_collection_work(admitted, monkeypatch):
    # mpvacious and GSM send guiBrowse "nid:1" while a previous write may still run.
    import plugin
    owner, service, drain, work, _ = admitted
    id = invoke(admitted, 'addNote', note=note())
    browsed = []
    monkeypatch.setattr(owner.runtime.gui, 'execute', lambda method, params, **kwargs: browsed.append((method, params)) or {})
    write = owner.handler_async({'action': 'updateNoteFields', 'version': 6, 'params': {
        'note': {'id': id, 'fields': {'Front': 'updated'}}}})
    browse = owner.handler_async({'action': 'guiBrowse', 'version': 6, 'params': {'query': 'nid:1'}})
    reload = owner.handler_async({'action': 'reloadCollection', 'version': 6})
    assert owner.window()._background_op_count == 1 and not browsed
    drain()
    assert write.value == {'result': None, 'error': None}
    assert browse.value == {'result': [], 'error': None}
    assert reload.value == {'result': None, 'error': None}
    assert [method for method, _ in browsed] == ['browser.open', 'collection.refresh']
    # Browser results keep Anki's native order, like findCards.
    invoke(admitted, 'createDeck', deck='Z')
    invoke(admitted, 'addNote', note={**note('z'), 'deckName': 'Z'})
    invoke(admitted, 'addNote', note=note('later'))  # Native order follows deck, not ID.
    query = 'deck:Default or deck:Z'
    browse = owner.handler_async({'action': 'guiBrowse', 'version': 6, 'params': {'query': query}})
    drain()
    cards = list(service.col.find_cards(query))
    # Before 2.1.24 the Python finder returned ascending ids.
    assert (cards != sorted(cards) or compat.release() < (2, 1, 24)) and browse.value == {'result': cards, 'error': None}
    # Work that outlasts the wait still fails instead of queueing indefinitely.
    monkeypatch.setattr(plugin, 'LEGACY_WAIT_SECONDS', 0)
    owner.window()._background_op_count = 1
    late = owner.handler_async({'action': 'guiBrowse', 'version': 6, 'params': {'query': 'nid:1'}})
    drain()
    assert late.value == {'result': None, 'error': 'A collection operation is active.'}


def test_normalized_nested_batches_keep_preflight_and_credentials(admitted, monkeypatch):
    owner, service, drain, work, _ = admitted
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'apiKey', 'secret')
    request = {'action': 'multi', 'version': '6', 'key': 'secret', 'params': {'actions': [
        {'action': 'version', 'version': '6', 'params': None},
        {'action': 'multi', 'key': 'secret', 'params': {'actions': [
            {'action': 'version', 'version': '6', 'key': 'secret', 'params': []}]}}
    ]}}
    assert exchange(owner, drain, request) == {'result': [
        {'result': None, 'error': 'valid api key must be provided'}, [{'result': 6, 'error': None}]], 'error': None}
    request['params']['actions'] = [
        {'action': 'createDeck', 'key': 'secret', 'params': {'deck': 'Must not exist'}},
        {'action': 'multi', 'version': '6', 'key': 'secret', 'params': {'actions': [
            {'action': 'guiExitAnki', 'key': 'secret', 'params': None}]}},
        {'action': 'version', 'key': 'secret'}]
    reply = owner.handler_async(request)
    assert reply.done
    assert reply.value['error'] == 'guiExitAnki must be the last executable multi action'
    assert not work and not owner.runtime.exit_requested
    assert service.col.decks.id_for_name('Must not exist') is None


def test_permission_context_and_origin_checks_survive_null_params(admitted, monkeypatch):
    owner, _, drain, _, _ = admitted
    seen = []
    monkeypatch.setattr(owner, 'permission', lambda origin, allowed: seen.append((origin, allowed)) or {'permission': 'denied'})
    request = WebRequest(b'POST', {b'origin': b'https://unknown.example'},
                         b'{"action":"requestPermission","version":"6","params":null}')
    pending = owner.server.handlerWrapper(request)
    drain()
    assert seen == [('https://unknown.example', False)]
    assert json.loads(pending.value.split(b'\r\n\r\n')[1]) == {'result': {'permission': 'denied'}, 'error': None}
    request.body = b'{"action":"version","version":"6","params":null}'
    assert owner.server.handlerWrapper(request).startswith(b'HTTP/1.1 403 Forbidden')


@pytest.mark.parametrize('value', [True, 1.5, '1.5', '1e3', '999 OR cid:1', 2**63, {'id': 1}])
def test_invalid_ids_do_not_turn_into_queries_or_mutations(admitted, value):
    owner, service, drain, _, _ = admitted
    id = invoke(admitted, 'addNote', note=note())
    for action in ('areDue', 'getIntervals', 'deleteNotes'):
        key = 'notes' if action == 'deleteNotes' else 'cards'
        reply = exchange(owner, drain, {'action': action, 'version': 6, 'params': {key: value}})
        assert reply['error'] == 'Expected a positive signed 64-bit decimal ID.'
    assert service.col.get_note(id)['Front'] == 'question'


def test_invalid_conversion_content_is_rejected_before_native_conversion(admitted):
    owner, service, drain, _, _ = admitted
    id = invoke(admitted, 'addNote', note=note())
    before = service.col.get_note(id)
    cards = before.card_ids()
    for patch in ({'fields': {'Front': ['invalid']}}, {'tags': [123]}):
        source = note('replacement', id=id, modelName='Basic (and reversed card)', **patch)
        reply = exchange(owner, drain, {'action': 'updateNoteModel', 'version': 6, 'params': {'note': source}})
        assert reply['error']
        after = service.col.get_note(id)
        assert after.mid == before.mid and after.fields == before.fields and after.card_ids() == cards


@pytest.mark.parametrize('value', ['false', '0', 'not a boolean'])
def test_false_or_invalid_deletion_flags_preserve_decks(admitted, value):
    owner, service, drain, _, _ = admitted
    id = invoke(admitted, 'createDeck', deck='Keep')
    reply = exchange(owner, drain, {'action': 'deleteDecks', 'version': '6',
                                    'params': {'decks': 'Keep', 'cardsToo': value}})
    expected = ('cardsToo must be boolean' if value == 'not a boolean' else
                "Since Anki 2.1.28 it's not possible to delete decks without deleting cards as well")
    assert reply == {'result': None, 'error': expected}
    assert service.col.decks.id_for_name('Keep') == id


@pytest.mark.parametrize('params', ['{}', [1], True])
def test_nonempty_malformed_parameter_containers_are_rejected(admitted, params):
    owner, service, drain, work, _ = admitted
    request = {'action': 'createDeck', 'version': '6', 'params': params}
    assert exchange(owner, drain, request) == {'result': None, 'error': 'params must be an object.'}
    assert not work and service.col.decks.all_names_and_ids()[0].name == 'Default'


def test_v1_keeps_strict_types_and_unknown_parameter_validation(admitted):
    owner, service, drain, _, _ = admitted
    for method, params in [('cards.getMany', {'ids': '1'}), ('notes.create', {
        'noteType': {'name': 'Basic'}, 'deck': {'name': 'Default'}, 'fields': {'Front': 'strict'}, 'tags': 'one two'}),
        ('notes.create', {'noteType': {'name': 'Basic'}, 'deck': {'name': 'Default'}, 'fields': {'Front': None}}),
        ('cards.setSuspended', {'ids': ['1'], 'suspended': 'false'}), ('decks.list', {'unused': True})]:
        pending = owner.runtime.dispatcher.request({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
        drain()
        assert pending.value['error']['data']['type'] == 'invalidParams'
    assert service.col.note_count() == 0

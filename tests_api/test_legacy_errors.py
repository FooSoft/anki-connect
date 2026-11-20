"""Pre-rewrite legacy failure contracts, including error text and sentinels.

Binding snapshots were captured from de6e6e1 (before f69c9e4), not generated
from the new dispatcher. Native cases were compared with that implementation's
handler against disposable collections. Safety changes documented in API_LEGACY
(editor/lifecycle guards, protected scheduler writes, limits) remain explicit.
Missing-argument wording is preserved; surplus parameters are now ignored.
"""
import json
from pathlib import Path

import pytest

from plugin import AnkiConnect, util
from tests_api.test_runtime import admitted, native
from tests_api.test_yomitan import exchange


BINDING = json.loads(Path(__file__).with_name('legacy_binding_errors.json').read_text())['cases']


@pytest.mark.parametrize('case', BINDING, ids=lambda c: c['action'] + ('-unexpected' if c['params'] else '-missing'))
def test_every_legacy_action_argument_errors_match_baseline(case, monkeypatch):
    """Missing addNote/multi arguments retain their wording; surplus keys are ignored."""
    monkeypatch.setattr(util, 'setting', util.DEFAULT_CONFIG.__getitem__)
    owner = AnkiConnect()
    payload = {'action': case['action'], 'version': 6, 'params': case['params']}
    expected = case['reply']
    if case['params']:
        missing = next((item for item in BINDING if item['action'] == case['action'] and not item['params']), None)
        if missing is None:
            # Resolve without executing lifecycle/GUI actions in this binder test.
            assert owner.resolve_action(case['action'], case['params'])[0] == case['action']
            return
        expected = missing['reply']
    pending = owner.handler_async(payload)
    assert pending.done and pending.value == expected


def test_binding_baseline_covers_every_retained_legacy_action():
    assert {case['action'] for case in BINDING} == set(AnkiConnect().legacy_actions())


@pytest.mark.parametrize('version', [4, 6])
@pytest.mark.parametrize('action,params,expected', [
    ('getEaseFactors', {'cards': [999]}, [None]),
    ('setEaseFactors', {'cards': [999], 'easeFactors': []}, [False]),
    ('areSuspended', {'cards': [999]}, [None]),
    ('suspended', {'card': 999}, 'Card was not found: 999'),
    ('suspend', {'cards': [999]}, 'Card was not found: 999'),
    ('unsuspend', {'cards': []}, None),
    ('getIntervals', {'cards': [999]}, 'list index out of range'),
    ('getIntervals', {'cards': [999], 'complete': True}, [[]]),
    ('areDue', {'cards': [999]}, 'list index out of range'),
    ('getReviewsOfCards', {'cards': [999]}, {'999': []}),
    ('setSpecificValueOfCard', {'card': 999, 'keys': ['factor'], 'newValues': [2500]},
     [[False, 'Card was not found: 999']]),
    ('notesInfo', {'notes': [999]}, [{}]),
    ('cardsInfo', {'cards': [999]}, [{}]),
    ('notesModTime', {'notes': [999]}, [{}]),
    ('cardsModTime', {'cards': [999]}, [{}]),
    ('getNoteTags', {'note': 999}, 'Note was not found: 999'),
    ('updateNoteTags', {'note': 999, 'tags': ['tag']}, 'Note was not found: 999'),
    ('addTags', {'notes': [999], 'tags': 'tag'}, None),
    ('removeTags', {'notes': [999], 'tags': 'tag'}, None),
    ('replaceTags', {'notes': [999], 'tag_to_replace': 'a', 'replace_with_tag': 'b'}, None),
    ('cardsToNotes', {'cards': [999]}, []),
    ('deleteNotes', {'notes': [999]}, None),
    ('getDeckConfig', {'deck': 'Missing'}, False),
    ('setDeckConfigId', {'decks': ['Missing'], 'configId': 999}, False),
    ('removeDeckConfigId', {'configId': 999}, False),
    ('cloneDeckConfigId', {'name': 'New', 'cloneFrom': 999}, False),
    ('guiSelectedNotes', {}, []),
    ('guiSelectCard', {'card': 999}, False),
    ('guiAddNoteSetData', {'note': {}}, {'error': 'Add Note dialog is not open', 'code': 1}),
    ('retrieveMediaFile', {'filename': 'missing.txt'}, False),
    ('deleteMediaFile', {'filename': 'missing.txt'}, None),
    ('storeMediaFile', {'filename': 'empty.txt', 'data': ''}, 'You must provide a "data", "path", or "url" field.'),
    ('exportPackage', {'deck': 'Missing', 'path': 'unused.apkg'}, False),
])
def test_legacy_missing_entities_and_failure_sentinels(admitted, version, action, params, expected):
    owner, service, drain, _, _ = admitted
    payload = {'action': action, 'version': version, 'params': params}
    pending = owner.handler_async(payload)
    drain()
    expected_reply = ({'result': None, 'error': expected} if isinstance(expected, str) else
                      expected if version <= 4 else {'result': expected, 'error': None})
    assert pending.value == expected_reply
    assert service.col.note_count() == 0


@pytest.mark.parametrize('version', [4, 6])
def test_legacy_nested_failures_keep_item_versions_credentials_and_order(admitted, monkeypatch, version):
    owner, service, drain, _, _ = admitted
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'apiKey', 'secret')
    request = {'action': 'multi', 'version': version, 'key': 'secret', 'params': {'actions': [
        {'action': 'notAnAction', 'version': 6, 'key': 'secret'},
        {'action': 'addNote', 'version': 2, 'key': 'secret'},
        {'action': 'version', 'version': 6},
        {'action': 'multi', 'key': 'secret', 'params': {'actions': [
            {'action': 'version', 'version': 6, 'key': 'secret'},
            {'action': 'version', 'key': 'secret'},
        ]}},
        {'action': 'createDeck', 'version': 6, 'key': 'secret', 'params': {'deck': 'After errors'}},
    ]}}
    reply = exchange(owner, drain, request)
    values = reply if version <= 4 else reply['result']
    assert values[:3] == [
        {'result': None, 'error': 'unsupported action'},
        {'result': None, 'error': "AnkiConnect.addNote() missing 1 required positional argument: 'note'"},
        {'result': None, 'error': 'valid api key must be provided'},
    ]
    assert values[3] == [{'result': 6, 'error': None}, 6]
    assert values[4] == {'result': service.col.decks.id_for_name('After errors'), 'error': None}


def test_legacy_bulk_note_failure_aggregates_errors_and_rolls_back(admitted):
    owner, service, drain, _, _ = admitted
    notes = [
        {'modelName': 'Missing', 'deckName': 'Default', 'fields': {'Front': 'a'}},
        {'modelName': 'Basic', 'deckName': 'Missing', 'fields': {'Front': 'b'}},
        {'modelName': 'Basic', 'deckName': 'Default', 'fields': {'Front': ''}},
    ]
    pending = owner.handler_async({'action': 'addNotes', 'version': 6, 'params': {'notes': notes}})
    drain()
    assert pending.value == {'result': None, 'error': str([
        'model was not found: Missing', 'deck was not found: Missing', 'cannot create note because it is empty'])}
    assert service.col.note_count() == 0
    duplicate = {'modelName': 'Basic', 'deckName': 'Default', 'fields': {'Front': 'same'}}
    pending = owner.handler_async({'action': 'addNotes', 'version': 6, 'params': {'notes': [duplicate] * 3}})
    drain()
    assert pending.value == {'result': None, 'error': str(['cannot create note because it is a duplicate'] * 2)}
    assert service.col.note_count() == 0


@pytest.mark.parametrize('action', ['guiReviewActive', 'guiCurrentCard', 'guiStartCardTimer',
                                  'guiShowQuestion', 'guiShowAnswer', 'guiPlayAudio', 'guiAnswerCard'])
def test_legacy_missing_reviewer_error(admitted, action):
    owner, _, drain, _, _ = admitted
    pending = owner.handler_async({'action': action, 'version': 6,
                                   'params': {'ease': 1} if action == 'guiAnswerCard' else {}})
    drain()
    assert pending.value == {'result': None, 'error': 'reviewer is not available'}


@pytest.mark.parametrize('sort,message', [
    ([], 'reorderCards should be a dict: []'),
    ({}, 'Must provide a "columnId" and a "order" property"'),
    ({'columnId': 'noteFld', 'order': 'wrong'}, 'invalid card order: wrong'),
    ({'columnId': 'missing', 'order': 'ascending'}, 'invalid columnId: missing'),
])
def test_legacy_browser_sort_errors(admitted, sort, message):
    owner, service, drain, _, _ = admitted
    pending = owner.handler_async({'action': 'guiBrowse', 'version': 6, 'params': {'reorderCards': sort}})
    drain()
    assert pending.value == {'result': None, 'error': message}


def test_legacy_collection_unavailable_keeps_wording_without_changing_v1(admitted):
    owner, _, drain, _, _ = admitted
    owner.window().col = None
    for action, params in [('modelNames', {}), ('addNote', {'note': {}}), ('findNotes', {'query': ''})]:
        pending = owner.handler_async({'action': action, 'version': 6, 'params': params})
        drain()
        assert pending.value == {'result': None, 'error': 'collection is not available'}
    pending = owner.runtime.dispatcher.request({'jsonrpc': '2.0', 'id': 1, 'method': 'collection.get'})
    drain()
    assert pending.value['error']['data']['type'] == 'collectionUnavailable'
    assert pending.value['error']['message'] == 'Collection is not available.'


@pytest.fixture
def media_server():
    import http.server
    import socketserver
    import threading
    seen = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get('User-Agent')))
            if self.path.startswith('/missing'):
                self.send_response(404)
                self.end_headers()
                return
            if self.path == '/empty':
                self.send_response(204)
                self.end_headers()
                return
            body = b'downloaded'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    # ThreadingHTTPServer needs Python 3.7; Anki 2.1.15 bundled 3.6.
    server_class = type('Server', (socketserver.ThreadingMixIn, http.server.HTTPServer), {'daemon_threads': True})
    server = server_class(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:{}'.format(server.server_address[1]), seen
    finally:
        server.shutdown()
        server.server_close()


def test_legacy_media_source_priority_whitespace_and_download_error(admitted, media_server, tmp_path):
    """URL media uses Anki's HTTP client: IRIs, its user agent, and status 200 only, like de6e6e1."""
    owner, service, drain, _, _ = admitted
    base, seen = media_server
    directory = Path(service.col.media.dir())
    def store(**params):
        pending = owner.handler_async({'action': 'storeMediaFile', 'version': 6, 'params': params})
        drain()
        return pending.value
    assert store(filename='legacy.txt', data=' bG VnYWN5\n', path=str(tmp_path / 'missing')) == {'result': 'legacy.txt', 'error': None}
    assert (directory / 'legacy.txt').read_bytes() == b'legacy'
    for path, status in (('/missing.mp3', 404), ('/empty', 204)):
        url = base + path
        assert store(filename='failed.mp3', url=url) == {
            'result': None, 'error': url + ' download failed with return code ' + str(status)}
    assert not (directory / 'failed.mp3').exists()
    assert store(filename='term.mp3', url=base + '/\u8a9e\u5f59.mp3?q=\u97f3') == {'result': 'term.mp3', 'error': None}
    assert (directory / 'term.mp3').read_bytes() == b'downloaded'
    assert seen[-1][0] == '/%E8%AA%9E%E5%BD%99.mp3?q=%E9%9F%B3'
    assert seen[-1][1].startswith('Anki ')
    (tmp_path / 'secret.txt').write_bytes(b'secret')
    assert store(filename='local.txt', url=(tmp_path / 'secret.txt').as_uri())['error']
    assert not (directory / 'local.txt').exists()


def test_legacy_missing_package_retains_os_error(admitted, tmp_path):
    owner, _, drain, _, _ = admitted
    path = str(tmp_path / 'missing.apkg')
    try:
        with open(path, 'rb'):
            pass
    except FileNotFoundError as error:
        expected = str(error)
    pending = owner.handler_async({'action': 'importPackage', 'version': 6, 'params': {'path': path}})
    drain()
    assert pending.value == {'result': None, 'error': expected}


@pytest.mark.parametrize('action,expected', [('getLatestReviewID', 0), ('cardReviews', [])])
def test_legacy_review_reads_create_missing_decks(admitted, action, expected):
    """getLatestReviewID and cardReviews retain their historical missing-deck results."""
    owner, service, drain, _, _ = admitted
    params = {'deck': 'New empty deck'}
    if action == 'cardReviews':
        params['startID'] = 0
    assert service.col.decks.id_for_name(params['deck']) is None
    pending = owner.handler_async({'action': action, 'version': 6, 'params': params})
    drain()
    assert pending.value == {'result': expected, 'error': None}
    assert service.col.decks.id_for_name(params['deck']) is not None


def test_legacy_deck_stats_create_missing_decks(admitted):
    owner, service, drain, _, _ = admitted
    pending = owner.handler_async({'action': 'getDeckStats', 'version': 6,
                                   'params': {'decks': ['New empty deck']}})
    drain()
    deck_id = service.col.decks.id_for_name('New empty deck')
    assert deck_id is not None
    assert pending.value == {'result': {str(deck_id): {'deck_id': deck_id, 'name': 'New empty deck',
        'new_count': 0, 'learn_count': 0, 'review_count': 0, 'total_in_deck': 0}}, 'error': None}


@pytest.mark.parametrize('action', ['addNote', 'addNotes', 'updateNoteFields'])
def test_legacy_attachment_acquisition_errors_are_embedded_in_fields(admitted, tmp_path, action):
    """addNote, addNotes and updateNoteFields retain legacy attachment failure results in entry order."""
    import html
    owner, service, drain, _, _ = admitted
    # Ampersands exercise HTML escaping while remaining valid on Windows.
    path = str(tmp_path / 'missing&.txt')
    try:
        with open(path, 'rb'):
            pass
    except FileNotFoundError as error:
        expected = html.escape(str(error), quote=False)
    note = {'modelName': 'Basic', 'deckName': 'Default', 'fields': {'Front': 'Question', 'Back': ''}}
    if action == 'updateNoteFields':
        initial = owner.handler_async({'action': 'addNote', 'version': 6, 'params': {'note': note}})
        drain()
        note = {'id': initial.value['result'], 'fields': {'Back': ''}}
    note['audio'] = [{'filename': 'present.mp3', 'data': 'b2s=', 'fields': ['Back']},
                     {'filename': 'missing.mp3', 'path': path, 'fields': ['Back']}]
    pending = owner.handler_async({'action': action, 'version': 6,
        'params': {'notes': [note]} if action == 'addNotes' else {'note': note}})
    drain()
    assert pending.value['error'] is None
    if action == 'updateNoteFields':
        assert pending.value['result'] is None
        note_id = note['id']
    else:
        note_id = pending.value['result'][0] if action == 'addNotes' else pending.value['result']
        assert isinstance(note_id, int)
    assert service.col.get_note(note_id)['Back'] == '[sound:present.mp3]' + expected
    assert service.col.note_count() == 1
    assert not (Path(service.col.media.dir()) / 'missing.mp3').exists()


@pytest.mark.parametrize('action', ['addNote', 'addNotes', 'updateNoteFields'])
def test_legacy_note_media_priority_whitespace_and_collision(admitted, tmp_path, action):
    """addNote, addNotes and updateNoteFields share storeMediaFile source precedence."""
    owner, service, drain, _, _ = admitted
    def invoke(action, **params):
        pending = owner.handler_async({'action': action, 'version': 6, 'params': params})
        drain()
        assert pending.value['error'] is None, pending.value
        return pending.value['result']
    assert invoke('storeMediaFile', filename='collision.txt', data='b3JpZ2luYWw=') == 'collision.txt'
    note = {'modelName': 'Basic', 'deckName': 'Default', 'fields': {'Front': 'Question', 'Back': ''},
            'options': {'duplicateScope': 'historically ignored'}}
    if action == 'updateNoteFields':
        note = {'id': invoke('addNote', note=note), 'fields': {'Back': ''}}
    note['audio'] = [{'filename': 'collision.txt', 'data': ' bG VnYWN5\n',
                     'path': str(tmp_path / 'missing'), 'deleteExisting': False, 'fields': ['Back']}]
    value = invoke(action, **({'notes': [note]} if action == 'addNotes' else {'note': note}))
    note_id = note['id'] if action == 'updateNoteFields' else value[0] if action == 'addNotes' else value
    back = service.col.get_note(note_id)['Back']
    assert back.startswith('[sound:') and back.endswith(']'), back
    filename = back[len('[sound:'):-1]
    assert filename != 'collision.txt'
    assert (Path(service.col.media.dir()) / filename).read_bytes() == b'legacy'
    assert (Path(service.col.media.dir()) / 'collision.txt').read_bytes() == b'original'


def test_legacy_short_ease_factor_list_retains_error_and_prior_updates(admitted):
    """setEaseFactors preserves ordered partial effects and its historical index error."""
    owner, service, drain, _, _ = admitted
    ids = []
    for front in ['First', 'Second']:
        pending = owner.handler_async({'action': 'addNote', 'version': 6, 'params': {'note': {
            'modelName': 'Basic', 'deckName': 'Default', 'fields': {'Front': front}}}})
        drain()
        ids.append(service.col.get_note(pending.value['result']).card_ids()[0])
    pending = owner.handler_async({'action': 'setEaseFactors', 'version': 6,
                                   'params': {'cards': ids, 'easeFactors': [2600]}})
    drain()
    assert pending.value == {'result': None, 'error': 'list index out of range'}
    assert service.col.get_card(ids[0]).factor == 2600
    assert service.col.get_card(ids[1]).factor != 2600


def test_api_log_records_legacy_requests_and_replies_without_key(admitted, monkeypatch, tmp_path):
    owner, _, drain, _, _ = admitted
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'apiKey', 'secret')
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'apiLogPath', str(tmp_path / 'api.log'))
    owner.initLogging()
    try:
        assert exchange(owner, drain, {'action': 'deckNames', 'version': 6, 'key': 'secret'}) == {
            'result': ['Default'], 'error': None}
    finally:
        owner.log.close()
    log = (tmp_path / 'api.log').read_text()
    assert '[request]' in log and '"action": "deckNames"' in log and 'secret' not in log
    assert '[reply]' in log and '"Default"' in log

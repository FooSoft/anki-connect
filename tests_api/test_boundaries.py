"""Regressions at native, GUI admission, transport, and installation boundaries."""
import base64
import json
import shutil
import socket
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugin import compat, parse_anki_version
from plugin.protocol import ApiError, Deferred, Dispatcher, completed
from tests_api.test_runtime import admitted, call, native
from tools.package_addon import build


@pytest.mark.parametrize('version, expected', [
    ('26.09.4', (26, 9, 4)),
    ('26.09.4+fsrs7', (26, 9, 4)),
    ('26.10b2+rc1', (26, 10, 2)),
    ('26.10rc1', (26, 10, 1)),
])
def test_anki_version_parsing_ignores_local_labels(version, expected):
    assert parse_anki_version(version) == expected


def test_addon_archive_matches_native_install_requirements(tmp_path, monkeypatch):
    import aqt.addons
    from aqt.addons import AddonManager
    # Anki validates package names from 2.1.47.
    package_name_valid = getattr(aqt.addons, 'package_name_valid', lambda name: True)

    source = tmp_path / 'plugin'
    source.mkdir()
    manifest = Path(__file__).resolve().parents[1] / 'plugin/manifest.json'
    (source / 'manifest.json').write_bytes(manifest.read_bytes())
    (source / '__init__.py').write_text('# entry point\n')
    (source / 'config.json').write_text('{"apiKey":null,"webBindPort":8765}')
    cached = source / '__pycache__'
    cached.mkdir()
    (cached / 'compiled.pyc').write_bytes(b'cache')
    (source / 'meta.json').write_text('{"config":{"apiKey":"private"}}')
    user_files = source / 'user_files'
    user_files.mkdir()
    (user_files / 'personal.json').write_text('{}')
    build(source, tmp_path / 'addon.zip')
    with zipfile.ZipFile(tmp_path / 'addon.zip') as archive:
        metadata = AddonManager.readManifestFile(object.__new__(AddonManager), archive)
        assert metadata['package'] == '2055492159'
        assert package_name_valid(metadata['package'])
        assert '__init__.py' in archive.namelist()
        assert not any(name.startswith('plugin/') or '__pycache__' in name for name in archive.namelist())
        assert 'meta.json' not in archive.namelist()
        assert not any(name.startswith('user_files/') for name in archive.namelist())
    assert (cached / 'compiled.pyc').read_bytes() == b'cache'
    assert (source / 'meta.json').exists() and (user_files / 'personal.json').exists()
    # Exercise Anki's actual local installer against an existing disposable
    # installation, including metadata and user-file preservation on upgrade.
    addons = tmp_path / 'addons'
    installed = addons / '2055492159'
    installed.mkdir(parents=True)
    (installed / '__init__.py').write_text('# old code\n')
    (installed / 'meta.json').write_text(json.dumps({'name': 'Old name', 'config': {'webBindPort': 9876}}))
    (installed / 'user_files').mkdir()
    (installed / 'user_files' / 'kept.txt').write_text('user data')
    manager = object.__new__(AddonManager)
    monkeypatch.setattr(manager, 'addonsFolder', lambda name=None: str(addons / name) if name else str(addons))
    monkeypatch.setattr(manager, '_disableConflicting', lambda *args: set())
    # Delete only the disposable old installation instead of using OS trash.
    monkeypatch.setattr(manager, 'deleteAddon', lambda name: shutil.rmtree(addons / name) or True)
    result = manager.install(str(tmp_path / 'addon.zip'))
    # Before 2.1.38 install returned (True, name, conflicts) rather than InstallOk.
    InstallOk = getattr(aqt.addons, 'InstallOk', None)
    assert isinstance(result, InstallOk) if InstallOk else result[0] is True, result
    assert manager.allAddons() == ['2055492159']
    assert manager.getConfig('2055492159')['webBindPort'] == 9876
    assert (installed / '__init__.py').read_text() == '# entry point\n'
    assert (installed / 'user_files' / 'kept.txt').read_text() == 'user data'


@pytest.mark.parametrize('request_id', [True, False, 1.5, [], {}])
def test_invalid_rpc_id_returns_null_without_execution(request_id):
    calls = []
    dispatcher = Dispatcher(SimpleNamespace(invoke=lambda *args: calls.append(args)))
    reply = dispatcher.request({'jsonrpc': '2.0', 'id': request_id, 'method': 'decks.list'}).value
    assert reply['id'] is None and reply['error']['code'] == -32600
    assert not calls


def test_nested_rpc_batch_is_rejected_without_executing_nested_commands():
    calls = []
    dispatcher = Dispatcher(SimpleNamespace(invoke=lambda *args: calls.append(args) or completed([])))
    command = {'jsonrpc': '2.0', 'id': 'write', 'method': 'decks.create', 'params': {'name': 'Hidden'}}
    reply = dispatcher.request([[command], {'jsonrpc': '2.0', 'id': 'read', 'method': 'decks.list'}]).value
    assert reply[0]['id'] is None and reply[0]['error']['code'] == -32600
    assert reply[1] == {'jsonrpc': '2.0', 'id': 'read', 'result': []}
    assert calls == [('decks.list', {})]


@pytest.mark.parametrize('requested,enabled', [(False, False), (False, True), (True, False), (True, True)])
def test_sync_respects_profile_media_setting(admitted, monkeypatch, requested, enabled):
    """Controlled collection.sync orchestration; no authenticated network sync."""
    import aqt
    owner, service, drain, work, notifications = admitted
    reason = owner.runtime.capability_reason('collection.sync', service.col)
    if reason:
        pytest.skip(reason)
    from anki.sync import SyncAuth, SyncOutput
    calls = []
    native_media = compat.collection_syncs_media(service.col)
    def sync_collection(auth, *media):
        calls.append(('sync', media[0] if native_media else None))
        return SyncOutput()
    monkeypatch.setattr(service.col, 'sync_collection', sync_collection)
    aqt.mw.pm.sync_auth = lambda: SyncAuth()
    aqt.mw.pm.media_syncing_enabled = lambda: enabled
    aqt.mw.pm.set_host_number = lambda value: None
    aqt.mw._refresh_after_sync = lambda: calls.append(('refresh',))
    # Before 23.10 the media syncer runs the media sync instead of monitoring it.
    media = lambda: calls.append(('media',))
    aqt.mw.media_syncer = SimpleNamespace(start_monitoring=media, start=media, is_syncing=lambda: False,
                                          _on_finished=lambda future: None)
    aqt.mw.taskman.with_progress = aqt.mw.taskman.run_in_background
    pending = owner.runtime.gui.collection_sync(includeMedia=requested)
    drain()
    assert pending.done and pending.error is None
    assert calls[0] == ('sync', requested and enabled if native_media else None)
    assert (('media',) in calls) == (requested and enabled)
    assert pending.value == {'collectionComplete': True, 'mediaComplete': requested and enabled}
    assert not owner.runtime.lifecycle_active


@pytest.mark.parametrize('failure,kind', [(None, None), ('Interrupted', 'cancelled'), ('NetworkError', 'ioError')])
def test_sync_reports_media_syncer_failures_before_23_10(admitted, monkeypatch, failure, kind):
    import aqt
    import aqt.qt
    from anki import errors
    owner, service, drain, work, notifications = admitted
    reason = owner.runtime.capability_reason('collection.sync', service.col)
    if reason or compat.collection_syncs_media(service.col):
        pytest.skip(reason or 'The collection reports media sync status from 23.10.')
    from anki.sync import SyncAuth, SyncOutput
    timers = owner.runtime.operations.schedule.__self__
    monkeypatch.setattr(aqt.qt, 'QTimer', SimpleNamespace(singleShot=lambda delay, callback: timers.append(callback)))
    monkeypatch.setattr(service.col, 'sync_collection', lambda auth: SyncOutput())
    aqt.mw.pm.sync_auth = lambda: SyncAuth()
    aqt.mw.pm.media_syncing_enabled = lambda: True
    aqt.mw.pm.set_host_number = lambda value: None
    aqt.mw._refresh_after_sync = lambda: None
    aqt.mw.taskman.with_progress = aqt.mw.taskman.run_in_background
    logged = []
    class MediaSyncer:
        # The 2.1.28-23.09 syncer logs failures and cancellation in _on_finished.
        _syncing = False
        def start(self):
            self._syncing = True
            def run():
                if failure:
                    error = getattr(errors, failure)
                    try:
                        raise error('media stopped', None, None, None)
                    except TypeError:
                        raise error('media stopped')
            aqt.mw.taskman.run_in_background(run, self._on_finished)
        def _on_finished(self, future):
            self._syncing = False
            logged.append(future.exception())
        def is_syncing(self):
            return self._syncing
    aqt.mw.media_syncer = MediaSyncer()
    pending = owner.runtime.gui.collection_sync(includeMedia=True)
    drain()
    assert len(logged) == 1 and pending.done and not owner.runtime.lifecycle_active
    assert '_on_finished' not in vars(aqt.mw.media_syncer)
    if kind:
        assert pending.error.kind == kind
    else:
        assert pending.value == {'collectionComplete': True, 'mediaComplete': True}


@pytest.mark.parametrize('failure', [None, 'network down'])
def test_legacy_sync_replies_after_sync_and_queues_other_requests(admitted, monkeypatch, failure):
    # ankimcp reports success from the reply; JL shows sync errors; yanki keeps going.
    import aqt
    owner, service, drain, work, notifications = admitted
    reason = owner.runtime.capability_reason('collection.sync', service.col)
    if reason:
        pytest.skip(reason)
    from anki.sync import SyncAuth, SyncOutput
    timers = owner.runtime.operations.schedule.__self__
    syncs = []
    def sync_collection(auth, *media):
        syncs.append(owner.runtime.lifecycle_active)
        if failure:
            raise Exception(failure)
        return SyncOutput()
    monkeypatch.setattr(service.col, 'sync_collection', sync_collection)
    aqt.mw.pm.sync_auth = lambda: SyncAuth()
    aqt.mw.pm.media_syncing_enabled = lambda: False
    aqt.mw.pm.set_host_number = lambda value: None
    aqt.mw._refresh_after_sync = lambda: None
    aqt.mw.taskman.with_progress = aqt.mw.taskman.run_in_background
    sync = owner.handler_async({'action': 'sync', 'version': 6})
    # Sync starts on a later tick; neither new nor waiting requests may slip in first.
    again = owner.handler_async({'action': 'sync', 'version': 6})
    decks = owner.handler_async({'action': 'deckNames', 'version': 6})
    version = owner.handler_async({'action': 'version', 'version': 6})
    assert version.value == {'result': 6, 'error': None}
    assert not owner.runtime.lifecycle_active and not work and len(timers) == 3
    for _ in range(3):
        timers.pop(0)()
    assert owner.runtime.lifecycle_active and not (sync.done or again.done or decks.done)
    drain()
    expected = {'result': None, 'error': failure} if failure else {'result': None, 'error': None}
    assert sync.value == again.value == expected and syncs == [True, True]
    assert decks.value == {'result': ['Default'], 'error': None}
    assert not owner.lifecycle_reserved and not owner.runtime.lifecycle_active


def test_http_idle_timeout_tracks_progress_and_waits_for_accepted_work(monkeypatch):
    from plugin import web

    now = [0.0]
    monkeypatch.setattr(web.time, 'monotonic', lambda: now[0])
    server_socket, peer = socket.socketpair()
    server_socket.setblocking(False)
    pending = Deferred()
    client = web.WebClient(server_socket, lambda request: pending)
    try:
        for at, chunk in ((9, b'POST / HTTP/1.1\r\n'), (18, b'Content-Length: 0\r\n'), (27, b'\r\n')):
            now[0] = at
            peer.sendall(chunk)
            assert client.advance()
        assert client.pending
        now[0] = 1000
        with monkeypatch.context() as waiting:
            waiting.setattr(web.select, 'select', lambda *args: pytest.fail('Pending work must not poll sockets.'))
            assert client.advance()  # Accepted work has no implicit deadline.
        pending.resolve(b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n')
        now[0] = 1001
        assert not client.advance()  # Reply receives a fresh write deadline.
        assert b'200 OK' in peer.recv(4096)
    finally:
        client.close()
        peer.close()


def test_http_stalled_response_times_out(monkeypatch):
    from plugin import web

    now = [0.0]
    monkeypatch.setattr(web.time, 'monotonic', lambda: now[0])
    server_socket, peer = socket.socketpair()
    server_socket.setblocking(False)
    # Limit each native write: Windows may buffer the whole response despite
    # SO_SNDBUF, so the buffer size alone cannot guarantee a pending reply.
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    transport = SimpleNamespace(fileno=server_socket.fileno, recv=server_socket.recv,
                                send=lambda data: server_socket.send(data[:4096]),
                                close=server_socket.close)
    client = web.WebClient(transport, lambda request: completed(b'x' * 1048576))
    try:
        peer.sendall(b'POST / HTTP/1.1\r\nContent-Length: 0\r\n\r\n')
        assert client.advance()
        for _ in range(20):
            assert client.advance()
        assert client.writeBuff
        now[0] = 11
        assert not client.advance()
        assert client.sock is None
    finally:
        client.close()
        peer.close()


@pytest.mark.parametrize('failure', [TypeError('not serializable'), ValueError('Out of range float values are not JSON compliant')])
def test_http_unexpected_handler_failure_returns_500(monkeypatch, failure):
    from plugin import web

    server_socket, peer = socket.socketpair()
    server_socket.setblocking(False)
    def handler(request):
        raise failure
    client = web.WebClient(server_socket, handler)
    try:
        peer.sendall(b'POST / HTTP/1.1\r\nContent-Length: 0\r\n\r\n')
        assert client.advance()
        assert not client.pending
        while client.advance():
            pass
        assert peer.recv(4096).startswith(b'HTTP/1.1 500 Internal Server Error')
    finally:
        client.close()
        peer.close()


@pytest.mark.parametrize('action', ['guiAddCards', 'guiAddNoteSetData'])
@pytest.mark.parametrize('reject', [False, True])
def test_legacy_gui_media_preparation_and_cleanup_are_queued(admitted, monkeypatch, action, reject):
    owner, service, drain, work, notifications = admitted
    service.store_bytes('draft.txt', b'original')
    directory = Path(service.col.media.dir())
    source = {'modelName': 'Basic', 'deckName': 'Default', 'fields': {'Front': 'GUI media', 'Back': 'answer'},
              'audio': [{'filename': 'draft.txt', 'data': base64.b64encode(b'replacement').decode(), 'fields': ['Back'],
                            'deleteExisting': True}]}
    dialog = SimpleNamespace(editor=SimpleNamespace())
    monkeypatch.setattr(owner.runtime.gui, 'add_dialog', lambda: dialog)
    def execute(method, params, operation_id=None):
        fields = params['note' if method == 'editors.openAdd' else 'patch']['fields']
        assert fields['Back'] == 'answer[sound:draft.txt]'
        if reject:
            raise ApiError('editorConflict', 'Draft changed during media preparation.')
        return {'id': 'editor', 'kind': 'add', 'variant': 'legacy', 'noteId': None,
                'noteType': service.summary(service.resolve({'name': 'Basic'}, 'noteType')),
                'deck': {'id': '1', 'name': 'Default'}, 'fields': fields, 'tags': [], 'dirty': True,
                'session': service.session}
    monkeypatch.setattr(owner.runtime.gui, 'execute', execute)
    pending = owner.handler_async({'action': action, 'version': 6, 'params': {'note': source}}, barrier=True)
    assert not pending.done and len(work) == 1
    assert (directory / 'draft.txt').read_bytes() == b'original'
    drain()
    assert pending.done
    if reject:
        assert 'Draft changed' in pending.value['error']
        assert (directory / 'draft.txt').read_bytes() == b'original'
    else:
        assert pending.value == {'result': 0 if action == 'guiAddCards' else True, 'error': None}
        assert (directory / 'draft.txt').read_bytes() == b'replacement'
    assert not list((directory.parent / '.anki-connect-media-journal').iterdir())


def test_native_package_io_failures_are_reported_without_closing_collection(native, tmp_path):
    owner, service = native
    broken = tmp_path / 'broken.apkg'
    broken.write_bytes(b'not a package')
    with pytest.raises(ApiError) as failure:
        call(service, 'packages.import', path=str(broken))
    assert failure.value.kind == 'ioError'
    assert 'invalid Zip archive' in str(failure.value)
    with pytest.raises(ApiError) as failure:
        call(service, 'packages.export', deck={'name': 'Default'}, path=str(tmp_path / 'missing' / 'output.apkg'))
    assert failure.value.kind == 'ioError'
    assert call(service, 'decks.list')[0]['name'] == 'Default'


def test_failed_media_journal_cleanup_can_be_recovered(native, monkeypatch):
    from plugin.media import MediaTransaction
    import shutil

    owner, service = native
    transaction = MediaTransaction(service)
    transaction.install('committed.txt', b'keep')
    with monkeypatch.context() as patch:
        patch.setattr(shutil, 'rmtree', lambda directory: (_ for _ in ()).throw(OSError('cleanup failed')))
        with pytest.raises(OSError, match='cleanup failed'):
            transaction.commit()
    assert transaction.path not in MediaTransaction._active
    MediaTransaction.recover(service)
    assert not transaction.path.exists()
    assert (Path(service.col.media.dir()) / 'committed.txt').read_bytes() == b'keep'


def test_legacy_gui_admission_does_not_read_collection_during_native_work(admitted, monkeypatch):
    owner, service, drain, work, notifications = admitted
    pending = owner.runtime.dispatcher.invoke('decks.create', {'name': 'Queued'})
    calls = []
    monkeypatch.setattr(owner.runtime.gui, 'execute', lambda *args, **kwargs: calls.append((args[0], pending.done)))
    replies = [owner.handler_async({'action': action, 'version': 6})
               for action in ('guiCurrentCard', 'guiAddCards', 'reloadCollection')]
    # Legacy GUI actions wait for the active native work instead of failing.
    assert not any(reply.done for reply in replies)
    assert not calls and len(work) == 1
    drain()
    assert pending.done and pending.error is None
    assert all(reply.done for reply in replies)
    assert calls and all(done for _, done in calls)


@pytest.mark.parametrize('path,size,status', [
    (b'/', 20 * 1048576, b'200 OK'),
    (b'/', 128 * 1048576 + 1, b'413 Payload Too Large'),
    (b'/api/v1', 16 * 1048576 + 1, b'413 Payload Too Large'),
])
def test_http_body_limits_stream_large_legacy_media_and_reply_with_cors(monkeypatch, path, size, status):
    # asbplayer, Memento, and mokuro send base64 clips above v1's request limit.
    import json
    from plugin import util, web

    monkeypatch.setattr(util, 'setting', lambda key: {**util.DEFAULT_CONFIG, 'apiKey': None}[key])
    received = []
    server = web.WebServer(lambda request: received.append(request) or completed(None),
                           lambda request, context: pytest.fail('oversized RPC body was handled'))
    envelope = b'{"action":"storeMediaFile","version":6,"params":{"filename":"clip.webm","data":"'
    body = envelope + b'A' * (size - len(envelope) - 3) + b'"}}'
    assert len(body) == size
    incoming = bytearray(b'POST ' + path + b' HTTP/1.1\r\nOrigin: chrome-extension://asbplayer\r\n'
                         b'Content-Length: ' + str(size).encode() + b'\r\n\r\n' + body)
    def recv(limit):
        # Every byte is already available, as with a fast local client.
        if not incoming:
            raise BlockingIOError
        chunk = bytes(incoming[:limit])
        del incoming[:limit]
        return chunk
    server_socket, peer = socket.socketpair()
    server_socket.setblocking(False)
    # EOF keeps select readable while recv supplies the in-memory request.
    # An unread marker byte makes Windows reset the connection on close.
    peer.shutdown(socket.SHUT_WR)
    transport = SimpleNamespace(fileno=server_socket.fileno, recv=recv,
                                send=server_socket.send, close=server_socket.close)
    client = web.WebClient(transport, server.handlerWrapper)
    total = len(incoming)
    try:
        assert client.advance() and not received
        if status == b'200 OK':
            # A poll reads up to 16 MiB instead of one 64 KiB chunk per Qt timer tick.
            assert total - len(incoming) == 16 * 1048576
        while client.advance():
            pass
        reply = peer.recv(65536)
        assert reply.startswith(b'HTTP/1.1 ' + status)
        assert b'Access-Control-Allow-Origin: chrome-extension://asbplayer' in reply
        if status == b'200 OK':
            assert len(received) == 1 and received[0]['params']['data'] == body[len(envelope):-3].decode()
        else:
            assert not received
            if path == b'/':
                assert json.loads(reply.split(b'\r\n\r\n', 1)[1]) == {
                    'result': None, 'error': 'request body exceeds 134217728 bytes'}
    finally:
        client.close()
        peer.close()

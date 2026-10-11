"""Regressions at native, GUI admission, transport, and installation boundaries."""
import base64
import json
import shutil
import socket
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugin.protocol import ApiError, Deferred, Dispatcher, completed
from tests_api.test_runtime import admitted, call, native
from tools.package_addon import build


def test_addon_archive_matches_native_install_requirements(tmp_path, monkeypatch):
    from aqt.addons import AddonManager, InstallOk, package_name_valid

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
    monkeypatch.setattr(manager, 'deleteAddon', lambda name: shutil.rmtree(addons / name))
    result = manager.install(str(tmp_path / 'addon.zip'))
    assert isinstance(result, InstallOk), result
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
    from anki.sync import SyncAuth, SyncOutput

    owner, service, drain, work, notifications = admitted
    calls = []
    monkeypatch.setattr(service.col, 'sync_collection',
                        lambda auth, media: calls.append(('sync', media)) or SyncOutput())
    aqt.mw.pm.sync_auth = lambda: SyncAuth()
    aqt.mw.pm.media_syncing_enabled = lambda: enabled
    aqt.mw.pm.set_host_number = lambda value: None
    aqt.mw._refresh_after_sync = lambda: calls.append(('refresh',))
    aqt.mw.media_syncer = SimpleNamespace(start_monitoring=lambda: calls.append(('media',)))
    aqt.mw.taskman.with_progress = aqt.mw.taskman.run_in_background
    pending = owner.runtime.gui.collection_sync(includeMedia=requested)
    drain()
    assert pending.done and pending.error is None
    assert calls[0] == ('sync', requested and enabled)
    assert (('media',) in calls) == (requested and enabled)
    assert pending.value == {'collectionComplete': True, 'mediaComplete': requested and enabled}
    assert not owner.runtime.lifecycle_active


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
    # Restrict the native socket buffer; the peer deliberately never reads.
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    client = web.WebClient(server_socket, lambda request: completed(b'x' * 1048576))
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


@pytest.mark.parametrize('action', ['guiAddCards', 'guiAddNoteSetData'])
@pytest.mark.parametrize('reject', [False, True])
def test_legacy_gui_media_preparation_and_cleanup_are_queued(admitted, monkeypatch, action, reject):
    owner, service, drain, work, notifications = admitted
    service.store_bytes('draft.txt', b'original')
    directory = Path(service.col.media.dir())
    source = {'modelName': 'Basic', 'deckName': 'Default', 'fields': {'Front': 'GUI media', 'Back': 'answer'},
              'audio': [{'filename': 'draft.txt', 'data': base64.b64encode(b'replacement').decode(), 'fields': ['Back']}]}
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
    monkeypatch.setattr(owner.runtime.gui, 'execute', lambda *args, **kwargs: calls.append(args))
    for action in ('guiCurrentCard', 'guiAddCards', 'reloadCollection'):
        reply = owner.handler_async({'action': action, 'version': 6})
        assert reply.done and reply.value['error'] == 'A collection operation is active.'
    assert not calls and len(work) == 1
    drain()
    assert pending.done and pending.error is None

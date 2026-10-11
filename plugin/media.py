"""Recoverable, request-owned media replacements for both API transports."""
import hashlib
import json
import shutil
import uuid
from pathlib import Path

from .protocol import ApiError


class MediaTransaction:
    _active = set()
    def __init__(self, service):
        self.service = service
        self.media = Path(service.col.media.dir())
        self.root = self.media.parent / '.anki-connect-media-journal'
        self.root.mkdir(exist_ok=True)
        self.recover(service, self.root)
        self.path = self.root / uuid.uuid4().hex
        self.path.mkdir()
        self._active.add(self.path)
        self.entries = {}
        self.committed = False
        try:
            self.persist()
        except BaseException:
            self._active.discard(self.path)
            raise

    def persist(self):
        pending = self.path / 'manifest.tmp'
        pending.write_text(json.dumps({'committed': self.committed, 'entries': self.entries}))
        pending.replace(self.path / 'manifest.json')

    def install(self, filename, data, skip=None, collision='replace'):
        filename = self.service.media_filename(filename)
        if skip and hashlib.new(skip['algorithm'], data).hexdigest() == skip['digest']:
            return None
        target = self.media / filename
        if filename not in self.entries:
            backup = None
            if target.is_file():
                backup = uuid.uuid4().hex
                (self.path / backup).write_bytes(target.read_bytes())
            self.entries[filename] = {'backup': backup, 'sha256': hashlib.sha256(data).hexdigest()}
        else:
            self.entries[filename]['sha256'] = hashlib.sha256(data).hexdigest()
        # Journal the original before the native manager moves it to trash.
        self.persist()
        existing_names = {path.name for path in self.media.iterdir()}
        actual = self.service._store_bytes(filename, data, collision)['filename']
        if actual != filename:
            entry = self.entries.pop(filename)
            backup = None
            if actual in existing_names:
                backup = uuid.uuid4().hex
                (self.path / backup).write_bytes((self.media / actual).read_bytes())
            self.entries[actual] = {'backup': backup, 'sha256': entry['sha256']}
            if entry['backup']:
                self.entries[filename] = entry
            self.persist()
        return actual

    def commit(self):
        self.committed = True
        try:
            self.persist()
            shutil.rmtree(self.path)
        finally:
            self._active.discard(self.path)

    def rollback(self):
        try:
            failures = self.restore(self.service, self.path, self.entries)
            if not failures:
                shutil.rmtree(self.path)
            return failures
        finally:
            self._active.discard(self.path)

    @staticmethod
    def restore(service, directory, entries, interrupted=False):
        media = Path(service.col.media.dir())
        failures = []
        for name, entry in entries.items():
            try:
                service.media_filename(name)
                destination = media / name
                backup = directory / entry['backup'] if entry['backup'] else None
                old = backup.read_bytes() if backup else None
                current = destination.read_bytes() if destination.is_file() else None
                if current == old:
                    continue
                if current is not None and hashlib.sha256(current).hexdigest() != entry['sha256']:
                    raise ApiError('conflict', 'Media changed outside this request: ' + name)
                if interrupted and service.col.db.scalar('select 1 from notes where instr(flds,?) > 0 limit 1', name):
                    # The native note commit may have completed before the journal
                    # was marked committed. Keep referenced media conservatively.
                    continue
                if current is not None:
                    service.col.media.trash_files([name])
                if old is not None:
                    actual = service.col.media.write_data(name, old)
                    if actual != name:
                        raise ApiError('ioError', 'Backup restored under a different name.')
            except Exception as error:
                failures.append({'filename': name, 'error': str(error)})
        return failures

    @classmethod
    def recover(cls, service, root=None):
        root = root or Path(service.col.media.dir()).parent / '.anki-connect-media-journal'
        if not root.exists():
            return
        failures = []
        for directory in root.iterdir():
            if not directory.is_dir() or directory in cls._active:
                continue
            manifest = directory / 'manifest.json'
            if not manifest.exists():
                # Acquisition-only work has not changed collection media.
                shutil.rmtree(directory)
                continue
            try:
                record = json.loads(manifest.read_text())
                unresolved = [] if record['committed'] else cls.restore(service, directory, record['entries'], interrupted=True)
                failures.extend(unresolved)
                if not unresolved:
                    shutil.rmtree(directory)
            except Exception as error:
                failures.append({'journal': directory.name, 'error': str(error)})
        if failures:
            raise ApiError('ioError', 'Interrupted media replacements need recovery.', {'failures': failures})

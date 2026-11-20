#!/usr/bin/env python3
"""Select Anki releases from tools/anki_matrix.json and prepare their test environments.

  anki_env.py select [--all] [VERSION ...]   print selected versions, one per line
  anki_env.py prepare CACHE UV VERSION       create/update an environment; print its interpreter

With no versions, `select` returns the latest stable release; `--all` returns every
release this platform can prepare. Releases without wheels install the modules of
their frozen GitHub builds (Linux x86_64). Versions may be
GitHub release tags (26.09.4) or PyPI versions (26.9.4); versions missing from
the matrix are installed unconstrained with the latest release's Python.
Uses only the standard library so every bootstrap interpreter can run it.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATRIX = ROOT / 'tools' / 'anki_matrix.json'
# uv no longer lists CPython 3.7, which the only Anki 2.1.24 backend wheel needs.
# Feed it the last python-build-standalone 3.7 builds with pinned digests.
PYTHON37_BASE = 'https://github.com/astral-sh/python-build-standalone/releases/download/20200822/'
PYTHON37 = {
    ('win32', 'x86_64'): ('cpython-3.7.9-x86_64-pc-windows-msvc-shared-pgo-20200823T0118.tar.zst',
                          '8769a244cfe54c32c5253b78897a0fe82fe419dfde653b1afc3f5f20594cca89', 'windows', 'none'),
    ('darwin', 'x86_64'): ('cpython-3.7.9-x86_64-apple-darwin-pgo-20200823T0123.tar.zst',
                           'e50a03a0db1f49f4d8521fa531f67390652457c83ca9c20b1dcbaf2e36770b1b', 'macos', 'none'),
}
# Neither uv nor python-build-standalone offers CPython 3.6, which frozen Anki 2.1.15
# bundled. The Linux 3.7 standalone build statically exports an old Xlib that crashes
# Qt's X11 probes, so Linux takes both from locked conda-forge environments.
MICROMAMBA = ('https://github.com/mamba-org/micromamba-releases/releases/download/2.10.0-0/micromamba-linux-64',
              '701f39c06f8e6a670a0e186c8479b9e5c0502a2f0cda6cef65d83bdd2875e8bd')
CONDA_PYTHON_LOCKS = {'3.6': ROOT / 'tools' / 'python36-linux-64.lock',
                      '3.7': ROOT / 'tools' / 'python37-linux-64.lock'}


def platform_key():
    return 'win32' if os.name == 'nt' else 'darwin' if sys.platform == 'darwin' else 'linux'


def machine():
    import platform
    value = platform.machine().lower()
    return {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(value, value)


def normalize(version):
    """Reduce a release tag or PyPI version to a comparable public version."""
    public = version.split('+')[0].lower()
    match = re.match(r'^(\d+(?:\.\d+)*)((?:a|b|rc)\d+)?$', public)
    if not match:
        return public
    release = '.'.join(str(int(part)) for part in match.group(1).split('.'))
    return release + (match.group(2) or '')


def load():
    return json.loads(MATRIX.read_text())


def find(version, document=None):
    document = document or load()
    wanted = normalize(version)
    for entry in document['releases']:
        if normalize(entry['version']) == wanted or normalize(entry['release']) == wanted:
            return entry
    for entry in document['excluded']:
        if normalize(entry['release']) == wanted:
            raise SystemExit(f"Anki {version} is excluded from the matrix: {entry['reason']}")
    latest = document['releases'][-1]
    return {'release': version, 'version': wanted, 'prerelease': False, 'python': latest['python'],
            'requirements': [f'anki=={wanted}', f'aqt=={wanted}'], 'constraints': [], 'platformConstraints': {}}


def preparable(entry):
    """Whether this platform can create the release's environment."""
    key = (platform_key(), machine())
    if 'bundle' in entry:
        return key == ('linux', 'x86_64')  # Frozen builds need their Linux x86_64 backend and Python.
    return entry['python'] != '3.7' or key in PYTHON37 or key == ('linux', 'x86_64')


def select(arguments):
    document = load()
    every = '--all' in arguments
    versions = [argument for argument in arguments if argument != '--all']
    if every and versions:
        raise SystemExit('Cannot combine --all with explicit Anki versions.')
    if every:
        entries = [entry for entry in document['releases'] if preparable(entry)]
        skipped = [entry['version'] for entry in document['releases'] if not preparable(entry)]
        if skipped:
            print('Skipping releases this platform cannot run: ' + ', '.join(skipped), file=sys.stderr)
    elif versions:
        entries = [find(version, document) for version in versions]
    else:
        entries = [[entry for entry in document['releases'] if not entry['prerelease']][-1]]
    for entry in entries:
        print(entry['version'])


def run(command, **options):
    print('+ ' + ' '.join(str(part) for part in command), file=sys.stderr)
    subprocess.run([str(part) for part in command], check=True, stdout=sys.stderr, **options)


def interpreter(environment):
    windows = environment / 'Scripts' / 'python.exe'
    return windows if windows.exists() else environment / 'bin' / 'python'


def install_python37(cache, uv):
    key = (platform_key(), machine())
    if key not in PYTHON37:
        raise SystemExit('No CPython 3.7 build is available for this platform; Anki 2.1.24 needs it.')
    filename, digest, system, libc = PYTHON37[key]
    metadata = cache / 'python-downloads-3.7.json'
    metadata.write_text(json.dumps({f'cpython-3.7.9-{system}-x86_64-{libc}': {
        'name': 'cpython', 'arch': {'family': 'x86_64', 'variant': None}, 'os': system, 'libc': libc,
        'major': 3, 'minor': 7, 'patch': 9, 'prerelease': '', 'url': PYTHON37_BASE + filename,
        'sha256': digest, 'variant': None, 'build': '20200822'}}))
    run([uv, 'python', 'install', '--no-bin', '--python-downloads-json-url', metadata, '3.7.9'])
    found = subprocess.run([str(uv), 'python', 'find', '--managed-python', '3.7.9'], check=True,
                           stdout=subprocess.PIPE, universal_newlines=True)
    return found.stdout.strip()


def install_conda_python(cache, python):
    if (platform_key(), machine()) != ('linux', 'x86_64'):
        raise SystemExit('Locked conda-forge CPython ' + python + ' is only provisioned on Linux x86_64.')
    prefix = cache / 'python' / ('conda-cpython-' + python)
    executable = prefix / 'bin' / ('python' + python)
    stamp = prefix / 'anki-lock.txt'
    lock = CONDA_PYTHON_LOCKS[python].read_text()
    if executable.exists() and stamp.exists() and stamp.read_text() == lock:
        return executable
    url, digest = MICROMAMBA
    micromamba = fetch_artifact(cache, {'url': url, 'sha256': digest})
    micromamba.chmod(0o755)
    run([micromamba, 'create', '--yes', '--quiet', '--root-prefix', cache / 'conda', '--prefix', prefix,
         '--file', CONDA_PYTHON_LOCKS[python]])
    stamp.write_text(lock)
    return executable


def base_interpreter(cache, uv, python):
    if python in CONDA_PYTHON_LOCKS and (python == '3.6' or (platform_key(), machine()) == ('linux', 'x86_64')):
        return install_conda_python(cache, python)
    return install_python37(cache, uv) if python == '3.7' else python


def fetch_artifact(cache, artifact):
    """Download an artifact once, verified against its published or pinned checksum."""
    import hashlib
    import urllib.request
    target = cache / 'bundles' / artifact['url'].rsplit('/', 1)[1]

    def digest(path):
        hasher = hashlib.sha256()
        with open(path, 'rb') as file:
            for block in iter(lambda: file.read(1 << 20), b''):
                hasher.update(block)
        return hasher.hexdigest()

    if not target.exists() or digest(target) != artifact['sha256']:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + '.part')
        print('+ download ' + artifact['url'], file=sys.stderr)
        with urllib.request.urlopen(artifact['url'], timeout=120) as response, open(partial, 'wb') as file:
            while True:
                block = response.read(1 << 20)
                if not block:
                    break
                file.write(block)
        if digest(partial) != artifact['sha256']:
            partial.unlink()
            raise SystemExit(artifact['url'] + ' does not match its published checksum.')
        partial.replace(target)
    return target


def unpack(archive, destination):
    import shutil
    import tarfile
    if destination.exists():
        return destination
    partial = destination.with_name(destination.name + '.part')
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    if archive.name.endswith('.dmg'):
        # Only the frozen executable is needed; HFS metadata elsewhere makes 7-Zip report errors.
        run([shutil.which('7z') or '7z', 'x', '-y', '-bd', '-o' + str(partial), '-ir!*.app/Contents/MacOS/Anki', archive])
    else:
        with tarfile.open(archive) as tar:
            tar.extractall(partial, **({'filter': 'tar'} if hasattr(tarfile, 'tar_filter') else {}))
    partial.replace(destination)
    return destination


def frozen_modules(executable, packages):
    """Yield (name, is_package, pyc) for packages in a PyInstaller executable's PYZ archive."""
    import marshal
    import struct
    import zlib
    data = executable.read_bytes()
    end = data.rfind(b'MEI\014\013\012\013\016')
    length, toc_offset, toc_length = struct.unpack('!iii', data[end + 8:end + 20])
    base = end + 88 - length
    position, archive = base + toc_offset, None
    while position < base + toc_offset + toc_length:
        size, offset, stored, _, compressed, kind = struct.unpack('!iiiiBc', data[position:position + 18])
        if kind == b'z':
            archive = data[base + offset:base + offset + stored]
            archive = zlib.decompress(archive) if compressed else archive
        position += size
    if archive is None or archive[:4] != b'PYZ\0':
        raise SystemExit(f'{executable} has no PyInstaller module archive.')
    magic = archive[4:8]
    # Sourceless .pyc: magic, flags from Python 3.7, then unchecked mtime and size.
    header = magic + bytes(12 if int.from_bytes(magic[:2], 'little') >= 3390 else 8)
    toc = marshal.loads(archive[struct.unpack('!i', archive[8:12])[0]:])
    # PyInstaller 3 stored the table as a dict.
    for name, (is_package, offset, stored) in toc.items() if isinstance(toc, dict) else toc:
        if name.split('.')[0] in packages:
            yield name, is_package, header + zlib.decompress(archive[offset:offset + stored])


def install_bundle(cache, entry, executable):
    """Install a release that published only frozen builds: its own anki/aqt bytecode,
    and the Rust backend and web data from a Linux build of the same code."""
    import shutil
    bundle = entry['bundle']
    if platform_key() != 'linux' or machine() != 'x86_64':
        raise SystemExit(f"Anki {entry['version']} has no wheels; its backend is only usable on Linux x86_64.")
    paths = subprocess.run([str(executable), '-c', 'import sys, sysconfig; print(sysconfig.get_paths()["purelib"]); print(sys.prefix)'],
                           check=True, stdout=subprocess.PIPE, universal_newlines=True).stdout.split('\n')
    purelib, prefix = Path(paths[0]), Path(paths[1])
    trees = {}
    for role in ('modules', 'backend'):
        artifact = bundle.get(role)
        if artifact:
            archive = fetch_artifact(cache, artifact)
            trees[role] = unpack(archive, cache / 'bundles' / (re.sub(r'\.(tar\.bz2|dmg)$', '', archive.name) + '-files'))
    frozen = [path for path in trees['modules'].rglob('*') if path.is_file() and path.name.lower() in ('anki', 'runanki')
              and b'MEI\014\013\012\013\016' in path.read_bytes()]
    if len(frozen) != 1:
        raise SystemExit(f"Expected one frozen Anki executable in {trees['modules']}, found {frozen}.")
    records = {'anki': [], 'aqt': []}
    for name in records:
        shutil.rmtree(purelib / name, ignore_errors=True)
    for name, is_package, pyc in frozen_modules(frozen[0], records):
        parts = name.split('.')
        target = purelib.joinpath(*parts, '__init__.pyc') if is_package else purelib.joinpath(*parts[:-1], parts[-1] + '.pyc')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pyc)
        records[parts[0]].append(target.relative_to(purelib).as_posix())
    native = trees.get('backend', trees['modules'])
    backends = list(native.rglob('ankirspy.*.so'))
    if 'backend' in bundle:
        if len(backends) != 1:
            raise SystemExit(f'Expected one ankirspy extension in {native}, found {backends}.')
        shutil.copy2(backends[0], purelib / backends[0].name)
        records['ankirspy'] = [backends[0].name]
    if bundle.get('backend', bundle['modules']) != bundle['modules']:
        # The backend refuses Python code from another build. That build differs
        # only in its version, so keep the release's version with the backend's hash.
        script = ('import importlib.util, sys; import ankirspy\n'
                  'spec = importlib.util.spec_from_file_location("buildinfo", sys.argv[1])\n'
                  'info = importlib.util.module_from_spec(spec); spec.loader.exec_module(info)\n'
                  'print(info.version); print(ankirspy.buildhash())\n')
        for package in ('anki', 'aqt'):
            compiled = purelib / package / 'buildinfo.pyc'
            version, buildhash = subprocess.run([str(executable), '-c', script, str(compiled)], check=True,
                                                stdout=subprocess.PIPE, universal_newlines=True).stdout.split()
            compiled.unlink()
            (purelib / package / 'buildinfo.py').write_text(f'version = {version!r}\nbuildhash = {buildhash!r}\n')
            records[package][records[package].index(f'{package}/buildinfo.pyc')] = f'{package}/buildinfo.py'
    data = next(native.rglob('aqt_data'), None)
    if data is not None:
        # aqt looks for sys.prefix/aqt_data, as a wheel installs it.
        shutil.rmtree(prefix / 'aqt_data', ignore_errors=True)
        shutil.copytree(data, prefix / 'aqt_data')
    else:
        # Earlier aqt looks for web and locale beside its packages, as when frozen.
        for name in ('web', 'locale'):
            source = frozen[0].parent / name
            if source.is_dir():
                shutil.rmtree(purelib / name, ignore_errors=True)
                shutil.copytree(source, purelib / name)
                records['aqt'] += [path.relative_to(purelib).as_posix()
                                   for path in sorted((purelib / name).rglob('*')) if path.is_file()]
    for name, files in records.items():
        metadata = purelib / f"{name}-{entry['version']}.dist-info"
        shutil.rmtree(metadata, ignore_errors=True)
        metadata.mkdir()
        (metadata / 'METADATA').write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {entry['version']}\n")
        (metadata / 'INSTALLER').write_text('anki-connect-tests\n')
        (metadata / 'WHEEL').write_text('Wheel-Version: 1.0\nGenerator: anki-connect-tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        listed = files + [f'{metadata.name}/{part}' for part in ('METADATA', 'INSTALLER', 'WHEEL', 'RECORD')]
        (metadata / 'RECORD').write_text(''.join(path + ',,\n' for path in listed))


def prepare(cache, uv, version):
    cache, uv = Path(cache), Path(uv)
    entry = find(version)
    environment = cache / 'envs' / ('anki-' + entry['version'])
    python = entry['python']
    configuration = environment / 'pyvenv.cfg'
    if configuration.exists():
        found = re.search(r'^version(?:_info)?\s*=\s*(\d+\.\d+)', configuration.read_text(), re.M)
        if not found or found.group(1) != python:
            # Environments from earlier runners may use a different interpreter.
            run([uv, 'venv', '--clear', '--python', base_interpreter(cache, uv, python), environment])
    else:
        run([uv, 'venv', '--python', base_interpreter(cache, uv, python), environment])
    executable = interpreter(environment)
    constraints = environment / 'anki-constraints.txt'
    pins = entry['constraints'] + entry['platformConstraints'].get(platform_key(), [])
    if python == '3.7':
        # Markdown 3.3 predates importlib-metadata 5's EntryPoints API, which pytest would pull in.
        pins.append('importlib-metadata<5')
    constraints.write_text(''.join(pin + '\n' for pin in pins))
    # aqt 2.1.24 requires PyAudio, which builds against system PortAudio headers.
    # Recording is never imported by the add-on or tests; a false marker drops it.
    overrides = environment / 'anki-overrides.txt'
    released = re.sub(r'\.post\d+$', '', entry['version'])
    options = {}
    if released == entry['version']:
        overrides.write_text('pyaudio; python_version < "0"\n')
    else:
        # The yanked 2.1.59.post1 wheels carry 2.1.59 metadata, which aqt requires.
        overrides.write_text('pyaudio; python_version < "0"\nanki=={}\n'.format(entry['version']))
        options['env'] = dict(os.environ, UV_SKIP_WHEEL_FILENAME_CHECK='1')
    # pytest 8 needs Python 3.8; 2.1.24's backend only exists for 3.7 and 2.1.15 bundled 3.6.
    tools = {'3.6': ['pytest>=7.0,<7.1'], '3.7': ['pytest>=7.4,<8']}.get(python, ['pytest>=8'])
    run([uv, 'pip', 'install', '--python', executable, '--constraint', constraints,
         '--override', overrides, *entry['requirements'], *tools], **options)
    if 'bundle' in entry:
        install_bundle(cache, entry, executable)
    checked = subprocess.run([str(uv), 'pip', 'check', '--python', str(executable)],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    print(checked.stdout, end='', file=sys.stderr)
    problems = [line for line in checked.stdout.splitlines() if line.startswith('The package')]
    if checked.returncode and (not problems or any('`pyaudio`' not in line for line in problems)):
        raise SystemExit('Installed packages are incompatible.')
    if problems or 'bundle' in entry:
        # aqt before 2.1.28 imports PyAudio at startup; recording is unused by tests.
        purelib = subprocess.run([str(executable), '-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])'],
                                 check=True, stdout=subprocess.PIPE, universal_newlines=True).stdout.strip()
        Path(purelib, 'pyaudio.py').write_text(
            '"""Test stub for PyAudio, which needs PortAudio headers to build."""\n'
            'paInt16 = 8\n\n\nclass PyAudio:\n    def __init__(self):\n'
            '        raise OSError("PyAudio is unavailable in this test environment.")\n')
    listed = subprocess.run([str(uv), 'pip', 'list', '--format', 'json', '--python', str(executable)],
                            check=True, stdout=subprocess.PIPE, universal_newlines=True)
    installed = {package['name'].lower(): package['version'] for package in json.loads(listed.stdout)}
    for name in ('anki', 'aqt'):
        if normalize(installed.get(name, '')) not in (normalize(entry['version']), normalize(released)):
            raise SystemExit(f"{name}: expected {entry['version']}, installed {installed.get(name)}")
        print(f'{name}=={installed[name]} (Python {python})', file=sys.stderr)
    print(executable.as_posix())


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == 'select':
        select(sys.argv[2:])
    elif len(sys.argv) == 5 and sys.argv[1] == 'prepare':
        prepare(*sys.argv[2:])
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main()

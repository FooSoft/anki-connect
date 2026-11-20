#!/usr/bin/env python3
"""Regenerate tools/anki_matrix.json from Anki's GitHub releases.

Every published GitHub release becomes a test environment: the matching PyPI
anki/aqt version, the Python minor version the official build bundled, and
dependency pins taken from that tag's own lockfiles. Old packages are often
incompatible with current dependency releases, and the bundled versions are
what add-ons meet in practice (for example jsonschema 3.2.0 before 2.1.50).
Releases without PyPI wheels are installed from their frozen GitHub builds:
the released anki/aqt bytecode, plus the Rust backend and web data from the
Linux build of the same code. Releases that cannot run are recorded as excluded.

Requires the `packaging` distribution and network access.
"""
import ast
import json
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from packaging.markers import Marker
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'tools' / 'anki_matrix.json'
RELEASES_URL = 'https://api.github.com/repos/ankitects/anki/releases?per_page=100&page={}'
RAW_URL = 'https://raw.githubusercontent.com/ankitects/anki/{}/{}'
PYPI_URL = 'https://pypi.org/pypi/{}/json'
PLATFORMS = ('linux', 'win32', 'darwin')
# Runtime distributions pinned from pip-compile lockfiles. Those files mix
# runtime and development tools; test-runner dependencies stay unconstrained.
RUNTIME = {
    'attrs', 'beautifulsoup4', 'blinker', 'certifi', 'chardet', 'charset-normalizer', 'click',
    'decorator', 'distro', 'flask', 'flask-cors', 'idna', 'itsdangerous', 'jinja2', 'jsonschema',
    'markdown', 'markupsafe', 'orjson', 'pip-system-certs', 'protobuf', 'psutil', 'pyrsistent',
    'pysocks', 'pywin32', 'requests', 'send2trash', 'six', 'soupsieve', 'stringcase', 'urllib3',
    'waitress', 'werkzeug', 'winrt', 'wrapt',
}
# Test tooling installed into every environment; never constrained by Anki locks.
TEST_TOOLS = {'pytest', 'pluggy', 'iniconfig', 'packaging', 'exceptiongroup', 'tomli',
              'colorama', 'typing-extensions', 'importlib-metadata', 'zipp'}
# 2.1.23 was a macOS-only rebuild of 2.1.22; its only Rust change is compiled
# for Apple targets, so 2.1.22's Linux backend is the same code.
BACKEND_FROM = {'2.1.23': '2.1.22'}
# Tags before 2.1.20 pin no Qt; use the PyQt matching the Qt their frozen builds shipped.
FROZEN_QT = {'2.1.15': '5.12.1'}
QT_PACKAGE = re.compile(r'^pyqt(5|6)(-|$)|^pyqtwebengine')


def fetch(url, required=True):
    request = urllib.request.Request(url, headers={'User-Agent': 'anki-connect-matrix'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404 and not required:
            return None
        raise


def tag_file(tag, path):
    data = fetch(RAW_URL.format(tag, path), required=False)
    return data.decode() if data is not None else None


def canonical(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def parse_requirements(text):
    pins = []
    for line in text.splitlines():
        match = re.match(r'^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?==([^\s;\\]+)\s*(?:;\s*([^#\\]+?))?\s*(?:\\|#|$)', line)
        if match:
            name, _, version, marker = match.groups()
            pins.append((canonical(name), version, marker.strip() if marker else None))
    return pins


def requirement(name, version, marker=None):
    return f'{name}=={version}' + (f'; {marker}' if marker else '')


def uv_lock_pins(text, python):
    lock = tomllib.loads(text)
    packages = {}
    for package in lock['package']:
        packages.setdefault(canonical(package['name']), []).append(package)
    environment = {'python_full_version': python + '.0', 'python_version': python}

    def applicable(package, platform):
        markers = package.get('resolution-markers')
        if not markers:
            return True
        return any(Marker(marker).evaluate({**environment, 'sys_platform': platform}) for marker in markers)

    # Runtime closure of anki plus aqt with its default "qt" extra.
    pending = ['anki', 'aqt']
    seen = set()
    while pending:
        name = pending.pop()
        if name in seen or name not in packages:
            continue
        seen.add(name)
        for package in packages[name]:
            dependencies = list(package.get('dependencies', []))
            if name == 'aqt':
                dependencies += package.get('optional-dependencies', {}).get('qt', [])
            pending.extend(canonical(dependency['name']) for dependency in dependencies)
    common = []
    by_platform = {platform: [] for platform in PLATFORMS}
    for name in sorted(seen - {'anki', 'aqt'} - TEST_TOOLS):
        for platform in PLATFORMS:
            candidates = [package for package in packages[name] if applicable(package, platform)]
            if len(candidates) == 1:
                by_platform[platform].append(requirement(name, candidates[0]['version']))
    for pin in by_platform['linux']:
        if all(pin in by_platform[platform] for platform in PLATFORMS):
            common.append(pin)
    platform_pins = {platform: [pin for pin in pins if pin not in common] for platform, pins in by_platform.items()}
    return common, platform_pins


def text_lock_pins(texts, runtime_only):
    pins = []
    for text in texts:
        for name, version, marker in parse_requirements(text):
            if name in TEST_TOOLS or (runtime_only and name not in RUNTIME and not QT_PACKAGE.match(name)):
                continue
            pins.append(requirement(name, version, marker))
    return list(dict.fromkeys(pins))


def pyqt5_pins(tag):
    for path in ('pip/pyqt5/install_pyqt5.py',):
        text = tag_file(tag, path)
        if text:
            return [requirement(canonical(name), version) for name, version in
                    re.findall(r'"(pyqt5|pyqtwebengine|pyqt5_sip)==([^"]+)"', text)]
    text = tag_file(tag, 'qt/requirements.qt')
    if not text and tag in FROZEN_QT:
        # PyQt5 5.12 requires its own sip 4.19 series.
        return [requirement(name, FROZEN_QT[tag]) for name in ('pyqt5', 'pyqtwebengine')]
    pins = [requirement(name, version) for name, version, _ in parse_requirements(text or '')]
    # Pre-Bazel builds left sip unpinned; use the first locked build's sip, which
    # still has wheels for Python 3.7 and 3.8.
    return pins + ['pyqt5-sip==12.8.1']


def qt6_pins(tag):
    # Probe raw files rather than the rate-limited contents API. The official
    # build bundles the newest Qt 6 lockfile present at the tag.
    files = {platform: tag_file(tag, f'python/requirements.qt6_{suffix}.txt')
             for platform, suffix in (('linux', 'lin'), ('win32', 'win'), ('darwin', 'mac'))}
    if all(files.values()):
        return [], {platform: text_lock_pins([text], False) for platform, text in files.items()}
    for path in ['python/pyqt/6/requirements.txt'] + [
            path for minor in range(12, 1, -1)
            for path in (f'python/requirements.qt6_{minor}.txt', f'python/pyqt/6_{minor}/requirements.txt')]:
        text = tag_file(tag, path)
        if text:
            return text_lock_pins([text], False), {}
    raise RuntimeError(f'No Qt 6 lockfile found for {tag}')


def available_versions(name, cache={}):
    if name not in cache:
        data = json.loads(fetch(PYPI_URL.format(name)))
        cache[name] = {Version(version) for version, files in data['releases'].items()
                       if files and not all(file.get('yanked') for file in files)}
    return cache[name]


def resolve_pin(pin):
    """Replace pins whose files were deleted from PyPI (old Qt wheels) with the nearest patch release."""
    match = re.match(r'^([a-z0-9-]+)==([^;\s]+)(.*)$', pin)
    name, version, rest = match.groups()
    pinned = Version(version)
    versions = available_versions(name)
    if pinned in versions:
        return pin
    same_minor = sorted(candidate for candidate in versions if candidate.release[:2] == pinned.release[:2])
    if not same_minor:
        raise RuntimeError(f'No published replacement for {pin}')
    newer = [candidate for candidate in same_minor if candidate > pinned]
    replacement = newer[0] if newer else same_minor[-1]
    print(f'  {name}=={version} is unavailable; using {replacement}', file=sys.stderr)
    return f'{name}=={replacement}{rest}'


def checksums(release):
    asset = next((asset for asset in release['assets'] if asset['name'].endswith('-checksums.txt')), None)
    text = fetch(asset['browser_download_url']).decode() if asset else ''
    return {name: digest for digest, name in re.findall(r'^([0-9a-f]{64})\s+(\S+)$', text, re.M)}


def artifact(release, suffix):
    names = {asset['name']: asset['browser_download_url'] for asset in release['assets']}
    name = next((name for name in names if name.endswith(suffix)), None)
    digest = checksums(release).get(name) if name else None
    return {'url': names[name], 'sha256': digest} if digest else None


def source_requirements(tag):
    """Runtime requirements declared at a tag before PyPI publishing began."""
    texts = [tag_file(tag, 'pylib/setup.py'), tag_file(tag, 'qt/setup.py')]
    if not any(texts):
        return [line.strip() for line in (tag_file(tag, 'requirements.txt') or '').splitlines() if line.strip()]
    found = []
    for text in filter(None, texts):
        block = re.search(r'install_requires\s*=\s*(\[.*?\])', text, re.S)
        found += ast.literal_eval(block.group(1)) if block else []
    # Old setup files spell the marker sys.platform, which current installers reject.
    return list(dict.fromkeys(item.replace('sys.platform', 'sys_platform') for item in found))


def bundle_entry(release, releases, version, fallback_lock):
    tag = release['tag_name']
    modules = artifact(release, '-linux-amd64.tar.bz2') or artifact(release, '-mac.dmg')
    if not modules:
        return None, 'No anki/aqt wheels or verifiable frozen build were published for this release.'
    bundle = {'modules': modules}
    if version >= Version('2.1.20'):
        source = next(other for other in releases if other['tag_name'] == BACKEND_FROM.get(tag, tag))
        backend = artifact(source, '-linux-amd64.tar.bz2')
        if not backend:
            return None, 'No Linux build of this release\'s Rust backend was published.'
        bundle['backend'] = backend
    requirements = [requirement for requirement in source_requirements(tag)
                    if canonical(re.split('[ ;<>=!]', requirement)[0]) != 'pyaudio']
    pins = text_lock_pins([fallback_lock], True) + pyqt5_pins(tag)
    return {'release': tag, 'version': str(version), 'prerelease': bool(release['prerelease']),
            'python': python_for(version), 'bundle': bundle,
            'requirements': requirements + ['pyqt5', 'pyqtwebengine'],
            'constraints': [resolve_pin(pin) for pin in pins], 'platformConstraints': {}}, None


def python_for(version):
    if version < Version('2.1.20'):
        return '3.6'  # The frozen 2.1.15 build bundled CPython 3.6.
    if version < Version('2.1.24'):
        return '3.8'  # The frozen builds' ankirspy is cp38.
    if version < Version('2.1.25'):
        return '3.7'  # The only ankirspy wheel for 2.1.24 is cp37.
    if version < Version('2.1.50'):
        return '3.8'
    if version < Version('25.7'):
        return '3.9'
    return None


def describe(release, releases, pypi_versions, fallback_lock):
    tag = release['tag_name']
    try:
        version = Version(tag)
    except InvalidVersion:
        return None, f'Tag {tag} is not a PEP 440 version.'
    if version.major == 2 and version.minor == 0:
        return None, 'Anki 2.0 runs Python 2 and Qt 4 with a separate add-on platform.'
    candidates = [published for key, published in pypi_versions.items() if Version(key).public == version.public]
    if not candidates:
        return bundle_entry(release, releases, version, fallback_lock)
    python = python_for(version)
    # 2.1.59 was replaced within a day; its yanked wheels are 2.1.59.post1.
    version = candidates[0]
    entry = {'release': tag, 'version': str(version), 'prerelease': bool(release['prerelease'])}
    common, platform_pins = [], {}
    if version >= Version('25.7'):
        python_version = (tag_file(tag, '.python-version') or '3.13').strip()
        python = '.'.join(python_version.split('.')[:2])
        common, platform_pins = uv_lock_pins(tag_file(tag, 'uv.lock'), python)
        requirements = [f'anki=={version}', f'aqt[qt]=={version}']
    elif version >= Version('2.1.50'):
        bundle = tag_file(tag, 'python/requirements.bundle.txt')
        common = text_lock_pins([bundle or tag_file(tag, 'python/requirements.txt')], True)
        qt_common, platform_pins = qt6_pins(tag)
        common += qt_common
        requirements = [f'anki=={version}', f'aqt[qt6]=={version}' if version < Version('25.2') else f'aqt=={version}']
    else:
        lock = tag_file(tag, 'pip/requirements.txt')
        # 2.1.24-2.1.35 have no runtime lockfile; use the earliest locked build's runtime.
        common = text_lock_pins([lock or fallback_lock], True) + pyqt5_pins(tag)
        requirements = [f'anki=={version}', f'aqt=={version}']
        if version < Version('2.1.36'):
            # The Rust backend and WebEngine shipped separately; some wheels omit them.
            requirements += [f'ankirspy=={version}', 'pyqtwebengine']
    common = [resolve_pin(pin) for pin in common]
    platform_pins = {platform: [resolve_pin(pin) for pin in pins] for platform, pins in platform_pins.items()}
    entry.update({'python': python, 'requirements': requirements, 'constraints': common,
                  'platformConstraints': {platform: pins for platform, pins in platform_pins.items() if pins}})
    return entry, None


def main():
    releases = []
    page = 1
    while True:
        batch = json.loads(fetch(RELEASES_URL.format(page)))
        if not batch:
            break
        releases += [release for release in batch if not release['draft']]
        page += 1
    published = {}
    for name in ('anki', 'aqt'):
        data = json.loads(fetch(PYPI_URL.format(name)))
        # Map each release key to the version in its wheel names, without local labels.
        published[name] = {key: Version(files[0]['filename'].split('-')[1].split('+')[0])
                           for key, files in data['releases'].items() if files}
    pypi_versions = {key: version for key, version in published['anki'].items()
                     if published['aqt'].get(key) == version}
    fallback_lock = tag_file('2.1.36', 'pip/requirements.txt')
    entries, excluded = [], []
    for release in releases:
        entry, reason = describe(release, releases, pypi_versions, fallback_lock)
        if entry:
            entries.append(entry)
        else:
            excluded.append({'release': release['tag_name'], 'reason': reason})
        print(release['tag_name'], 'ok' if entry else reason, file=sys.stderr)
    entries.sort(key=lambda entry: Version(entry['version']))
    excluded.sort(key=lambda entry: Version(entry['release']))
    document = {
        '$comment': 'Generated by tools/update_anki_matrix.py; ordered oldest to latest.',
        'releases': entries,
        'excluded': excluded,
    }
    OUTPUT.write_text(json.dumps(document, indent=1) + '\n')
    print(f'{len(entries)} releases, {len(excluded)} excluded', file=sys.stderr)


if __name__ == '__main__':
    main()

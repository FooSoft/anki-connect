#!/usr/bin/env python3
"""Cache a pinned uv binary from a SHA-256-verified PyPI wheel."""
import base64
import hashlib
import io
import json
import os
import platform
import sys
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

UV_VERSION = '0.13.0'


def download(url, timeout):
    if os.name != 'nt':
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read()
    # .NET uses Windows certificate-chain validation, including intermediate
    # certificate retrieval. Python's OpenSSL can fail on the same trusted URL.
    # Keep URLs and paths out of executable PowerShell source.
    script = '''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -UseBasicParsing -Uri $env:ANKI_TEST_DOWNLOAD_URL -OutFile $env:ANKI_TEST_DOWNLOAD_FILE -TimeoutSec ([int]$env:ANKI_TEST_DOWNLOAD_TIMEOUT)
'''
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    with tempfile.TemporaryDirectory(prefix='anki-test-download-') as directory:
        target = Path(directory) / 'download'
        environment = dict(os.environ, ANKI_TEST_DOWNLOAD_URL=url,
                           ANKI_TEST_DOWNLOAD_FILE=str(target),
                           ANKI_TEST_DOWNLOAD_TIMEOUT=str(timeout))
        completed = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout + 30)
        if completed.returncode:
            diagnostic = completed.stderr.decode(errors='replace').strip()
            raise RuntimeError('Windows HTTPS download failed: ' + diagnostic)
        return target.read_bytes()


def main():
    cache = Path(sys.argv[1]).resolve() / 'tools' / ('uv-' + UV_VERSION)
    executable = cache / ('uv.exe' if os.name == 'nt' else 'uv')
    digest_file = cache / 'sha256'
    if executable.exists() and digest_file.exists():
        if hashlib.sha256(executable.read_bytes()).hexdigest() == digest_file.read_text().strip():
            print(executable.as_posix())
            return
    machine = platform.machine().lower()
    machine = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(machine, machine)
    if sys.platform == 'darwin':
        tag = 'macosx_11_0_arm64' if machine == 'aarch64' else 'macosx_10_12_x86_64'
    elif os.name == 'nt':
        tag = {'x86_64': 'win_amd64', 'aarch64': 'win_arm64', 'x86': 'win32'}[machine]
    elif sys.platform.startswith('linux'):
        libc = platform.libc_ver()[0]
        tag = ('musllinux_1_1_' if libc == 'musl' else 'manylinux_2_17_') + machine
    else:
        raise RuntimeError('Unsupported platform for the test runner: ' + sys.platform)
    print('Downloading uv ' + UV_VERSION + ' for ' + tag, file=sys.stderr)
    metadata = json.loads(download('https://pypi.org/pypi/uv/' + UV_VERSION + '/json', 30))
    candidates = [item for item in metadata['urls']
                  if item['filename'].endswith('.whl') and tag in item['filename']]
    if not candidates:
        raise RuntimeError('No uv wheel for ' + tag)
    package = sorted(candidates, key=lambda item: item['filename'])[0]
    wheel = download(package['url'], 120)
    if hashlib.sha256(wheel).hexdigest() != package['digests']['sha256']:
        raise RuntimeError('Downloaded uv wheel failed SHA-256 validation')
    with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
        members = [name for name in archive.namelist()
                   if name.endswith('/scripts/' + executable.name)]
        if len(members) != 1:
            raise RuntimeError('Expected one uv executable in wheel')
        binary = archive.read(members[0])
    cache.mkdir(parents=True, exist_ok=True)
    temporary = executable.with_suffix('.tmp-' + str(os.getpid()))
    temporary.write_bytes(binary)
    temporary.chmod(0o755)
    temporary.replace(executable)
    digest_file.write_text(hashlib.sha256(binary).hexdigest() + '\n')
    print(executable.as_posix())


if __name__ == '__main__':
    main()

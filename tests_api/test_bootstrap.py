"""Test Windows download isolation and failure handling without network access."""
import base64
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import bootstrap_test_uv as bootstrap


@pytest.mark.parametrize('exit_code', [0, 1])
def test_windows_bootstrap_download(monkeypatch, exit_code):
    url = "https://example.invalid/wheel?value='quoted'"
    monkeypatch.setattr(bootstrap, 'os', SimpleNamespace(name='nt', environ=dict(os.environ)))
    destinations = []

    def run(arguments, **kwargs):
        assert arguments[:4] == ['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand']
        script = base64.b64decode(arguments[4]).decode('utf-16-le')
        assert 'Invoke-WebRequest -UseBasicParsing' in script
        assert url not in script
        assert 'SkipCertificateCheck' not in script
        assert kwargs['env']['ANKI_TEST_DOWNLOAD_URL'] == url
        assert kwargs['env']['ANKI_TEST_DOWNLOAD_TIMEOUT'] == '30'
        assert kwargs['timeout'] == 60
        target = Path(kwargs['env']['ANKI_TEST_DOWNLOAD_FILE'])
        destinations.append(target)
        target.write_bytes(b'verified transport payload')
        return SimpleNamespace(returncode=exit_code, stderr=b'certificate chain rejected')

    monkeypatch.setattr(bootstrap.subprocess, 'run', run)
    if exit_code:
        with pytest.raises(RuntimeError, match='certificate chain rejected'):
            bootstrap.download(url, 30)
    else:
        assert bootstrap.download(url, 30) == b'verified transport payload'
    assert not destinations[0].parent.exists()

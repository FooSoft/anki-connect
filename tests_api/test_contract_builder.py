"""Contract freshness must depend on schema content, not the host's zlib build."""
import base64
import zlib

import pytest

from tools.build_api_contract import matches, render


@pytest.mark.parametrize('level', [0, 1, 6, 9])
def test_contract_accepts_equivalent_compression(level):
    schema = b'{"x-methods":{},"x-legacyTargets":{}}'
    encoded = base64.b85encode(zlib.compress(schema, level)).decode()
    content = render(encoded)
    assert matches(content, schema)
    assert not matches(content, b'{"x-methods":{"changed":{}}}')
    assert not matches(content + '\nraise RuntimeError("modified wrapper")\n', schema)


@pytest.mark.parametrize('content', ['', 'invalid python!', render('corrupted'), 'SCHEMA = 123'])
def test_contract_rejects_malformed_generated_file(content):
    assert not matches(content, b'{}')

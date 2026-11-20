import copy

import pytest

from plugin.contract import SCHEMA
from plugin.schema import Draft202012Validator, Validator

METHODS = SCHEMA['x-methods']


def variants(value, depth=1):
    yield value
    if isinstance(value, dict):
        yield {**value, 'unexpectedProperty': True}
        for key in value:
            yield {name: member for name, member in value.items() if name != key}
            for replacement in (None, '', -1, [], {}, True):
                yield {**value, key: replacement}
            for nested in variants(value[key], depth - 1) if depth and isinstance(value[key], (dict, list)) else ():
                yield {**value, key: nested}
    elif isinstance(value, list) and value:
        yield value[1:]
        yield value + value[:1]
        yield [None] + value[1:]


def cases():
    for item in SCHEMA['x-examples']:
        for kind in ('request', 'response'):
            yield item['method'], kind, item[kind], True
    for item in SCHEMA['x-invalidExamples']:
        yield item['method'], 'params', item['params'], False


@pytest.mark.parametrize('method,kind,value,valid', list(cases()))
def test_fallback_validator_matches_contract_examples(method, kind, value, valid):
    fallback = Validator({**SCHEMA, 'oneOf': [METHODS[method][kind]]})
    assert fallback.is_valid(value) is valid
    errors = list(fallback.iter_errors(value))
    assert bool(errors) is not valid
    if errors:
        assert errors[0].message.endswith('is not valid under any of the given schemas')
        assert errors[0].path == []


@pytest.mark.skipif(Draft202012Validator is None, reason='bundled jsonschema predates Draft 2020-12 references')
def test_fallback_validator_agrees_with_jsonschema():
    checked = 0
    for item in SCHEMA['x-examples']:
        for kind, sample in (('params', item['request'].get('params', {})), ('result', item['response'].get('result'))):
            if kind == 'result' and 'result' not in item['response']:
                continue
            schema = {**SCHEMA, 'oneOf': [METHODS[item['method']][kind]]}
            official, fallback = Draft202012Validator(schema), Validator(schema)
            for value in variants(copy.deepcopy(sample), 1 if kind == 'params' else 0):
                assert fallback.is_valid(value) == official.is_valid(value), (item['method'], kind, value)
                checked += 1
    assert checked > 500, checked

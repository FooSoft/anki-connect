#!/usr/bin/env python3
"""Check the design artifacts without importing Anki or launching Qt.

The dependency-free example evaluator implements only the schema keywords used
by this contract. It is not a general JSON Schema implementation. When installed,
jsonschema additionally checks the Draft 2020-12 metaschema and all examples.
"""

import ast
import datetime
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InvalidExample(ValueError):
    pass


def check(condition, message):
    if not condition:
        raise ValueError(message)


class ExampleValidator:
    """Evaluate this specification's vocabulary, failing on unknown keywords."""

    KEYWORDS = {
        '$schema', '$id', '$ref', '$defs', 'title', 'description', 'default',
        'type', 'properties', 'required', 'additionalProperties', 'propertyNames',
        'unevaluatedProperties', 'minProperties', 'items', 'minItems', 'maxItems',
        'uniqueItems', 'minLength', 'maxLength', 'pattern', 'format',
        'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum',
        'enum', 'const', 'allOf', 'anyOf', 'oneOf', 'not', 'if', 'then', 'else',
        'contentEncoding',
    }

    def __init__(self, document):
        self.document = document

    def resolve(self, pointer):
        check(pointer.startswith('#/'), f'Nonlocal reference: {pointer}')
        value = self.document
        for part in pointer[2:].split('/'):
            value = value[part.replace('~1', '/').replace('~0', '~')]
        return value

    def inspect(self, schema):
        check(isinstance(schema, (dict, bool)), 'Schema must be an object or boolean')
        if isinstance(schema, bool):
            return
        for key in schema:
            check(key in self.KEYWORDS or key.startswith('x-'), f'Unsupported schema keyword: {key}')
        if '$ref' in schema:
            self.resolve(schema['$ref'])
        for key in ['properties', '$defs']:
            for child in schema.get(key, {}).values():
                self.inspect(child)
        for key in ['allOf', 'anyOf', 'oneOf']:
            check(key not in schema or bool(schema[key]), f'Empty {key}')
            for child in schema.get(key, []):
                self.inspect(child)
        for key in ['items', 'additionalProperties', 'propertyNames', 'not', 'if', 'then', 'else']:
            if key in schema:
                self.inspect(schema[key])
        if 'required' in schema:
            check(len(schema['required']) == len(set(schema['required'])), 'Duplicate required property')
        if schema.get('additionalProperties') is False:
            check(set(schema.get('required', [])) <= set(schema.get('properties', {})),
                  'Required property cannot be present in a closed object')
        check(not ('then' in schema or 'else' in schema) or 'if' in schema,
              'Conditional branch without if')

    def matches(self, schema, value):
        try:
            self.validate(schema, value)
        except InvalidExample:
            return False
        return True

    def validate(self, schema, value, path='$'):
        def fail(message):
            raise InvalidExample(f'{path}: {message}')

        if schema is False:
            fail('Forbidden value')
        if schema is True:
            return set()
        evaluated = set()
        if '$ref' in schema:
            evaluated |= self.validate(self.resolve(schema['$ref']), value, path)
        if 'const' in schema and (type(value) is not type(schema['const']) or value != schema['const']):
            fail('Const mismatch')
        if 'enum' in schema and not any(type(value) is type(v) and value == v for v in schema['enum']):
            fail('Enum mismatch')
        types = {
            'object': isinstance(value, dict), 'array': isinstance(value, list),
            'string': isinstance(value, str),
            'integer': type(value) is int or (type(value) is float and value.is_integer()),
            'number': type(value) in (int, float), 'boolean': type(value) is bool,
            'null': value is None,
        }
        if 'type' in schema and not types[schema['type']]:
            fail('Type mismatch: ' + schema['type'])
        for child in schema.get('allOf', []):
            evaluated |= self.validate(child, value, path)
        for key in ['anyOf', 'oneOf']:
            if key not in schema:
                continue
            successes = []
            for child in schema[key]:
                try:
                    successes.append(self.validate(child, value, path))
                except InvalidExample:
                    pass
            if not successes or (key == 'oneOf' and len(successes) != 1):
                fail(f'{key} matched {len(successes)} branches')
            for properties in successes:
                evaluated |= properties
        if 'not' in schema and self.matches(schema['not'], value):
            fail('Forbidden schema matched')
        if 'if' in schema:
            branch = 'then' if self.matches(schema['if'], value) else 'else'
            if branch in schema:
                evaluated |= self.validate(schema[branch], value, path)
        if isinstance(value, dict):
            if not set(schema.get('required', [])) <= set(value):
                fail('Missing required property')
            if len(value) < schema.get('minProperties', 0):
                fail('Too few properties')
            props = schema.get('properties', {})
            for key, member in value.items():
                if 'propertyNames' in schema:
                    self.validate(schema['propertyNames'], key, path + '.' + key)
                if key in props:
                    self.validate(props[key], member, path + '.' + key)
                    evaluated.add(key)
                elif 'additionalProperties' in schema:
                    self.validate(schema['additionalProperties'], member, path + '.' + key)
                    evaluated.add(key)
            if schema.get('unevaluatedProperties') is False and set(value) - evaluated:
                fail('Unevaluated properties: ' + ', '.join(sorted(set(value) - evaluated)))
        if isinstance(value, list):
            if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', float('inf')):
                fail('Array length out of bounds')
            if schema.get('uniqueItems') and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
                fail('Duplicate array items')
            if 'items' in schema:
                for index, member in enumerate(value):
                    self.validate(schema['items'], member, path + f'[{index}]')
        if isinstance(value, str):
            if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', float('inf')):
                fail('String length out of bounds')
            if 'pattern' in schema and not re.search(schema['pattern'], value):
                fail('String pattern mismatch')
            if schema.get('format') in ['date', 'date-time']:
                try:
                    if schema['format'] == 'date':
                        datetime.date.fromisoformat(value)
                    else:
                        parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
                        if parsed.tzinfo is None:
                            fail('Timestamp lacks timezone')
                except ValueError:
                    fail('Invalid date/time')
            if schema is self.document['$defs']['EntityId'] and int(value) > 9223372036854775807:
                fail('Entity ID exceeds signed int64')
        if type(value) in (int, float):
            for keyword, invalid in [
                ('minimum', lambda bound: value < bound),
                ('maximum', lambda bound: value > bound),
                ('exclusiveMinimum', lambda bound: value <= bound),
                ('exclusiveMaximum', lambda bound: value >= bound),
            ]:
                if keyword in schema and invalid(schema[keyword]):
                    fail(keyword + ' violated')
        return evaluated


def source_actions():
    tree = ast.parse((ROOT / 'plugin/__init__.py').read_text(encoding='utf-8'))
    actions = {}
    aliases = []
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef) or cls.name != 'AnkiConnect':
            continue
        for node in cls.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            decorators = [d for d in node.decorator_list
                          if isinstance(d, ast.Call) and ast.unparse(d.func) == 'util.api']
            if not decorators:
                continue
            args = ast.arguments(posonlyargs=[], args=node.args.args[1:], vararg=node.args.vararg,
                                 kwonlyargs=node.args.kwonlyargs, kw_defaults=node.args.kw_defaults,
                                 kwarg=node.args.kwarg, defaults=node.args.defaults)
            actions[node.name] = ast.unparse(args)
            for decorator in decorators:
                aliases.extend((node.name, ast.literal_eval(arg)) for arg in decorator.args)
    return actions, aliases


def main():
    schema = json.loads((ROOT / 'api-v1.schema.json').read_text(encoding='utf-8'))
    reference = (ROOT / 'API_V1.md').read_text(encoding='utf-8')
    validator = ExampleValidator(schema)
    validator.inspect(schema)
    methods = schema['x-methods']
    documented = re.findall(r'^### `([^`]+)`$', reference, re.M)
    check(set(documented) == set(methods) and len(documented) == len(methods),
          'Method reference differs from schema registry')
    for name, meta in methods.items():
        check(meta['completion'] in ['completed', 'operation'], f'Invalid completion: {name}')
        check(meta['scope'] in ['collection', 'application'], f'Invalid scope: {name}')
        check((meta['completion'] == 'operation') == ('operationResult' in meta),
              f'Operation result missing/unexpected: {name}')
        check(set(meta['errors']) <= set(schema['x-errors']),
              f'Undeclared error type: {name}')
        for key in ['params', 'result', 'request', 'response', 'operationResult']:
            if key in meta:
                validator.resolve(meta[key]['$ref'])
        params = validator.resolve(meta['params']['$ref'])
        check(('session' in params['properties']) == (meta['scope'] == 'collection'),
              f'Session guard differs from scope: {name}')
        for value in params['properties'].values():
            if 'default' in value:
                validator.validate(value, value['default'])
    actions, aliases = source_actions()
    targets = schema['x-legacyTargets']
    check(set(targets) == set(actions), 'Legacy registry differs from source actions')
    for action, services in targets.items():
        check(bool(services), f'No targets for legacy action: {action}')
        check(set(services) <= set(methods), f'Unknown legacy service target: {action}')
    check(set(schema['x-limits']) == set(schema['$defs']['Description']['properties']['limits']['properties']),
          'Discovery limits differ from declared limits')
    for item in schema['x-examples']:
        meta = methods[item['method']]
        validator.validate(schema, item['request'])
        validator.validate(schema, item['response'])
        validator.validate(meta['request'], item['request'])
        validator.validate(meta['response'], item['response'])
        check(item['request']['id'] == item['response']['id'], 'Example response ID mismatch')
        if item['method'] == 'api.execute':
            for command in item['request']['params']['commands']:
                validator.validate(methods[command['method']]['params'], command.get('params', {}))
    for item in schema['x-invalidExamples']:
        check(not validator.matches(methods[item['method']]['params'], item['params']),
              'Negative fixture was accepted: ' + item['method'])
    operation = next(e['response']['result'] for e in schema['x-examples'] if e['method'] == 'operations.get')
    for change in [{'result': {'completed': True}}, {'error': {'code': 1007, 'message': 'Cancelled'}},
                   {'state': 'running'}, {'unexpected': True}]:
        bad = {**operation, **change}
        check(not validator.matches({'$ref': '#/$defs/Operation'}, bad),
              'Invalid terminal operation fixture was accepted')
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:
        print('jsonschema unavailable: official metaschema check skipped; contract-vocabulary/example checks passed.')
    else:
        Draft202012Validator.check_schema(schema)
        full = Draft202012Validator(schema, format_checker=FormatChecker())
        for item in schema['x-examples']:
            full.validate(item['request'])
            full.validate(item['response'])
            for kind in ['request', 'response']:
                Draft202012Validator(
                    {**schema, 'oneOf': [methods[item['method']][kind]]},
                    format_checker=FormatChecker(),
                ).validate(item[kind])
        for item in schema['x-invalidExamples']:
            negative = Draft202012Validator({**schema, 'oneOf': [methods[item['method']]['params']]})
            check(not negative.is_valid(item['params']), 'Full validator accepted a negative fixture')
        print('Official Draft 2020-12 metaschema and example validation passed.')
    print(f'{len(methods)} methods; {len(actions)} legacy actions; {len(aliases)} aliases; '
          f'{len(schema["x-examples"])} positive and {len(schema["x-invalidExamples"])} negative examples checked.')


if __name__ == '__main__':
    main()

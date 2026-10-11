#!/usr/bin/env python3
"""Check public references, exact coverage, and every documented JSON request."""
import ast
import inspect
import json
import re
from pathlib import Path

from check_api_spec import ExampleValidator, check, source_actions

ROOT = Path(__file__).resolve().parents[1]


def sections(path):
    text = path.read_text(encoding='utf-8')
    parts = re.split(r'^### `([^`]+)`\s*$', text, flags=re.M)
    names = parts[1::2]
    check(len(names) == len(set(names)), f'Duplicate entry in {path.name}')
    return dict(zip(names, parts[2::2]))


def blocks(text):
    return [json.loads(value) for value in re.findall(r'```json\s*\n(.*?)```', text, re.S)]


def signature(source):
    args = ast.parse('def action(' + source + '): pass').body[0].args
    optional_start = len(args.args) - len(args.defaults)
    parameters = []
    for index, arg in enumerate(args.args):
        default = inspect.Parameter.empty
        if index >= optional_start:
            default = ast.literal_eval(args.defaults[index - optional_start])
        parameters.append(inspect.Parameter(arg.arg, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                            default=default))
    return inspect.Signature(parameters)


def main():
    schema = json.loads((ROOT / 'api-v1.schema.json').read_text(encoding='utf-8'))
    validator = ExampleValidator(schema)
    methods = schema['x-methods']
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:
        full_validators = {}
    else:
        full_validators = {
            name: Draft202012Validator({**schema, 'oneOf': [meta['request']]},
                                      format_checker=FormatChecker())
            for name, meta in methods.items()
        }
    v1 = sections(ROOT / 'API_V1.md')
    check(set(v1) == set(methods), 'V1 documentation coverage differs from registry')
    requests = 0
    for name, body in v1.items():
        examples = [value for value in blocks(body)
                    if isinstance(value, dict) and value.get('method') == name]
        check(bool(examples), f'No request example: {name}')
        for value in examples:
            validator.validate(methods[name]['request'], value)
            if name in full_validators:
                full_validators[name].validate(value)
            if name == 'api.execute':
                for command in value['params']['commands']:
                    validator.validate(methods[command['method']]['params'], command.get('params', {}))
            requests += 1
        for value in blocks(body):
            if isinstance(value, dict) and 'jsonrpc' in value and 'result' in value:
                validator.validate(methods[name]['response'], value)
    actions, _ = source_actions()
    legacy = sections(ROOT / 'API_LEGACY.md')
    check(set(legacy) == set(actions), 'Legacy documentation coverage differs from decorators')
    for name, body in legacy.items():
        check(f'`{name}({actions[name]})`' in body, f'Signature differs: {name}')
        examples = [value for value in blocks(body)
                    if isinstance(value, dict) and value.get('action') == name]
        check(bool(examples), f'No request example: {name}')
        for value in examples:
            check(value.get('version') == 6, f'Example must specify version 6: {name}')
            params = value.get('params', {})
            if name == 'requestPermission':
                params = {**params, 'origin': None, 'allowed': True}
            try:
                signature(actions[name]).bind(**params)
            except TypeError as error:
                raise ValueError(f'{name}: {error}') from error
            requests += 1
        targets = re.findall(r'\[([^\]]+)\]\(API_V1.md#', body)
        check(targets == schema['x-legacyTargets'][name], f'Legacy targets differ: {name}')
    # Catch invalid JSON in introductions and shared types too.
    for filename in ('README.md', 'API_V1.md', 'API_LEGACY.md'):
        text = (ROOT / filename).read_text(encoding='utf-8')
        blocks(text)
        for language, source in re.findall(r'```(python|bash)\s*\n(.*?)```', text, re.S):
            if language == 'python':
                ast.parse(source)
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if '://' in target:
                continue
            path, _, fragment = target.partition('#')
            linked = ROOT / (path or filename)
            check(linked.exists(), f'Broken link in {filename}: {target}')
            if fragment and linked.suffix == '.md':
                linked_text = linked.read_text(encoding='utf-8')
                anchors = set(re.findall(r'<a id="([^"]+)"', linked_text))
                for heading in re.findall(r'^#+ (.+)$', linked_text, re.M):
                    anchors.add(re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-'))
                check(fragment in anchors, f'Broken anchor in {filename}: {target}')
    print(f'Documentation checked: {len(v1)} v1 methods, {len(legacy)} legacy actions, '
          f'{requests} valid request examples.')


if __name__ == '__main__':
    main()

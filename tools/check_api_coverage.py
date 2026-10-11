#!/usr/bin/env python3
"""Validate the reviewed API test inventory and render its public report.

This checks references and completeness, not execution or behavioral coverage.
Use --write after reviewing tests_api/api_coverage.json to regenerate the report.
"""
import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re

from check_api_spec import check, source_actions

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests_api/api_coverage.json'
REPORT = ROOT / 'API_TEST_COVERAGE.md'
LAYERS = {
    'native-service': 'Native service',
    'legacy-forwarder': 'Legacy forwarder',
    'legacy-dispatch': 'Legacy dispatch/direct action',
    'controlled-admission': 'Controlled admission',
    'mocked-gui': 'Mocked GUI completion',
    'real-gui': 'Real GUI',
    'http-gui': 'Real HTTP + GUI',
    'validation-only': 'Validation/transport only',
}
EXECUTION_LAYERS = set(LAYERS) - {'validation-only', 'mocked-gui'}


def source_case(source, case):
    path = Path(source)
    check(source == 'tools/smoke_gui.py' or (
        path.parent == Path('tests_api') and path.name.startswith('test_') and path.suffix == '.py'),
          f'Unknown test source: {source}')
    tree = ast.parse((ROOT / source).read_text(encoding='utf-8'))
    if source.startswith('tests_api/'):
        matches = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name == case and case.startswith('test_')]
    elif case == 'setup':
        # Common setup inside the top-level scenario try block, before branches.
        matches = [node for node in tree.body if isinstance(node, ast.Try)]
        check(len(matches) == 1, 'GUI setup block changed; review inventory')
        statements = []
        for node in matches[0].body:
            if isinstance(node, ast.If):
                break
            statements.append(node)
        return statements, statements[0].lineno
    else:
        matches = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
                continue
            condition = node.test
            if (isinstance(condition.left, ast.Name) and condition.left.id == 'scenario'
                    and len(condition.comparators) == 1):
                value = condition.comparators[0]
                if ((isinstance(condition.ops[0], ast.Eq) and isinstance(value, ast.Constant)
                     and value.value == case) or (isinstance(condition.ops[0], ast.In)
                     and isinstance(value, (ast.Tuple, ast.List)) and case in ast.literal_eval(value))):
                    matches.append(node)
    check(len(matches) == 1, f'Missing or ambiguous case: {source}:{case}')
    return matches, matches[0].lineno


def load_inventory():
    schema = json.loads((ROOT / 'api-v1.schema.json').read_text(encoding='utf-8'))
    actions, _ = source_actions()
    registry = {'v1': set(schema['x-methods']), 'legacy': set(actions)}
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    check(set(manifest) == {'description', 'evidence', 'unreferenced', 'ui_deferrals'}, 'Invalid inventory keys')
    check(set(manifest['unreferenced']) == set(registry), 'Invalid unreferenced protocols')
    indexed = {protocol: {name: [] for name in names} for protocol, names in registry.items()}
    seen = set()
    for evidence in manifest['evidence']:
        check(set(evidence) == {'source', 'case', 'layer', 'outcome', 'v1', 'legacy', 'notes'},
              'Invalid evidence keys')
        key = tuple(evidence[field] for field in ('source', 'case', 'layer', 'outcome'))
        check(key not in seen, f'Duplicate evidence: {key}')
        seen.add(key)
        check(evidence['layer'] in LAYERS, f'Unknown evidence layer: {key}')
        check(evidence['outcome'] in {'success', 'failure', 'not-executed'}, f'Unknown outcome: {key}')
        if evidence['layer'] in EXECUTION_LAYERS:
            check(evidence['outcome'] != 'not-executed', f'Execution evidence needs an outcome: {key}')
        else:
            check(evidence['outcome'] == 'not-executed', f'Mock/validation is not execution: {key}')
        check(bool(evidence['notes']), f'Missing limitations: {key}')
        check(bool(evidence['v1'] or evidence['legacy']), f'Empty evidence: {key}')
        nodes, line = source_case(evidence['source'], evidence['case'])
        source = '\n'.join(ast.unparse(node) for node in nodes)
        evidence['line'] = line
        for protocol in registry:
            names = evidence[protocol]
            check(len(names) == len(set(names)), f'Duplicate methods: {key}')
            check(set(names) <= registry[protocol], f'Unknown {protocol} methods: {key}')
            for name in names:
                # A source reference is necessary, not proof that a call ran.
                check(name in source, f'Method no longer appears in cited case: {name}, {key}')
                indexed[protocol][name].append(evidence)
    for protocol, entries in indexed.items():
        missing = manifest['unreferenced'][protocol]
        check(len(missing) == len(set(missing)), f'Duplicate {protocol} gaps')
        expected = {name for name, evidence in entries.items() if not evidence}
        check(set(missing) == expected,
              f'{protocol} registry/test inventory differs; review new, removed, or newly tested methods')
    deferred = {}
    gui_tree = ast.parse((ROOT / 'plugin/gui.py').read_text(encoding='utf-8'))
    gui_methods = {function.name for node in gui_tree.body
                   if isinstance(node, ast.ClassDef) and node.name == 'Gui'
                   for function in node.body if isinstance(function, ast.FunctionDef)}
    for entry in manifest['ui_deferrals']:
        check(set(entry) == {'protocol', 'name', 'reason', 'alternative'}, 'Invalid UI deferral keys')
        protocol, name = entry['protocol'], entry['name']
        check(protocol in registry and name in registry[protocol], f'Unknown UI deferral: {entry}')
        targets = [name] if protocol == 'v1' else schema['x-legacyTargets'][name]
        check(any(target.replace('.', '_') in gui_methods for target in targets),
              f'UI deferral does not identify a GUI adapter: {name}')
        check(bool(entry['reason']) and bool(entry['alternative']), f'Unexplained UI deferral: {name}')
        key = (protocol, name)
        check(key not in deferred, f'Duplicate UI deferral: {name}')
        deferred[key] = entry
    return indexed, schema, deferred


def status(evidence):
    executable = [entry for entry in evidence if entry['layer'] in EXECUTION_LAYERS]
    if any(entry['outcome'] == 'success' for entry in executable):
        return 'Partial execution evidence'
    if executable:
        return 'Failure execution only'
    if evidence:
        return 'Validation/mock only'
    return 'No method test'


def gap(protocol, name, evidence, deferred):
    if (protocol, name) in deferred:
        return 'Real UI effect deferred. ' + deferred[(protocol, name)]['alternative']
    state = status(evidence)
    if name in {'collection.sync', 'sync'}:
        return 'Offline native/GUI interface checks and missing-auth rejection are covered; authenticated sync still needs a disposable account.'
    if state in {'No method test', 'Validation/mock only', 'Failure execution only'}:
        return 'Exercise the real Anki dependency and assert its result/effect across supported versions.'
    if protocol == 'legacy':
        return 'Verify legacy translation against real Anki; strengthen result/effect assertions.'
    if any(entry['layer'] in {'real-gui', 'http-gui'} for entry in evidence):
        return 'Retain real GUI completion/effect checks and run the supported OS/version matrix.'
    return 'Strengthen native result/effect assertions; check real Qt completion where admission matters.'


def adapter_links(schema):
    """Locate source adapters and declared capability probes without importing Anki.

    The probes are an intentionally incomplete runtime registry, not an exhaustive
    map of native calls. Source links expose the implementation for further review.
    """
    definitions = {}
    requirements = {}
    for source in ('plugin/services.py', 'plugin/gui.py', 'plugin/runtime.py',
                   'plugin/protocol.py', 'plugin/__init__.py'):
        tree = ast.parse((ROOT / source).read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for function in node.body:
                    if isinstance(function, ast.FunctionDef):
                        definitions[(node.name, function.name)] = (source, function.lineno)
            if (source == 'plugin/runtime.py' and isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'NATIVE_REQUIREMENTS'
                            for target in node.targets)):
                requirements = ast.literal_eval(node.value)
    special = {
        'api.describe': ('Runtime', 'describe'),
        'api.execute': ('Runtime', 'execute_commands'),
        'media.store': ('Runtime', 'acquire_media'),
        'access.requestPermission': ('AnkiConnect', 'permission'),
        'operations.get': ('Operations', 'get'),
        'operations.cancel': ('Operations', 'cancel'),
    }
    result = {}
    for name in schema['x-methods']:
        method = name.replace('.', '_')
        candidates = [key for key in (('Services', method), ('Gui', method)) if key in definitions]
        if name in special:
            key = special[name]
        else:
            check(len(candidates) == 1, f'Review source adapter for {name}')
            key = candidates[0]
        source, line = definitions[key]
        link = f'[{key[0]}.{key[1]}]({source}#L{line})'
        probes = requirements.get(name, ())
        if probes:
            link += '<br>' + ', '.join(f'`Collection.{probe}`' for probe in probes)
        result[name] = link
    return result, definitions


def render(indexed, schema, deferred):
    adapters, definitions = adapter_links(schema)
    lines = [
        '# API test coverage inventory', '',
        'This inventory maps every public API entry to reviewed test evidence. It is a',
        'coverage backlog, not a claim that all methods work. No entry is marked fully tested.',
        'The report describes test code; it does not record a passing run on any OS or Anki version.', '',
        'Both runners execute the maintained unit suite and, by default, all GUI scenarios.',
        'See [test.sh](test.sh) and [test.ps1](test.ps1) for the current version matrix.',
        'Windows must be validated separately.', '',
        '## Primary goal: Anki compatibility', '',
        'The main purpose of the version matrix is to detect changes in Anki internals that break',
        'the plugin. Prioritize calls into real collections, scheduler/model/media services, and',
        'real GUI objects, with assertions on returned data and observable effects. Test operation',
        'completion and lifecycle hooks where changes in Anki scheduling could break admission.', '',
        'A service test against real Anki is useful compatibility evidence even when it bypasses HTTP.',
        'Protocol/authentication tests protect our API but are separate from Anki compatibility.',
        'Do not require a separate HTTP test for every method. Shared native behavior can be exercised',
        'once; legacy argument/result translation still needs its own checks.', '',
        'Source adapter links identify where to investigate Anki changes. Listed `Collection.*`',
        'dependencies come from the runtime capability probes and are not exhaustive. A callable',
        'probe alone cannot catch changed signatures, semantics, result formats, or GUI completion.',
        'Follow the linked adapter and its helpers when planning compatibility assertions.', '',
        'Legacy rows also show related v1 adapters from the contract mapping. Those links are',
        'navigation aids, not proof of the exact legacy call path or of coverage for that action.', '',
        'Exceedingly difficult GUI effects may be deferred with a reason and a practical alternative.',
        'Deferring a UI effect does not make a mocked test evidence of real Anki compatibility.', '',
        '## How to read this report', '',
        '- **Partial execution evidence:** at least one reviewed successful call exists.',
        '  Some calls only check result schemas or serve as setup; this does not certify every behavior.',
        '- **Failure execution only:** a method call or admission is tested for failure, with no successful call listed.',
        '- **Validation/mock only:** checks stop before the implementation or use a fabricated GUI result.',
        '- **No method test:** no direct method evidence is listed. Shared infrastructure, legacy target',
        '  mappings, reflected method names, and documentation examples do not qualify.', '',
        'Native service tests bypass runtime admission and HTTP. Legacy forwarder tests bypass the',
        'public legacy dispatcher and HTTP. Controlled admission uses real collections with mocked Qt',
        'scheduling/main windows. Real GUI scenarios use Qt windows and temporary profiles, generally',
        'through the runtime dispatcher. The exit and legacy-exit scenarios send real HTTP requests.',
        'Internal Operations helpers are not credited as calls to operations.get or operations.cancel.', '',
        'Evidence notes identify important limits, injected failures, and assertion scope.',
        'Read each linked test before interpreting a row as behavioral coverage.', '',
        '## Summary', '',
        '| API | Entries | Partial execution | Failure execution only | Validation/mock only | No method test |',
        '| --- | ---: | ---: | ---: | ---: | ---: |',
    ]
    for protocol, label in [('v1', 'API v1'), ('legacy', 'Legacy API')]:
        counts = Counter(status(evidence) for evidence in indexed[protocol].values())
        values = [counts[key] for key in ('Partial execution evidence', 'Failure execution only',
                                         'Validation/mock only', 'No method test')]
        lines.append(f'| {label} | {len(indexed[protocol])} | ' + ' | '.join(map(str, values)) + ' |')
    lines += ['', '## Maintaining the inventory', '',
              'Edit [tests_api/api_coverage.json](tests_api/api_coverage.json) after reviewing new tests.',
              'List protocol-specific evidence, its layer, success/failure/not-executed outcome, and limits.',
              'Move entries out of `unreferenced` when adding their first evidence; never infer legacy',
              'coverage from its v1 target. Record impractical real UI effects in `ui_deferrals`, with',
              'a reason and a practical alternative; deferrals are not passing coverage.', '',
              '```bash', 'python tools/check_api_coverage.py --write',
              'python tools/check_api_coverage.py', '```', '',
              'The normal test runners check registry completeness, referenced cases, method mentions,',
              'and this generated report. A new API entry requires an explicit test or unreferenced entry.',
              'Existing gaps remain visible and do not fail the test suite. Full behavioral coverage will',
              'need assertions at Anki integration boundaries and passing platform/version runs.', '',
              '## Deferred real GUI effects', '',
              '| API entry | Reason | Practical alternative |',
              '| --- | --- | --- |']
    for (protocol, name), entry in sorted(deferred.items()):
        lines.append(f"| {protocol}: `{name}` | {entry['reason']} | {entry['alternative']} |")
    lines.append('')
    for protocol, title, guide in [('v1', 'API v1 methods', 'API_V1.md'),
                                   ('legacy', 'Legacy actions', 'API_LEGACY.md')]:
        lines += [f'## {title}', '',
                  '| Method/action | Status | Adapter / declared Anki dependencies | Test evidence | Compatibility work |',
                  '| --- | --- | --- | --- | --- |']
        for name, evidence in sorted(indexed[protocol].items()):
            links = []
            for entry in evidence:
                label = f"{entry['case']} ({LAYERS[entry['layer']]}; {entry['outcome']})"
                links.append(f"[{label}]({entry['source']}#L{entry['line']})")
            anchor = re.sub(r'[^\w\- ]', '', name.lower()).replace(' ', '-')
            if protocol == 'v1':
                boundary = adapters[name]
            else:
                source, line = definitions[('AnkiConnect', name)]
                boundary = f'[Legacy action]({source}#L{line})<br>' + '<br>'.join(
                    adapters[target] for target in schema['x-legacyTargets'][name])
            lines.append(f'| [`{name}`]({guide}#{anchor}) | {status(evidence)} | {boundary} | '
                         + ('<br>'.join(links) or '—') + ' | '
                         + gap(protocol, name, evidence, deferred) + ' |')
        lines.append('')
    lines += ['## Evidence notes', '']
    all_evidence = {}
    for entries in indexed.values():
        for records in entries.values():
            for entry in records:
                key = tuple(entry[field] for field in ('source', 'case', 'layer', 'outcome'))
                all_evidence[key] = entry
    for _, entry in sorted(all_evidence.items()):
        lines.append(f"- [{entry['case']}]({entry['source']}#L{entry['line']}) "
                     f"({LAYERS[entry['layer']]}; {entry['outcome']}): {entry['notes']}")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Regenerate the Markdown report')
    args = parser.parse_args()
    indexed, schema, deferred = load_inventory()
    report = render(indexed, schema, deferred)
    if args.write:
        REPORT.write_text(report, encoding='utf-8', newline='\n')
    else:
        check(REPORT.exists() and REPORT.read_text(encoding='utf-8') == report,
              'Coverage report is stale; run python tools/check_api_coverage.py --write')
    for protocol, entries in indexed.items():
        counts = Counter(status(evidence) for evidence in entries.values())
        print(f'{protocol}: {len(entries)} entries; ' + ', '.join(
            f'{count} {name.lower()}' for name, count in sorted(counts.items())))


if __name__ == '__main__':
    main()

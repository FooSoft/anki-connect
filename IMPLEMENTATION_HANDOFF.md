# New Anki API implementation handoff

Updated: 2026-10-10. The runtime and forwarders are implemented and reviewed;
representative native and real GUI regressions pass. **Full integration validation
is not finished**, especially network sync and extended GUI stress/variant testing.

Base commit for this continuation: `63d62ff` (`handoff`). The previous implementation
was transferred in that commit. This continuation's changes are uncommitted; no
commit, push, publication or packaging was requested or performed. Transfer the
whole working tree, including `tools/smoke_gui.py` and `tests/README.md`.

## Resume context

The user authorized the API rewrite and obsolete-content replacement. Read
`API_V1.md`, `api-v1.schema.json`, `LEGACY_API_MAPPING.md`, `INTEGRATION_ISSUES.md`
and the implementation before further changes. Do not spawn subagents unless
explicitly requested. Preserve legacy signatures and transport/access behavior
through the shared services. Do not use personal collections for validation.

The runtime has 94 v1 methods and 122 legacy entry points. The module boundaries,
execution model and media journal are described in the rewritten `ARCHITECTURE.md`.
`README.md` now documents both endpoints, minimum Anki 26.9.3, dependencies,
compatibility limitations, and the new validation workflow. The schema, mapping,
audit follow-up and repository guidance have been reconciled with implementation.
The old `tests/` suite is retained as legacy reference, outside default pytest.

## Changes completed in this continuation

- V1 media replacement now uses the request-owned transaction journal. A native
  write failure after trash restores the original bytes; ownership conflicts
  retain the journal and expose rollback failures. Legacy installs use the same
  primitive without recursively opening another transaction.
- Nested legacy multi preflights the entire request tree before work: malformed
  nodes/signatures, depth 16, total 100 request nodes (including containers), and
  exit only as the final executable action. Per-item credentials remain independent.
- Discovery checks adapter presence and selected native dependencies; missing
  checked capabilities produce unsupportedCapability at admission/execution.
  Availability remains a capability probe, not full integration certification.
- Template usage mirrors the baseline's token grammar, handling HTML comments,
  conditional fields, filters and the alternate delimiter directive. Anki's
  parsed tree is not exposed to Python; the contract now accurately says this.
- Typed presets and legacy saveDeckConfig support newPerDayMinimum.
- Native profile/temporary-close hooks invalidate sessions, tokens, cursors,
  editor registrations and custom-editor history. Collection identity changes
  also clear history. Stale queued work cannot run media recovery before rejection.
- Queued GUI jobs recheck active collection work. Editor conflict messages now
  explicitly require closing affected editors, including saved/clean ones.
- Terminal operation successes are checked against their final result schemas.
  Import/full-sync dialogs expose waitingForUser and running states.
- Svelte editor readiness waits for its exported functions without assuming a
  global require. Empty Add snapshots await native note/deck initialization;
  draft snapshots/updates await pending native field saves.
- Custom editor uses the current Anki form, retains its main-window reference,
  and cleans up idempotently to avoid callbacks touching deleted widgets.
- Browser opening awaits its editor before native search/sort calls. This removed
  observed saveNow-is-undefined errors. Legacy guiBrowse awaits that completion.
- Exit uses native main-window close(), replacing the removed onClose method.
  A real HTTP test verifies the acceptance reply and native profile shutdown.
- Missing add-on configuration falls back to DEFAULT_CONFIG. During GUI testing,
  getConfig returned None and the old blanket exception misleadingly reported
  "setting webBindAddress not found". The fallback and permission dictionaries
  now handle absent config; overrides still take precedence.
- Added a reproducible optional GUI harness, tools/smoke_gui.py. Each scenario
  uses a separate process and newly created disposable profile. The harness has
  bounded waits and reports uncaught Qt/Python callback errors.

## Validation evidence

Native environment: `/tmp/anki-api-runtime-env/bin/python3`, Python 3.13.5,
Anki/aqt 26.9.3, PyQt6 6.11.0, bundled Qt/WebEngine 6.11.2, pytest 9.1.1,
jsonschema 4.26.0. Source reference staged by the user:
`/home/alex/projects/anki/anki-26.09.3` (`.version`: 26.09.3).

**32 tests pass** in the default tests_api suite. The previous 19 tests remain;
new regressions cover failed replacement rollback, full nested multi preflight,
preset translation, native template tokens, capability/dispatch consistency,
same-object reopen invalidation, cancellation preserving completed outcomes,
source/bundled contract and adapter consistency, queued GUI admission,
stale-work recovery prevention, terminal result validation, absent config defaults,
and legacy browser completion.

Specification checks pass with official Draft 2020-12 validation: 94 methods,
122 actions, 27 audit/lifecycle dispositions, 15 positive and 16 negative fixtures.
Compilation and git diff --check pass.

Real desktop GUI scenarios have passed individually using temporary profiles:

- editors: empty and populated Add drafts, append updates, actual native saves,
  and close for both legacy and Svelte variants;
- browser: search, note selection, numeric sorting ascending/descending both on
  first selection and when already active, plus legacy forwarding completion;
- custom: custom editor open, native field save and close;
- reviewer: question/answer state tokens, hook veto, native answer/revlog completion;
- imports: CSV import success, cancellation, invalid-package failure;
- profiles: native switch and fresh session;
- colpkg: cancellation, replacement from this temporary profile's own backup,
  reopen, preserved note and invalidated session (confirmation decision stubbed);
- exit: real HTTP acceptance reply followed by native Anki close/profile unload.

The last aggregate run passed every scenario except a harness-only browser model
index error. That harness error was fixed and the browser scenario rerun passed.
Subsequent browser initialization/legacy completion changes were validated by the
browser scenario and native regression suite. An aggregate rerun is optional;
do not claim a single aggregate passing run unless rerun successfully.

Expected invalid-package errors produce a native Anki traceback in the import
scenario. Qt emits portal/graphics/MathJax warnings. Native shutdown can emit a
Waitress shutdown race warning. Earlier combined-process GUI runs also segfaulted
(exit 139) after repeated editor destruction/import cancellation. Isolated runs
pass, but they do not establish that repeated production window churn is crash-free.
Most scenarios deliberately terminate their process after checks; only exit uses
and verifies the native application shutdown path.

## Remaining validation and limitations

1. Network sync, full upload/download, media sync, failures and cancellation need
   a suitable **disposable** test account. No account/credentials were supplied;
   do not inspect or use personal profiles. Code paths were source-reviewed but
   have not been exercised against AnkiWeb.
2. Stress repeated editor/browser/import open/close in one process; investigate
   the combined-run Qt/WebEngine crash rather than treating process isolation as
   proof of stability. Check alternate OS/Qt versions and native shutdown warnings.
3. Broaden GUI coverage: user typing still pending in JavaScript, draft replacement
   conflicts, custom-editor history/navigation/preview across reopen, user-cancelled
   profile close, import failures after collection unload, custom scheduling and
   FSRS/leech reviewer hooks, and cancelled exit. Conservative affected-editor
   gates intentionally remain in place.
4. Capability probes check selected native API dependencies and adapter presence,
   not every protobuf field or native optional feature on later Anki releases.
   Expand them if a supported release differs; add explicit unsupported failures.
5. Third-party hooks and filesystem/database operations are outside a shared
   atomicity guarantee. Media recovery conservatively preserves referenced files
   when interruption leaves native note-commit status uncertain.
6. Packaging is nondestructive but has not been exercised in this continuation.
   Do not restore the old git clean -xdf packaging behavior.

## Commands

From the repository root:

```bash
/tmp/anki-api-runtime-env/bin/python3 tools/build_api_contract.py
/tmp/anki-api-runtime-env/bin/python3 -m pytest -q --tb=short
/tmp/anki-api-runtime-env/bin/python3 tools/check_api_spec.py
/tmp/anki-api-runtime-env/bin/python3 -m compileall -q plugin tools
git diff --check
```

Optional GUI checks with a working display (may require display/socket permissions):

```bash
QTWEBENGINE_DISABLE_SANDBOX=1 /tmp/anki-api-runtime-env/bin/python3 tools/smoke_gui.py all
# Or one scenario: editors, browser, custom, reviewer, imports, profiles, colpkg, exit.
```

Temporary profiles are retained under `/tmp/anki-api-gui-*` for diagnosis. No
personal collection is read or written by the harness. On another machine recreate
the separate environment using the README commands; temporary environments are
not tracked. Regenerate plugin/contract.py after source schema/mapping edits.

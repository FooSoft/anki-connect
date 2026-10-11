# New Anki API implementation handoff

Updated: 2026-10-10. Work is **not finished**. Core implementation exists; final
review, documentation updates, and GUI validation remain. No implementation
changes have been committed. Current base commit: `4a4bc2b` (`Schema`).

## Resume request

Continue implementing and validating the new API and legacy forwarders. Read
this file, `API_V1.md`, `api-v1.schema.json`, `LEGACY_API_MAPPING.md`, and
`INTEGRATION_ISSUES.md`, then inspect the implementation before editing.

The user authorized a broad rewrite and removal of obsolete repository content:
“Everything in this repo should be seen as legacy pretty much.” Preserve useful
external compatibility through forwarders, but do not feel constrained by old
internal architecture. Do not spawn subagents unless explicitly requested.

## Moving to another PC

**Transfer the entire working tree, including untracked files.** A normal push
of the current commit will not include the implementation. Either commit these
changes before pushing, or copy the checkout with all files listed below. This
session has not committed or pushed anything.

Modified tracked files:

- `package.sh`
- `plugin/__init__.py`
- `plugin/web.py`

New, currently untracked implementation files:

- `plugin/contract.py`
- `plugin/gui.py`
- `plugin/legacy.py`
- `plugin/media.py`
- `plugin/protocol.py`
- `plugin/runtime.py`
- `plugin/services.py`
- `pyproject.toml`
- `tests_api/` (especially `test_runtime.py`)
- `tools/build_api_contract.py`
- `tools/package_addon.py`
- This handoff file

The temporary Python environment and GUI smoke script live under `/tmp` on the
original PC and will not travel with Git. Recreate the environment on the new
machine. Generated caches need not be transferred.

## Implemented so far

The committed specification defines 94 new methods and maps 122 legacy actions.
The working tree now implements the new runtime and all 122 forwarder entry
points. This means code exists, not that every GUI or network-dependent path has
been verified end to end.

- `plugin/__init__.py`: add-on startup, minimum Anki version 26.9.3, facade,
  exact legacy signatures/decorators, authentication and permissions, async
  legacy dispatch, sequential `multi` completion barriers, delayed exit.
- `plugin/web.py`: nonblocking HTTP server, `/api/v1` JSON-RPC routing, legacy
  root routing, body/header limits, strict JSON, CORS, Bearer authentication,
  notification responses, deferred socket replies.
- `plugin/protocol.py`: typed errors, schema validation, Deferred composition,
  operation records/cancellation, batch dispatch, metadata-only request logging.
- `plugin/runtime.py`: Qt main-thread admission, serialized native collection
  background work, session pins, native change notifications, lifecycle gates,
  operation execution, ordered `api.execute`, paging and prediction tokens.
- `plugin/services.py`: native collection services for notes, cards, scheduling,
  decks, note types, presets, media, reviews, statistics, packages, and undo.
  Native scheduler states drive answers; native APIs drive structural changes.
- `plugin/gui.py`: browser, legacy/Svelte add editors, custom editors, reviewer,
  profile changes, sync, native import dialogs, and collection package import.
- `plugin/legacy.py`: compatibility translations, typed/native projections,
  accepted-operation timing and barriers, attachment acquisition, preset
  translation, and explicit errors for unsafe legacy behavior.
- `plugin/media.py`: request-owned media journal, backups, rollback, and recovery
  after interruption, with ownership checks to avoid removing unrelated files.
- `tools/build_api_contract.py`: generates bundled `plugin/contract.py` from the
  schema and legacy mapping. Regenerate when either source contract changes.
- `tools/package_addon.py` and `package.sh`: nondestructive packaging replaces
  the old `git clean -xdf` script. Packaging has not been run.
- `pyproject.toml`: dependency/test configuration. Default tests are `tests_api`.
  Old `tests/` depend on obsolete pytest-anki and are not the default suite.

Most recent fixes: grouped text replacement now produces one native undo entry;
normal-to-cloze conversion uses the native cloze mapping rules. Both regression
tests pass.

## Remaining work, in priority order

### 1. Finish implementation review and close concrete gaps

- **New API media replacement:** inspect `Runtime.acquire_media` and
  `Services.store_bytes`. The new `media.store` replacement path currently uses
  a low-level trash/write sequence; unlike the legacy path it needs the media
  transaction journal so a failed native write restores the previous file.
  Add a meaningful failure/rollback regression test.
- Audit capabilities: `api.describe` currently advertises all 94 methods as
  available. Ensure availability reflects actual supported native capabilities
  and that unsupported subfeatures fail explicitly. Do not equate implemented
  entry points with verified GUI behavior.
- Review template field-usage parsing: current implementation uses regex token
  scanning, while the specification promises native parsing. Investigate native
  support or implement robust parsing and accurately revise the contract.
- Review legacy preset coverage: changes to unmapped legacy settings are
  rejected. In particular, `newPerDayMinimum` is absent from the typed v1 preset
  fields. Decide whether to extend the new API to preserve this feature.
- Review affected-editor gates. They conservatively reject affected open
  editors, including clean editors, and may reject pending JavaScript state.
  Messages/docs should reflect actual behavior; improve safe cases if feasible.
- Review session invalidation on native collection unload/reopen outside the
  adapter. Current detection mostly uses collection identity; explicit profile
  and full-sync paths invalidate sessions. Native unload hooks may be needed.
- Review nested `multi` exit ordering and queued GUI admission checks. Exit is
  restricted to the final immediate action, but nested cases need inspection.
- Add contract consistency checks if useful: bundled schema equals source,
  all 122 legacy targets exist, and all 94 methods have handlers.
- Exercise cancellation between `api.execute` commands and preservation of
  completed outcomes if further tests are needed. Running native operations
  cannot all be interrupted; GUI operations register native cancellation hooks.

### 2. Update documentation to describe the actual implementation

Documentation still largely describes the old runtime or a future design.

- `README.md`: new endpoint/example, minimum Anki 26.9.3, dependencies and test
  setup, compatibility behavior, known limitations.
- `ARCHITECTURE.md`: rewrite around the modules above, main-thread admission,
  serialized collection work, sessions, operation completion barriers, native
  change notifications, and media transactions.
- `API_V1.md` and `api-v1.schema.json`: replace future/design-only status language;
  reconcile promises with actual implementation and explicit unsupported cases.
- `LEGACY_API_MAPPING.md`: explain that forwarders are implemented; preserve the
  historical audit/mapping where useful and document compatibility failures.
- `INTEGRATION_ISSUES.md`: record implementation dispositions against the
  original issues, distinguishing resolved code from unverified integration.
- Clearly mark old `tests/` as legacy if retained; avoid documenting the broken
  pytest-anki workflow as the primary validation path.
- Regenerate `plugin/contract.py` after contract/mapping updates.

### 3. Complete GUI integration validation

Actual native collection integration is tested. GUI integration is incomplete.

An offscreen Anki smoke test loaded a temporary profile, exercised new collection
reads/native note creation, and verified a populated legacy Add draft with its
typed snapshot. However, Qt WebEngine subsequently segfaulted (exit 139).
Software-rendering retries and a Svelte-only attempt also crashed. There was no
Python traceback identifying an implementation error. Do not claim full GUI
validation from these runs.

On the new PC, use a working display and **temporary Anki profiles** to validate:

- Legacy and Svelte Add editors: open, populate, update, inspect, save/close.
- Browser selection/search and custom edit windows.
- Reviewer question/answer tokens, hooks, native answer completion, UI refresh.
- Import dialogs: success, failure, cancellation, final operation result.
- Profile switching and collection package import/reopen/session invalidation.
- Sync/full sync/media sync, when a suitable disposable test account is available.
- GUI exit after queued HTTP replies finish.

Original temporary smoke script: `/tmp/anki_api_gui_smoke.py`. It is not checked
in and is not a reliable passing test. Recreate or recover it only as a starting
point. Avoid personal collections and destructive sync testing.

### 4. Final checks and completion report

Run the commands below after edits; inspect `git diff --check` and the final diff.
Report the actual tests run and remaining GUI/network validation limitations.
Do not mark the entire task done while known implementation gaps remain.
No commit or publication was requested; leave changes reviewable unless asked.

## Validation already completed

Most recent run: **19 tests passed** in `tests_api/test_runtime.py` (about 1 second).
They use real temporary native Anki collections plus fake Qt admission where
appropriate. Coverage includes native CRUD, legacy forwarding/signatures,
schema/HTTP authentication/CORS/notifications, operations, atomic validation,
media ownership/recovery, decks/presets/tags, historical review transactions,
cursor binding, conversion and undo, scheduling tokens, package export/import,
HTTP `multi` barriers, and ordered execution after errors.

`tools/check_api_spec.py` passed with the official JSON Schema validator:
94 methods, 122 legacy actions, 27 issue dispositions, 15 positive and 16
negative fixtures. Compilation passed earlier; rerun after final edits.

## Environment and commands

Original environment: `/tmp/anki-api-runtime-env/bin/python3`, Python 3.13,
Anki/aqt 26.9.3, PyQt6 and Qt WebEngine 6.11, jsonschema, pytest 9.
Reference source: `/home/alex/projects/anki/anki-26.09.3`; the user's original
reference location was `~/projects/anki`. Locate the equivalent on the new PC.

Suggested new environment (adapt Python executable/path to the new PC):

```bash
python3 -m venv /tmp/anki-api-runtime-env
/tmp/anki-api-runtime-env/bin/python3 -m pip install 'anki==26.9.3' 'aqt==26.9.3' 'jsonschema>=4.18' 'pytest>=8'
```

Do not install pytest-anki for the new suite. Its installed version on the old
PC imports removed `anki.importing.apkg` and PyQt5; pytest configuration disables
its plugin, as well as xvfb auto-loading.

From the repository root:

```bash
/tmp/anki-api-runtime-env/bin/python3 tools/build_api_contract.py
/tmp/anki-api-runtime-env/bin/python3 -m pytest -q --tb=short
/tmp/anki-api-runtime-env/bin/python3 tools/check_api_spec.py
/tmp/anki-api-runtime-env/bin/python3 -m compileall -q plugin tools
git diff --check
git status --short
```

For GUI smoke tests, the old PC used `QT_QPA_PLATFORM=offscreen` and
`QTWEBENGINE_DISABLE_SANDBOX=1`, but the WebEngine crashes remain unresolved.
A working desktop display on the new PC is preferable. Sandbox permissions and
approved command prefixes from the old session will not necessarily transfer.

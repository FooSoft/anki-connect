# Repository guidance

## Purpose

Anki-Connect is a Python add-on loaded by Anki Desktop. It lets external programs,
including browser extensions such as Yomichan, query and modify the active Anki
collection and control parts of the GUI through a JSON-over-HTTP API. Anki must
be running; the default endpoint is `http://127.0.0.1:8765` and the API version
is 6. The source currently enforces a minimum Anki version of 26.08; `/api/v1` uses JSON-RPC 2.0 and the root endpoint retains legacy API version 6.

Read [ARCHITECTURE.md](ARCHITECTURE.md) for runtime structure and
[API_V1.md](API_V1.md) and [API_LEGACY.md](API_LEGACY.md) for method documentation and request examples. Where the
README and implementation differ, inspect the implementation before making or
documenting a change.

## Source map

- `plugin/__init__.py`: startup, legacy signatures/dispatch and permissions.
- `plugin/runtime.py` and `plugin/protocol.py`: Qt admission, sessions, schema
  dispatch, asynchronous completion, operations, and ordered execution.
- `plugin/services.py`, `plugin/gui.py`, `plugin/legacy.py`, `plugin/media.py`:
  native domain services, Qt adapters, forwarders, and media recovery.
- `plugin/web.py`: socket HTTP transport, JSON schema validation, CORS, and reply
  formatting.
- `plugin/edit.py`: custom note editor, note history, browser integration, and
  card preview.
- `plugin/util.py`: API decorator, configuration defaults, downloads, and
  compatibility helpers.
- `plugin/config.json`: shipped add-on settings; `plugin/config.md` supplies the
  configuration help text.
- `tests_api/`: default native collection and admission regression tests.
- `API_TEST_COVERAGE.md`: every public method's reviewed test evidence and gaps;
  generated from `tests_api/api_coverage.json` by `tools/check_api_coverage.py --write`.
- `test.sh` and `test.ps1`: cached Anki version matrix for both APIs on Unix and Windows.
- `tools/smoke_gui.py`: GUI scenarios with disposable profiles.
- `link.sh`: links `plugin/` into an existing Linux or macOS Anki add-ons folder
  as `AnkiConnectDev`.
- `package.sh`: creates `AnkiConnect.zip` through the nondestructive Python builder.

## Making changes

- Match the surrounding Python style, including existing public camelCase action
  names and parameter names. They are part of the external API.
- Add new v1 methods to the source schema and shared adapters, then regenerate
  `plugin/contract.py`. Legacy actions use `@util.api()`; preserve versioned aliases
  and the dispatcher rules when changing them.
- Add API guide documentation with request/result examples and behavior tests for
  new or changed API features, following the contribution guidance in README.
- Keep GUI access and request admission on Qt's main thread. Use Anki's
  serialized task manager for collection work and completion callbacks for native
  notifications. Avoid blocking Qt or running nested event loops in production.
- Use the existing collection, scheduler, model, and media helpers. Preserve
  mutation/reset behavior and account for editor state and asynchronous Anki
  operations when changing writes.
- Preserve API key checking, origin permission handling, and response shapes.
  Successful requests at version 4 or lower return a bare result; exceptions
  currently return a `result`/`error` object even at those versions.
- When changing settings, check both `plugin/config.json` and
  `plugin/util.py::DEFAULT_CONFIG`; the shipped config contains only a subset of
  available defaults.
- Do not hand-edit the distribution ZIP for source changes.

## Validation

The main goal of tests is detecting changes in Anki internals that break the plugin.
Prioritize real native services and GUI boundaries, result/effect assertions, and
completion/lifecycle checks across versions. Protocol checks are supplementary;
do not require HTTP coverage per method. Exceedingly difficult GUI effects may be
deferred in the coverage inventory with a reason and a practical alternative.

Run `./test.sh` for the cached version matrix, including UI scenarios by default.
On Windows, run `.\test.ps1`; `-NoUI` skips UI scenarios.
Use `./test.sh --no-ui` for unit-only validation. The default suite is configured in `pyproject.toml`. Use Python 3.10+ with
`anki==26.9.3`, `aqt==26.9.3`, `jsonschema>=4.18`, and `pytest>=8` in a separate
environment. Do not install pytest-anki for this suite.

```bash
python tools/build_api_contract.py
python -m pytest -q --tb=short
python tools/check_api_spec.py
python tools/check_api_docs.py
python tools/check_api_coverage.py
python -m compileall -q plugin tools
git diff --check
```

Native tests use disposable collections; controlled admission tests do not
certify real GUI completion. GUI scenarios use a working display and run by default through `test.sh`:
`python tools/smoke_gui.py all`. They create temporary profiles, use no sync
credentials, and isolate processes. Check the output for Qt/JavaScript failures;
the exit scenario checks HTTP reply delivery before native shutdown. Network sync needs a disposable account.

Use temporary profiles rather than personal collections. Packaging is not a
routine validation step and must not clean untracked or ignored files.

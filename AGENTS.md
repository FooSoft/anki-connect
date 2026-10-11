# Repository guidance

## Purpose

Anki-Connect is a Python add-on loaded by Anki Desktop. It lets external programs,
including browser extensions such as Yomichan, query and modify the active Anki
collection and control parts of the GUI through a JSON-over-HTTP API. Anki must
be running; the default endpoint is `http://127.0.0.1:8765` and the API version
is 6. The source currently enforces a minimum Anki version of 23.10.0.

Read [ARCHITECTURE.md](ARCHITECTURE.md) for runtime structure and
[README.md](README.md) for action documentation and request examples. Where the
README and implementation differ, inspect the implementation before making or
documenting a change.

## Source map

- `plugin/__init__.py`: version check, add-on startup, `AnkiConnect` dispatcher,
  and API actions for notes, cards, decks, models, media, statistics, and GUI.
- `plugin/web.py`: socket HTTP transport, JSON schema validation, CORS, and reply
  formatting.
- `plugin/edit.py`: custom note editor, note history, browser integration, and
  card preview.
- `plugin/util.py`: API decorator, configuration defaults, downloads, and
  compatibility helpers.
- `plugin/config.json`: shipped add-on settings; `plugin/config.md` supplies the
  configuration help text.
- `tests/`: pytest tests using real Anki/Qt sessions and temporary profiles.
- `link.sh`: links `plugin/` into an existing Linux or macOS Anki add-ons folder
  as `AnkiConnectDev`.
- `package.sh`: cleans the checkout and creates `AnkiConnect.zip` with `7za`.

## Making changes

- Match the surrounding Python style, including existing public camelCase action
  names and parameter names. They are part of the external API.
- Expose new actions with `@util.api()`. Preserve versioned aliases and the
  dispatcher rules when changing existing actions.
- Add README documentation with request/result examples and behavior tests for
  new or changed API features, following the contribution guidance in README.
- Keep Anki collection and GUI access on the Qt main thread. The HTTP server is
  advanced by a timer, so blocking work can also block the UI.
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

The repository has no dependency manifest or checked-in test runner config.
Tests need an environment with a compatible Anki/`aqt`, its Qt dependencies,
`jsonschema`, `pytest`, `pytest-anki`, `pytest-forked`, and `waitress`.
The fixtures access pytest's `forked` option, so `pytest-forked` must be available
even when running without `--forked`. Qt tests need a working display or a
configured headless environment that supports Anki's web views.

From the repository root, in that environment:

```bash
python -m pytest tests/test_notes.py
python -m pytest tests/test_server.py
python -m pytest tests/
```

Choose the action-category test module relevant to the change. Transport,
validation, CORS, and serialization changes should also exercise
`tests/test_server.py`; editor changes belong in `tests/test_edit.py`.
On platforms supporting process forking, `--forked` provides per-test process
isolation. The fixtures otherwise recreate the temporary profile by default.
`-T` disables that recreation and provides weaker cleanup; use it deliberately.
Report missing dependencies or display failures as validation limitations.

Use temporary test profiles rather than a personal collection. Inspect
`package.sh` before packaging: its `git clean -xdf` deletes untracked and ignored
files, including local environments and newly created files. Do not run it as a
routine validation step.

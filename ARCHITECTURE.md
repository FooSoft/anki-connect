# Anki-Connect architecture

Anki-Connect runs inside Anki Desktop 26.08 or later. It serves JSON-RPC 2.0 at
`POST /api/v1` and the legacy action protocol at `/`, on `127.0.0.1:8765` by
default. The canonical contract is [API_V1.md](API_V1.md) and
[api-v1.schema.json](api-v1.schema.json). The legacy API still reports version 6.

| Module | Responsibility |
| --- | --- |
| `plugin/__init__.py` | Version gate, startup, settings, permissions, exact legacy signatures, and asynchronous legacy dispatch. |
| `plugin/web.py` | Nonblocking sockets, path routing, strict JSON, HTTP limits, CORS, authentication, and deferred replies. |
| `plugin/protocol.py` | Schema validation, typed errors, callback completion, operation records and cancellation. |
| `plugin/runtime.py` | Qt admission, collection/session pins, serialized native work, completion notifications, ordered commands and tokens/cursors. |
| `plugin/services.py` | Native collection, scheduler, note-type, preset, media, package, statistics and undo services. |
| `plugin/gui.py` | Browser, editor, reviewer, import, profile and sync adapters on Qt's main thread. |
| `plugin/legacy.py` | Argument translation, result projection, compatibility failures and attachment orchestration. |
| `plugin/media.py` | Request-owned media backups, rollback and interrupted-request recovery. |
| `plugin/contract.py` | Generated bundled schema and legacy target map. |
| `plugin/edit.py` | Custom note editor and session-local history. |

## Execution and completion

Add-on startup registers the custom editor and unload hooks, opens optional
metadata logging, and starts a retained Qt timer. Importing as `plugin` in tests
skips automatic startup. The timer advances socket reads/writes without blocking
on API completion. Each connection closes after its reply drains.

Admission captures the active collection and opaque session on Qt's main thread.
GUI operations stay there. Collection tasks use Anki's task manager with its
serialized collection access and background-operation lifecycle counter. File
reads/downloads use background tasks without collection access. Completion callbacks
publish native changes through `on_op_finished` before resolving API replies.
Failed operations also publish changes from successful prefixes.

```mermaid
flowchart LR
    Client -->|HTTP| Transport[web.py]
    Transport --> Dispatcher[protocol.py]
    Dispatcher --> Admission[runtime.py on Qt]
    Admission --> Native[services.py serialized collection work]
    Admission --> GUI[gui.py on Qt]
    Native --> Completion[Qt completion and native notifications]
    GUI --> Completion
    Completion -->|deferred reply or operation result| Transport
```

Completed methods reply after work and native notifications. Interactive/long
methods return operation handles; poll `operations.get` for final results.
`api.execute` waits for each final outcome and continues after item errors.
Cancellation between commands preserves completed outcomes in error details.
Running work is cancellable only where a native cancellation callback is wired.
Disconnecting a socket does not cancel accepted work.

Legacy standalone GUI actions preserve accepted-return timing where documented.
Legacy `multi` waits for each final outcome, including nested batches. It preflights
the full request tree for malformed actions, depth/count limits and final exit
ordering. Neither command form creates a transaction across items. Exit begins
only after outstanding socket replies drain.

## Sessions and editor coordination

Sessions change on collection identity changes, profile unload, temporary collection
close/full sync and adapter-controlled reopen. Tokens, cursors, editor registrations
and custom editor history are invalidated. Collection calls pin their admission
session and recheck it before execution; lifecycle transitions reject competing work.
Queued GUI calls recheck active collection work when they start.

Affected open editors conservatively block writes, including clean/saved editors
and potentially pending webview changes. Close affected editors to proceed. Add
drafts have explicit update methods and reject content replacement/type changes
when a draft already contains unsaved content. This release does not claim fully
synchronized dirty-state detection for every editor variant.

## Native writes and media

Services use native note-type conversion, deck moves, scheduler states/answers and
coordinated preset update requests. Atomic bulk note creation preflights before a
native bulk transaction; ordinary bulk work returns independent item outcomes.
Undo support is declared per method; grouped undo is distinct from atomicity.
Advanced history import is an explicit database transaction, clears undo and
requests native cache/window refresh. Template usage uses an adapter mirroring
Anki's token grammar because the parsed tree is not exposed to Python.

Media acquisition finishes before replacement. Replacement writes use a journal
outside the media directory, backing up originals before native trash/write.
Failure restores request-owned files; ownership conflicts preserve unrelated
changes and retain the journal for recovery. Legacy note attachments use the same
journal around collection changes. Database and filesystem writes do not share
an atomic transaction. Recovery conservatively keeps media referenced by notes
when interruption makes collection commit status uncertain.

## Access, configuration and validation

Existing settings and default fallbacks remain in `plugin/config.json` and
`plugin/util.py`. Legacy requests use body `key`; v1 uses Bearer authentication.
Permission methods alone bypass key checks and receive origin context from the
transport. Origin filtering and authentication are independent. Routine logs
contain method/ID/timing/error metadata, excluding credentials and note/media bodies.

`api.describe` reports adapter presence and checked native dependencies. Availability
is a capability probe, not proof of integration testing; method-specific state and
unsupported subfeatures can still produce explicit errors.

`tests_api/` is the default suite and uses disposable native collections, with
controlled Qt admission for ordering tests. Real GUI checks require a working
display and temporary profiles; sync requires a disposable test account. Run `./test.sh` to execute unit tests and all GUI scenarios for both protocols against
the Anki versions listed in its array, using isolated cached environments.
On Windows, `.\test.ps1` runs the same matrix in PowerShell.
Use `--no-ui` (PowerShell: `-NoUI`) to skip GUI scenarios when a display is unavailable.
The public references are [API v1](API_V1.md) and [legacy API](API_LEGACY.md).
The [coverage inventory](API_TEST_COVERAGE.md) distinguishes direct service,
controlled admission, and real GUI evidence for each public method. Both test
runners validate its registry coverage and source references; known testing gaps
are explicitly listed and remain work to do.

`tools/build_api_contract.py` bundles the source contract, including the
`x-legacyTargets` registry used for legacy capability checks. Use `--check` to
verify generated output without writing files. `package.sh` invokes
`tools/package_addon.py`, which builds a ZIP without cleaning the checkout.

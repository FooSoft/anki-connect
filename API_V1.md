# Anki-Connect API v1

Use this API for new integrations. It provides named methods, typed records, explicit
completion for long-running work, and structured errors. Existing applications can
continue using the [legacy API](API_LEGACY.md) at `/`.

Anki Desktop must be running with the add-on enabled. This rewrite requires Anki
26.08 or later; the test matrix covers 26.08 and 26.09.3. Call `api.describe` to check which
methods are available in the current runtime. Native tests cover both protocols. GUI scenarios require a working display;
network sync requires a disposable account and separate integration testing.

## Quick start

Send UTF-8 JSON to `POST http://127.0.0.1:8765/api/v1`:

```bash
curl --request POST http://127.0.0.1:8765/api/v1 \
  --header 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"decks.list","params":{}}'
```

A successful response has the same request ID and a `result`:

```json
{"jsonrpc":"2.0","id":1,"result":[{"id":"1","name":"Default","kind":"normal","presetId":"1"}]}
```

### Python client

This helper uses Python's standard library. Copy it into your application, then use
`call("decks.list")` or `call("notes.search", query="deck:Default")`.

```python
import itertools
import json
import time
import urllib.request

ENDPOINT = "http://127.0.0.1:8765/api/v1"
API_KEY = None  # Set to the configured apiKey, if enabled.
request_ids = itertools.count(1)


def call(method, **params):
    request_id = next(request_ids)
    body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    headers = {"Content-Type": "application/json"}
    if API_KEY is not None:
        headers["Authorization"] = f"Bearer {API_KEY}"
    request = urllib.request.Request(
        ENDPOINT, json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request) as response:
        reply = json.load(response)
    if reply.get("id") != request_id:
        raise RuntimeError("Unexpected response ID")
    if "error" in reply:
        raise RuntimeError(reply["error"])
    return reply["result"]


def wait_for_operation(handle, timeout=300):
    deadline = time.monotonic() + timeout
    delay = 0.25
    while True:
        operation = call("operations.get", operationId=handle["operationId"])
        if operation["state"] == "succeeded":
            return operation["result"]
        if operation["state"] in ("failed", "cancelled"):
            raise RuntimeError(operation["error"])
        if time.monotonic() >= deadline:
            raise TimeoutError("Operation is still pending; retain the handle")
        time.sleep(delay)
        delay = min(delay * 1.5, 2)


print(call("decks.list"))
```

The polling timeout is a client choice. It does not cancel server work.

### JavaScript client

Use this helper from an environment with `fetch`, such as a browser extension or
modern Node.js. Browser requests also need an allowed origin.

```javascript
const endpoint = "http://127.0.0.1:8765/api/v1";
const apiKey = null; // Set to the configured apiKey, if enabled.
let nextId = 1;

async function call(method, params = {}) {
  const id = nextId++;
  const headers = {"Content-Type": "application/json"};
  if (apiKey !== null) headers.Authorization = `Bearer ${apiKey}`;
  const response = await fetch(endpoint, {
    method: "POST",
    headers,
    body: JSON.stringify({jsonrpc: "2.0", id, method, params}),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const reply = await response.json();
  if (reply.id !== id) throw new Error("Unexpected response ID");
  if (reply.error) throw Object.assign(new Error(reply.error.message), {rpc: reply.error});
  return reply.result;
}

async function main() {
  console.log(await call("decks.list"));
}
main().catch(console.error);
```

## Requests, authentication, and errors

The endpoint uses JSON-RPC 2.0 with **named parameters**. `params` may be omitted
when empty. Always send an `id` for commands. Entity IDs are decimal strings;
request IDs may be strings, integers, or null. `/api/v1` is the API version and `"2.0"`
is the JSON-RPC protocol version.

If `apiKey` is configured, include `Authorization: Bearer <key>`. Authentication
is disabled when the key is null. Origin permission is checked separately using
`webCorsOriginList` and `ignoreOriginList`. `access.requestPermission` uses the
actual HTTP origin, is exempt from the API key check, and never returns the key.

JSON-RPC results and errors use HTTP 200, including parse errors. Transport
rejections have empty bodies: 401 for an invalid key, 403 for a rejected origin,
405 for a non-POST request, and 413 for an oversized body. Check the HTTP status
before parsing JSON. Allowed OPTIONS requests support browser preflight.

```json
{"jsonrpc":"2.0","id":1,"error":{"code":1001,"message":"Note not found.","data":{"type":"notFound"}}}
```

Match `error.data.type` or `error.code`, rather than the human-readable message.
Standard codes are -32700 (parse error), -32600 (invalid request), -32601 (unknown
method), -32602 (invalid parameters), and -32603 (internal error).

| Code | Error type | Meaning |
| --- | --- | --- |
| 1001 | `notFound` | A referenced resource does not exist. |
| 1002 | `validationFailed` | Content or native validation failed. |
| 1003 | `editorConflict` | An open editor prevents the requested change. |
| 1004 | `collectionUnavailable` | No collection is open. |
| 1005 | `staleSession` | The collection session changed. |
| 1006 | `unsupportedCapability` | The runtime cannot safely perform this method. |
| 1007 | `cancelled` | The operation was cancelled. |
| 1008 | `conflict` | A token or resource conflicts with current state. |
| 1009 | `invalidState` | The GUI or scheduler is in an incompatible state. |
| 1010 | `busy` | A lifecycle transition or capacity limit prevents admission. |
| 1011 | `authenticationRequired` | Anki sync credentials are unavailable. |
| 1012 | `ioError` | File, download, import, or export failed. |
| 1013 | `invalidSearch` | Anki rejected the search query. |
| 1014 | `staleCursor` | A cursor expired or belongs to another session. |
| 1015 | `vetoed` | A reviewer hook prevented the answer. |
| 1016 | `compatibilityError` | A legacy request cannot be translated safely. |

Additional error details may identify invalid inputs with JSON pointers or item
indexes. `retryable` is advisory. A request ID is not an idempotency key: do not
retry a write automatically after losing its response.

## Working with collections

- Get the current `session` with `collection.get` and pass it to subsequent
  collection methods. A stale session fails before work. Without an explicit
  session, the server captures the current session at admission and checks it
  again at execution. IDs belong to a collection, so reacquire them after switching
  profiles. Switching invalidates cursors, scheduling tokens, and editor history.
- Reference a deck, preset, or note type with exactly one of `{"id":"1"}` or
  `{"name":"Default"}`. Reads never create missing resources.
- Fields contain HTML. Field names are exact. Updates change only supplied
  properties; note field patches merge by name, while supplied tags replace the
  entire tag set. Null is accepted only where documented. Empty patches fail.
- Bulk results use `{"items":[...]}` with the original `index` and either `result`
  or `error` for each item. Shape errors reject the whole request. Item failures
  are otherwise independent unless the method documents atomic behavior.
- Affected editors must be closed before collection writes, including saved
  editors. An operation may still require user interaction in Anki.
- Timestamps use RFC 3339 UTC. Intervals include units. Scheduling day numbers
  belong to Anki's collection epoch, rather than Unix time. SM-2 ease is in
  permille; FSRS stability and difficulty are separate values.

### Undo behavior

Method entries label their undo behavior: `single` creates one entry, `perItem`
creates independent entries, and `perItemOrAtomic` depends on the atomic option.
`perCommand` follows each ordered command’s behavior. `clears` clears existing
undo history; `none` creates no collection undo entry. `undo` performs native undo.
Undo grouping does not imply a transaction across multiple native calls.

### Search and pagination

Search uses Anki's query syntax; an empty query matches everything. The default
page size is 100 and the maximum is 1000. Search results use ascending ID order
unless a browser column sort is supplied. Explicit sorts use Anki's native browser
ordering; `column` is a browser column key such as `noteFld` or `cardDue`.

```python
session = call("collection.get")["session"]
cursor = None
while True:
    params = {"query": "deck:Default", "limit": 100, "session": session}
    if cursor is not None:
        params["cursor"] = cursor
    page = call("notes.search", **params)
    print(page["ids"])
    cursor = page["nextCursor"]
    if cursor is None:
        break
```

Repeat the same query, sort, and limit on subsequent pages. Cursors snapshot the
ordered matching IDs for ten minutes: deleted resources are omitted, and newly
matching resources appear in a new search. Review pagination likewise snapshots
IDs; `afterId` is exclusive. Methods without cursors return their whole list.

### Operations and ordered commands

Methods marked **operation** return an `OperationHandle`, rather than their final
result. Poll `operations.get`, or use `wait_for_operation` above. States are
`queued`, `running`, `waitingForUser`, `succeeded`, `failed`, and `cancelled`.
Only terminal records contain a result or error. Handles remain readable after
profile switching, but are lost when Anki restarts.

```python
handle = call("browser.open", query="deck:Default")
selection = wait_for_operation(handle)
print(selection)
```

A completed method replies after its required work and notifications. An operation
succeeds after its final work and notifications. `application.exit` is a special
case: its reply acknowledges a scheduled close; user dialogs can still prevent exit.

`operations.cancel` requests supported cancellation. Check `cancellable` first;
a cancellation can race with success and does not undo changes already committed.
Disconnecting a client does not cancel accepted work. Operations are retained for
one hour after completion, with at most 1000 terminal and 100 active records.

A JSON-RPC batch array does not order commands and does not create a transaction.
For ordered execution, use `api.execute`: it waits for each command's final
outcome, continues after errors, and returns an operation whose final result has
item results. It does not substitute earlier results into later parameters.
Nested execute, profile switching, and application exit are prohibited inside it.
Notifications omit `id`, return HTTP 204, and execute only read methods;
notifications requesting side effects are ignored. Batches are limited to 100
requests. The maximum request body is 16 MiB.
Batch items must be request objects; nested batch arrays are rejected without
executing their contents. Invalid request IDs produce an error with `id:null`.

### Notes and media

Validate notes before creation when you need eligibility feedback. Validation
performs no downloads or media writes. `notes.createMany` normally commits each
item independently; `atomic:true` preflights the entire batch, including duplicates,
and adds it in one native transaction with one undo entry. Third-party add-on hook
I/O is outside this transaction.

Store media separately, then insert the **returned** filename into field HTML or
`[sound:filename]` references. The server may normalize or rename the requested
filename. `skipIfHash` compares incoming bytes; a skipped result has no filename
and promises no stored file. Explicit replacement journals the original file for
rollback on owned-write failure. Media writes cannot be undone with collection undo.
File paths refer to the machine running Anki. Files are limited to 64 MiB; for data
larger than the JSON body limit, use a path source. Socket read/write idle timeout
is ten seconds; accepted work has no implicit execution timeout.

### Scheduling and reviewer tokens

Use `scheduling.predict` to obtain the current `stateToken`, then pass that token
and an offered rating to `scheduling.answer`. Tokens are session-bound and become
invalid when the relevant state changes. For the active GUI reviewer, use
`reviewer.get` and the `reviewer.*` methods so custom scheduling and reviewer hooks
are respected. Show the answer before answering, and reacquire the reviewer token
after changing the displayed side or card.

Advanced card edits are restricted to validated metadata. History import adds
historical records, clears undo, and does not answer or reschedule cards.

## Method reference

Every JSON request below can be saved as `request.json` and sent with:

```bash
curl --request POST http://127.0.0.1:8765/api/v1 \
  --header 'Content-Type: application/json' --data-binary @request.json
```

Add the Authorization header if needed. Examples assume the referenced resources
exist. Replace example entity IDs, paths, profile names, and opaque tokens with
values from your Anki instance. The examples demonstrate individual calls; they
are not a script to run sequentially. Collection methods also accept optional
`session`. Parameter tables list all supported inputs, including defaults; unknown
input properties are rejected. Return types describe `result`, without the JSON-RPC
envelope. Clients should tolerate added response properties.

- **Discovery and ordered execution:** [api.describe](#apidescribe), [api.execute](#apiexecute).
- **Access permissions:** [access.requestPermission](#accessrequestpermission).
- **Profiles:** [profiles.list](#profileslist), [profiles.getActive](#profilesgetactive), [profiles.switch](#profilesswitch).
- **Collection lifecycle:** [collection.get](#collectionget), [collection.sync](#collectionsync), [collection.refresh](#collectionrefresh), [collection.checkIntegrity](#collectioncheckintegrity), [collection.undo](#collectionundo).
- **Notes:** [notes.get](#notesget), [notes.getMany](#notesgetmany), [notes.search](#notessearch), [notes.validate](#notesvalidate), [notes.validateMany](#notesvalidatemany), [notes.create](#notescreate), [notes.createMany](#notescreatemany), [notes.update](#notesupdate), [notes.delete](#notesdelete), [notes.planConversion](#notesplanconversion), [notes.convert](#notesconvert), [notes.findEmpty](#notesfindempty).
- **Tags:** [tags.list](#tagslist), [tags.add](#tagsadd), [tags.remove](#tagsremove), [tags.replace](#tagsreplace), [tags.deleteUnused](#tagsdeleteunused).
- **Cards:** [cards.get](#cardsget), [cards.getMany](#cardsgetmany), [cards.search](#cardssearch), [cards.render](#cardsrender), [cards.move](#cardsmove), [cards.setSuspended](#cardssetsuspended), [cards.setFlags](#cardssetflags).
- **Scheduling:** [scheduling.get](#schedulingget), [scheduling.predict](#schedulingpredict), [scheduling.getDue](#schedulinggetdue), [scheduling.answer](#schedulinganswer), [scheduling.answerMany](#schedulinganswermany), [scheduling.reset](#schedulingreset), [scheduling.setDueDate](#schedulingsetduedate).
- **Decks:** [decks.list](#deckslist), [decks.get](#decksget), [decks.create](#deckscreate), [decks.update](#decksupdate), [decks.delete](#decksdelete), [decks.getCounts](#decksgetcounts).
- **Deck presets:** [deckPresets.list](#deckpresetslist), [deckPresets.get](#deckpresetsget), [deckPresets.create](#deckpresetscreate), [deckPresets.update](#deckpresetsupdate), [deckPresets.assign](#deckpresetsassign), [deckPresets.delete](#deckpresetsdelete).
- **Note types:** [noteTypes.list](#notetypeslist), [noteTypes.get](#notetypesget), [noteTypes.create](#notetypescreate), [noteTypes.update](#notetypesupdate), [noteTypes.editStructure](#notetypeseditstructure), [noteTypes.getTemplateUsage](#notetypesgettemplateusage), [noteTypes.replaceText](#notetypesreplacetext), [noteTypes.deleteUnused](#notetypesdeleteunused).
- **Media:** [media.store](#mediastore), [media.get](#mediaget), [media.list](#medialist), [media.delete](#mediadelete), [media.getDirectory](#mediagetdirectory).
- **Review history:** [reviews.list](#reviewslist), [reviews.getLatestId](#reviewsgetlatestid).
- **Statistics:** [statistics.getToday](#statisticsgettoday), [statistics.getReviewDays](#statisticsgetreviewdays), [statistics.getSummary](#statisticsgetsummary), [statistics.getHtml](#statisticsgethtml).
- **Package import and export:** [packages.import](#packagesimport), [packages.export](#packagesexport).
- **Browser:** [browser.open](#browseropen), [browser.getSelection](#browsergetselection), [browser.select](#browserselect).
- **Editors:** [editors.openNote](#editorsopennote), [editors.openAdd](#editorsopenadd), [editors.updateDraft](#editorsupdatedraft).
- **Reviewer:** [reviewer.get](#reviewerget), [reviewer.startTimer](#reviewerstarttimer), [reviewer.showQuestion](#reviewershowquestion), [reviewer.showAnswer](#reviewershowanswer), [reviewer.answer](#revieweranswer), [reviewer.playAudio](#reviewerplayaudio).
- **Application:** [application.navigate](#applicationnavigate), [application.importFile](#applicationimportfile), [application.exit](#applicationexit).
- **Advanced writes:** [advanced.cards.update](#advancedcardsupdate), [advanced.reviews.import](#advancedreviewsimport).
- **Operation tracking:** [operations.get](#operationsget), [operations.cancel](#operationscancel).

[Shared types](#shared-types) · [Machine-readable schema](api-v1.schema.json)

## Discovery and ordered execution

### `api.describe`

Discover methods, schemas, limits and runtime capabilities.

**Scope:** application. **Completion:** completed. **Undo:** `none`.

**Parameters**

No parameters.

**Returns**

[Description](#type-description).

**Errors:** `internalError`, `invalidParams`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "api.describe",
  "params": {}
}
```

### `api.execute`

Execute commands sequentially with completion barriers and independent results.

**Scope:** application. **Completion:** operation. **Undo:** `perCommand`.

Continue after errors. No nested api.execute, application.exit or profiles.switch commands. Pin the active collection session for collection-scoped commands; a session change fails remaining such commands. Validate each command with its named method schema. Never an atomic transaction.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `commands` | array of [Command](#type-command) | Yes | Maximum items: 100. |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"api.execute"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[BatchResult](#type-batchresult).

**Errors:** `internalError`, `invalidParams`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "api.execute",
  "params": {
    "commands": [
      {
        "method": "decks.create",
        "params": {
          "name": "Vocabulary"
        }
      },
      {
        "method": "decks.list",
        "params": {}
      }
    ]
  }
}
```

## Access permissions

### `access.requestPermission`

Ask for access using the transport-supplied origin.

**Scope:** application. **Completion:** completed. **Undo:** `none`.

Never accept origin or allowed from parameters. Authentication exemption matches legacy permission discovery.

**Parameters**

No parameters.

**Returns**

[Permission](#type-permission).

**Errors:** `internalError`, `invalidParams`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "access.requestPermission",
  "params": {}
}
```

## Profiles

### `profiles.list`

List existing profiles.

**Scope:** application. **Completion:** completed. **Undo:** `none`.

**Parameters**

No parameters.

**Returns**

array of [Profile](#type-profile).

**Errors:** `internalError`, `invalidParams`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "profiles.list",
  "params": {}
}
```

### `profiles.getActive`

Return the active profile or null.

**Scope:** application. **Completion:** completed. **Undo:** `none`.

**Parameters**

No parameters.

**Returns**

Variant result, with the following schema:

```json
{
  "anyOf": [
    {
      "$ref": "#/$defs/Profile"
    },
    {
      "type": "null"
    }
  ]
}
```

**Errors:** `internalError`, `invalidParams`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "profiles.getActive",
  "params": {}
}
```

### `profiles.switch`

Switch profiles and finish when the destination collection is ready.

**Scope:** application. **Completion:** operation. **Undo:** `none`.

Replace `User 1` with a name returned by `profiles.list`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `name` | string | Yes | Minimum length: 1. |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"profiles.switch"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[Collection](#type-collection).

**Errors:** `busy`, `cancelled`, `internalError`, `invalidParams`, `notFound`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "profiles.switch",
  "params": {
    "name": "User 1"
  }
}
```

## Collection lifecycle

### `collection.get`

Inspect the active collection and its session.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Collection](#type-collection).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "collection.get",
  "params": {}
}
```

### `collection.sync`

Run one coordinated GUI/background sync.

**Scope:** collection. **Completion:** operation. **Undo:** `none`.

Full sync choices are waitingForUser; never launch a second sync. includeMedia is intersected with profile media-sync settings.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `includeMedia` | boolean | No | Default: `true`. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"collection.sync"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[SyncResult](#type-syncresult).

**Errors:** `authenticationRequired`, `busy`, `cancelled`, `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `ioError`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "collection.sync",
  "params": {}
}
```

**Example response**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "operationId": "op-sync-1",
    "method": "collection.sync",
    "session": "session-1"
  }
}
```

### `collection.refresh`

Refresh windows, optionally invalidating supported collection caches first.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

Does not close/reopen the collection and does not repair invalid scheduling state.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `target` | `"windows"` / `"cachesAndWindows"` | No | Default: `"windows"`. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Ack](#type-ack).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "collection.refresh",
  "params": {}
}
```

### `collection.checkIntegrity`

Run Anki database checks and repairs with normal UI completion.

**Scope:** collection. **Completion:** operation. **Undo:** `clears`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"collection.checkIntegrity"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[IntegrityResult](#type-integrityresult).

**Errors:** `cancelled`, `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "collection.checkIntegrity",
  "params": {}
}
```

### `collection.undo`

Undo the current Anki undo entry.

**Scope:** collection. **Completion:** operation. **Undo:** `undo`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"collection.undo"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[UndoResult](#type-undoresult).

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `invalidState`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "collection.undo",
  "params": {}
}
```

## Notes

### `notes.get`

Get a note, including an empty cardIds array for cardless notes.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `id` | [EntityId](#type-entityid) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Note](#type-note).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "notes.get",
  "params": {
    "id": "1700000000001"
  }
}
```

### `notes.getMany`

Get notes in input order, preserving repeated IDs.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `ids` | array of [EntityId](#type-entityid) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [NoteGetItem](#type-notegetitem) | Yes | — |

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "notes.getMany",
  "params": {
    "ids": [
      "1700000000001"
    ]
  }
}
```

### `notes.search`

Search with Anki syntax; an empty query searches all notes.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `query` | string | Yes | — |
| `limit` | integer | No | Default: `100`. Minimum: 1. Maximum: 1000. |
| `cursor` | string | No | Minimum length: 1. |
| `sort` | [Sort](#type-sort) | No | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[IdPage](#type-idpage).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `invalidSearch`, `staleCursor`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "notes.search",
  "params": {
    "query": "deck:Default"
  }
}
```

### `notes.validate`

Validate note content and duplicate scope without acquiring media.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

Semantic content failures return valid=false and issues; bad references or parameter types are RPC errors.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `note` | [NoteInput](#type-noteinput) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Validation](#type-validation).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "notes.validate",
  "params": {
    "note": {
      "noteType": {
        "name": "Basic"
      },
      "deck": {
        "name": "Default"
      },
      "fields": {
        "Front": "cat",
        "Back": "猫"
      },
      "tags": [
        "vocabulary"
      ]
    }
  }
}
```

### `notes.validateMany`

Validate each note independently without side effects.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `notes` | array of [NoteInput](#type-noteinput) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [NoteValidationItem](#type-notevalidationitem) | Yes | — |

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "notes.validateMany",
  "params": {
    "notes": [
      {
        "noteType": {
          "name": "Basic"
        },
        "deck": {
          "name": "Default"
        },
        "fields": {
          "Front": "cat",
          "Back": "猫"
        },
        "tags": [
          "vocabulary"
        ]
      }
    ]
  }
}
```

### `notes.create`

Create a note and return its actual generated cards.

**Scope:** collection. **Completion:** completed. **Undo:** `single`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `noteType` | [Reference](#type-reference) | Yes | — |
| `deck` | [Reference](#type-reference) | Yes | — |
| `fields` | [FieldValues](#type-fieldvalues) | Yes | — |
| `tags` | array of string | No | Default: `[]`. |
| `duplicates` | [DuplicatePolicy](#type-duplicatepolicy) | No | — |
| `rejectEmptyQuestions` | boolean | No | Default: `true`. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[NoteCreated](#type-notecreated).

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "notes.create",
  "params": {
    "noteType": {
      "name": "Basic"
    },
    "deck": {
      "name": "Default"
    },
    "fields": {
      "Front": "cat",
      "Back": "猫"
    },
    "tags": [
      "vocabulary"
    ]
  }
}
```

### `notes.createMany`

Create notes independently, or as one native atomic collection batch.

**Scope:** collection. **Completion:** completed. **Undo:** `perItemOrAtomic`.

atomic=true validates the full set including within-batch duplicates, then uses Collection.add_notes. Any failure is a top-level error with indexed issues and no collection changes. Success keeps the same items result shape. Empty input is a no-op.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `notes` | array of [NoteInput](#type-noteinput) | Yes | — |
| `atomic` | boolean | No | Default: `false`. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [NoteCreationItem](#type-notecreationitem) | Yes | — |

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "notes.createMany",
  "params": {
    "notes": [
      {
        "noteType": {
          "name": "Basic"
        },
        "deck": {
          "name": "Default"
        },
        "fields": {
          "Front": "cat",
          "Back": "猫"
        },
        "tags": [
          "vocabulary"
        ]
      }
    ],
    "atomic": true
  }
}
```

### `notes.update`

Apply fields and tags together in one native note update.

**Scope:** collection. **Completion:** completed. **Undo:** `single`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `id` | [EntityId](#type-entityid) | Yes | — |
| `patch` | [NotePatch](#type-notepatch) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Note](#type-note).

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "notes.update",
  "params": {
    "id": "1700000000001",
    "patch": {
      "fields": {
        "Back": "猫 (cat)"
      },
      "tags": [
        "vocabulary",
        "animals"
      ]
    }
  }
}
```

### `notes.delete`

Delete notes and their cards; missing IDs are item errors.

**Scope:** collection. **Completion:** completed. **Undo:** `perItem`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `ids` | array of [EntityId](#type-entityid) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [NoteDeleteItem](#type-notedeleteitem) | Yes | — |

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "notes.delete",
  "params": {
    "ids": [
      "1700000000001"
    ]
  }
}
```

### `notes.planConversion`

Get native suggested field/template mappings and a schema token.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `source` | [Reference](#type-reference) | Yes | — |
| `target` | [Reference](#type-reference) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[ConversionPlan](#type-conversionplan).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "notes.planConversion",
  "params": {
    "source": {
      "name": "Basic"
    },
    "target": {
      "name": "Basic (and reversed card)"
    }
  }
}
```

### `notes.convert`

Convert same-type notes through Anki note-type conversion.

**Scope:** collection. **Completion:** completed. **Undo:** `single`.

Mappings are complete target-name to source-name/null lists. Reject duplicate source mappings, mixed source note types and stale tokens. Removed source templates lose their cards/history as defined by Anki; cloze mappings use native supported rules, never raw mid assignment.

First call `notes.planConversion`. Use its `token` as `planToken` and adapt the returned complete field/template mappings. The token in this example is a placeholder.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `ids` | array of [EntityId](#type-entityid) | Yes | — |
| `target` | [Reference](#type-reference) | Yes | — |
| `fields` | array of [ConversionMapping](#type-conversionmapping) | Yes | — |
| `templates` | array of [ConversionMapping](#type-conversionmapping) | Yes | — |
| `planToken` | string | Yes | Minimum length: 1. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Count](#type-count).

**Errors:** `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `unsupportedCapability`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "notes.convert",
  "params": {
    "ids": [
      "1700000000001"
    ],
    "target": {
      "name": "Basic (and reversed card)"
    },
    "fields": [
      {
        "target": "Front",
        "source": "Front"
      },
      {
        "target": "Back",
        "source": "Back"
      }
    ],
    "templates": [
      {
        "target": "Card 1",
        "source": "Card 1"
      },
      {
        "target": "Card 2",
        "source": null
      }
    ],
    "planToken": "replace-with-conversion-plan-token"
  }
}
```

### `notes.findEmpty`

Find cleanup candidates by an explicit criterion.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

No deletion. allFieldsEmpty uses native HTML-aware emptiness; allQuestionsEmpty uses native empty-card generation. Return all matching IDs through normal cursor pagination.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `criterion` | `"allFieldsEmpty"` / `"noCards"` / `"allQuestionsEmpty"` | Yes | — |
| `query` | string | No | Default: `""`. |
| `session` | [SessionId](#type-sessionid) | No | — |
| `limit` | integer | No | Default: `100`. Minimum: 1. Maximum: 1000. |
| `cursor` | string | No | Minimum length: 1. |

**Returns**

[IdPage](#type-idpage).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `invalidSearch`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "notes.findEmpty",
  "params": {
    "criterion": "noCards",
    "limit": 100
  }
}
```

## Tags

### `tags.list`

List registered tags.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

array of string.

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tags.list",
  "params": {}
}
```

### `tags.add`

Add tags on selected notes.

**Scope:** collection. **Completion:** completed. **Undo:** `perItem`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `noteIds` | array of [EntityId](#type-entityid) | Yes | — |
| `tags` | array of string | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [TagAddItem](#type-tagadditem) | Yes | — |

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tags.add",
  "params": {
    "noteIds": [
      "1700000000001"
    ],
    "tags": [
      "animals"
    ]
  }
}
```

### `tags.remove`

Remove tags on selected notes.

**Scope:** collection. **Completion:** completed. **Undo:** `perItem`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `noteIds` | array of [EntityId](#type-entityid) | Yes | — |
| `tags` | array of string | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [TagRemoveItem](#type-tagremoveitem) | Yes | — |

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tags.remove",
  "params": {
    "noteIds": [
      "1700000000001"
    ],
    "tags": [
      "animals"
    ]
  }
}
```

### `tags.replace`

Replace a tag on explicit notes or all notes.

**Scope:** collection. **Completion:** completed. **Undo:** `single`.

Exactly one selector: noteIds or allNotes=true. Never interpret an omitted selector as all notes.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `from` | string | Yes | Minimum length: 1. |
| `to` | string | Yes | Minimum length: 1. |
| `noteIds` | array of [EntityId](#type-entityid) | No | — |
| `allNotes` | boolean | No | Default: `false`. |
| `session` | [SessionId](#type-sessionid) | No | — |

Additional `oneOf` constraint:

```json
{
  "oneOf": [
    {
      "required": [
        "noteIds"
      ],
      "not": {
        "required": [
          "allNotes"
        ]
      }
    },
    {
      "required": [
        "allNotes"
      ],
      "not": {
        "required": [
          "noteIds"
        ]
      },
      "properties": {
        "allNotes": {
          "const": true
        }
      }
    }
  ]
}
```

**Returns**

[Count](#type-count).

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tags.replace",
  "params": {
    "from": "animals",
    "to": "vocabulary::animals",
    "noteIds": [
      "1700000000001"
    ]
  }
}
```

### `tags.deleteUnused`

Remove unused tag registrations.

**Scope:** collection. **Completion:** completed. **Undo:** `single`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Count](#type-count).

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tags.deleteUnused",
  "params": {}
}
```

## Cards

### `cards.get`

Read stored card state without rendering or predicting answers.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `id` | [EntityId](#type-entityid) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Card](#type-card).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "cards.get",
  "params": {
    "id": "1700000000002"
  }
}
```

### `cards.getMany`

Get cards in input order.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `ids` | array of [EntityId](#type-entityid) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [CardGetItem](#type-cardgetitem) | Yes | — |

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "cards.getMany",
  "params": {
    "ids": [
      "1700000000002"
    ]
  }
}
```

### `cards.search`

Search cards using Anki search syntax.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `query` | string | Yes | — |
| `limit` | integer | No | Default: `100`. Minimum: 1. Maximum: 1000. |
| `cursor` | string | No | Minimum length: 1. |
| `sort` | [Sort](#type-sort) | No | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[IdPage](#type-idpage).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `invalidSearch`, `staleCursor`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "cards.search",
  "params": {
    "query": "deck:Default"
  }
}
```

### `cards.render`

Render a stored card with Anki rendering.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `id` | [EntityId](#type-entityid) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[RenderedCard](#type-renderedcard).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "cards.render",
  "params": {
    "id": "1700000000002"
  }
}
```

### `cards.move`

Move cards with Collection.set_deck and target-preset invariants.

**Scope:** collection. **Completion:** completed. **Undo:** `perItem`.

Target must already exist and be normal. Moving out of a filtered deck restores native state first through the native move operation.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `ids` | array of [EntityId](#type-entityid) | Yes | — |
| `deck` | [Reference](#type-reference) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [CardMoveItem](#type-cardmoveitem) | Yes | — |

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "cards.move",
  "params": {
    "ids": [
      "1700000000002"
    ],
    "deck": {
      "name": "Default"
    }
  }
}
```

### `cards.setSuspended`

Suspend or restore cards idempotently.

**Scope:** collection. **Completion:** completed. **Undo:** `perItem`.

changed=false means already in requested state. Process repeated mutation IDs once and repeat their result.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `ids` | array of [EntityId](#type-entityid) | Yes | — |
| `suspended` | boolean | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [CardSuspensionItem](#type-cardsuspensionitem) | Yes | — |

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "cards.setSuspended",
  "params": {
    "ids": [
      "1700000000002"
    ],
    "suspended": true
  }
}
```

### `cards.setFlags`

Set the user flag through Anki native flag persistence.

**Scope:** collection. **Completion:** completed. **Undo:** `perItem`.

Zero clears the user flag; preserve other backend flag bits.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `ids` | array of [EntityId](#type-entityid) | Yes | — |
| `flag` | integer | Yes | Minimum: 0. Maximum: 7. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [CardFlagItem](#type-cardflagitem) | Yes | — |

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "cards.setFlags",
  "params": {
    "ids": [
      "1700000000002"
    ],
    "flag": 1
  }
}
```

## Scheduling

### `scheduling.get`

Read authoritative current scheduling state.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardId` | [EntityId](#type-entityid) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[SchedulingState](#type-schedulingstate).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "scheduling.get",
  "params": {
    "cardId": "1700000000002"
  }
}
```

### `scheduling.predict`

Predict native answers and issue a session-scoped state token.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

Does not represent custom states held by the GUI reviewer. Tokens are invalidated by relevant writes, undo, profile change and scheduler-day rollover.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardId` | [EntityId](#type-entityid) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Predictions](#type-predictions).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "scheduling.predict",
  "params": {
    "cardId": "1700000000002"
  }
}
```

**Example response**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "cardId": "1700000000002",
    "source": "scheduler",
    "stateToken": "prediction-1",
    "answers": [
      {
        "rating": "again",
        "label": "1m",
        "interval": {
          "value": 60,
          "unit": "seconds"
        }
      },
      {
        "rating": "good",
        "label": "10d",
        "interval": {
          "value": 10,
          "unit": "days"
        }
      }
    ]
  }
}
```

### `scheduling.getDue`

Inspect queue-aware due eligibility without requiring history.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

dueNow excludes learn-ahead and suspended/buried queues. New cards are available but have no timed due obligation. available ignores daily deck limits; includeLearnAhead expands learning availability only.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardId` | [EntityId](#type-entityid) | Yes | — |
| `includeLearnAhead` | boolean | No | Default: `false`. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[DueEligibility](#type-dueeligibility).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "scheduling.getDue",
  "params": {
    "cardId": "1700000000002"
  }
}
```

### `scheduling.answer`

Answer using native states matching the supplied prediction token.

**Scope:** collection. **Completion:** completed. **Undo:** `single`.

Reject suspended/buried and filtered-preview cards. For the active GUI card use reviewer.answer. Native elapsed-time capping applies. No client-supplied historical answer timestamp.

Get `stateToken` from `scheduling.predict` for this card immediately before answering.
The named rating selects Anki's corresponding native scheduling state; review
history records `again`, `hard`, `good`, and `easy` as ease values 1, 2, 3, and 4.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardId` | [EntityId](#type-entityid) | Yes | — |
| `rating` | [Rating](#type-rating) | Yes | — |
| `stateToken` | string | Yes | Minimum length: 1. |
| `elapsedMs` | integer | No | Default: `0`. Minimum: 0. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[AnswerResult](#type-answerresult).

**Errors:** `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "scheduling.answer",
  "params": {
    "cardId": "1700000000002",
    "rating": "good",
    "stateToken": "replace-with-prediction-state-token",
    "elapsedMs": 2500
  }
}
```

### `scheduling.answerMany`

Answer cards independently in input order.

**Scope:** collection. **Completion:** completed. **Undo:** `perItem`.

Get a fresh prediction token for each answer. Each item is independently validated and completed.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `answers` | array of [Answer](#type-answer) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [CardAnswerItem](#type-cardansweritem) | Yes | — |

**Errors:** `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "scheduling.answerMany",
  "params": {
    "answers": [
      {
        "cardId": "1700000000002",
        "rating": "good",
        "stateToken": "replace-with-prediction-state-token",
        "elapsedMs": 2500
      }
    ]
  }
}
```

### `scheduling.reset`

Reset cards as new using the native scheduler.

**Scope:** collection. **Completion:** completed. **Undo:** `perItem`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardIds` | array of [EntityId](#type-entityid) | Yes | — |
| `restorePosition` | boolean | No | Default: `true`. |
| `resetCounts` | boolean | No | Default: `false`. |
| `log` | boolean | No | Default: `true`. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [CardResetItem](#type-cardresetitem) | Yes | — |

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "scheduling.reset",
  "params": {
    "cardIds": [
      "1700000000002"
    ]
  }
}
```

### `scheduling.setDueDate`

Set due dates using Anki native days/range syntax.

**Scope:** collection. **Completion:** completed. **Undo:** `perItem`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardIds` | array of [EntityId](#type-entityid) | Yes | — |
| `days` | string | Yes | Minimum length: 1. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [CardDueDateItem](#type-cardduedateitem) | Yes | — |

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "scheduling.setDueDate",
  "params": {
    "cardIds": [
      "1700000000002"
    ],
    "days": "3"
  }
}
```

## Decks

### `decks.list`

List decks in case-sensitive name order.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

array of [Deck](#type-deck).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "decks.list",
  "params": {}
}
```

### `decks.get`

Resolve a deck without creating it or falling back to Default.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `deck` | [Reference](#type-reference) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Deck](#type-deck).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "decks.get",
  "params": {
    "deck": {
      "name": "Default"
    }
  }
}
```

### `decks.create`

Create a normal deck, returning the existing deck for an exact existing name.

**Scope:** collection. **Completion:** completed. **Undo:** `single`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `name` | string | Yes | Minimum length: 1. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Deck](#type-deck).

**Errors:** `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "decks.create",
  "params": {
    "name": "Vocabulary"
  }
}
```

### `decks.update`

Rename a deck using native hierarchy handling.

**Scope:** collection. **Completion:** completed. **Undo:** `single`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `deck` | [Reference](#type-reference) | Yes | — |
| `name` | string | Yes | Minimum length: 1. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Deck](#type-deck).

**Errors:** `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "decks.update",
  "params": {
    "deck": {
      "name": "Vocabulary"
    },
    "name": "Languages::Vocabulary"
  }
}
```

### `decks.delete`

Delete decks and their cards with explicit acknowledgement.

**Scope:** collection. **Completion:** completed. **Undo:** `perItem`.

Includes native child-deck deletion and removal of resulting cardless notes; deleting Default follows native behavior.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `decks` | array of [Reference](#type-reference) | Yes | — |
| `deleteCards` | `true` | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [DeckDeleteItem](#type-deckdeleteitem) | Yes | — |

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "decks.delete",
  "params": {
    "decks": [
      {
        "name": "Unused deck"
      }
    ],
    "deleteCards": true
  }
}
```

### `decks.getCounts`

Get native due-tree counts and total cards.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `deck` | [Reference](#type-reference) | Yes | — |
| `includeChildren` | boolean | No | Default: `true`. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[DeckCounts](#type-deckcounts).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "decks.getCounts",
  "params": {
    "deck": {
      "name": "Default"
    }
  }
}
```

## Deck presets

### `deckPresets.list`

List available deck presets.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

array of [EntitySummary](#type-entitysummary).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "deckPresets.list",
  "params": {}
}
```

### `deckPresets.get`

Read a typed preset.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `preset` | [Reference](#type-reference) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[DeckPreset](#type-deckpreset).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "deckPresets.get",
  "params": {
    "preset": {
      "id": "1"
    }
  }
}
```

### `deckPresets.create`

Create a preset by cloning a specified preset or native defaults.

**Scope:** collection. **Completion:** completed. **Undo:** `single`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `name` | string | Yes | Minimum length: 1. |
| `cloneFrom` | [Reference](#type-reference) | No | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[DeckPreset](#type-deckpreset).

**Errors:** `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "deckPresets.create",
  "params": {
    "name": "Vocabulary",
    "cloneFrom": {
      "id": "1"
    }
  }
}
```

### `deckPresets.update`

Update a preset and all dependent cards through the coordinated backend request.

**Scope:** collection. **Completion:** operation. **Undo:** `single`.

Require name or settings. Preserve current target deck, collection settings, overrides and custom scheduler in the update request. rescheduleFsrs explicitly controls optional full rescheduling; mandatory native memory/step updates still run.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `preset` | [Reference](#type-reference) | Yes | — |
| `name` | string | No | Minimum length: 1. |
| `settings` | [PresetPatch](#type-presetpatch) | No | — |
| `rescheduleFsrs` | boolean | No | Default: `false`. |
| `session` | [SessionId](#type-sessionid) | No | — |

Additional `anyOf` constraint:

```json
{
  "anyOf": [
    {
      "required": [
        "name"
      ]
    },
    {
      "required": [
        "settings"
      ]
    }
  ]
}
```

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"deckPresets.update"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[DeckPreset](#type-deckpreset).

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "deckPresets.update",
  "params": {
    "preset": {
      "id": "1"
    },
    "settings": {
      "newPerDay": 20,
      "newPerDayMinimum": 10
    }
  }
}
```

### `deckPresets.assign`

Assign a preset and execute native dependent-card updates.

**Scope:** collection. **Completion:** operation. **Undo:** `perItem`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `decks` | array of [Reference](#type-reference) | Yes | — |
| `preset` | [Reference](#type-reference) | Yes | — |
| `rescheduleFsrs` | boolean | No | Default: `false`. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"deckPresets.assign"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [PresetAssignmentItem](#type-presetassignmentitem) | Yes | — |

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "deckPresets.assign",
  "params": {
    "decks": [
      {
        "name": "Vocabulary"
      }
    ],
    "preset": {
      "name": "Vocabulary"
    }
  }
}
```

### `deckPresets.delete`

Delete a preset, explicitly reassigning dependent decks first.

**Scope:** collection. **Completion:** operation. **Undo:** `grouped`.

replacement is required when in use. Reject Default preset deletion. No changes occur on failed preflight; do not promise atomicity across multiple native backend operations.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `preset` | [Reference](#type-reference) | Yes | — |
| `replacement` | [Reference](#type-reference) | No | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"deckPresets.delete"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[Ack](#type-ack).

**Errors:** `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "deckPresets.delete",
  "params": {
    "preset": {
      "name": "Unused preset"
    },
    "replacement": {
      "id": "1"
    }
  }
}
```

## Note types

### `noteTypes.list`

List note types in name order.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

array of [EntitySummary](#type-entitysummary).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "noteTypes.list",
  "params": {}
}
```

### `noteTypes.get`

Read ordered fields/templates and styling.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `noteType` | [Reference](#type-reference) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[NoteType](#type-notetype).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "noteTypes.get",
  "params": {
    "noteType": {
      "name": "Basic"
    }
  }
}
```

### `noteTypes.create`

Create a normal or cloze note type.

**Scope:** collection. **Completion:** completed. **Undo:** `single`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `name` | string | Yes | Minimum length: 1. |
| `kind` | `"normal"` / `"cloze"` | No | Default: `"normal"`. |
| `fields` | array of [FieldConfig](#type-fieldconfig) | Yes | Minimum items: 1. |
| `templates` | array of [TemplateConfig](#type-templateconfig) | Yes | Minimum items: 1. |
| `css` | string | No | Default: `""`. |
| `sortField` | string | No | Minimum length: 1. |
| `latexHeader` | string | No | Default: `""`. |
| `latexFooter` | string | No | Default: `""`. |
| `latexSvg` | boolean | No | Default: `false`. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[NoteType](#type-notetype).

**Errors:** `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `staleSession`, `validationFailed`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "noteTypes.create",
  "params": {
    "name": "Vocabulary",
    "fields": [
      {
        "name": "Front"
      },
      {
        "name": "Back"
      }
    ],
    "templates": [
      {
        "name": "Card 1",
        "questionHtml": "{{Front}}",
        "answerHtml": "{{FrontSide}}<hr id=\"answer\">{{Back}}"
      }
    ],
    "css": ".card { font-family: Arial; font-size: 20px; }"
  }
}
```

### `noteTypes.update`

Update nonstructural note-type settings.

**Scope:** collection. **Completion:** completed. **Undo:** `single`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `noteType` | [Reference](#type-reference) | Yes | — |
| `patch` | [NoteTypePatch](#type-notetypepatch) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[NoteType](#type-notetype).

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "noteTypes.update",
  "params": {
    "noteType": {
      "name": "Basic"
    },
    "patch": {
      "css": ".card { font-size: 24px; }"
    }
  }
}
```

### `noteTypes.editStructure`

Apply ordered structural edits and persist once using native note-type updates.

**Scope:** collection. **Completion:** completed. **Undo:** `single`.

Carry original field/template ordinals to preserve card identity. Added entries have no original ordinal. Validate all edits on a copy before saving; reject last field/template removal and invalid cloze structures.

Structure edits can affect existing notes and cards. Indexes are zero-based.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `noteType` | [Reference](#type-reference) | Yes | — |
| `edits` | array of [StructureEdit](#type-structureedit) | Yes | Minimum items: 1. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[NoteType](#type-notetype).

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "noteTypes.editStructure",
  "params": {
    "noteType": {
      "name": "Basic"
    },
    "edits": [
      {
        "op": "addField",
        "field": {
          "name": "Source"
        }
      }
    ]
  }
}
```

### `noteTypes.getTemplateUsage`

Inspect question/answer template field references.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

Python adapter mirrors native token rules because the parsed tree is not exposed to Python. Includes conditional fields and filtered replacements, ignores HTML comments and special fields, supports legacy alternate delimiters, and returns real fields once in first-reference order.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `noteType` | [Reference](#type-reference) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

array of [TemplateUsage](#type-templateusage).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "noteTypes.getTemplateUsage",
  "params": {
    "noteType": {
      "name": "Basic"
    }
  }
}
```

### `noteTypes.replaceText`

Replace literal text in explicit note types or all note types.

**Scope:** collection. **Completion:** completed. **Undo:** `grouped`.

Exactly one selector: noteTypes or allNoteTypes=true. Count changed types, not occurrences.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `find` | string | Yes | Minimum length: 1. |
| `replace` | string | Yes | — |
| `noteTypes` | array of [Reference](#type-reference) | No | — |
| `allNoteTypes` | boolean | No | Default: `false`. |
| `targets` | array of `"question"` / `"answer"` / `"css"` | No | Default: `["question", "answer", "css"]`. Minimum items: 1. Items must be unique. |
| `session` | [SessionId](#type-sessionid) | No | — |

Additional `oneOf` constraint:

```json
{
  "oneOf": [
    {
      "required": [
        "noteTypes"
      ],
      "not": {
        "required": [
          "allNoteTypes"
        ]
      }
    },
    {
      "required": [
        "allNoteTypes"
      ],
      "not": {
        "required": [
          "noteTypes"
        ]
      },
      "properties": {
        "allNoteTypes": {
          "const": true
        }
      }
    }
  ]
}
```

**Returns**

[Count](#type-count).

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "noteTypes.replaceText",
  "params": {
    "find": "font-size: 20px",
    "replace": "font-size: 24px",
    "noteTypes": [
      {
        "name": "Basic"
      }
    ],
    "targets": [
      "css"
    ]
  }
}
```

### `noteTypes.deleteUnused`

Delete only explicitly selected note types whose use count is zero.

**Scope:** collection. **Completion:** completed. **Undo:** `perItem`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `noteTypes` | array of [Reference](#type-reference) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [NoteTypeCleanupItem](#type-notetypecleanupitem) | Yes | — |

**Errors:** `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "noteTypes.deleteUnused",
  "params": {
    "noteTypes": [
      {
        "name": "Unused note type"
      }
    ]
  }
}
```

## Media

### `media.store`

Acquire and store media using Anki filename normalization.

**Scope:** collection. **Completion:** operation. **Undo:** `none`.

Reject traversal and path separators in filename. Validate strict base64 and source types before acquisition. Skip comparison is against incoming bytes and never deletes an existing file. Replacement is explicit and not collection-undoable.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `filename` | [MediaFilename](#type-mediafilename) | Yes | — |
| `source` | [MediaSource](#type-mediasource) | Yes | — |
| `collision` | `"rename"` / `"replace"` / `"error"` | No | Default: `"rename"`. |
| `skipIfHash` | [MediaSkip](#type-mediaskip) | No | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"media.store"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[MediaStored](#type-mediastored).

**Errors:** `collectionUnavailable`, `conflict`, `internalError`, `invalidParams`, `ioError`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "media.store",
  "params": {
    "filename": "hello.txt",
    "source": {
      "data": "SGVsbG8h"
    },
    "collision": "rename"
  }
}
```

### `media.get`

Read media bytes as base64.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

A basename is required; no filesystem traversal or arbitrary paths.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `filename` | [MediaFilename](#type-mediafilename) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[MediaFile](#type-mediafile).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "media.get",
  "params": {
    "filename": "hello.txt"
  }
}
```

### `media.list`

List normalized media basenames matching a basename glob.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `pattern` | [MediaFilename](#type-mediafilename) | No | Default: `"*"`. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

array of string.

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "media.list",
  "params": {
    "pattern": "*.png"
  }
}
```

### `media.delete`

Move media to Anki trash without deleting notes.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `filename` | [MediaFilename](#type-mediafilename) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Ack](#type-ack).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "media.delete",
  "params": {
    "filename": "hello.txt"
  }
}
```

### `media.getDirectory`

Return the local active collection media directory.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `path` | string | Yes | Minimum length: 1. |

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "media.getDirectory",
  "params": {}
}
```

## Review history

### `reviews.list`

Read review history ordered by ascending review ID.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

cardIds and deck are mutually exclusive. No selector means all history. afterId is exclusive. Current/home membership is explicit for filtered cards.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardIds` | array of [EntityId](#type-entityid) | No | — |
| `deck` | [Reference](#type-reference) | No | — |
| `includeChildren` | boolean | No | Default: `false`. |
| `membership` | `"current"` / `"home"` | No | Default: `"current"`. |
| `afterId` | [EntityId](#type-entityid) | No | — |
| `includeManual` | boolean | No | Default: `true`. |
| `limit` | integer | No | Default: `100`. Minimum: 1. Maximum: 1000. |
| `cursor` | string | No | Minimum length: 1. |
| `session` | [SessionId](#type-sessionid) | No | — |

Additional `not` constraint:

```json
{
  "not": {
    "required": [
      "cardIds",
      "deck"
    ]
  }
}
```

**Returns**

[ReviewPage](#type-reviewpage).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleCursor`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "reviews.list",
  "params": {
    "cardIds": [
      "1700000000002"
    ],
    "limit": 100
  }
}
```

### `reviews.getLatestId`

Return the latest matching history ID or null.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `deck` | [Reference](#type-reference) | No | — |
| `cardIds` | array of [EntityId](#type-entityid) | No | — |
| `membership` | `"current"` / `"home"` | No | Default: `"current"`. |
| `session` | [SessionId](#type-sessionid) | No | — |

Additional `not` constraint:

```json
{
  "not": {
    "required": [
      "cardIds",
      "deck"
    ]
  }
}
```

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `id` | [EntityId](#type-entityid) or null | Yes | — |

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "reviews.getLatestId",
  "params": {
    "cardIds": [
      "1700000000002"
    ]
  }
}
```

## Statistics

### `statistics.getToday`

Count actual reviews in Anki current scheduler day, excluding manual/rescheduled entries.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[ReviewCount](#type-reviewcount).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "statistics.getToday",
  "params": {}
}
```

### `statistics.getReviewDays`

Return all nonempty historical review days in descending date order using native graph day conventions.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

array of [ReviewDay](#type-reviewday).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "statistics.getReviewDays",
  "params": {}
}
```

### `statistics.getSummary`

Get structured collection statistics or an explicit deck including children.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `deck` | [Reference](#type-reference) | No | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[StatisticsSummary](#type-statisticssummary).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "statistics.getSummary",
  "params": {}
}
```

### `statistics.getHtml`

Return the supported legacy HTML report, labelled as such.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `deck` | [Reference](#type-reference) | No | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `html` | string | Yes | — |
| `format` | `"legacyReport"` | Yes | — |

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "statistics.getHtml",
  "params": {}
}
```

## Package import and export

### `packages.import`

Import an Anki package with normal collection completion.

**Scope:** collection. **Completion:** operation. **Undo:** `clears`.

Replace the path with an existing package on the machine running Anki. A collection package can replace the collection and invalidate its session.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `path` | string | Yes | Minimum length: 1. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"packages.import"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[ImportResult](#type-importresult).

**Errors:** `cancelled`, `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `ioError`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "packages.import",
  "params": {
    "path": "C:/Users/Alex/Downloads/vocabulary.apkg"
  }
}
```

### `packages.export`

Export the specified deck package.

**Scope:** collection. **Completion:** operation. **Undo:** `none`.

Replace the path with a writable destination on the machine running Anki.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `deck` | [Reference](#type-reference) | Yes | — |
| `path` | string | Yes | Minimum length: 1. |
| `includeScheduling` | boolean | No | Default: `false`. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"packages.export"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[ExportResult](#type-exportresult).

**Errors:** `cancelled`, `collectionUnavailable`, `internalError`, `invalidParams`, `ioError`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "packages.export",
  "params": {
    "deck": {
      "name": "Default"
    },
    "path": "C:/Users/Alex/Desktop/default.apkg"
  }
}
```

## Browser

### `browser.open`

Open the browser and finish after the requested search/sort completes.

**Scope:** collection. **Completion:** operation. **Undo:** `none`.

Omitted query preserves existing browser search. Explicit direction is applied regardless of previous/default column order.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `query` | string | No | — |
| `sort` | [Sort](#type-sort) | No | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"browser.open"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[BrowserState](#type-browserstate).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `invalidSearch`, `invalidState`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "browser.open",
  "params": {
    "query": "deck:Default",
    "sort": {
      "column": "noteFld",
      "direction": "ascending"
    }
  }
}
```

### `browser.getSelection`

Read browser selection; closed browser returns open=false and empty arrays.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[BrowserState](#type-browserstate).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "browser.getSelection",
  "params": {}
}
```

### `browser.select`

Replace selection in an already open browser.

**Scope:** collection. **Completion:** operation. **Undo:** `none`.

Exactly one selector. Note IDs select their cards in card mode; card IDs select their notes in note mode. This method does not open a closed browser.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardIds` | array of [EntityId](#type-entityid) | No | — |
| `noteIds` | array of [EntityId](#type-entityid) | No | — |
| `session` | [SessionId](#type-sessionid) | No | — |

Additional `oneOf` constraint:

```json
{
  "oneOf": [
    {
      "required": [
        "cardIds"
      ],
      "not": {
        "required": [
          "noteIds"
        ]
      }
    },
    {
      "required": [
        "noteIds"
      ],
      "not": {
        "required": [
          "cardIds"
        ]
      }
    }
  ]
}
```

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"browser.select"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[BrowserState](#type-browserstate).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "browser.select",
  "params": {
    "cardIds": [
      "1700000000002"
    ]
  }
}
```

## Editors

### `editors.openNote`

Open the custom note editor and finish once it is ready.

**Scope:** collection. **Completion:** operation. **Undo:** `none`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `noteId` | [EntityId](#type-entityid) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"editors.openNote"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[EditorState](#type-editorstate).

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "editors.openNote",
  "params": {
    "noteId": "1700000000001"
  }
}
```

### `editors.openAdd`

Open or activate the configured Add editor and optionally populate a draft.

**Scope:** collection. **Completion:** operation. **Undo:** `none`.

Use the active legacy/Svelte variant. Do not run duplicate/empty-field eligibility checks on an unfinished draft. Return noteId=null until persisted; do not claim ID 0 identifies a future note.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `note` | [DraftInput](#type-draftinput) | No | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"editors.openAdd"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[EditorState](#type-editorstate).

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "editors.openAdd",
  "params": {
    "note": {
      "noteType": {
        "name": "Basic"
      },
      "deck": {
        "name": "Default"
      },
      "fields": {
        "Front": "cat",
        "Back": "猫"
      },
      "tags": [
        "vocabulary"
      ]
    }
  }
}
```

### `editors.updateDraft`

Update an Add draft through coordinated dialog setters.

**Scope:** collection. **Completion:** operation. **Undo:** `none`.

Set note type before explicit deck. replace changes only supplied fields/tags. append concatenates supplied field strings and unions tags; deck/type still replace. Reject invalid fields before altering the draft.

Use the editor `id` from the completed `editors.openAdd` operation. The example editor ID is a placeholder.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `editorId` | string | Yes | Minimum length: 1. |
| `patch` | [EditorPatch](#type-editorpatch) | Yes | — |
| `mode` | `"replace"` / `"append"` | No | Default: `"replace"`. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"editors.updateDraft"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[EditorState](#type-editorstate).

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "editors.updateDraft",
  "params": {
    "editorId": "replace-with-editor-id",
    "patch": {
      "fields": {
        "Back": "猫 (cat)"
      }
    },
    "mode": "replace"
  }
}
```

## Reviewer

### `reviewer.get`

Read active reviewer state and retained custom scheduling predictions.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

Inactive reviewer returns null card/rendered/token, side=none and empty answers.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[ReviewerState](#type-reviewerstate).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "reviewer.get",
  "params": {}
}
```

### `reviewer.startTimer`

Restart the active reviewer card timer.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

Use the current `stateToken` from `reviewer.get`; the example token is a placeholder.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `stateToken` | string | Yes | Minimum length: 1. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Ack](#type-ack).

**Errors:** `collectionUnavailable`, `conflict`, `internalError`, `invalidParams`, `invalidState`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "reviewer.startTimer",
  "params": {
    "stateToken": "replace-with-current-state-token"
  }
}
```

### `reviewer.showQuestion`

Show the question for the active reviewer card.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

Use the current `stateToken` from `reviewer.get`; the example token is a placeholder.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `stateToken` | string | Yes | Minimum length: 1. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Ack](#type-ack).

**Errors:** `collectionUnavailable`, `conflict`, `internalError`, `invalidParams`, `invalidState`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "reviewer.showQuestion",
  "params": {
    "stateToken": "replace-with-current-state-token"
  }
}
```

### `reviewer.showAnswer`

Show the answer for the active reviewer card.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

Use the current `stateToken` from `reviewer.get`; the example token is a placeholder.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `stateToken` | string | Yes | Minimum length: 1. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Ack](#type-ack).

**Errors:** `collectionUnavailable`, `conflict`, `internalError`, `invalidParams`, `invalidState`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "reviewer.showAnswer",
  "params": {
    "stateToken": "replace-with-current-state-token"
  }
}
```

### `reviewer.answer`

Answer the active card using reviewer-retained states and await actual completion.

**Scope:** collection. **Completion:** operation. **Undo:** `single`.

Requires answer side and an offered rating. Success follows backend completion and UI notifications; reviewer hook veto returns vetoed.

Use the current `stateToken` from `reviewer.get`; the example token is a placeholder.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `stateToken` | string | Yes | Minimum length: 1. |
| `rating` | [Rating](#type-rating) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"reviewer.answer"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[AnswerResult](#type-answerresult).

**Errors:** `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `invalidState`, `staleSession`, `vetoed`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "reviewer.answer",
  "params": {
    "stateToken": "replace-with-reviewer-state-token",
    "rating": "good"
  }
}
```

### `reviewer.playAudio`

Replay audio for the current side.

**Scope:** collection. **Completion:** completed. **Undo:** `none`.

Use the current `stateToken` from `reviewer.get`; the example token is a placeholder.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `stateToken` | string | Yes | Minimum length: 1. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Ack](#type-ack).

**Errors:** `collectionUnavailable`, `conflict`, `internalError`, `invalidParams`, `invalidState`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "reviewer.playAudio",
  "params": {
    "stateToken": "replace-with-current-state-token"
  }
}
```

## Application

### `application.navigate`

Navigate the main window to a requested view.

**Scope:** collection. **Completion:** operation. **Undo:** `none`.

deck is required for deckOverview/review and prohibited for deckBrowser.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `view` | `"deckBrowser"` / `"deckOverview"` / `"review"` | Yes | — |
| `deck` | [Reference](#type-reference) | No | — |
| `session` | [SessionId](#type-sessionid) | No | — |

Additional `oneOf` constraint:

```json
{
  "oneOf": [
    {
      "properties": {
        "view": {
          "const": "deckBrowser"
        }
      },
      "not": {
        "required": [
          "deck"
        ]
      }
    },
    {
      "properties": {
        "view": {
          "enum": [
            "deckOverview",
            "review"
          ]
        }
      },
      "required": [
        "deck"
      ]
    }
  ]
}
```

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"application.navigate"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[Ack](#type-ack).

**Errors:** `collectionUnavailable`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "application.navigate",
  "params": {
    "view": "deckOverview",
    "deck": {
      "name": "Default"
    }
  }
}
```

### `application.importFile`

Run the interactive import workflow, including file choice when omitted.

**Scope:** collection. **Completion:** operation. **Undo:** `clears`.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `path` | string | No | Minimum length: 1. |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"application.importFile"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[ImportResult](#type-importresult).

**Errors:** `cancelled`, `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `ioError`, `notFound`, `staleSession`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "application.importFile",
  "params": {
    "path": "C:/Users/Alex/Downloads/vocabulary.csv"
  }
}
```

### `application.exit`

Acknowledge a close request, then initiate normal application close after sending the response.

**Scope:** application. **Completion:** completed. **Undo:** `none`.

Accepted means the request was scheduled, not that Anki has exited. Native close/save/sync dialogs may cancel it. Process exit prevents polling a final operation result.

**Parameters**

No parameters.

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `accepted` | `true` | Yes | — |

**Errors:** `internalError`, `invalidParams`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "application.exit",
  "params": {}
}
```

## Advanced writes

### `advanced.cards.update`

Edit validated expert scheduling metadata through native card persistence.

**Scope:** collection. **Completion:** completed. **Undo:** `single`.

No id/noteId/deckId/template/queue/type/due/mod/usn writes. Moves, due changes and transitions use domain commands. Reject inconsistent coupled-state edits instead of inferring omitted state. Capability detection may restrict writable properties.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardId` | [EntityId](#type-entityid) | Yes | — |
| `patch` | [RawCardPatch](#type-rawcardpatch) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

[Card](#type-card).

**Errors:** `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `unsupportedCapability`, `validationFailed`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "advanced.cards.update",
  "params": {
    "cardId": "1700000000002",
    "patch": {
      "customData": "{\"source\":\"vocabulary\"}"
    }
  }
}
```

### `advanced.reviews.import`

Import historical revlog records, not live answers.

**Scope:** collection. **Completion:** operation. **Undo:** `clears`.

Validate all records; reject duplicate IDs both internally and against collection. Derive answeredAt from ID, set usn=-1 locally. Records are imported in one database transaction. Do not change card scheduling/counters or claim a live answer. FSRS memory remains current stored state; later recomputation may consume imported history. Availability depends on runtime capability checks.

Use a unique review ID and an existing card ID. The example assumes an SM-2 historical record; do not infer its factor encoding from the current scheduler.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `reviews` | array of [ReviewImport](#type-reviewimport) | Yes | — |
| `session` | [SessionId](#type-sessionid) | No | — |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | `"advanced.reviews.import"` | Yes | — |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |

**Final operation result** (read with `operations.get`)

[Count](#type-count).

**Errors:** `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `unsupportedCapability`, `validationFailed`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "advanced.reviews.import",
  "params": {
    "reviews": [
      {
        "id": "1791633600000",
        "cardId": "1700000000002",
        "rating": "good",
        "interval": {
          "value": 10,
          "unit": "days"
        },
        "previousInterval": {
          "value": 5,
          "unit": "days"
        },
        "factor": {
          "encoding": "legacySm2EasePermille",
          "value": 2500
        },
        "elapsedMs": 2500,
        "kind": "review"
      }
    ]
  }
}
```

## Operation tracking

### `operations.get`

Poll operation status and its eventual typed result/error.

**Scope:** application. **Completion:** completed. **Undo:** `none`.

Use `operationId` from a method that returns an operation handle.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |

**Returns**

[Operation](#type-operation).

**Errors:** `internalError`, `invalidParams`, `notFound`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "operations.get",
  "params": {
    "operationId": "replace-with-operation-id"
  }
}
```

### `operations.cancel`

Request supported cancellation without claiming rollback.

**Scope:** application. **Completion:** completed. **Undo:** `none`.

Already terminal returns requested=false. Queued operations can cancel; running operations use native cancellation only. A cancellation request may lose a race with success.

Use an existing operation ID and inspect its `cancellable` property before requesting cancellation.

**Parameters**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |

**Returns**

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `requested` | boolean | Yes | — |

**Errors:** `internalError`, `invalidParams`, `notFound`, `unsupportedCapability`.

**Example request**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "operations.cancel",
  "params": {
    "operationId": "replace-with-operation-id"
  }
}
```

## Shared types

These types are used by the parameter and return tables above. `oneOf` means
exactly one variant; `anyOf` means at least one variant. Required properties must
be present. Unless a type allows additional properties, unknown inputs are rejected.
Return records may gain properties in future releases; clients should ignore them.

<a id="type-ack"></a>

### Ack

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `changed` | boolean | Yes | — |

<a id="type-answer"></a>

### Answer

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardId` | [EntityId](#type-entityid) | Yes | — |
| `rating` | [Rating](#type-rating) | Yes | — |
| `stateToken` | string | Yes | Minimum length: 1. |
| `elapsedMs` | integer | No | Default: `0`. Minimum: 0. |

<a id="type-answerresult"></a>

### AnswerResult

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardId` | [EntityId](#type-entityid) | Yes | — |
| `reviewId` | [EntityId](#type-entityid) or null | Yes | — |
| `scheduling` | [SchedulingState](#type-schedulingstate) | Yes | — |

<a id="type-batchresult"></a>

### BatchResult

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [BatchItem](#type-batchitem) | Yes | — |

<a id="type-batchitem"></a>

### BatchItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "method": {
          "type": "string",
          "minLength": 1
        },
        "result": {}
      },
      "required": [
        "index",
        "method",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "method": {
          "type": "string",
          "minLength": 1
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "method",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-browserstate"></a>

### BrowserState

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `open` | boolean | Yes | — |
| `selectedNoteIds` | array of [EntityId](#type-entityid) | Yes | — |
| `selectedCardIds` | array of [EntityId](#type-entityid) | Yes | — |

<a id="type-card"></a>

### Card

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `id` | [EntityId](#type-entityid) | Yes | — |
| `noteId` | [EntityId](#type-entityid) | Yes | — |
| `deck` | [EntitySummary](#type-entitysummary) | Yes | — |
| `homeDeck` | [EntitySummary](#type-entitysummary) or null | Yes | — |
| `templateIndex` | integer | Yes | Minimum: 0. |
| `flags` | integer | Yes | Minimum: 0. Maximum: 7. |
| `modifiedAt` | [Timestamp](#type-timestamp) | Yes | — |
| `scheduling` | [SchedulingState](#type-schedulingstate) | Yes | — |

<a id="type-cardansweritem"></a>

### CardAnswerItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/AnswerResult"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-cardduedateitem"></a>

### CardDueDateItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/Ack"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-cardflagitem"></a>

### CardFlagItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/Ack"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-cardgetitem"></a>

### CardGetItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/Card"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-cardmoveitem"></a>

### CardMoveItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/Ack"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-cardresetitem"></a>

### CardResetItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/Ack"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-cardsuspensionitem"></a>

### CardSuspensionItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/Ack"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-collection"></a>

### Collection

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `profile` | string | Yes | Minimum length: 1. |
| `session` | [SessionId](#type-sessionid) | Yes | — |
| `scheduler` | `"sm2"` / `"fsrs"` | Yes | — |

<a id="type-command"></a>

### Command

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `method` | string | Yes | Minimum length: 1. |
| `params` | object | No | — |

<a id="type-conversionmapping"></a>

### ConversionMapping

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `target` | string | Yes | Minimum length: 1. |
| `source` | string or null | Yes | — |

<a id="type-conversionplan"></a>

### ConversionPlan

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `source` | [EntitySummary](#type-entitysummary) | Yes | — |
| `target` | [EntitySummary](#type-entitysummary) | Yes | — |
| `fields` | array of [ConversionMapping](#type-conversionmapping) | Yes | — |
| `templates` | array of [ConversionMapping](#type-conversionmapping) | Yes | — |
| `token` | string | Yes | Minimum length: 1. |

<a id="type-count"></a>

### Count

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `changedCount` | integer | Yes | Minimum: 0. |

<a id="type-deck"></a>

### Deck

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `id` | [EntityId](#type-entityid) | Yes | — |
| `name` | string | Yes | Minimum length: 1. |
| `kind` | `"normal"` / `"filtered"` | Yes | — |
| `presetId` | [EntityId](#type-entityid) or null | Yes | — |

<a id="type-deckcounts"></a>

### DeckCounts

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `deckId` | [EntityId](#type-entityid) | Yes | — |
| `new` | integer | Yes | Minimum: 0. |
| `learning` | integer | Yes | Minimum: 0. |
| `review` | integer | Yes | Minimum: 0. |
| `total` | integer | Yes | Minimum: 0. |

<a id="type-deckdeleteitem"></a>

### DeckDeleteItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/Ack"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-deckpreset"></a>

### DeckPreset

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `id` | [EntityId](#type-entityid) | Yes | — |
| `name` | string | Yes | Minimum length: 1. |
| `settings` | [PresetSettings](#type-presetsettings) | Yes | — |
| `modifiedAt` | [Timestamp](#type-timestamp) | Yes | — |

<a id="type-description"></a>

### Description

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `apiMajor` | `1` | Yes | — |
| `ankiVersion` | string | Yes | Minimum length: 1. |
| `schema` | object | Yes | — |
| `methods` | array of object | Yes | — |
| `limits` | object | Yes | — |

<a id="type-draftinput"></a>

### DraftInput

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `noteType` | [Reference](#type-reference) | Yes | — |
| `deck` | [Reference](#type-reference) | Yes | — |
| `fields` | [FieldValues](#type-fieldvalues) | No | Default: `{}`. |
| `tags` | array of string | No | Default: `[]`. |

<a id="type-dueeligibility"></a>

### DueEligibility

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardId` | [EntityId](#type-entityid) | Yes | — |
| `dueNow` | boolean | Yes | — |
| `available` | boolean | Yes | — |
| `learnAhead` | boolean | Yes | — |

<a id="type-duplicatepolicy"></a>

### DuplicatePolicy

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `allow` | boolean | No | Default: `false`. |
| `scope` | `"collection"` / `"deck"` | No | Default: `"collection"`. |
| `deck` | [Reference](#type-reference) | No | — |
| `includeChildren` | boolean | No | Default: `false`. |
| `acrossNoteTypes` | boolean | No | Default: `false`. |

Additional `allOf` constraint:

```json
{
  "allOf": [
    {
      "if": {
        "properties": {
          "scope": {
            "const": "deck"
          }
        },
        "required": [
          "scope"
        ]
      },
      "then": {
        "required": [
          "deck"
        ]
      }
    }
  ]
}
```

<a id="type-editorpatch"></a>

### EditorPatch

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `deck` | [Reference](#type-reference) | No | — |
| `noteType` | [Reference](#type-reference) | No | — |
| `fields` | [FieldValues](#type-fieldvalues) | No | — |
| `tags` | array of string | No | — |

<a id="type-editorstate"></a>

### EditorState

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `id` | string | Yes | Minimum length: 1. |
| `kind` | `"add"` / `"note"` | Yes | — |
| `variant` | `"legacy"` / `"svelte"` / `"custom"` | Yes | — |
| `noteId` | [EntityId](#type-entityid) or null | Yes | — |
| `deck` | [EntitySummary](#type-entitysummary) or null | Yes | — |
| `noteType` | [EntitySummary](#type-entitysummary) | Yes | — |
| `fields` | [FieldValues](#type-fieldvalues) | Yes | — |
| `tags` | array of string | Yes | — |
| `dirty` | boolean | Yes | — |
| `session` | [SessionId](#type-sessionid) | Yes | — |

<a id="type-entityid"></a>

### EntityId

Positive signed int64 in decimal; additionally enforce <= 9223372036854775807.

string. Pattern: `^[1-9][0-9]{0,18}$`. Positive signed int64 in decimal; additionally enforce <= 9223372036854775807.

<a id="type-entitysummary"></a>

### EntitySummary

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `id` | [EntityId](#type-entityid) | Yes | — |
| `name` | string | Yes | Minimum length: 1. |

<a id="type-error"></a>

### Error

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `code` | integer | Yes | — |
| `message` | string | Yes | Minimum length: 1. |
| `data` | object | No | — |

Additional `allOf` constraint:

```json
{
  "allOf": [
    {
      "if": {
        "properties": {
          "code": {
            "const": 1001
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "notFound"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1002
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "validationFailed"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1003
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "editorConflict"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1004
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "collectionUnavailable"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1005
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "staleSession"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1006
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "unsupportedCapability"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1007
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "cancelled"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1008
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "conflict"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1009
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "invalidState"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1010
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "busy"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1011
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "authenticationRequired"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1012
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "ioError"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1013
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "invalidSearch"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1014
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "staleCursor"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1015
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "vetoed"
              }
            }
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "code": {
            "const": 1016
          }
        },
        "required": [
          "code"
        ]
      },
      "then": {
        "required": [
          "data"
        ],
        "properties": {
          "data": {
            "properties": {
              "type": {
                "const": "compatibilityError"
              }
            }
          }
        }
      }
    }
  ]
}
```

<a id="type-exportresult"></a>

### ExportResult

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `path` | string | Yes | Minimum length: 1. |

<a id="type-fieldconfig"></a>

### FieldConfig

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `name` | string | Yes | Minimum length: 1. |
| `fontFamily` | string | No | Default: `"Arial"`. Minimum length: 1. |
| `fontSize` | integer | No | Default: `20`. Minimum: 1. |
| `description` | string | No | Default: `""`. |
| `sticky` | boolean | No | Default: `false`. |
| `rtl` | boolean | No | Default: `false`. |
| `plainText` | boolean | No | Default: `false`. |
| `collapsed` | boolean | No | Default: `false`. |
| `excludeFromSearch` | boolean | No | Default: `false`. |

<a id="type-fieldvalues"></a>

### FieldValues

object.

```json
{
  "type": "object",
  "additionalProperties": {
    "type": "string"
  },
  "propertyNames": {
    "type": "string",
    "minLength": 1
  }
}
```

<a id="type-idpage"></a>

### IdPage

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `ids` | array of [EntityId](#type-entityid) | Yes | — |
| `nextCursor` | string or null | Yes | — |

<a id="type-importresult"></a>

### ImportResult

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `completed` | boolean | Yes | — |

<a id="type-integrityresult"></a>

### IntegrityResult

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `problems` | array of string | Yes | — |
| `repaired` | boolean | Yes | — |

<a id="type-mediafile"></a>

### MediaFile

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `filename` | string | Yes | Minimum length: 1. |
| `data` | string | Yes | Encoding: base64. |

<a id="type-mediafilename"></a>

### MediaFilename

string. Minimum length: 1. Pattern: `^[^/\\\u0000]+$`.

<a id="type-mediaskip"></a>

### MediaSkip

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `algorithm` | `"md5"` / `"sha256"` | Yes | — |
| `digest` | string | Yes | Minimum length: 1. |

<a id="type-mediasource"></a>

### MediaSource

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "data": {
          "type": "string",
          "contentEncoding": "base64"
        }
      },
      "required": [
        "data"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "minLength": 1
        }
      },
      "required": [
        "path"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "url": {
          "type": "string",
          "pattern": "^https?://"
        }
      },
      "required": [
        "url"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-mediastored"></a>

### MediaStored

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "filename": {
          "type": "string",
          "minLength": 1
        },
        "status": {
          "const": "stored"
        },
        "sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        }
      },
      "required": [
        "filename",
        "status",
        "sha256"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "filename": {
          "type": "null"
        },
        "status": {
          "const": "skipped"
        },
        "sha256": {
          "type": "string",
          "pattern": "^[0-9a-f]{64}$"
        }
      },
      "required": [
        "filename",
        "status",
        "sha256"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-note"></a>

### Note

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `id` | [EntityId](#type-entityid) | Yes | — |
| `noteType` | [EntitySummary](#type-entitysummary) | Yes | — |
| `fields` | [FieldValues](#type-fieldvalues) | Yes | — |
| `tags` | array of string | Yes | — |
| `cardIds` | array of [EntityId](#type-entityid) | Yes | — |
| `modifiedAt` | [Timestamp](#type-timestamp) | Yes | — |

<a id="type-notecreated"></a>

### NoteCreated

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `noteId` | [EntityId](#type-entityid) | Yes | — |
| `cardIds` | array of [EntityId](#type-entityid) | Yes | — |

<a id="type-notecreationitem"></a>

### NoteCreationItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/NoteCreated"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-notedeleteitem"></a>

### NoteDeleteItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/Ack"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-notegetitem"></a>

### NoteGetItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/Note"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-noteinput"></a>

### NoteInput

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `noteType` | [Reference](#type-reference) | Yes | — |
| `deck` | [Reference](#type-reference) | Yes | — |
| `fields` | [FieldValues](#type-fieldvalues) | Yes | — |
| `tags` | array of string | No | Default: `[]`. |
| `duplicates` | [DuplicatePolicy](#type-duplicatepolicy) | No | — |
| `rejectEmptyQuestions` | boolean | No | Default: `true`. |

<a id="type-notepatch"></a>

### NotePatch

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `fields` | [FieldValues](#type-fieldvalues) | No | — |
| `tags` | array of string | No | — |

<a id="type-notetype"></a>

### NoteType

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `name` | string | Yes | Minimum length: 1. |
| `kind` | `"normal"` / `"cloze"` | Yes | Default: `"normal"`. |
| `fields` | array of [FieldConfig](#type-fieldconfig) | Yes | Minimum items: 1. |
| `templates` | array of [TemplateConfig](#type-templateconfig) | Yes | Minimum items: 1. |
| `css` | string | Yes | Default: `""`. |
| `sortField` | string | Yes | Minimum length: 1. |
| `latexHeader` | string | Yes | Default: `""`. |
| `latexFooter` | string | Yes | Default: `""`. |
| `latexSvg` | boolean | Yes | Default: `false`. |
| `id` | [EntityId](#type-entityid) | Yes | — |
| `modifiedAt` | [Timestamp](#type-timestamp) | Yes | — |

<a id="type-notetypecleanupitem"></a>

### NoteTypeCleanupItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/Ack"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-notetypepatch"></a>

### NoteTypePatch

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `name` | string | No | Minimum length: 1. |
| `css` | string | No | — |
| `sortField` | string | No | Minimum length: 1. |
| `latexHeader` | string | No | — |
| `latexFooter` | string | No | — |
| `latexSvg` | boolean | No | — |

<a id="type-notevalidationitem"></a>

### NoteValidationItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/Validation"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-operation"></a>

### Operation

Includes all [OperationBase](#type-operationbase) properties, plus the state below.

| State | Additional required property | Meaning |
| --- | --- | --- |
| `queued`, `running`, `waitingForUser` | None | Pending; no result or error. |
| `succeeded` | `result` | The originating method’s final operation result, documented in its entry. |
| `failed`, `cancelled` | `error` ([Error](#type-error)) | Terminal failure or cancellation. |

`method` identifies the originating method. Only methods marked **operation** produce
these records. Result and error are mutually exclusive and absent while pending.

<a id="type-operationbase"></a>

### OperationBase

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `operationId` | string | Yes | Minimum length: 1. |
| `method` | string | Yes | Minimum length: 1. |
| `session` | [SessionId](#type-sessionid) or null | Yes | — |
| `createdAt` | [Timestamp](#type-timestamp) | Yes | — |
| `updatedAt` | [Timestamp](#type-timestamp) | Yes | — |
| `cancellable` | boolean | Yes | — |
| `progress` | [Progress](#type-progress) or null | Yes | — |

<a id="type-permission"></a>

### Permission

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `permission` | `"granted"` / `"denied"` | Yes | — |
| `requireApiKey` | boolean | Yes | — |

<a id="type-predictions"></a>

### Predictions

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardId` | [EntityId](#type-entityid) | Yes | — |
| `source` | `"scheduler"` | Yes | — |
| `stateToken` | string | Yes | Minimum length: 1. |
| `answers` | array of [Prediction](#type-prediction) | Yes | Minimum items: 1. |

<a id="type-prediction"></a>

### Prediction

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `rating` | [Rating](#type-rating) | Yes | — |
| `label` | string | Yes | — |
| `interval` | [Interval](#type-interval) or null | Yes | — |

<a id="type-interval"></a>

### Interval

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `value` | integer | Yes | Minimum: 0. |
| `unit` | `"seconds"` / `"days"` | Yes | — |

<a id="type-presetassignmentitem"></a>

### PresetAssignmentItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/Ack"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-presetpatch"></a>

### PresetPatch

[PresetSettings](#type-presetsettings). Minimum properties: 1.

<a id="type-presetsettings"></a>

### PresetSettings

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `learnStepsMinutes` | array of number | No | — |
| `relearnStepsMinutes` | array of number | No | — |
| `fsrsParameters4` | array of number | No | — |
| `fsrsParameters5` | array of number | No | — |
| `fsrsParameters6` | array of number | No | — |
| `newPerDay` | integer | No | Minimum: 0. |
| `reviewsPerDay` | integer | No | Minimum: 0. |
| `leechThreshold` | integer | No | Minimum: 0. |
| `answerTimeLimitSeconds` | integer | No | Minimum: 0. |
| `maximumIntervalDays` | integer | No | Minimum: 1. |
| `minimumLapseIntervalDays` | integer | No | Minimum: 1. |
| `graduatingGoodDays` | integer | No | Minimum: 1. |
| `graduatingEasyDays` | integer | No | Minimum: 1. |
| `initialEase` | number | No | Minimum: 0. |
| `easyMultiplier` | number | No | Minimum: 0. |
| `hardMultiplier` | number | No | Minimum: 0. |
| `lapseMultiplier` | number | No | Minimum: 0. |
| `intervalMultiplier` | number | No | Minimum: 0. |
| `desiredRetention` | number | No | — |
| `historicalRetention` | number | No | — |
| `newInsertOrder` | `"due"` / `"random"` | No | — |
| `newGatherOrder` | `"deck"` / `"deckThenRandomNotes"` / `"lowestPosition"` / `"highestPosition"` / `"randomNotes"` / `"randomCards"` | No | — |
| `newSortOrder` | `"template"` / `"none"` / `"templateThenRandom"` / `"randomNoteThenTemplate"` / `"randomCard"` | No | — |
| `reviewOrder` | `"day"` / `"dayThenDeck"` / `"deckThenDay"` / `"intervalAscending"` / `"intervalDescending"` / `"easeAscending"` / `"easeDescending"` / `"retrievabilityAscending"` / `"retrievabilityDescending"` / `"relativeOverdueness"` / `"random"` / `"added"` / `"reverseAdded"` | No | — |
| `newMix` | `"mixed"` / `"afterReviews"` / `"beforeReviews"` | No | — |
| `dayLearningMix` | `"mixed"` / `"afterReviews"` / `"beforeReviews"` | No | — |
| `leechAction` | `"suspend"` / `"tagOnly"` | No | — |
| `questionAction` | `"showAnswer"` / `"showReminder"` | No | — |
| `answerAction` | `"buryCard"` / `"again"` / `"good"` / `"hard"` / `"showReminder"` | No | — |
| `easyDaysPercentages` | array of number | No | Minimum items: 7. Maximum items: 7. |
| `ignoreReviewsBefore` | string | No | Pattern: `^$&#124;^[0-9]{4}-[0-9]{2}-[0-9]{2}$`. |
| `parameterSearch` | string | No | — |
| `questionDisplaySeconds` | number | No | Minimum: 0. |
| `answerDisplaySeconds` | number | No | Minimum: 0. |
| `disableAutoplay` | boolean | No | — |
| `showTimer` | boolean | No | — |
| `stopTimerOnAnswer` | boolean | No | — |
| `waitForAudio` | boolean | No | — |
| `skipQuestionOnAnswerReplay` | boolean | No | — |
| `buryNew` | boolean | No | — |
| `buryReviews` | boolean | No | — |
| `buryDayLearning` | boolean | No | — |
| `newPerDayMinimum` | integer | No | Minimum: 0. |

<a id="type-profile"></a>

### Profile

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `name` | string | Yes | Minimum length: 1. |

<a id="type-progress"></a>

### Progress

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `completed` | integer | Yes | Minimum: 0. |
| `total` | integer or null | Yes | — |
| `message` | string | Yes | — |

<a id="type-rating"></a>

### Rating

`"again"` / `"hard"` / `"good"` / `"easy"`.

<a id="type-rawcardpatch"></a>

### RawCardPatch

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `intervalDays` | integer | No | Minimum: 0. |
| `sm2EasePermille` | integer | No | Minimum: 0. |
| `repetitions` | integer | No | Minimum: 0. |
| `lapses` | integer | No | Minimum: 0. |
| `remainingSteps` | integer | No | Minimum: 0. |
| `fsrsMemory` | [MemoryState](#type-memorystate) or null | No | — |
| `customData` | string | No | — |

<a id="type-memorystate"></a>

### MemoryState

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `difficulty` | number | Yes | Minimum: 0. Maximum: 10. |
| `stabilityDays` | number | Yes | Minimum: 0. |

<a id="type-reference"></a>

### Reference

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "id": {
          "$ref": "#/$defs/EntityId"
        }
      },
      "required": [
        "id"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "name": {
          "type": "string",
          "minLength": 1
        }
      },
      "required": [
        "name"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-renderedcard"></a>

### RenderedCard

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardId` | [EntityId](#type-entityid) | Yes | — |
| `questionHtml` | string | Yes | — |
| `answerHtml` | string | Yes | — |
| `css` | string | Yes | — |

<a id="type-reviewcount"></a>

### ReviewCount

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `count` | integer | Yes | Minimum: 0. |
| `day` | string | Yes | Format: `date`. |
| `nextDayAt` | [Timestamp](#type-timestamp) | Yes | — |

<a id="type-reviewday"></a>

### ReviewDay

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `day` | string | Yes | Format: `date`. |
| `count` | integer | Yes | Minimum: 0. |

<a id="type-reviewimport"></a>

### ReviewImport

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `id` | [EntityId](#type-entityid) | Yes | — |
| `cardId` | [EntityId](#type-entityid) | Yes | — |
| `rating` | [Rating](#type-rating) or null | Yes | — |
| `interval` | [Interval](#type-interval) | Yes | — |
| `previousInterval` | [Interval](#type-interval) | Yes | — |
| `factor` | object | Yes | — |
| `elapsedMs` | integer | Yes | Minimum: 0. |
| `kind` | `"learning"` / `"review"` / `"relearning"` / `"filtered"` / `"manual"` / `"rescheduled"` | Yes | — |

<a id="type-reviewpage"></a>

### ReviewPage

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `items` | array of [Review](#type-review) | Yes | — |
| `nextCursor` | string or null | Yes | — |

<a id="type-review"></a>

### Review

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `id` | [EntityId](#type-entityid) | Yes | — |
| `cardId` | [EntityId](#type-entityid) | Yes | — |
| `answeredAt` | [Timestamp](#type-timestamp) | Yes | — |
| `rating` | [Rating](#type-rating) or null | Yes | — |
| `interval` | [Interval](#type-interval) | Yes | — |
| `previousInterval` | [Interval](#type-interval) | Yes | — |
| `factor` | object | Yes | — |
| `elapsedMs` | integer | Yes | Minimum: 0. |
| `kind` | `"learning"` / `"review"` / `"relearning"` / `"filtered"` / `"manual"` / `"rescheduled"` | Yes | — |
| `syncSequence` | integer | Yes | Minimum: -1. |

<a id="type-reviewerstate"></a>

### ReviewerState

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `active` | boolean | Yes | — |
| `card` | [Card](#type-card) or null | Yes | — |
| `rendered` | [RenderedCard](#type-renderedcard) or null | Yes | — |
| `side` | `"question"` / `"answer"` / `"none"` | Yes | — |
| `stateToken` | string or null | Yes | — |
| `answers` | array of [Prediction](#type-prediction) | Yes | — |
| `source` | `"reviewer"` | Yes | — |

<a id="type-schedulingstate"></a>

### SchedulingState

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `type` | `"new"` / `"learning"` / `"review"` / `"relearning"` | Yes | — |
| `queue` | `"new"` / `"learning"` / `"review"` / `"dayLearning"` / `"preview"` / `"suspended"` / `"buriedByScheduler"` / `"buriedByUser"` | Yes | — |
| `due` | [Due](#type-due) | Yes | — |
| `intervalDays` | integer | Yes | Minimum: 0. |
| `learningIntervalSeconds` | integer or null | Yes | — |
| `remainingSteps` | integer | Yes | Minimum: 0. |
| `repetitions` | integer | Yes | Minimum: 0. |
| `lapses` | integer | Yes | Minimum: 0. |
| `sm2EasePermille` | integer | Yes | Minimum: 0. |
| `fsrsMemory` | [MemoryState](#type-memorystate) or null | Yes | — |
| `desiredRetention` | number or null | Yes | — |

<a id="type-due"></a>

### Due

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "kind": {
          "const": "position"
        },
        "position": {
          "type": "integer",
          "minimum": 0
        }
      },
      "required": [
        "kind",
        "position"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "kind": {
          "const": "timestamp"
        },
        "at": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "kind",
        "at"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "kind": {
          "const": "day"
        },
        "day": {
          "type": "integer"
        }
      },
      "required": [
        "kind",
        "day"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-sessionid"></a>

### SessionId

string. Minimum length: 1.

<a id="type-sort"></a>

### Sort

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `column` | string | Yes | Minimum length: 1. |
| `direction` | `"ascending"` / `"descending"` | Yes | — |

<a id="type-statisticssummary"></a>

### StatisticsSummary

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `cardCount` | integer | Yes | Minimum: 0. |
| `noteCount` | integer | Yes | Minimum: 0. |
| `reviewCount` | integer | Yes | Minimum: 0. |
| `reviewTimeMs` | integer | Yes | Minimum: 0. |
| `newCount` | integer | Yes | Minimum: 0. |
| `learningCount` | integer | Yes | Minimum: 0. |
| `reviewCardCount` | integer | Yes | Minimum: 0. |
| `suspendedCount` | integer | Yes | Minimum: 0. |

<a id="type-structureedit"></a>

### StructureEdit

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "op": {
          "const": "addField"
        },
        "field": {
          "$ref": "#/$defs/FieldConfig"
        },
        "index": {
          "type": "integer",
          "minimum": 0
        }
      },
      "required": [
        "op",
        "field"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "op": {
          "const": "updateField"
        },
        "name": {
          "type": "string",
          "minLength": 1
        },
        "patch": {
          "$ref": "#/$defs/FieldPatch"
        }
      },
      "required": [
        "op",
        "name",
        "patch"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "op": {
          "const": "moveField"
        },
        "name": {
          "type": "string",
          "minLength": 1
        },
        "index": {
          "type": "integer",
          "minimum": 0
        }
      },
      "required": [
        "op",
        "name",
        "index"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "op": {
          "const": "removeField"
        },
        "name": {
          "type": "string",
          "minLength": 1
        }
      },
      "required": [
        "op",
        "name"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "op": {
          "const": "addTemplate"
        },
        "template": {
          "$ref": "#/$defs/TemplateConfig"
        },
        "index": {
          "type": "integer",
          "minimum": 0
        }
      },
      "required": [
        "op",
        "template"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "op": {
          "const": "updateTemplate"
        },
        "name": {
          "type": "string",
          "minLength": 1
        },
        "patch": {
          "$ref": "#/$defs/TemplatePatch"
        }
      },
      "required": [
        "op",
        "name",
        "patch"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "op": {
          "const": "moveTemplate"
        },
        "name": {
          "type": "string",
          "minLength": 1
        },
        "index": {
          "type": "integer",
          "minimum": 0
        }
      },
      "required": [
        "op",
        "name",
        "index"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "op": {
          "const": "removeTemplate"
        },
        "name": {
          "type": "string",
          "minLength": 1
        }
      },
      "required": [
        "op",
        "name"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-fieldpatch"></a>

### FieldPatch

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `name` | string | No | Minimum length: 1. |
| `fontFamily` | string | No | Minimum length: 1. |
| `fontSize` | integer | No | Minimum: 1. |
| `description` | string | No | — |
| `sticky` | boolean | No | — |
| `rtl` | boolean | No | — |
| `plainText` | boolean | No | — |
| `collapsed` | boolean | No | — |
| `excludeFromSearch` | boolean | No | — |

<a id="type-syncresult"></a>

### SyncResult

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `collectionComplete` | boolean | Yes | — |
| `mediaComplete` | boolean | Yes | — |

<a id="type-tagadditem"></a>

### TagAddItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/Ack"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-tagremoveitem"></a>

### TagRemoveItem

Exactly one variant below.

```json
{
  "oneOf": [
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "result": {
          "$ref": "#/$defs/Ack"
        }
      },
      "required": [
        "index",
        "result"
      ],
      "additionalProperties": false
    },
    {
      "type": "object",
      "properties": {
        "index": {
          "type": "integer",
          "minimum": 0
        },
        "error": {
          "$ref": "#/$defs/Error"
        }
      },
      "required": [
        "index",
        "error"
      ],
      "additionalProperties": false
    }
  ]
}
```

<a id="type-templateconfig"></a>

### TemplateConfig

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `name` | string | Yes | Minimum length: 1. |
| `questionHtml` | string | Yes | — |
| `answerHtml` | string | Yes | — |
| `browserQuestionHtml` | string | No | Default: `""`. |
| `browserAnswerHtml` | string | No | Default: `""`. |
| `deck` | [Reference](#type-reference) or null | No | — |
| `browserFontFamily` | string | No | Default: `"Arial"`. Minimum length: 1. |
| `browserFontSize` | integer | No | Default: `20`. Minimum: 1. |

<a id="type-templatepatch"></a>

### TemplatePatch

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `name` | string | No | Minimum length: 1. |
| `questionHtml` | string | No | — |
| `answerHtml` | string | No | — |
| `browserQuestionHtml` | string | No | — |
| `browserAnswerHtml` | string | No | — |
| `deck` | [Reference](#type-reference) or null | No | — |
| `browserFontFamily` | string | No | Minimum length: 1. |
| `browserFontSize` | integer | No | Minimum: 1. |

<a id="type-templateusage"></a>

### TemplateUsage

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `templateName` | string | Yes | Minimum length: 1. |
| `questionFields` | array of string | Yes | — |
| `answerFields` | array of string | Yes | — |

<a id="type-timestamp"></a>

### Timestamp

RFC 3339 UTC timestamp, emitted with Z; millisecond precision when available.

string. Format: `date-time`. RFC 3339 UTC timestamp, emitted with Z; millisecond precision when available.

<a id="type-undoresult"></a>

### UndoResult

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `label` | string | Yes | — |
| `changed` | boolean | Yes | — |

<a id="type-validation"></a>

### Validation

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `valid` | boolean | Yes | — |
| `issues` | array of [Issue](#type-issue) | Yes | — |
| `duplicateNoteIds` | array of [EntityId](#type-entityid) | Yes | — |

<a id="type-issue"></a>

### Issue

| Property | Type | Required | Details |
| --- | --- | --- | --- |
| `type` | `"emptyFirstField"` / `"duplicate"` / `"missingCloze"` / `"notClozeNoteType"` / `"notClozeField"` / `"emptyQuestions"` / `"unknownField"` / `"invalidTag"` | Yes | — |
| `message` | string | Yes | Minimum length: 1. |
| `field` | string | No | Minimum length: 1. |

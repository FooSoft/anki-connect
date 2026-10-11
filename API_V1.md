# Anki-Connect API v1

**Status: specification for a future rewrite; the current add-on does not implement this API.**
Baseline: local Anki 26.09.3, audited on 2026-10-10. Support for later versions
requires capability checks and integration verification, not just version comparison.

This API serves existing Anki-Connect features with consistent domain objects,
explicit operation completion, and a legacy adapter sharing the same services.
The [machine-readable contract](api-v1.schema.json) contains request/result
schemas and method metadata. The [legacy mapping](LEGACY_API_MAPPING.md) covers
all 122 current actions and the integration audit. The current runtime remains
described by [ARCHITECTURE.md](ARCHITECTURE.md).

## Protocol and shared conventions

### Transport, access and discovery

Use `POST http://127.0.0.1:8765/api/v1` with UTF-8 JSON and
`Content-Type: application/json`. The existing root endpoint keeps its legacy
protocol. The rewritten listener must route by path; the current parser does not.
Use [JSON-RPC 2.0](https://www.jsonrpc.org/specification), named parameters only.
Omitted params mean `{}`. Positional arrays produce invalid-params errors.
The `jsonrpc` value is the protocol version; `/api/v1` is the API major version.

Use the configured API key as `Authorization: Bearer <key>` on v1. A null key
disables authentication as today. Preserve existing CORS/origin configuration,
the loopback binding, origin-less callers and permission persistence. Origin and
authentication checks remain independent. `access.requestPermission` is the sole
key-exempt method and is allowed through origin rejection for the permission
workflow; its origin/allowed inputs come from the transport. It returns only
permission status and whether a key is required, never the key itself.
Legacy calls keep the body `key` field. Redact both credential forms and note/media
content from routine logs; log method, request ID, duration and error type instead.

HTTP 200 carries JSON-RPC successes and errors, including malformed JSON.
Use HTTP 401 for a rejected key, 403 for a rejected origin, 405 for a non-POST
method, and 413 for an oversized body. Transport rejection executes no method.
Transport rejection responses have empty bodies; clients inspect the HTTP status.
Allowed OPTIONS requests use the existing preflight/private-network policy.
Notifications (no id) are accepted for read-only methods, execute without a reply,
and return HTTP 204. Notifications for any side-effecting method are ignored,
logged as invalidParams, and never execute; JSON-RPC forbids an error response
to a notification. Batch arrays follow JSON-RPC response-ID matching rules;
they do not establish ordering or transactions. A batch containing only
notifications returns 204. Clients must use IDs for commands.

`api.describe` returns the schema, each method's runtime availability, unavailable
reason, and server limits. Metadata in `x-methods` declares params, result,
scope, effect, completion, undo and errors; `operationResult` describes the final
result of a method returning a handle. Envelope validation alone does not validate
method arguments: resolve the exact method and validate its request schema.
Unknown methods return method-not-found; known unavailable methods return
unsupportedCapability. Additive methods and optional properties remain within v1;
changed meanings, new required inputs or removed fields require a new major URL.
Clients ignore unknown response properties; servers reject unknown input properties.
Object property ordering has no meaning.
Response schemas describe the producer's current shape; clients must permit extra
response properties instead of treating these closed producer schemas as a reason
to reject a later additive release.

### Identity, values and updates

Entity IDs are decimal **strings** representing positive signed 64-bit IDs.
Operation/editor/session IDs are opaque strings. Decks, presets and note types
accept exactly one of `{id: "123"}` or `{name: "Basic"}`. Resolution uses Anki's
native canonical name rules and never creates or substitutes a resource.
Return resolved IDs and canonical names together. IDs belong to a collection,
not a global namespace.

Every collection-scoped method accepts an optional `session` from `collection.get`.
It guards against using an ID in the wrong profile: mismatches fail before any
read/write. Without it, the server captures the active session at acceptance,
and rechecks before execution. A queued call never silently switches collection.
Profile unload invalidates sessions, cursors, prediction tokens and editor history.
Collection calls during profile switching fail busy until a collection is ready.

Emit timestamps in RFC 3339 UTC with `Z`; milliseconds when available. Intervals
always carry units. Scheduling day numbers are relative to Anki's collection day
epoch, not Unix days. New positions, day-based due dates and timestamp-based
learning due dates have distinct `Due` variants. Suspended/buried cards retain
the underlying due encoding according to their stored card type/native state.

`update` applies only supplied properties. Omission preserves values; `""`, `[]`
or `{}` clears only where the schema permits it. Null has meaning only where
explicitly allowed. Field names are exact in v1, field values are HTML strings,
tags are arrays canonicalized by Anki. Reject unknown fields before mutation.
Creating notes initializes omitted note-type fields as empty strings; tags default
to empty. Update fields merges by name; supplied tags replace the entire tag set.
An empty patch is invalid. Public records exclude backend cache/USN dictionaries
except the explicitly historical `Review.syncSequence` read field.

Single missing resources return notFound. Bulk results have `{items: [...]}`;
each entry has its input index and exactly one of result/error. Preserve repeated
IDs on reads. For ID-set mutations process each distinct ID once and repeat its
outcome; independently authored note/answer inputs are not deduplicated.
Top-level shape errors reject the call before work. Semantic item failures are
independent by default. Empty bulk arrays return empty items without mutation.

Search accepts Anki syntax. Empty query means all resources. Default page size
is 100; maximum 1000. Default sort is ID ascending; explicit browser column
sorts include ID as a tie breaker. The cursor is opaque, session-bound and binds
query/sort plus a snapshot of ordered matching IDs for ten minutes. Subsequent
pages must repeat the same query/sort/limit; changes fail invalidParams. Deleted
IDs are omitted as pages advance; newly matching IDs wait for a new search.
Review pages likewise snapshot ordered IDs; afterId is exclusive. Cursor expiry
or profile change is staleCursor. Lists without cursors explicitly return the
whole list; no silent truncation. notes.findEmpty returns a full IdPage using
the same pagination rules and accepts limit/cursor through its schema.

### Errors

Use standard JSON-RPC codes -32700 (parse), -32600 (request), -32601 (method),
-32602 (params), -32603 (internal). Domain error codes are fixed:

| Code | data.type | Meaning |
| --- | --- | --- |
| 1001 | notFound | Referenced resource does not exist |
| 1002 | validationFailed | Native/content validation failed |
| 1003 | editorConflict | Unsaved editor content would be overwritten |
| 1004 | collectionUnavailable | No open collection |
| 1005 | staleSession | Collection/profile session changed |
| 1006 | unsupportedCapability | Operation is known but unsupported here |
| 1007 | cancelled | Operation was cancelled |
| 1008 | conflict | Stale token, duplicate resource, or conflicting state |
| 1009 | invalidState | Operation cannot run in current GUI/scheduler state |
| 1010 | busy | Lifecycle transition or operation capacity prevents admission |
| 1011 | authenticationRequired | Anki sync credentials are unavailable |
| 1012 | ioError | File/download/import/export failure |
| 1013 | invalidSearch | Anki rejected the search |
| 1014 | staleCursor | Cursor expired or belongs to another session |
| 1015 | vetoed | A reviewer hook prevented the answer |
| 1016 | compatibilityError | A legacy operation cannot be safely translated |

`error.data.type` is stable; human messages are not a matching contract.
Details use JSON pointers for invalid input and indexed issues for bulk preflight.
Never expose stack traces or credentials. `retryable` is advisory; clients must
not automatically retry writes after a lost response. Request IDs correlate
responses and are **not** idempotency keys. No automatic mutation retries in v1.

## Operations, mutation semantics and integration

### Completion and cancellation

Methods marked completed reply after backend work, commit, required post-write
notifications and undo-state update. Long-running/interactive methods return
`{operationId, method, session}`. Poll `operations.get` for queued, running,
waitingForUser, succeeded, failed or cancelled. Nonterminal records contain
neither result nor error; success contains result; failure/cancellation contains
error. Terminal results are validated against the originating method's
operationResult schema. Handles remain accessible after profile switching so
clients can observe terminal stale-session/cancellation outcomes.

Poll at 250 ms initially, backing off to two seconds. Operations are in-memory,
lost on restart, and retained for one hour after terminal completion. Retain at
most 1000 terminal records, evicting oldest first; permit at most 100 active
operations. Evicted IDs return notFound. Tokens/cursors use bounded retention;
capacity rejection is busy, never silent eviction of active work. Server limits
are discoverable. Max request body is 16 MiB, max batch size 100, max acquired
media file 64 MiB. A local upload larger than the JSON body limit can use path.
Socket read/write idle timeout is 10 seconds; detached jobs have no implicit
execution timeout, so awaiting user input never silently means cancellation.
The I/O timeout covers receiving requests and draining replies, not the wait for
a completed method's background work.

Only expose cancellation after connecting to a native cancellation path.
Queued jobs can be cancelled; running jobs may not be. A requested cancellation
may race with success and does not undo committed partial work. User dialogs
produce waitingForUser; cancellation propagates explicitly. A client disconnect
does not cancel accepted work. application.exit is the explicit exception:
its acceptance reply is flushed before a retained callback initiates native close,
and native cancellation may keep Anki open.

`api.execute` is an ordered command batch: await each final result, then execute
the next item, continuing after item errors. It returns a handle whose terminal
result contains final item results, not nested handles. Do not infer parameter
dependencies or substitute results into later commands. Profile switch, exit,
and recursive execute are prohibited inside it. No cross-command transaction.

### Notes, media and advanced operations

Use native field/cloze validation. Duplicate checks always use the same native
normalization and HTML-aware emptiness regardless of scope; compare full normalized
first-field content after checksum matches. Deck scope uses home membership when
cards are filtered; includeChildren/acrossNoteTypes are explicit. Recheck at commit.
Empty-question rejection uses native generation/empty-card checks before insertion,
including Anki's fallback-card case. Validation performs no downloads or media writes.

Each note update applies fields and tags together, with one undo entry.
notes.createMany defaults to independent item commits/undo entries. atomic=true
preflights all notes and intra-batch duplicates under serialized collection access,
then uses the native bulk-add transaction with one undo entry. Failures yield
no collection changes, not compensating deletes. External add-on hooks are outside
the guarantee; suppress API-owned side effects in hooks/staging and document that
third-party hook I/O cannot be rolled back. No media is part of the new note input.

Store media explicitly and insert the returned normalized filename into HTML/sound
references. Return the actual filename, never the requested name as a promise.
When skipIfHash matches incoming bytes, status=skipped and filename=null: no stored
file is promised and no field reference should be inserted.
The skip hash compares incoming bytes. On rename use native collision handling;
replace must be explicit and preserves existing media until acquisition succeeds.
Download/file reads run outside Qt and enforce configured timeouts and size caps.
Media writes are not collection-undoable. The legacy staging protocol is specified
separately; filesystem and database operations do not form one atomic transaction.

Scheduler answers consume session-scoped tokens tied to the relevant card state.
Revalidate tokens at execution. The active reviewer is a different source: use
retained custom scheduling states, offered buttons, and hook/async completion.
Due eligibility reads current queues and scheduler timing, never depends on revlog.
SM-2 ease is a stored permille integer; FSRS memory carries difficulty and stability.
History retains its original factor integer with explicit/unknown encoding; do not
infer historical scheduler solely from the currently enabled scheduler.

Advanced card edits reject system IDs, ownership, template, queue/type/due and
sync metadata; route those intentions through native commands. Validate coupled
state constraints and reject unsupported combinations. History import binds SQL
values, validates the whole batch, rejects duplicate IDs, derives timestamps from
IDs and assigns unsynced metadata locally. It imports history only, not live answers
or implicit FSRS rescheduling; it can affect future native statistics/recomputation.
Publish changes, invalidate relevant queues/caches and disclose clearing undo.
Advertise unavailable until this completion behavior is verified on the baseline.

### Rewrite architecture

Implement five boundaries: transport/access, schema-driven dispatcher,
domain services, Anki integration adapters, and legacy translation. The registry
is the shared source for runtime validation/discovery/documentation. Public schemas
are independent of Anki protobuf evolution. Compatibility code performs argument
translation/result projection and orchestration; it never becomes a second collection
implementation. Retain existing configuration keys and check both shipped/default
settings when the runtime is rewritten.

GUI access and editor coordination stay on Qt's main thread. Collection work uses
Anki serialized QueryOp/CollectionOp machinery; background callbacks must not read
widgets. Capture GUI inputs before dispatch. CollectionOp success callbacks run
before on_op_finished in the audited Anki source: do not publish completed HTTP/job
results from that callback until the final change notification has actually run.
Supply failure handlers instead of surfacing unattended API exceptions as dialogs.
Network/file acquisition uses non-collection workers and applies results only after
session revalidation. The HTTP listener must keep Qt responsive and support deferred
responses rather than running nested/blocking event loops.

Register all open editor variants. Flush pending web-view change messages and detect
dirty state before note/type/deck writes; return editorConflict without auto-saving
or discarding edits. Lock/recheck the affected editor during commit and reload only
clean editors after native changes. If a variant cannot provide safe coordination,
report unsupportedCapability for that feature. Draft-targeted edits are explicit;
changing a dirty draft's type or replacing existing supplied content returns conflict.
Append may preserve existing content, but never bypass type-change conflict checks.

Use native note-type conversion, deck moves and coordinated preset updates.
Preset adapters merge against current values and preserve collection-global settings,
custom scheduling and deck overrides when building update requests. Every write
declares undo support; grouped means merged Anki undo entries, not database atomicity.
For multi-stage failures report committed work in error details and publish changes
for that work. Lifecycle operations serialize against admitted collection requests.

Roll out the runtime by domain, keeping unimplemented new methods unavailable
and legacy calls on their old implementation until their full translation/integration
tests pass. At completion all legacy calls use the shared services. Gate the new
endpoint release on complete feature mapping and the audit regression suite.
Record method duration, completion/failure/cancellation and compatibility errors
without secrets/content. Push events, remote hosting, schema migrations and package
production are outside this specification.

## Method reference

The following reference is generated from the schema. Optional parameters include
their defaults where defined. `session` is optional for every collection-scoped method.
Every method also undergoes transport access checks; runtime unavailable methods
return unsupportedCapability even when not repeated in each error list.

### `api.describe`

Discover methods, schemas, limits and runtime capabilities.

Scope: application. Effect: read. Completion: completed. Undo: none.

Parameters: none.

Result: `Description`.

Errors: `internalError`, `invalidParams`.

### `access.requestPermission`

Ask for access using the transport-supplied origin.

Scope: application. Effect: permission. Completion: completed. Undo: none.

Parameters: none.

Result: `Permission`.

Errors: `internalError`, `invalidParams`.

Never accept origin or allowed from parameters. Authentication exemption matches legacy permission discovery.

### `profiles.list`

List existing profiles.

Scope: application. Effect: read. Completion: completed. Undo: none.

Parameters: none.

Result: `Array<Profile>`.

Errors: `internalError`, `invalidParams`.

### `profiles.getActive`

Return the active profile or null.

Scope: application. Effect: read. Completion: completed. Undo: none.

Parameters: none.

Result: `Profile | null`.

Errors: `internalError`, `invalidParams`.

### `profiles.switch`

Switch profiles and finish when the destination collection is ready.

Scope: application. Effect: lifecycle. Completion: operation. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `name` | `string` | required |

Result: `{operationId: string, method: "profiles.switch", session: SessionId | null}`.
Final operation result: `Collection`.

Errors: `busy`, `cancelled`, `internalError`, `invalidParams`, `notFound`.

### `collection.get`

Inspect the active collection and its session.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `session` | `SessionId` | optional |

Result: `Collection`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

### `collection.sync`

Run one coordinated GUI/background sync.

Scope: collection. Effect: lifecycle. Completion: operation. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `includeMedia` | `boolean` | default `true` |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "collection.sync", session: SessionId | null}`.
Final operation result: `SyncResult`.

Errors: `authenticationRequired`, `busy`, `cancelled`, `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

Full sync choices are waitingForUser; never launch a second sync. includeMedia is intersected with profile media-sync settings.

### `collection.refresh`

Refresh windows, optionally invalidating supported collection caches first.

Scope: collection. Effect: refresh. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `target` | `"windows" \| "cachesAndWindows"` | default `"windows"` |
| `session` | `SessionId` | optional |

Result: `Ack`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

Does not close/reopen the collection and does not repair invalid scheduling state.

### `collection.checkIntegrity`

Run Anki database checks and repairs with normal UI completion.

Scope: collection. Effect: write. Completion: operation. Undo: clears.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "collection.checkIntegrity", session: SessionId | null}`.
Final operation result: `IntegrityResult`.

Errors: `cancelled`, `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `staleSession`.

### `collection.undo`

Undo the current Anki undo entry.

Scope: collection. Effect: write. Completion: operation. Undo: undo.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "collection.undo", session: SessionId | null}`.
Final operation result: `UndoResult`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `invalidState`, `staleSession`.

### `notes.get`

Get a note, including an empty cardIds array for cardless notes.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `id` | `EntityId` | required |
| `session` | `SessionId` | optional |

Result: `Note`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `notes.getMany`

Get notes in input order, preserving repeated IDs.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `ids` | `Array<EntityId>` | required |
| `session` | `SessionId` | optional |

Result: `{items: Array<NoteGetItem>}`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `notes.search`

Search with Anki syntax; an empty query searches all notes.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `query` | `string` | required |
| `limit` | `integer` | default `100` |
| `cursor` | `string` | optional |
| `sort` | `Sort` | optional |
| `session` | `SessionId` | optional |

Result: `IdPage`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `invalidSearch`, `staleCursor`, `staleSession`.

### `notes.validate`

Validate note content and duplicate scope without acquiring media.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `note` | `NoteInput` | required |
| `session` | `SessionId` | optional |

Result: `Validation`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

Semantic content failures return valid=false and issues; bad references or parameter types are RPC errors.

### `notes.validateMany`

Validate each note independently without side effects.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `notes` | `Array<NoteInput>` | required |
| `session` | `SessionId` | optional |

Result: `{items: Array<NoteValidationItem>}`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

### `notes.create`

Create a note and return its actual generated cards.

Scope: collection. Effect: write. Completion: completed. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `noteType` | `Reference` | required |
| `deck` | `Reference` | required |
| `fields` | `FieldValues` | required |
| `tags` | `Array<string>` | default `[]` |
| `duplicates` | `DuplicatePolicy` | optional |
| `rejectEmptyQuestions` | `boolean` | default `true` |
| `session` | `SessionId` | optional |

Result: `NoteCreated`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

### `notes.createMany`

Create notes independently, or as one native atomic collection batch.

Scope: collection. Effect: write. Completion: completed. Undo: perItemOrAtomic.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `notes` | `Array<NoteInput>` | required |
| `atomic` | `boolean` | default `false` |
| `session` | `SessionId` | optional |

Result: `{items: Array<NoteCreationItem>}`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

atomic=true validates the full set including within-batch duplicates, then uses Collection.add_notes. Any failure is a top-level error with indexed issues and no collection changes. Success keeps the same items result shape. Empty input is a no-op.

### `notes.update`

Apply fields and tags together in one native note update.

Scope: collection. Effect: write. Completion: completed. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `id` | `EntityId` | required |
| `patch` | `NotePatch` | required |
| `session` | `SessionId` | optional |

Result: `Note`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

### `notes.delete`

Delete notes and their cards; missing IDs are item errors.

Scope: collection. Effect: write. Completion: completed. Undo: perItem.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `ids` | `Array<EntityId>` | required |
| `session` | `SessionId` | optional |

Result: `{items: Array<NoteDeleteItem>}`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `notes.planConversion`

Get native suggested field/template mappings and a schema token.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `source` | `Reference` | required |
| `target` | `Reference` | required |
| `session` | `SessionId` | optional |

Result: `ConversionPlan`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `notes.convert`

Convert same-type notes through Anki note-type conversion.

Scope: collection. Effect: write. Completion: completed. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `ids` | `Array<EntityId>` | required |
| `target` | `Reference` | required |
| `fields` | `Array<ConversionMapping>` | required |
| `templates` | `Array<ConversionMapping>` | required |
| `planToken` | `string` | required |
| `session` | `SessionId` | optional |

Result: `Count`.

Errors: `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `unsupportedCapability`.

Mappings are complete target-name to source-name/null lists. Reject duplicate source mappings, mixed source note types and stale tokens. Removed source templates lose their cards/history as defined by Anki; cloze mappings use native supported rules, never raw mid assignment.

### `notes.findEmpty`

Find cleanup candidates by an explicit criterion.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `criterion` | `"allFieldsEmpty" \| "noCards" \| "allQuestionsEmpty"` | required |
| `query` | `string` | default `""` |
| `session` | `SessionId` | optional |
| `limit` | `integer` | default `100` |
| `cursor` | `string` | optional |

Result: `IdPage`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `invalidSearch`, `staleSession`.

No deletion. allFieldsEmpty uses native HTML-aware emptiness; allQuestionsEmpty uses native empty-card generation. Return all matching IDs through normal cursor pagination.

### `tags.list`

List registered tags.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `session` | `SessionId` | optional |

Result: `Array<string>`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

### `tags.add`

Add tags on selected notes.

Scope: collection. Effect: write. Completion: completed. Undo: perItem.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `noteIds` | `Array<EntityId>` | required |
| `tags` | `Array<string>` | required |
| `session` | `SessionId` | optional |

Result: `{items: Array<TagAddItem>}`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `tags.remove`

Remove tags on selected notes.

Scope: collection. Effect: write. Completion: completed. Undo: perItem.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `noteIds` | `Array<EntityId>` | required |
| `tags` | `Array<string>` | required |
| `session` | `SessionId` | optional |

Result: `{items: Array<TagRemoveItem>}`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `tags.replace`

Replace a tag on explicit notes or all notes.

Scope: collection. Effect: write. Completion: completed. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `from` | `string` | required |
| `to` | `string` | required |
| `noteIds` | `Array<EntityId>` | optional |
| `allNotes` | `boolean` | default `false` |
| `session` | `SessionId` | optional |

Result: `Count`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `staleSession`.

Exactly one selector: noteIds or allNotes=true. Never interpret an omitted selector as all notes.

### `tags.deleteUnused`

Remove unused tag registrations.

Scope: collection. Effect: write. Completion: completed. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `session` | `SessionId` | optional |

Result: `Count`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `staleSession`.

### `cards.get`

Read stored card state without rendering or predicting answers.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `id` | `EntityId` | required |
| `session` | `SessionId` | optional |

Result: `Card`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `cards.getMany`

Get cards in input order.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `ids` | `Array<EntityId>` | required |
| `session` | `SessionId` | optional |

Result: `{items: Array<CardGetItem>}`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `cards.search`

Search cards using Anki search syntax.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `query` | `string` | required |
| `limit` | `integer` | default `100` |
| `cursor` | `string` | optional |
| `sort` | `Sort` | optional |
| `session` | `SessionId` | optional |

Result: `IdPage`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `invalidSearch`, `staleCursor`, `staleSession`.

### `cards.render`

Render a stored card with Anki rendering.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `id` | `EntityId` | required |
| `session` | `SessionId` | optional |

Result: `RenderedCard`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `cards.move`

Move cards with Collection.set_deck and target-preset invariants.

Scope: collection. Effect: write. Completion: completed. Undo: perItem.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `ids` | `Array<EntityId>` | required |
| `deck` | `Reference` | required |
| `session` | `SessionId` | optional |

Result: `{items: Array<CardMoveItem>}`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

Target must already exist and be normal. Moving out of a filtered deck restores native state first through the native move operation.

### `cards.setSuspended`

Suspend or restore cards idempotently.

Scope: collection. Effect: write. Completion: completed. Undo: perItem.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `ids` | `Array<EntityId>` | required |
| `suspended` | `boolean` | required |
| `session` | `SessionId` | optional |

Result: `{items: Array<CardSuspensionItem>}`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

changed=false means already in requested state. Process repeated mutation IDs once and repeat their result.

### `cards.setFlags`

Set the user flag through Anki native flag persistence.

Scope: collection. Effect: write. Completion: completed. Undo: perItem.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `ids` | `Array<EntityId>` | required |
| `flag` | `integer` | required |
| `session` | `SessionId` | optional |

Result: `{items: Array<CardFlagItem>}`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

Zero clears the user flag; preserve other backend flag bits.

### `scheduling.get`

Read authoritative current scheduling state.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `cardId` | `EntityId` | required |
| `session` | `SessionId` | optional |

Result: `SchedulingState`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `scheduling.predict`

Predict native answers and issue a session-scoped state token.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `cardId` | `EntityId` | required |
| `session` | `SessionId` | optional |

Result: `Predictions`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

Does not represent custom states held by the GUI reviewer. Tokens are invalidated by relevant writes, undo, profile change and scheduler-day rollover.

### `scheduling.getDue`

Inspect queue-aware due eligibility without requiring history.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `cardId` | `EntityId` | required |
| `includeLearnAhead` | `boolean` | default `false` |
| `session` | `SessionId` | optional |

Result: `DueEligibility`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

dueNow excludes learn-ahead and suspended/buried queues. New cards are available but have no timed due obligation. available ignores daily deck limits; includeLearnAhead expands learning availability only.

### `scheduling.answer`

Answer using native states matching the supplied prediction token.

Scope: collection. Effect: write. Completion: completed. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `cardId` | `EntityId` | required |
| `rating` | `Rating` | required |
| `stateToken` | `string` | required |
| `elapsedMs` | `integer` | default `0` |
| `session` | `SessionId` | optional |

Result: `AnswerResult`.

Errors: `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

Reject suspended/buried and filtered-preview cards. For the active GUI card use reviewer.answer. Native elapsed-time capping applies. No client-supplied historical answer timestamp.

### `scheduling.answerMany`

Answer cards independently in input order.

Scope: collection. Effect: write. Completion: completed. Undo: perItem.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `answers` | `Array<Answer>` | required |
| `session` | `SessionId` | optional |

Result: `{items: Array<CardAnswerItem>}`.

Errors: `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

### `scheduling.reset`

Reset cards as new using the native scheduler.

Scope: collection. Effect: write. Completion: completed. Undo: perItem.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `cardIds` | `Array<EntityId>` | required |
| `restorePosition` | `boolean` | default `true` |
| `resetCounts` | `boolean` | default `false` |
| `log` | `boolean` | default `true` |
| `session` | `SessionId` | optional |

Result: `{items: Array<CardResetItem>}`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `scheduling.setDueDate`

Set due dates using Anki native days/range syntax.

Scope: collection. Effect: write. Completion: completed. Undo: perItem.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `cardIds` | `Array<EntityId>` | required |
| `days` | `string` | required |
| `session` | `SessionId` | optional |

Result: `{items: Array<CardDueDateItem>}`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

### `decks.list`

List decks in case-sensitive name order.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `session` | `SessionId` | optional |

Result: `Array<Deck>`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

### `decks.get`

Resolve a deck without creating it or falling back to Default.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `deck` | `Reference` | required |
| `session` | `SessionId` | optional |

Result: `Deck`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `decks.create`

Create a normal deck, returning the existing deck for an exact existing name.

Scope: collection. Effect: write. Completion: completed. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `name` | `string` | required |
| `session` | `SessionId` | optional |

Result: `Deck`.

Errors: `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `staleSession`.

### `decks.update`

Rename a deck using native hierarchy handling.

Scope: collection. Effect: write. Completion: completed. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `deck` | `Reference` | required |
| `name` | `string` | required |
| `session` | `SessionId` | optional |

Result: `Deck`.

Errors: `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `decks.delete`

Delete decks and their cards with explicit acknowledgement.

Scope: collection. Effect: write. Completion: completed. Undo: perItem.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `decks` | `Array<Reference>` | required |
| `deleteCards` | `true` | required |
| `session` | `SessionId` | optional |

Result: `{items: Array<DeckDeleteItem>}`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

Includes native child-deck deletion and removal of resulting cardless notes; deleting Default follows native behavior.

### `decks.getCounts`

Get native due-tree counts and total cards.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `deck` | `Reference` | required |
| `includeChildren` | `boolean` | default `true` |
| `session` | `SessionId` | optional |

Result: `DeckCounts`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `deckPresets.list`

List available deck presets.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `session` | `SessionId` | optional |

Result: `Array<EntitySummary>`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

### `deckPresets.get`

Read a typed preset.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `preset` | `Reference` | required |
| `session` | `SessionId` | optional |

Result: `DeckPreset`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `deckPresets.create`

Create a preset by cloning a specified preset or native defaults.

Scope: collection. Effect: write. Completion: completed. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `name` | `string` | required |
| `cloneFrom` | `Reference` | optional |
| `session` | `SessionId` | optional |

Result: `DeckPreset`.

Errors: `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `deckPresets.update`

Update a preset and all dependent cards through the coordinated backend request.

Scope: collection. Effect: write. Completion: operation. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `preset` | `Reference` | required |
| `name` | `string` | optional |
| `settings` | `PresetPatch` | optional |
| `rescheduleFsrs` | `boolean` | default `false` |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "deckPresets.update", session: SessionId | null}`.
Final operation result: `DeckPreset`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

Require name or settings. Preserve current target deck, collection settings, overrides and custom scheduler in the update request. rescheduleFsrs explicitly controls optional full rescheduling; mandatory native memory/step updates still run.

### `deckPresets.assign`

Assign a preset and execute native dependent-card updates.

Scope: collection. Effect: write. Completion: operation. Undo: perItem.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `decks` | `Array<Reference>` | required |
| `preset` | `Reference` | required |
| `rescheduleFsrs` | `boolean` | default `false` |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "deckPresets.assign", session: SessionId | null}`.
Final operation result: `{items: Array<PresetAssignmentItem>}`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

### `deckPresets.delete`

Delete a preset, explicitly reassigning dependent decks first.

Scope: collection. Effect: write. Completion: operation. Undo: grouped.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `preset` | `Reference` | required |
| `replacement` | `Reference` | optional |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "deckPresets.delete", session: SessionId | null}`.
Final operation result: `Ack`.

Errors: `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

replacement is required when in use. Reject Default preset deletion. No changes occur on failed preflight; do not promise atomicity across multiple native backend operations.

### `noteTypes.list`

List note types in name order.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `session` | `SessionId` | optional |

Result: `Array<EntitySummary>`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

### `noteTypes.get`

Read ordered fields/templates and styling.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `noteType` | `Reference` | required |
| `session` | `SessionId` | optional |

Result: `NoteType`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `noteTypes.create`

Create a normal or cloze note type.

Scope: collection. Effect: write. Completion: completed. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `name` | `string` | required |
| `kind` | `"normal" \| "cloze"` | default `"normal"` |
| `fields` | `Array<FieldConfig>` | required |
| `templates` | `Array<TemplateConfig>` | required |
| `css` | `string` | default `""` |
| `sortField` | `string` | optional |
| `latexHeader` | `string` | default `""` |
| `latexFooter` | `string` | default `""` |
| `latexSvg` | `boolean` | default `false` |
| `session` | `SessionId` | optional |

Result: `NoteType`.

Errors: `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `staleSession`, `validationFailed`.

### `noteTypes.update`

Update nonstructural note-type settings.

Scope: collection. Effect: write. Completion: completed. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `noteType` | `Reference` | required |
| `patch` | `NoteTypePatch` | required |
| `session` | `SessionId` | optional |

Result: `NoteType`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

### `noteTypes.editStructure`

Apply ordered structural edits and persist once using native note-type updates.

Scope: collection. Effect: write. Completion: completed. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `noteType` | `Reference` | required |
| `edits` | `Array<StructureEdit>` | required |
| `session` | `SessionId` | optional |

Result: `NoteType`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `validationFailed`.

Carry original field/template ordinals to preserve card identity. Added entries have no original ordinal. Validate all edits on a copy before saving; reject last field/template removal and invalid cloze structures.

### `noteTypes.getTemplateUsage`

Inspect question/answer template field references.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `noteType` | `Reference` | required |
| `session` | `SessionId` | optional |

Result: `Array<TemplateUsage>`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `noteTypes.replaceText`

Replace literal text in explicit note types or all note types.

Scope: collection. Effect: write. Completion: completed. Undo: grouped.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `find` | `string` | required |
| `replace` | `string` | required |
| `noteTypes` | `Array<Reference>` | optional |
| `allNoteTypes` | `boolean` | default `false` |
| `targets` | `Array<"question" \| "answer" \| "css">` | default `["question", "answer", "css"]` |
| `session` | `SessionId` | optional |

Result: `Count`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `staleSession`.

Exactly one selector: noteTypes or allNoteTypes=true. Count changed types, not occurrences.

### `noteTypes.deleteUnused`

Delete only explicitly selected note types whose use count is zero.

Scope: collection. Effect: write. Completion: completed. Undo: perItem.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `noteTypes` | `Array<Reference>` | required |
| `session` | `SessionId` | optional |

Result: `{items: Array<NoteTypeCleanupItem>}`.

Errors: `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `media.store`

Acquire and store media using Anki filename normalization.

Scope: collection. Effect: media. Completion: operation. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `filename` | `MediaFilename` | required |
| `source` | `MediaSource` | required |
| `collision` | `"rename" \| "replace" \| "error"` | default `"rename"` |
| `skipIfHash` | `MediaSkip` | optional |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "media.store", session: SessionId | null}`.
Final operation result: `MediaStored`.

Errors: `collectionUnavailable`, `conflict`, `internalError`, `invalidParams`, `ioError`, `notFound`, `staleSession`.

Reject traversal and path separators in filename. Validate strict base64 and source types before acquisition. Skip comparison is against incoming bytes and never deletes an existing file. Replacement is explicit and not collection-undoable.

### `media.get`

Read media bytes as base64.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `filename` | `MediaFilename` | required |
| `session` | `SessionId` | optional |

Result: `MediaFile`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

A basename is required; no filesystem traversal or arbitrary paths.

### `media.list`

List normalized media basenames matching a basename glob.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `pattern` | `MediaFilename` | default `"*"` |
| `session` | `SessionId` | optional |

Result: `Array<string>`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

### `media.delete`

Move media to Anki trash without deleting notes.

Scope: collection. Effect: media. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `filename` | `MediaFilename` | required |
| `session` | `SessionId` | optional |

Result: `Ack`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `media.getDirectory`

Return the local active collection media directory.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `session` | `SessionId` | optional |

Result: `{path: string}`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

### `reviews.list`

Read review history ordered by ascending review ID.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `cardIds` | `Array<EntityId>` | optional |
| `deck` | `Reference` | optional |
| `includeChildren` | `boolean` | default `false` |
| `membership` | `"current" \| "home"` | default `"current"` |
| `afterId` | `EntityId` | optional |
| `includeManual` | `boolean` | default `true` |
| `limit` | `integer` | default `100` |
| `cursor` | `string` | optional |
| `session` | `SessionId` | optional |

Result: `ReviewPage`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleCursor`, `staleSession`.

cardIds and deck are mutually exclusive. No selector means all history. afterId is exclusive. Current/home membership is explicit for filtered cards.

### `reviews.getLatestId`

Return the latest matching history ID or null.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `deck` | `Reference` | optional |
| `cardIds` | `Array<EntityId>` | optional |
| `membership` | `"current" \| "home"` | default `"current"` |
| `session` | `SessionId` | optional |

Result: `{id: EntityId | null}`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `statistics.getToday`

Count actual reviews in Anki current scheduler day, excluding manual/rescheduled entries.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `session` | `SessionId` | optional |

Result: `ReviewCount`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

### `statistics.getReviewDays`

Return all nonempty historical review days in descending date order using native graph day conventions.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `session` | `SessionId` | optional |

Result: `Array<ReviewDay>`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

### `statistics.getSummary`

Get structured collection statistics or an explicit deck including children.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `deck` | `Reference` | optional |
| `session` | `SessionId` | optional |

Result: `StatisticsSummary`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `statistics.getHtml`

Return the supported legacy HTML report, labelled as such.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `deck` | `Reference` | optional |
| `session` | `SessionId` | optional |

Result: `{html: string, format: "legacyReport"}`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `packages.import`

Import an Anki package with normal collection completion.

Scope: collection. Effect: write. Completion: operation. Undo: clears.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `path` | `string` | required |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "packages.import", session: SessionId | null}`.
Final operation result: `ImportResult`.

Errors: `cancelled`, `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `ioError`, `notFound`, `staleSession`.

### `packages.export`

Export the specified deck package.

Scope: collection. Effect: filesystem. Completion: operation. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `deck` | `Reference` | required |
| `path` | `string` | required |
| `includeScheduling` | `boolean` | default `false` |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "packages.export", session: SessionId | null}`.
Final operation result: `ExportResult`.

Errors: `cancelled`, `collectionUnavailable`, `internalError`, `invalidParams`, `ioError`, `notFound`, `staleSession`.

### `browser.open`

Open the browser and finish after the requested search/sort completes.

Scope: collection. Effect: gui. Completion: operation. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `query` | `string` | optional |
| `sort` | `Sort` | optional |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "browser.open", session: SessionId | null}`.
Final operation result: `BrowserState`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `invalidSearch`, `invalidState`, `staleSession`.

Omitted query preserves existing browser search. Explicit direction is applied regardless of previous/default column order.

### `browser.getSelection`

Read browser selection; closed browser returns open=false and empty arrays.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `session` | `SessionId` | optional |

Result: `BrowserState`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

### `browser.select`

Replace selection in an already open browser.

Scope: collection. Effect: gui. Completion: operation. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `cardIds` | `Array<EntityId>` | optional |
| `noteIds` | `Array<EntityId>` | optional |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "browser.select", session: SessionId | null}`.
Final operation result: `BrowserState`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

Exactly one selector. Note IDs select their cards in card mode; card IDs select their notes in note mode. This method does not open a closed browser.

### `editors.openNote`

Open the custom note editor and finish once it is ready.

Scope: collection. Effect: gui. Completion: operation. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `noteId` | `EntityId` | required |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "editors.openNote", session: SessionId | null}`.
Final operation result: `EditorState`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

### `editors.openAdd`

Open or activate the configured Add editor and optionally populate a draft.

Scope: collection. Effect: gui. Completion: operation. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `note` | `DraftInput` | optional |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "editors.openAdd", session: SessionId | null}`.
Final operation result: `EditorState`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

Use the active legacy/Svelte variant. Do not run duplicate/empty-field eligibility checks on an unfinished draft. Return noteId=null until persisted; do not claim ID 0 identifies a future note.

### `editors.updateDraft`

Update an Add draft through coordinated dialog setters.

Scope: collection. Effect: gui. Completion: operation. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `editorId` | `string` | required |
| `patch` | `EditorPatch` | required |
| `mode` | `"replace" \| "append"` | default `"replace"` |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "editors.updateDraft", session: SessionId | null}`.
Final operation result: `EditorState`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`.

Set note type before explicit deck. replace changes only supplied fields/tags. append concatenates supplied field strings and unions tags; deck/type still replace. Reject invalid fields before altering the draft.

### `reviewer.get`

Read active reviewer state and retained custom scheduling predictions.

Scope: collection. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `session` | `SessionId` | optional |

Result: `ReviewerState`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `staleSession`.

Inactive reviewer returns null card/rendered/token, side=none and empty answers.

### `reviewer.startTimer`

Restart the active reviewer card timer.

Scope: collection. Effect: gui. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `stateToken` | `string` | required |
| `session` | `SessionId` | optional |

Result: `Ack`.

Errors: `collectionUnavailable`, `conflict`, `internalError`, `invalidParams`, `invalidState`, `staleSession`.

### `reviewer.showQuestion`

Show the question for the active reviewer card.

Scope: collection. Effect: gui. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `stateToken` | `string` | required |
| `session` | `SessionId` | optional |

Result: `Ack`.

Errors: `collectionUnavailable`, `conflict`, `internalError`, `invalidParams`, `invalidState`, `staleSession`.

### `reviewer.showAnswer`

Show the answer for the active reviewer card.

Scope: collection. Effect: gui. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `stateToken` | `string` | required |
| `session` | `SessionId` | optional |

Result: `Ack`.

Errors: `collectionUnavailable`, `conflict`, `internalError`, `invalidParams`, `invalidState`, `staleSession`.

### `reviewer.answer`

Answer the active card using reviewer-retained states and await actual completion.

Scope: collection. Effect: write. Completion: operation. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `stateToken` | `string` | required |
| `rating` | `Rating` | required |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "reviewer.answer", session: SessionId | null}`.
Final operation result: `AnswerResult`.

Errors: `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `invalidState`, `staleSession`, `vetoed`.

Requires answer side and an offered rating. Do not resolve success until backend completion and UI notifications; reviewer hook veto returns vetoed.

### `reviewer.playAudio`

Replay audio for the current side.

Scope: collection. Effect: gui. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `stateToken` | `string` | required |
| `session` | `SessionId` | optional |

Result: `Ack`.

Errors: `collectionUnavailable`, `conflict`, `internalError`, `invalidParams`, `invalidState`, `staleSession`.

### `application.navigate`

Navigate the main window to a requested view.

Scope: collection. Effect: gui. Completion: operation. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `view` | `"deckBrowser" \| "deckOverview" \| "review"` | required |
| `deck` | `Reference` | optional |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "application.navigate", session: SessionId | null}`.
Final operation result: `Ack`.

Errors: `collectionUnavailable`, `internalError`, `invalidParams`, `invalidState`, `notFound`, `staleSession`.

deck is required for deckOverview/review and prohibited for deckBrowser.

### `application.importFile`

Run the interactive import workflow, including file choice when omitted.

Scope: collection. Effect: write. Completion: operation. Undo: clears.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `path` | `string` | optional |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "application.importFile", session: SessionId | null}`.
Final operation result: `ImportResult`.

Errors: `cancelled`, `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `ioError`, `notFound`, `staleSession`.

### `application.exit`

Acknowledge a close request, then initiate normal application close after sending the response.

Scope: application. Effect: lifecycle. Completion: completed. Undo: none.

Parameters: none.

Result: `{accepted: true}`.

Errors: `internalError`, `invalidParams`.

Accepted means the request was scheduled, not that Anki has exited. Native close/save/sync dialogs may cancel it. Retain timer/callback ownership; process exit prevents polling a final operation result.

### `advanced.cards.update`

Edit validated expert scheduling metadata through native card persistence.

Scope: collection. Effect: advancedWrite. Completion: completed. Undo: single.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `cardId` | `EntityId` | required |
| `patch` | `RawCardPatch` | required |
| `session` | `SessionId` | optional |

Result: `Card`.

Errors: `collectionUnavailable`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `unsupportedCapability`, `validationFailed`.

No id/noteId/deckId/template/queue/type/due/mod/usn writes. Moves, due changes and transitions use domain commands. Reject inconsistent coupled-state edits instead of inferring omitted state. Capability detection may restrict writable properties.

### `advanced.reviews.import`

Import historical revlog records, not live answers.

Scope: collection. Effect: advancedWrite. Completion: operation. Undo: clears.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `reviews` | `Array<ReviewImport>` | required |
| `session` | `SessionId` | optional |

Result: `{operationId: string, method: "advanced.reviews.import", session: SessionId | null}`.
Final operation result: `Count`.

Errors: `collectionUnavailable`, `conflict`, `editorConflict`, `internalError`, `invalidParams`, `notFound`, `staleSession`, `unsupportedCapability`, `validationFailed`.

Validate all records; reject duplicate IDs both internally and against collection. Derive answeredAt from ID, set usn=-1 locally. Bound SQL in one database transaction; no schema interpolation. Do not change card scheduling/counters or claim a live answer. FSRS memory remains current stored state; later recomputation may consume imported history. Expose only when transactional import and post-write notifications are verified.

### `api.execute`

Execute commands sequentially with completion barriers and independent results.

Scope: application. Effect: batch. Completion: operation. Undo: perCommand.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `commands` | `Array<Command>` | required |

Result: `{operationId: string, method: "api.execute", session: SessionId | null}`.
Final operation result: `BatchResult`.

Errors: `internalError`, `invalidParams`.

Continue after errors. No nested api.execute, application.exit or profiles.switch commands. Pin the active collection session for collection-scoped commands; a session change fails remaining such commands. Validate each command with its named method schema. Never an atomic transaction.

### `operations.get`

Poll operation status and its eventual typed result/error.

Scope: application. Effect: read. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `operationId` | `string` | required |

Result: `Operation`.

Errors: `internalError`, `invalidParams`, `notFound`.

### `operations.cancel`

Request supported cancellation without claiming rollback.

Scope: application. Effect: lifecycle. Completion: completed. Undo: none.

| Parameter | Type | Required/default |
| --- | --- | --- |
| `operationId` | `string` | required |

Result: `{requested: boolean}`.

Errors: `internalError`, `invalidParams`, `notFound`, `unsupportedCapability`.

Already terminal returns requested=false. Queued operations can cancel; running operations use native cancellation only. A cancellation request may lose a race with success.

## Shared type reference

The complete validation rules, bounds and unions are in the schema. Input defaults
are applied when creating values; patches never apply creation defaults. Response
records include all required properties even when their values are null or empty.

- **`EntityId`**: `string`.
- **`SessionId`**: `string`.
- **`Timestamp`**: `string`.
- **`Reference`**: `{id: EntityId} | {name: string}`.
- **`EntitySummary`**: `{id: EntityId, name: string}`.
- **`FieldValues`**: `Map<string, string>`.
- **`Error`**: `{code: integer, message: string, data?: {type: string, details?: {}, retryable?: boolean}}`.
- **`RpcId`**: `string | integer | null`.
- **`RpcErrorResponse`**: `{jsonrpc: "2.0", id: RpcId, error: Error}`.
- **`Ack`**: `{changed: boolean}`.
- **`Count`**: `{changedCount: integer}`.
- **`IdResult`**: `{id: EntityId}`.
- **`NoteCreated`**: `{noteId: EntityId, cardIds: Array<EntityId>}`.
- **`Issue`**: `{type: "emptyFirstField" | "duplicate" | "missingCloze" | "notClozeNoteType" | "notClozeField" | "emptyQuestions" | "unknownField" | "invalidTag", message: string, field?: string}`.
- **`Validation`**: `{valid: boolean, issues: Array<Issue>, duplicateNoteIds: Array<EntityId>}`.
- **`DuplicatePolicy`**: `{allow?: boolean, scope?: "collection" | "deck", deck?: Reference, includeChildren?: boolean, acrossNoteTypes?: boolean}`.
- **`NoteInput`**: `{noteType: Reference, deck: Reference, fields: FieldValues, tags?: Array<string>, duplicates?: DuplicatePolicy, rejectEmptyQuestions?: boolean}`.
- **`DraftInput`**: `{noteType: Reference, deck: Reference, fields?: FieldValues, tags?: Array<string>}`.
- **`NotePatch`**: `{fields?: FieldValues, tags?: Array<string>}`.
- **`Note`**: `{id: EntityId, noteType: EntitySummary, fields: FieldValues, tags: Array<string>, cardIds: Array<EntityId>, modifiedAt: Timestamp}`.
- **`Interval`**: `{value: integer, unit: "seconds" | "days"}`.
- **`Due`**: `{kind: "position", position: integer} | {kind: "timestamp", at: Timestamp} | {kind: "day", day: integer}`.
- **`MemoryState`**: `{difficulty: number, stabilityDays: number}`.
- **`SchedulingState`**: `{type: "new" | "learning" | "review" | "relearning", queue: "new" | "learning" | "review" | "dayLearning" | "preview" | "suspended" | "buriedByScheduler" | "buriedByUser", due: Due, intervalDays: integer, learningIntervalSeconds: integer | null, remainingSteps: integer, repetitions: integer, lapses: integer, sm2EasePermille: integer, fsrsMemory: MemoryState | null, desiredRetention: number | null}`.
- **`Card`**: `{id: EntityId, noteId: EntityId, deck: EntitySummary, homeDeck: EntitySummary | null, templateIndex: integer, flags: integer, modifiedAt: Timestamp, scheduling: SchedulingState}`.
- **`RenderedCard`**: `{cardId: EntityId, questionHtml: string, answerHtml: string, css: string}`.
- **`Rating`**: `"again" | "hard" | "good" | "easy"`.
- **`Prediction`**: `{rating: Rating, label: string, interval: Interval | null}`.
- **`Predictions`**: `{cardId: EntityId, source: "scheduler", stateToken: string, answers: Array<Prediction>}`.
- **`DueEligibility`**: `{cardId: EntityId, dueNow: boolean, available: boolean, learnAhead: boolean}`.
- **`Answer`**: `{cardId: EntityId, rating: Rating, stateToken: string, elapsedMs?: integer}`.
- **`AnswerResult`**: `{cardId: EntityId, reviewId: EntityId | null, scheduling: SchedulingState}`.
- **`Deck`**: `{id: EntityId, name: string, kind: "normal" | "filtered", presetId: EntityId | null}`.
- **`DeckCounts`**: `{deckId: EntityId, new: integer, learning: integer, review: integer, total: integer}`.
- **`FieldConfig`**: `{name: string, fontFamily?: string, fontSize?: integer, description?: string, sticky?: boolean, rtl?: boolean, plainText?: boolean, collapsed?: boolean, excludeFromSearch?: boolean}`.
- **`TemplateConfig`**: `{name: string, questionHtml: string, answerHtml: string, browserQuestionHtml?: string, browserAnswerHtml?: string, deck?: Reference | null, browserFontFamily?: string, browserFontSize?: integer}`.
- **`NoteTypeInput`**: `{name: string, kind?: "normal" | "cloze", fields: Array<FieldConfig>, templates: Array<TemplateConfig>, css?: string, sortField?: string, latexHeader?: string, latexFooter?: string, latexSvg?: boolean}`.
- **`NoteType`**: `{name: string, kind: "normal" | "cloze", fields: Array<FieldConfig>, templates: Array<TemplateConfig>, css: string, sortField: string, latexHeader: string, latexFooter: string, latexSvg: boolean, id: EntityId, modifiedAt: Timestamp}`.
- **`NoteTypePatch`**: `{name?: string, css?: string, sortField?: string, latexHeader?: string, latexFooter?: string, latexSvg?: boolean}`.
- **`FieldPatch`**: `{name?: string, fontFamily?: string, fontSize?: integer, description?: string, sticky?: boolean, rtl?: boolean, plainText?: boolean, collapsed?: boolean, excludeFromSearch?: boolean}`.
- **`TemplatePatch`**: `{name?: string, questionHtml?: string, answerHtml?: string, browserQuestionHtml?: string, browserAnswerHtml?: string, deck?: Reference | null, browserFontFamily?: string, browserFontSize?: integer}`.
- **`StructureEdit`**: `{op: "addField", field: FieldConfig, index?: integer} | {op: "updateField", name: string, patch: FieldPatch} | {op: "moveField", name: string, index: integer} | {op: "removeField", name: string} | {op: "addTemplate", template: TemplateConfig, index?: integer} | {op: "updateTemplate", name: string, patch: TemplatePatch} | {op: "moveTemplate", name: string, index: integer} | {op: "removeTemplate", name: string}`.
- **`TemplateUsage`**: `{templateName: string, questionFields: Array<string>, answerFields: Array<string>}`.
- **`ConversionMapping`**: `{target: string, source: string | null}`.
- **`ConversionPlan`**: `{source: EntitySummary, target: EntitySummary, fields: Array<ConversionMapping>, templates: Array<ConversionMapping>, token: string}`.
- **`PresetSettings`**: `{learnStepsMinutes?: Array<number>, relearnStepsMinutes?: Array<number>, fsrsParameters4?: Array<number>, fsrsParameters5?: Array<number>, fsrsParameters6?: Array<number>, newPerDay?: integer, reviewsPerDay?: integer, leechThreshold?: integer, answerTimeLimitSeconds?: integer, maximumIntervalDays?: integer, minimumLapseIntervalDays?: integer, graduatingGoodDays?: integer, graduatingEasyDays?: integer, initialEase?: number, easyMultiplier?: number, hardMultiplier?: number, lapseMultiplier?: number, intervalMultiplier?: number, desiredRetention?: number, historicalRetention?: number, newInsertOrder?: "due" | "random", newGatherOrder?: "deck" | "deckThenRandomNotes" | "lowestPosition" | "highestPosition" | "randomNotes" | "randomCards", newSortOrder?: "template" | "none" | "templateThenRandom" | "randomNoteThenTemplate" | "randomCard", reviewOrder?: "day" | "dayThenDeck" | "deckThenDay" | "intervalAscending" | "intervalDescending" | "easeAscending" | "easeDescending" | "retrievabilityAscending" | "retrievabilityDescending" | "relativeOverdueness" | "random" | "added" | "reverseAdded", newMix?: "mixed" | "afterReviews" | "beforeReviews", dayLearningMix?: "mixed" | "afterReviews" | "beforeReviews", leechAction?: "suspend" | "tagOnly", questionAction?: "showAnswer" | "showReminder", answerAction?: "buryCard" | "again" | "good" | "hard" | "showReminder", easyDaysPercentages?: Array<number>, ignoreReviewsBefore?: string, parameterSearch?: string, questionDisplaySeconds?: number, answerDisplaySeconds?: number, disableAutoplay?: boolean, showTimer?: boolean, stopTimerOnAnswer?: boolean, waitForAudio?: boolean, skipQuestionOnAnswerReplay?: boolean, buryNew?: boolean, buryReviews?: boolean, buryDayLearning?: boolean}`.
- **`PresetPatch`**: `PresetSettings`.
- **`DeckPreset`**: `{id: EntityId, name: string, settings: PresetSettings, modifiedAt: Timestamp}`.
- **`Review`**: `{id: EntityId, cardId: EntityId, answeredAt: Timestamp, rating: Rating | null, interval: Interval, previousInterval: Interval, factor: {encoding: "legacySm2EasePermille" | "fsrsNormalizedDifficulty" | "unknown", value: integer}, elapsedMs: integer, kind: "learning" | "review" | "relearning" | "filtered" | "manual" | "rescheduled", syncSequence: integer}`.
- **`ReviewImport`**: `{id: EntityId, cardId: EntityId, rating: Rating | null, interval: Interval, previousInterval: Interval, factor: {encoding: "legacySm2EasePermille" | "fsrsNormalizedDifficulty" | "unknown", value: integer}, elapsedMs: integer, kind: "learning" | "review" | "relearning" | "filtered" | "manual" | "rescheduled"}`.
- **`MediaSource`**: `{data: string} | {path: string} | {url: string}`.
- **`MediaStored`**: `{filename: string, status: "stored", sha256: string} | {filename: null, status: "skipped", sha256: string}`.
- **`MediaFile`**: `{filename: string, data: string}`.
- **`MediaFilename`**: `string`.
- **`MediaSkip`**: `{algorithm: "md5" | "sha256", digest: string}`.
- **`Sort`**: `{column: string, direction: "ascending" | "descending"}`.
- **`IdPage`**: `{ids: Array<EntityId>, nextCursor: string | null}`.
- **`ReviewPage`**: `{items: Array<Review>, nextCursor: string | null}`.
- **`ReviewCount`**: `{count: integer, day: string, nextDayAt: Timestamp}`.
- **`ReviewDay`**: `{day: string, count: integer}`.
- **`StatisticsSummary`**: `{cardCount: integer, noteCount: integer, reviewCount: integer, reviewTimeMs: integer, newCount: integer, learningCount: integer, reviewCardCount: integer, suspendedCount: integer}`.
- **`Permission`**: `{permission: "granted" | "denied", requireApiKey: boolean}`.
- **`Profile`**: `{name: string}`.
- **`Collection`**: `{profile: string, session: SessionId, scheduler: "sm2" | "fsrs"}`.
- **`BrowserState`**: `{open: boolean, selectedNoteIds: Array<EntityId>, selectedCardIds: Array<EntityId>}`.
- **`EditorState`**: `{id: string, kind: "add" | "note", variant: "legacy" | "svelte" | "custom", noteId: EntityId | null, deck: EntitySummary | null, noteType: EntitySummary, fields: FieldValues, tags: Array<string>, dirty: boolean, session: SessionId}`.
- **`EditorPatch`**: `{deck?: Reference, noteType?: Reference, fields?: FieldValues, tags?: Array<string>}`.
- **`ReviewerState`**: `{active: boolean, card: Card | null, rendered: RenderedCard | null, side: "question" | "answer" | "none", stateToken: string | null, answers: Array<Prediction>, source: "reviewer"}`.
- **`OperationHandle`**: `{operationId: string, method: string, session: SessionId | null}`.
- **`Progress`**: `{completed: integer, total: integer | null, message: string}`.
- **`RawCardPatch`**: `{intervalDays?: integer, sm2EasePermille?: integer, repetitions?: integer, lapses?: integer, remainingSteps?: integer, fsrsMemory?: MemoryState | null, customData?: string}`.
- **`IntegrityResult`**: `{problems: Array<string>, repaired: boolean}`.
- **`ImportResult`**: `{completed: boolean}`.
- **`ExportResult`**: `{path: string}`.
- **`SyncResult`**: `{collectionComplete: boolean, mediaComplete: boolean}`.
- **`UndoResult`**: `{label: string, changed: boolean}`.
- **`Description`**: `{apiMajor: 1, ankiVersion: string, schema: {}, methods: Array<{name: string, available: boolean, reason: string | null}>, limits: {maxRequestBytes: integer, maxBatchItems: integer, maxPageSize: integer, operationRetentionSeconds: integer, maxActiveOperations: integer, maxRetainedOperations: integer, maxMediaBytes: integer}}`.
- **`NoteGetItem`**: `{index: integer, result: Note} | {index: integer, error: Error}`.
- **`NoteValidationItem`**: `{index: integer, result: Validation} | {index: integer, error: Error}`.
- **`NoteCreationItem`**: `{index: integer, result: NoteCreated} | {index: integer, error: Error}`.
- **`NoteDeleteItem`**: `{index: integer, result: Ack} | {index: integer, error: Error}`.
- **`TagAddItem`**: `{index: integer, result: Ack} | {index: integer, error: Error}`.
- **`TagRemoveItem`**: `{index: integer, result: Ack} | {index: integer, error: Error}`.
- **`CardGetItem`**: `{index: integer, result: Card} | {index: integer, error: Error}`.
- **`CardMoveItem`**: `{index: integer, result: Ack} | {index: integer, error: Error}`.
- **`CardSuspensionItem`**: `{index: integer, result: Ack} | {index: integer, error: Error}`.
- **`CardFlagItem`**: `{index: integer, result: Ack} | {index: integer, error: Error}`.
- **`CardAnswerItem`**: `{index: integer, result: AnswerResult} | {index: integer, error: Error}`.
- **`CardResetItem`**: `{index: integer, result: Ack} | {index: integer, error: Error}`.
- **`CardDueDateItem`**: `{index: integer, result: Ack} | {index: integer, error: Error}`.
- **`DeckDeleteItem`**: `{index: integer, result: Ack} | {index: integer, error: Error}`.
- **`PresetAssignmentItem`**: `{index: integer, result: Ack} | {index: integer, error: Error}`.
- **`NoteTypeCleanupItem`**: `{index: integer, result: Ack} | {index: integer, error: Error}`.
- **`Command`**: `{method: string, params?: {}}`.
- **`BatchItem`**: `{index: integer, method: string, result: JSON} | {index: integer, method: string, error: Error}`.
- **`BatchResult`**: `{items: Array<BatchItem>}`.
- **`OperationBase`**: `{operationId: string, method: string, session: SessionId | null, createdAt: Timestamp, updatedAt: Timestamp, cancellable: boolean, progress: Progress | null}`.
- **`RpcRequest`**: `{jsonrpc: "2.0", id?: RpcId, method: string, params?: {}}`.
- **`RpcResponse`**: `{jsonrpc: "2.0", id: RpcId, result: JSON} | RpcErrorResponse`.
- **`TransportBatch`**: `Array<RpcRequest>`.
- **`TransportBatchResponse`**: `Array<RpcResponse>`.

`Operation` is a discriminated union by method and state. Its final result
uses the corresponding method operationResult schema; see operations.get.

## Workflows

### Browser-extension capture

Discover access/capabilities, fetch collection session, resolve or explicitly create
a deck, inspect the note type, validate content, store optional media, and create
the note using the returned media basename. If creation fails after explicit media
storage, the file remains and the caller may delete it; no silent rollback is claimed.

### Bulk import

Use notes.validateMany for previews, stage media explicitly, and choose independent
notes.createMany or atomic=true for a collection-only batch. Revalidate duplicates
inside the atomic batch. Inspect every indexed result in independent mode. Invoke
collection.sync separately and poll until both requested sync stages complete.

### External reviewer

Search/get a card, render it, read queue-aware eligibility, request scheduling.predict
and submit its stateToken/rating/elapsedMs to scheduling.answer. Refresh prediction
on conflict; do not retry an answer after uncertain delivery. Active GUI review uses
reviewer.get and reviewer.answer so custom retained states and veto hooks apply.

### GUI automation

Open the browser and await completion; select cards/notes explicitly, open a note
editor, or open/populate an Add draft and inspect its null persisted ID. Poll dialog
operations rather than treating accepted work as a saved note. editorConflict requires
the user/client to explicitly save or discard edits through the normal editor.

### Wire examples

`notes.create`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "notes.create",
  "params": {
    "noteType": {
      "name": "Basic"
    },
    "deck": {
      "name": "Japanese"
    },
    "fields": {
      "Front": "猫",
      "Back": "cat"
    },
    "tags": [
      "vocabulary"
    ]
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "result": {
    "noteId": "1700000000001",
    "cardIds": [
      "1700000000002"
    ]
  }
}
```

`notes.update`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "notes.update",
  "params": {
    "id": "1700000000001",
    "patch": {
      "tags": []
    }
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "result": {
    "id": "1700000000001",
    "noteType": {
      "id": "1700000000000",
      "name": "Basic"
    },
    "fields": {
      "Front": "猫",
      "Back": "cat"
    },
    "tags": [],
    "cardIds": [
      "1700000000002"
    ],
    "modifiedAt": "2026-10-10T12:00:00Z"
  }
}
```

`notes.validate`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "notes.validate",
  "params": {
    "note": {
      "noteType": {
        "name": "Basic"
      },
      "deck": {
        "name": "Japanese"
      },
      "fields": {
        "Front": "",
        "Back": "cat"
      }
    }
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "result": {
    "valid": false,
    "issues": [
      {
        "type": "emptyFirstField",
        "message": "First field is empty."
      }
    ],
    "duplicateNoteIds": []
  }
}
```

`cards.setSuspended`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "cards.setSuspended",
  "params": {
    "ids": [
      "1700000000002",
      "1700000000003"
    ],
    "suspended": true
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "result": {
    "items": [
      {
        "index": 0,
        "result": {
          "changed": false
        }
      },
      {
        "index": 1,
        "error": {
          "code": 1001,
          "message": "Card not found.",
          "data": {
            "type": "notFound"
          }
        }
      }
    ]
  }
}
```

`collection.sync`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "collection.sync",
  "params": {}
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "result": {
    "operationId": "op-sync-1",
    "method": "collection.sync",
    "session": "session-1"
  }
}
```

`operations.get`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "operations.get",
  "params": {
    "operationId": "op-sync-1"
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "result": {
    "operationId": "op-sync-1",
    "method": "collection.sync",
    "session": "session-1",
    "createdAt": "2026-10-10T12:00:00Z",
    "updatedAt": "2026-10-10T12:01:00Z",
    "cancellable": false,
    "progress": null,
    "state": "succeeded",
    "result": {
      "collectionComplete": true,
      "mediaComplete": true
    }
  }
}
```

`media.store`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "media.store",
  "params": {
    "filename": "cat.mp3",
    "source": {
      "data": "Y2F0"
    },
    "collision": "rename"
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "result": {
    "operationId": "op-media-1",
    "method": "media.store",
    "session": "session-1"
  }
}
```

`api.execute`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "api.execute",
  "params": {
    "commands": [
      {
        "method": "notes.create",
        "params": {
          "noteType": {
            "name": "Basic"
          },
          "deck": {
            "name": "Japanese"
          },
          "fields": {
            "Front": "猫",
            "Back": "cat"
          }
        }
      },
      {
        "method": "collection.sync",
        "params": {}
      }
    ]
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "result": {
    "operationId": "op-batch-1",
    "method": "api.execute",
    "session": "session-1"
  }
}
```

`notes.createMany`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "notes.createMany",
  "params": {
    "notes": [
      {
        "noteType": {
          "name": "Basic"
        },
        "deck": {
          "id": "1"
        },
        "fields": {
          "Front": "one",
          "Back": "一"
        }
      },
      {
        "noteType": {
          "name": "Basic"
        },
        "deck": {
          "id": "1"
        },
        "fields": {
          "Front": "two",
          "Back": "二"
        }
      }
    ],
    "atomic": true
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "result": {
    "items": [
      {
        "index": 0,
        "result": {
          "noteId": "1700000000011",
          "cardIds": [
            "1700000000012"
          ]
        }
      },
      {
        "index": 1,
        "result": {
          "noteId": "1700000000013",
          "cardIds": [
            "1700000000014"
          ]
        }
      }
    ]
  }
}
```

`noteTypes.editStructure`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "noteTypes.editStructure",
  "params": {
    "noteType": {
      "name": "Basic"
    },
    "edits": [
      {
        "op": "updateTemplate",
        "name": "Card 1",
        "patch": {
          "questionHtml": "{{Front}}"
        }
      }
    ]
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "result": {
    "id": "1700000000000",
    "name": "Basic",
    "kind": "normal",
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
        "answerHtml": "{{FrontSide}}<hr>{{Back}}"
      }
    ],
    "css": "",
    "sortField": "Front",
    "latexHeader": "",
    "latexFooter": "",
    "latexSvg": false,
    "modifiedAt": "2026-10-10T12:00:00Z"
  }
}
```

`scheduling.predict`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "scheduling.predict",
  "params": {
    "cardId": "1700000000002"
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
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

`scheduling.answer`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "scheduling.answer",
  "params": {
    "cardId": "1700000000002",
    "stateToken": "prediction-1",
    "rating": "good",
    "elapsedMs": 2500
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "result": {
    "cardId": "1700000000002",
    "reviewId": "1791633600000",
    "scheduling": {
      "type": "review",
      "queue": "review",
      "due": {
        "kind": "day",
        "day": 200
      },
      "intervalDays": 10,
      "learningIntervalSeconds": null,
      "remainingSteps": 0,
      "repetitions": 3,
      "lapses": 0,
      "sm2EasePermille": 2500,
      "fsrsMemory": null,
      "desiredRetention": null
    }
  }
}
```

`editors.openAdd`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "editors.openAdd",
  "params": {
    "note": {
      "noteType": {
        "name": "Basic"
      },
      "deck": {
        "id": "1"
      },
      "fields": {
        "Front": "cat"
      }
    }
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "result": {
    "operationId": "op-editor-1",
    "method": "editors.openAdd",
    "session": "session-1"
  }
}
```

`operations.get`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "operations.get",
  "params": {
    "operationId": "op-editor-1"
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "result": {
    "operationId": "op-editor-1",
    "method": "editors.openAdd",
    "session": "session-1",
    "createdAt": "2026-10-10T12:00:00Z",
    "updatedAt": "2026-10-10T12:00:01Z",
    "cancellable": false,
    "progress": null,
    "state": "succeeded",
    "result": {
      "id": "editor-1",
      "kind": "add",
      "variant": "legacy",
      "noteId": null,
      "deck": {
        "id": "1",
        "name": "Default"
      },
      "noteType": {
        "id": "1700000000000",
        "name": "Basic"
      },
      "fields": {
        "Front": "cat",
        "Back": ""
      },
      "tags": [],
      "dirty": true,
      "session": "session-1"
    }
  }
}
```

`operations.get`:

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "method": "operations.get",
  "params": {
    "operationId": "op-sync-cancelled"
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "example",
  "result": {
    "operationId": "op-sync-cancelled",
    "method": "collection.sync",
    "session": "session-1",
    "createdAt": "2026-10-10T12:00:00Z",
    "updatedAt": "2026-10-10T12:01:00Z",
    "cancellable": false,
    "progress": null,
    "state": "cancelled",
    "error": {
      "code": 1007,
      "message": "Sync cancelled.",
      "data": {
        "type": "cancelled"
      }
    }
  }
}
```

## Acceptance and validation

- Verify schemas and every local reference; check all method params/results, operation
  results, and examples, including negative fixtures. Check the legacy map against
  source decorators/signatures and require all audit/lifecycle dispositions.
- Protocol tests: malformed JSON, unknown methods/params, numeric entity IDs, auth,
  CORS/preflight, notifications, empty/oversized batches, response IDs and transport
  vs ordered batch semantics. Include operation admission, retention and cancellation.
- Contract tests: every legacy signature/default/projection and version response
  shape, media failures, conversion ambiguity and documented compatibility errors.
- Real Anki/Qt tests: temporary profiles, FSRS and SM-2, learning/relearning/new
  cards, filtered decks, differing presets, custom scheduling, both Add variants,
  open browser/editor/reviewer, undo, reopen and incremental sync.
- Exercise genuine asynchronous completion; existing action fixtures replace
  background operations and cannot validate production ordering by themselves.
- Audit-specific expected behavior is listed in LEGACY_API_MAPPING.md. These are
  required future runtime tests, not claims that the new runtime has been tested.

Run `python3 tools/check_api_spec.py` for standalone coverage/reference/example
checks without importing Anki. Install jsonschema to additionally validate against
the official Draft 2020-12 metaschema; the checker reports its availability.

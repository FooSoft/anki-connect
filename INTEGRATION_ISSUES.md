# Integration audit: Anki-Connect against Anki 26.09.3

## Implementation follow-up

The findings below are a historical audit of the old implementation; source line
links refer to that snapshot. The rewrite now supplies all 94 v1 entry points and
122 shared-service legacy forwarders. The 27 issue/lifecycle dispositions are
mapped individually in [LEGACY_API_MAPPING.md](LEGACY_API_MAPPING.md).

Native regression tests cover dedicated conversion (I01), deck moves/presets
(I02/I20), native scheduling and due/interval projections (I03/I08–I11),
post-write notifications and undo (I04), note validation and atomic bulk creation
(I12–I14), persisted template changes and safe empty-note handling (I15/I16),
transactional historical review import (I17), resolved IDs/filter membership
(I18), missing-item projections (I22) and shared legacy results. Media replacement
failure restores original bytes through the request journal. Unmapped legacy
settings/raw scheduler edits fail explicitly; newPerDayMinimum is now mapped.

GUI adapters exist for both Add variants (I05–I07), browser sorting/selection
(I23), reviewer hooks and answer completion, import dialogs, profiles and sync
(I19). Their presence is not integration certification. Affected editors are
conservatively gated even when saved. Sessions and editor history are invalidated
on native unload hooks; nested multi checks exit ordering before any work.

See [IMPLEMENTATION_HANDOFF.md](IMPLEMENTATION_HANDOFF.md) for actual tests run and
remaining GUI/network scenarios. Do not read the historical audit's statement
that dependencies were absent as a statement about the current environment.

## Scope and evidence

Reviewed on 2026-10-10 against the local source tree at
`/home/alex/projects/anki/anki-26.09.3`. Its `.version` contains `26.09.3`;
this is the application's version used throughout this report, not a claim
about another installed application or the latest upstream release.
Plugin baseline: commit `62e014e1e71d03a4673677034ab6157672c5a9ee`.

The review covers all **122 methods decorated with `@util.api()`**, their
shared helpers, and the custom editor. It compares Python calls with Anki's
Python/Qt implementations and, for scheduling, note conversion, configuration,
and database behavior, the Rust backend. The coverage index below lists every
action. Anki links point to this local source tree; plugin links are relative
to this repository. Line references describe the reviewed snapshots.

This is a source audit, supplemented by seven isolated checks that execute
extracted method bodies with controlled stand-ins. Anki, `aqt`, PyQt6, pytest,
pytest-anki, and jsonschema are not installed in the current Python environment.
The desktop application, Rust backend, network sync, and Qt event loop were
**not executed**. Observed isolated failures are distinguished from consequences
inferred from the implementation. Runtime verification targets are supplied
for each finding; they are not claims of completed integration tests.

Severity: **High** means collection/scheduling integrity or wrong-target writes;
**Medium** means incorrect results, missing updates, or significant workflow
failure; **Low** means a narrower compatibility or contract problem.

## Findings

### I01 — High: `updateNoteModel` bypasses note-type conversion

The action replaces `Note.mid`, its field map, fields, and tags, then calls
`update_note()`. The field-map assignment itself matches current Anki and is
not a missing-attribute bug. The problem is that a normal note update does not
perform the dedicated conversion's card removal/remapping or schema change.
Changing a two-template note to a one-template model can leave its old second
card associated with a nonexistent template. Reordered templates can also
attach existing scheduling history to the wrong card meaning. Omitted tags
are replaced with an empty list.

Evidence: [plugin conversion](plugin/__init__.py:849),
[Anki: pylib/anki/models.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/models.py:387), [Anki: rslib/src/notetype/notetypechange.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/notetype/notetypechange.rs:211),
[Anki: rslib/src/notes/mod.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/notes/mod.rs:432).

Use `change_notetype_info()` / `change_notetype_of_notes()` with explicit field
and template mappings, then update content and emit the resulting changes.
Verify two-to-one template conversion, reordered templates, normal/cloze
conversion, omitted tags, and undo/sync behavior.

### I02 — High: `changeDeck` skips current card-move invariants

The action uses legacy `remFromDyn()` and directly updates `cards.did`, `mod`,
and `usn`. Anki's `Collection.set_deck()` additionally rejects filtered target
decks, adjusts remaining learning/relearning steps for the target preset,
clears the previous FSRS state, and recomputes memory state with target
parameters and desired retention. The plugin bypasses all those steps and
performs the filtered-deck removal and move as separate database writes.

Evidence: [plugin move](plugin/__init__.py:575),
[Anki: pylib/anki/collection.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/collection.py:624), [Anki: rslib/src/card/mod.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/card/mod.rs:200),
[Anki: rslib/src/card/mod.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/card/mod.rs:370), [Anki: pylib/anki/scheduler/legacy.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/scheduler/legacy.py:89).

Use `Collection.set_deck()` and its returned changes. Verify a move between
presets with different learning steps and FSRS parameters, a move out of a
filtered deck, and rejection of a filtered destination.

### I03 — High: `relearnCards` writes an inconsistent scheduling state

The action only sets `type=3, queue=1` through SQL. For queue 1, Anki interprets
`due` as a Unix timestamp; a review card's old `due` is instead a day number.
The action retains that day number, remaining steps, interval, lapse count,
and memory state. It also leaves the card's modification time and update
sequence number unchanged. The card can become immediately overdue and its
change may not be included in incremental card sync.

Anki's actual relearning transition updates interval, remaining steps, lapses,
ease, FSRS memory, queue, and the correctly encoded due value together.
Evidence: [plugin SQL](plugin/__init__.py:1613),
[Anki: rslib/src/card/mod.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/card/mod.rs:50),
[Anki: rslib/src/scheduler/answering/relearning.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/scheduler/answering/relearning.rs:13).

Define the intended operation precisely: failing a review and placing a card
back into the new queue have different semantics. Use the applicable scheduler
transition rather than changing queue/type in isolation. Verify review,
learning, suspended, filtered, and FSRS cards, including sync to another client.

### I04 — High: mutation notifications are missing or occur before the write

`startEditing()` calls `mw.requireReset()` before actions mutate the collection.
In current Anki, `requireReset()` immediately calls `reset()` and fires a
synthetic `operation_did_execute` notification. It does not defer a reset until
editing finishes. Thus browser/editor/reviewer refreshes can read the old
state, and most actions do not emit a post-write notification.

Other mutations, including `deleteNotes`, `updateNoteModel`, `setDueDate`,
`setEaseFactors`, model edits, and `answerCards`, omit even that notification.
They discard backend `OpChanges`. This can leave open windows, reviewer state,
and undo menus stale. An editor holding old fields may subsequently save them
over an API update. The precise window behavior requires GUI verification.

Evidence: [shared helper](plugin/__init__.py:223),
[note writes](plugin/__init__.py:823), [Anki: qt/aqt/main.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/main.py:893),
[Anki: qt/aqt/operations/__init__.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/operations/__init__.py:49),
[Anki: qt/aqt/operations/__init__.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/operations/__init__.py:146).

Integrate mutations with `CollectionOp` or an equivalent serialized operation
flow that publishes changes after completion. Preserve HTTP completion/error
semantics when introducing asynchronous work. Test writes with browser, custom
editor, and reviewer open, followed by editing, undo, and the next API request.

### I05 — High: `guiAddCards` does not synchronize the dialog's choosers

The plugin selects a collection deck/model and directly sets
`addCards.editor.note`. Current legacy AddCards has separate deck and note-type
choosers; it adds to `deck_chooser.selected_deck_id`, not the collection's
selected deck. Its `reopen()` returns without changing defaults when fields
are nonempty. The plugin's repeated dialog opening and `setAndFocusNote()`
never explicitly set either chooser.

If the requested deck differs from the dialog's chosen deck, the displayed
note can be added to the wrong deck. Model/chooser disagreement can also affect
later input. Current AddCards already offers `set_note(note, deck_id)` to
synchronize these values. The new unsaved `Note.id` is 0, so the returned ID
is not the future persisted note's ID despite the plugin comment's intent.

Evidence: [plugin dialog setup](plugin/__init__.py:1890),
[Anki: qt/aqt/addcards_legacy.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/addcards_legacy.py:68), [Anki: qt/aqt/addcards_legacy.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/addcards_legacy.py:110),
[Anki: qt/aqt/addcards_legacy.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/addcards_legacy.py:279), [Anki: pylib/anki/notes.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/notes.py:36).

Use the dialog-level setter with the explicit deck, and define the returned ID
as an unsaved-note result or obtain it after actual addition. Verify a request
for deck B while the existing dialog is set to deck A, including a model change.

### I06 — Medium: `guiAddNoteSetData` can override an explicit deck

The action sets the deck first and the model second. Anki's model chooser
setter invokes `on_notetype_change()`; its default `update_deck=True` replaces
the selected deck with the default deck for the new model. A request containing
both `deckName` and a different `modelName` can therefore lose `deckName`.

Evidence: [plugin setter order](plugin/__init__.py:1841),
[Anki: qt/aqt/notetypechooser.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/notetypechooser.py:140),
[Anki: qt/aqt/addcards_legacy.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/addcards_legacy.py:165).

Set the model before applying the explicit deck, or use a coordinated setter.
Verify a model whose default deck differs from the requested deck.

### I07 — Medium: Add dialog APIs only handle the legacy editor

Anki 26.09.3 can open `NewAddCards` when the Svelte editor experiment is enabled.
The plugin looks up or opens only the `AddCards` registry entry. Consequently,
`guiAddNoteSetData` reports that the dialog is closed when the visible new Add
dialog is open, and `guiAddCards` opens another, legacy dialog. `NewEditor` uses
`nid` and asynchronous note information instead of the legacy `editor.note`
object interface, so changing only the registry key is insufficient.

Evidence: [plugin registry access](plugin/__init__.py:1846),
[Anki: qt/aqt/main.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/main.py:1313), [Anki: qt/aqt/addcards.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/addcards.py:46),
[Anki: qt/aqt/editor.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/editor.py:402).

Explicitly support both editor variants or document the limitation. Verify both
experiment settings and operations on the dialog the user actually opened.

### I08 — Medium: `guiCurrentCard.nextReviews` can disagree with the reviewer

The action calls `sched.nextIvlStr()` for each button, which fetches new default
scheduling states from the backend. Anki's reviewer renders intervals from its
retained `reviewer._v3.states`, which can be changed by custom scheduling.
The plugin's intervals can therefore differ from the visible buttons and from
the states used when `guiAnswerCard` answers the card.

Evidence: [plugin interval lookup](plugin/__init__.py:1958),
[Anki: pylib/anki/scheduler/v3.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/scheduler/v3.py:144), [Anki: qt/aqt/reviewer.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/reviewer.py:84),
[Anki: qt/aqt/reviewer.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/reviewer.py:915), [Anki: qt/aqt/reviewer.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/reviewer.py:531).

Describe the reviewer's active states for the active card, with an appropriate
compatibility boundary. Verify custom scheduling that changes one button's
interval. `cardsInfo` computes default states too; distinguish those predictions
from the current reviewer's potentially modified state in API documentation.

### I09 — Medium: review counts include manual scheduling records

`getNumCardsReviewedToday` and `getNumCardsReviewedByDay` count every revlog row.
Current Anki's statistics exclude Manual (4) and Rescheduled (5) entries.
Resetting cards or setting due dates can therefore increase the plugin's
reported review counts without a user reviewing a card. The daily aggregation
also reconstructs historical day boundaries with today's rollover hour and
SQLite local time, rather than following Anki's graph aggregation.

Evidence: [plugin statistics](plugin/__init__.py:520),
[Anki: rslib/src/stats/graphs/today.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/stats/graphs/today.rs:10),
[Anki: rslib/src/stats/graphs/reviews.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/stats/graphs/reviews.rs:12),
[Anki: rslib/src/revlog/mod.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/revlog/mod.rs:77).

Use current stats output or reproduce its filtering and day convention
explicitly. Verify review counts before and after `forgetCards`, `setDueDate`,
and rescheduling, plus rollover and daylight-saving boundaries.

### I10 — Medium: `areDue` does not use the card's authoritative due state

The new-card branch uses `is:new`, which Anki implements as `type=0` regardless
of queue: suspended or buried new cards are reported due. Other cards require
at least one revlog row and otherwise raise `IndexError`. For long negative
intervals the action computes due time from the last returned revlog row and
ignores current queue and due fields; a suspended learning card can be reported
due, and moving/rescheduling a card can invalidate the calculation. Its query
has no `ORDER BY`, so it does not explicitly select the latest row.

Evidence: [plugin due calculation](plugin/__init__.py:1083),
[Anki: rslib/src/search/sqlwriter.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/search/sqlwriter.rs:460), [Anki: rslib/src/card/mod.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/card/mod.rs:50).
The missing-history error was reproduced in an isolated method check.

Use queue-aware current card/scheduler state and define whether learn-ahead
counts as due. Verify suspended/buried new and learning cards, day learning,
filtered preview cards, manually rescheduled cards, and missing history.

### I11 — Medium: `getIntervals` confuses historical intervals with current state

For non-new cards, the action selects `revlog.ivl` without ordering and indexes
the last row. Cards with no history raise `IndexError`; manual/reschedule
records can become the reported latest interval. Current Anki stores the
card's current interval in `cards.ivl` and its scheduling state separately.
The result is not a reliable current-card interval or a consistently defined
chronological review history.

Evidence: [plugin interval query](plugin/__init__.py:1099),
[Anki: pylib/anki/cards.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/cards.py:85), [Anki: rslib/src/revlog/mod.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/revlog/mod.rs:40).
The missing-history error was reproduced in isolation.

Separate current interval from history. Order history by ID and specify
whether manual entries are included. Verify no-history review cards, manual
due changes, imported out-of-order history, and learning/relearning records.

### I12 — Medium: custom note validation diverges from Anki's checks

Default validation calls `dupeOrEmpty()`, now an alias for `fields_check()`.
Current results include MISSING_CLOZE (3), NOTETYPE_NOT_CLOZE (4), and
FIELD_NOT_CLOZE (5), but the plugin only understands 0, 1, and 2 and reports
an unhelpful "unknown reason" for the others.

Deck-scoped/all-model duplicate checking bypasses Anki's text normalization,
HTML-aware empty-field check, cloze validation, and full-field comparison after
the checksum match. It also considers only `cards.did`, not the home deck
represented by `odid` for a card in a filtered deck. The same note payload can
therefore produce different eligibility results when duplicate scope changes.

Finally, `addNote` expects zero generated cards to identify empty questions.
Anki's card generation now creates card 0 when no template generates a card,
so that post-add guard does not reject such a payload.

Evidence: [plugin creation/checks](plugin/__init__.py:227),
[custom duplicate check](plugin/__init__.py:300), [post-add guard](plugin/__init__.py:745),
[Anki: proto/anki/notes.proto](/home/alex/projects/anki/anki-26.09.3/proto/anki/notes.proto:113), [Anki: rslib/src/notes/mod.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/notes/mod.rs:606),
[Anki: rslib/src/notetype/cardgen.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/notetype/cardgen.rs:100).

Reuse native field validation and extend only duplicate scoping, comparing
normalized field values and defining filtered-deck membership. Validate card
generation before insertion if empty-question rejection is an API requirement.
Verify HTML-only fields, NFC-equivalent text, cloze errors, cards temporarily
in filtered decks, and templates requiring an empty second field.

### I13 — Medium: note eligibility checks write media into the collection

`canAddNote`, `canAddNoteWithErrorDetail`, and their batch variants call
`createNote()`, which calls `addMediaFromNote()` before validation. It can
download, write, and, when requested, trash an existing media file even if the
note is rejected or never added. A supposedly predictive API can modify media
used by other notes and leave unreferenced files behind.

Evidence: [creation order](plugin/__init__.py:227),
[preflight actions](plugin/__init__.py:804), [media writes](plugin/__init__.py:691),
[Anki: pylib/anki/media.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/media.py:108), [Anki: pylib/anki/media.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/media.py:141).

Separate pure eligibility validation from media acquisition and final note
construction. Verify that all `canAdd*` calls leave the media directory and
trash unchanged, including duplicate and empty-note rejection.

### I14 — Medium: `addNotes` compensation is not an atomic collection operation

Each item is added separately; if any fails, successful notes are subsequently
deleted. Media writes/replacements, changes to last-used deck/model defaults,
and undo history are not rolled back as a unit. The API raises after these
side effects even though its comment claims that "nothing happens" on error.
Undoing the compensating deletion can expose the supposedly failed batch.

Evidence: [plugin batch](plugin/__init__.py:2134),
[Anki: pylib/anki/collection.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/collection.py:537), [Anki: rslib/src/notes/mod.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/notes/mod.rs:377),
[Anki: pylib/anki/dbproxy.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/dbproxy.py:35).

Validate the batch first, define media rollback semantics, and use an atomic
backend/transaction strategy with one coherent undo operation. Verify one valid
and one invalid note, replaced media, last-used defaults, undo, and sync.

### I15 — Medium: updating an existing template through `modelTemplateAdd` is unsaved

The existing-template branch mutates the model dictionary and returns before
`save_model()`. Anki returns a cached dictionary from `models.get()` / `by_name()`
and explicitly requires `update_dict()` to persist changes. Reads can appear
to show the update while the backend and later sessions retain the old template.

Evidence: [plugin early return](plugin/__init__.py:1377),
[Anki: pylib/anki/models.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/models.py:153), [Anki: pylib/anki/models.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/models.py:225).
An isolated check confirmed that the branch makes no save call.

Save both paths and publish changes. Verify an existing-template update through
Python reads, backend rendering, cache invalidation, and collection reopen.

### I16 — High: `removeEmptyNotes` deletes unused note types instead of notes

The action checks each model's use count and removes models with no notes.
`models.use_count()` counts notes of a note type; it does not identify notes
with empty fields or empty cards. `models.remove()` deletes the note type.
Thus this API can delete intentionally prepared unused models while failing
to remove any empty notes. Removing models also changes the schema.

Evidence: [plugin action](plugin/__init__.py:1771),
[Anki: pylib/anki/models.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/models.py:198), [Anki: pylib/anki/models.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/models.py:250).

Define "empty" as an explicit note/card criterion and implement that criterion,
or rename/document this action as unused-note-type removal. Verify that unused
custom models survive a request to remove empty notes, and test empty cards
separately from notes with empty fields.

### I17 — Medium: `insertReviews` bypasses review and sync invariants

The action concatenates row values directly into SQL with no row-length/type
validation or bound parameters. Strings can be interpreted as SQL expressions
rather than rejected as invalid review values. Caller-provided `usn` is trusted;
rows inserted with an already-synced sequence number need not be uploaded.
Writing revlog alone does not update cards, daily counters, last-review time,
or existing FSRS memory state. Historical import needs defined semantics for
those values instead of implicitly behaving like a real review.

Direct SQL also clears Anki's undo and study queues. It is inaccurate to claim
the backend queues are never invalidated; the missing part is the coherent
operation/UI notification and scheduling data update.

Evidence: [plugin insertion](plugin/__init__.py:1689),
[Anki: pylib/anki/dbproxy.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/dbproxy.py:105), [Anki: rslib/src/backend/dbproxy.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/backend/dbproxy.rs:162),
[Anki: rslib/src/undo/mod.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/undo/mod.rs:233), [Anki: rslib/src/revlog/mod.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/revlog/mod.rs:40),
[Anki: rslib/src/storage/revlog/mod.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/storage/revlog/mod.rs:56).

Validate and bind rows, specify sync/duplicate-ID handling, and distinguish
historical import from answering cards. Recompute dependent scheduling state
when appropriate. Verify malformed rows, sync upload, existing FSRS cards,
daily counts, and undo behavior.

### I18 — Medium: deck reads can create decks or substitute Default

`getDeckStats`, `cardReviews`, and `getLatestReviewID` resolve names with
`decks.id(name)`, whose default is `create=True`. Querying a misspelled deck
therefore creates it. Separately, `deckNameFromId` and `getDecks` use
`decks.get()` with its default fallback: nonexistent IDs or missing cards
can be reported as belonging to Default. The plugin's `None` check in
`deckNameFromId` does not prevent that fallback.

Evidence: [stats lookup](plugin/__init__.py:678),
[review lookup](plugin/__init__.py:1638), [deck lookup](plugin/__init__.py:1508),
[Anki: pylib/anki/decks.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/decks.py:125), [Anki: pylib/anki/decks.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/decks.py:242).

Use `id_for_name()` or `id(..., create=False)` for reads and
`get(..., default=False)` when existence matters. Verify nonexistent deck names,
IDs, and card IDs without changing deck count.

### I19 — Medium: `sync` performs a blocking sync before starting the GUI sync flow

The action calls `col.sync_collection()` directly on the Qt timer thread, then
calls `mw.onSync()`. The latter is the GUI sync-button handler and can initiate
another collection sync. The first response's host/endpoint updates, scheduler
reload, cache clearing, hooks, and media monitoring are not applied through
the normal completion path. Full-sync-required responses instead cause the
plugin to raise before the GUI's upload/download choice is offered.

Evidence: [plugin sync](plugin/__init__.py:502),
[Anki: qt/aqt/main.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/main.py:1090), [Anki: qt/aqt/main.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/main.py:1107),
[Anki: qt/aqt/sync.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/sync.py:94), [Anki: qt/aqt/sync.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/sync.py:138).

Use one coordinated GUI/background sync flow and define whether an HTTP result
means started or completed. Verify normal sync, endpoint migration, full-sync
requirements, auth failure, cancellation, media sync, and UI responsiveness.

### I20 — High: preset changes skip Anki's dependent-card update logic

`saveDeckConfig` uses legacy config save/update calls; `setDeckConfigId` writes
a deck dictionary's `conf` directly. Current Deck Options uses
`update_deck_configs()`, which compares old and new presets, adjusts remaining
learning/relearning steps, resorts new cards when required, and schedules FSRS
memory recomputation for parameter/retention changes. The legacy paths do not
perform that coordinated update. `saveDeckConfig` also writes the config twice
because `decks.save()` already dispatches config dictionaries to `update_config()`.

Evidence: [plugin config save](plugin/__init__.py:620),
[preset assignment](plugin/__init__.py:637), [Anki: pylib/anki/decks.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/decks.py:88),
[Anki: pylib/anki/decks.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/decks.py:294), [Anki: rslib/src/deckconfig/service.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/deckconfig/service.rs:19),
[Anki: rslib/src/deckconfig/update.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/deckconfig/update.rs:225).

Use the current deck-config update request, with explicit rescheduling choices
and appropriate undo/UI completion. Verify changing step counts on existing
learning cards, assigning a different preset, changing FSRS parameters/retention,
and changing new-card order.

### I21 — Medium: `reloadCollection` calls a no-op

The action calls `Collection.reset()`. In current Anki that method is deprecated
and its body is `pass`; it does not reload the collection, clear model caches,
or notify windows. It cannot repair stale state from other API mutations.

Evidence: [plugin action](plugin/__init__.py:1676),
[Anki: pylib/anki/collection.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/collection.py:529).
An isolated check confirmed the no-op call.

Define whether this action means refreshing windows or reopening the collection
and implement the appropriate operation. Verify stale browser data and model
cache behavior independently; those are different kinds of refresh.

### I22 — Low: edge-case reads and suspension results are inconsistent

`notesInfo` indexes `nid_to_card_ids[nid]` after successfully loading a note.
An existing note with no associated cards raises `KeyError` for the entire
request rather than returning `cards: []`. Current normal addition creates at
least one card, so this primarily concerns incomplete/imported/manually altered
collections, not the normal new-note path.

`unsuspend` calls `suspend(cards, False)` but does not return its boolean, so
successful HTTP replies contain null. `suspend` also removes entries from its
input list while iterating, which can skip checks and incorrectly return true
when all requested cards were already in the desired state.

Evidence: [note response](plugin/__init__.py:1699),
[suspension actions](plugin/__init__.py:1041),
[Anki: pylib/anki/notes.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/notes.py:134), [Anki: pylib/anki/scheduler/legacy.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/scheduler/legacy.py:141).
The cardless-note error and discarded unsuspend return were reproduced in
isolated checks. Use a default empty card list and a separate filtered list of
cards to change; propagate the result. Verify cardless notes, repeated IDs,
and several already-suspended/unsuspended cards in succession.

### I23 — Medium: `guiBrowse` can reverse the requested numeric sort order

The action passes the client's requested order to the private table callback
`_on_sort_column_changed()`. When switching to a column whose default sort is
descending, current Anki overwrites the passed order with descending. A request
for ascending order can therefore display descending results when changing
columns. The callback models a user's first column click, not an explicit API
sort command. Its behavior differs when that column is already selected.

Evidence: [plugin sorting](plugin/__init__.py:1784),
[Anki: qt/aqt/browser/table/table.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/browser/table/table.py:494).

Implement an explicit sort operation that preserves the requested direction.
Verify ascending and descending requests for a numeric column both when it is
newly selected and when it is already active.

## Additional lifecycle risks requiring GUI verification

- **`guiExitAnki`:** the delayed `QTimer` is a local variable with no parent or
  retained attribute. It may be destroyed before its timeout. The plugin's
  server timer is correctly retained in `self.timer`; apply the same lifetime
  discipline or use `QTimer.singleShot()`. Verify that the HTTP response arrives
  and the application actually closes. [Exit action](plugin/__init__.py:2121),
  [retained server timer](plugin/__init__.py:76).
- **`loadProfile`:** switching is started asynchronously, but success is returned
  immediately. The waiter polls window visibility rather than the existing
  completion callback and has no timeout/cancellation path. A canceled close or
  sync can leave a pending waiter. Verify cancellation and follow-up collection
  requests during switching. [Plugin switch](plugin/__init__.py:474),
  [Anki: qt/aqt/main.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/main.py:568), [Anki: qt/aqt/main.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/main.py:601).
- **`guiAnswerCard`, `guiUndo`, `guiCheckDatabase`, `guiImportFile`:** GUI calls
  can start asynchronous work or offer cancellation; successful HTTP dispatch
  is not proof that the operation committed. In particular, reviewer hooks can
  veto an answer after the plugin's pre-checks. Verify completion and failure
  semantics before using these actions in a sequential `multi` workflow.
  [Answer action](plugin/__init__.py:2021), [Anki: qt/aqt/reviewer.py](/home/alex/projects/anki/anki-26.09.3/qt/aqt/reviewer.py:531).
- **Custom editor history:** history is a process-global list of note IDs and
  has no profile identity. Profile changes can retain old IDs; if another
  profile has matching IDs, navigation can show unrelated notes. Verify profile
  switching and histories in imported copies of a collection.
  [History](plugin/edit.py:133), [dialog registration](plugin/edit.py:450).

## Compatibility that should not be mistaken for breakage

Current Anki still supplies legacy compatibility for `addNote`, `dupeOrEmpty`,
`bulkAdd`, `registerNotes`, `suspendCards`, `unsuspendCards`, `answerCard`,
`nextIvlStr`, `writeData`, `stripIllegal`, `AnkiRequestsClient.streamContent`,
`AnkiPackageImporter`, and `AnkiPackageExporter`. Many model camelCase calls
are also resolved through `DeprecatedNamesMixin`. These names are maintenance
dependencies, but their mere presence is not an AttributeError finding.

Sources: [Anki: pylib/anki/_legacy.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/_legacy.py:60), [Anki: pylib/anki/collection.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/collection.py:1265),
[Anki: pylib/anki/tags.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/tags.py:187), [Anki: pylib/anki/media.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/media.py:246),
[Anki: pylib/anki/sync.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/sync.py:12), [Anki: pylib/anki/httpclient.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/httpclient.py:35),
[Anki: pylib/anki/importing.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/importing.py:14), [Anki: pylib/anki/exporting.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/exporting.py:11).

`getCollectionStatsHTML` still calls an implemented legacy report. It is not the
modern graph/report path and should not be assumed to include all current FSRS
statistics; treat that as a capability limitation, not a removed method.
[Anki: pylib/anki/stats.py](/home/alex/projects/anki/anki-26.09.3/pylib/anki/stats.py:96).

`getEaseFactors` / `setEaseFactors` still read/write the SM-2 ease field. Under
FSRS, changing that field is not equivalent to changing difficulty/stability.
Likewise, review-history `factor` encodes normalized difficulty for FSRS, not
always an ease percentage. Document the distinction for clients consuming
`cardReviews` / `getReviewsOfCards`. [Anki: rslib/src/revlog/mod.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/revlog/mod.rs:53),
[Anki: rslib/src/scheduler/states/review.rs](/home/alex/projects/anki/anki-26.09.3/rslib/src/scheduler/states/review.rs:73).

## Validation performed and next checks

Seven isolated checks passed: current Note field-map compatibility;
`modelTemplateAdd`'s missing save; refresh-before-write ordering in `createDeck`;
`notesInfo`'s cardless-note failure; missing-history failures in `areDue` and
`getIntervals`; the discarded `unsuspend` result; and `reloadCollection`'s no-op.
These checks use source-extracted Python methods and controlled stand-ins,
not an Anki session. The temporary harness is
`/tmp/anki_integration_checks.py` in the review environment.

Prioritize real integration tests for I01–I05, I16, and I20 in a temporary
profile with Anki 26.09.3. Include FSRS and SM-2, differing deck presets, a
filtered deck, custom scheduling, both Add editor variants, and open browser/
editor/reviewer windows. Existing fixtures replace background operations with
immediate main-thread execution; test production async completion separately.
[Fixture override](tests/conftest.py:220).

The original audit changed no behavior. Implementation follow-up is described above.

## Action coverage index

Every decorated API method is listed below. Finding references include shared
integration behavior where relevant. A dash means no additional specific
discrepancy was identified in this source audit; it is not a runtime certification.

<!-- The index is generated from the reviewed plugin's decorated methods. -->

### Miscellaneous (9)

| Action | Findings / notes |
| --- | --- |
| [version](plugin/__init__.py:403) | — |
| [requestPermission](plugin/__init__.py:408) | — |
| [getProfiles](plugin/__init__.py:466) | — |
| [getActiveProfile](plugin/__init__.py:470) | — |
| [loadProfile](plugin/__init__.py:474) | Profile-switch lifecycle risk |
| [sync](plugin/__init__.py:502) | I19 |
| [multi](plugin/__init__.py:515) | No async barrier / transaction |
| [reloadCollection](plugin/__init__.py:1676) | I21 |
| [apiReflect](plugin/__init__.py:2202) | — |

### Decks (13)

| Action | Findings / notes |
| --- | --- |
| [deckNames](plugin/__init__.py:541) | — |
| [deckNamesAndIds](plugin/__init__.py:546) | — |
| [getDecks](plugin/__init__.py:555) | I18 |
| [createDeck](plugin/__init__.py:569) | I04 |
| [changeDeck](plugin/__init__.py:575) | I02, I04 |
| [deleteDecks](plugin/__init__.py:592) | I04 |
| [getDeckConfig](plugin/__init__.py:610) | — |
| [saveDeckConfig](plugin/__init__.py:620) | I04, I20 |
| [setDeckConfigId](plugin/__init__.py:637) | I04, I20 |
| [cloneDeckConfigId](plugin/__init__.py:658) | I04 |
| [removeDeckConfigId](plugin/__init__.py:669) | I04 |
| [getDeckStats](plugin/__init__.py:678) | I18 |
| [deckNameFromId](plugin/__init__.py:1508) | I18 |

### Media (5)

| Action | Findings / notes |
| --- | --- |
| [storeMediaFile](plugin/__init__.py:691) | — |
| [retrieveMediaFile](plugin/__init__.py:717) | — |
| [getMediaFilesNames](plugin/__init__.py:731) | — |
| [deleteMediaFile](plugin/__init__.py:737) | — |
| [getMediaDirPath](plugin/__init__.py:741) | — |

### Notes and tags (23)

| Action | Findings / notes |
| --- | --- |
| [addNote](plugin/__init__.py:745) | I04, I12, I13 |
| [canAddNote](plugin/__init__.py:804) | I12, I13 |
| [canAddNoteWithErrorDetail](plugin/__init__.py:811) | I12, I13 |
| [updateNoteFields](plugin/__init__.py:823) | I04 |
| [updateNote](plugin/__init__.py:837) | I04 |
| [updateNoteModel](plugin/__init__.py:849) | I01, I04 |
| [updateNoteTags](plugin/__init__.py:901) | I04 |
| [getNoteTags](plugin/__init__.py:914) | — |
| [addTags](plugin/__init__.py:919) | I04 |
| [removeTags](plugin/__init__.py:925) | I04 |
| [getTags](plugin/__init__.py:930) | — |
| [clearUnusedTags](plugin/__init__.py:935) | I04 |
| [replaceTags](plugin/__init__.py:940) | I04 |
| [replaceTagsInAllNotes](plugin/__init__.py:960) | I04 |
| [findNotes](plugin/__init__.py:1517) | — |
| [notesInfo](plugin/__init__.py:1699) | I22 |
| [notesModTime](plugin/__init__.py:1748) | — |
| [deleteNotes](plugin/__init__.py:1766) | I04 |
| [removeEmptyNotes](plugin/__init__.py:1771) | I04, I16 |
| [cardsToNotes](plugin/__init__.py:1779) | — |
| [addNotes](plugin/__init__.py:2134) | I04, I12, I13, I14 |
| [canAddNotes](plugin/__init__.py:2154) | I12, I13 |
| [canAddNotesWithErrorDetail](plugin/__init__.py:2162) | I12, I13 |

### Cards and scheduling (16)

| Action | Findings / notes |
| --- | --- |
| [setEaseFactors](plugin/__init__.py:977) | I04, SM-2/FSRS distinction |
| [setSpecificValueOfCard](plugin/__init__.py:993) | I04 |
| [getEaseFactors](plugin/__init__.py:1026) | SM-2/FSRS distinction |
| [suspend](plugin/__init__.py:1041) | I04, I22 |
| [unsuspend](plugin/__init__.py:1060) | I04, I22 |
| [suspended](plugin/__init__.py:1065) | — |
| [areSuspended](plugin/__init__.py:1071) | — |
| [areDue](plugin/__init__.py:1083) | I10 |
| [getIntervals](plugin/__init__.py:1099) | I11 |
| [findCards](plugin/__init__.py:1525) | — |
| [cardsInfo](plugin/__init__.py:1533) | I08 |
| [cardsModTime](plugin/__init__.py:1583) | — |
| [forgetCards](plugin/__init__.py:1601) | I04 |
| [relearnCards](plugin/__init__.py:1613) | I03, I04 |
| [answerCards](plugin/__init__.py:1620) | I04 |
| [setDueDate](plugin/__init__.py:1670) | I04 |

### Models (26)

| Action | Findings / notes |
| --- | --- |
| [modelNames](plugin/__init__.py:1115) | — |
| [createModel](plugin/__init__.py:1120) | I04 |
| [modelNamesAndIds](plugin/__init__.py:1164) | — |
| [findModelsById](plugin/__init__.py:1173) | — |
| [findModelsByName](plugin/__init__.py:1184) | — |
| [modelNameFromId](plugin/__init__.py:1195) | — |
| [modelFieldNames](plugin/__init__.py:1204) | — |
| [modelFieldDescriptions](plugin/__init__.py:1213) | — |
| [modelFieldFonts](plugin/__init__.py:1226) | — |
| [modelFieldsOnTemplates](plugin/__init__.py:1241) | — |
| [modelTemplates](plugin/__init__.py:1272) | — |
| [modelStyling](plugin/__init__.py:1285) | — |
| [updateModelTemplates](plugin/__init__.py:1294) | I04 |
| [updateModelStyling](plugin/__init__.py:1316) | I04 |
| [findAndReplaceInModels](plugin/__init__.py:1328) | I04 |
| [modelTemplateRename](plugin/__init__.py:1357) | I04 |
| [modelTemplateReposition](plugin/__init__.py:1367) | I04 |
| [modelTemplateAdd](plugin/__init__.py:1377) | I04, I15 |
| [modelTemplateRemove](plugin/__init__.py:1401) | I04 |
| [modelFieldRename](plugin/__init__.py:1411) | I04 |
| [modelFieldReposition](plugin/__init__.py:1422) | I04 |
| [modelFieldAdd](plugin/__init__.py:1433) | I04 |
| [modelFieldRemove](plugin/__init__.py:1453) | I04 |
| [modelFieldSetFont](plugin/__init__.py:1464) | I04 |
| [modelFieldSetFontSize](plugin/__init__.py:1478) | I04 |
| [modelFieldSetDescription](plugin/__init__.py:1492) | I04 |

### GUI (21)

| Action | Findings / notes |
| --- | --- |
| [guiBrowse](plugin/__init__.py:1784) | I23 |
| [guiEditNote](plugin/__init__.py:1816) | Editor/history lifecycle risk |
| [guiSelectNote](plugin/__init__.py:1820) | — |
| [guiSelectCard](plugin/__init__.py:1825) | — |
| [guiSelectedNotes](plugin/__init__.py:1834) | — |
| [guiAddNoteSetData](plugin/__init__.py:1841) | I06, I07 |
| [guiAddCards](plugin/__init__.py:1890) | I05, I07 |
| [guiReviewActive](plugin/__init__.py:1953) | — |
| [guiCurrentCard](plugin/__init__.py:1958) | I08 |
| [guiStartCardTimer](plugin/__init__.py:1990) | — |
| [guiShowQuestion](plugin/__init__.py:2003) | — |
| [guiShowAnswer](plugin/__init__.py:2012) | — |
| [guiAnswerCard](plugin/__init__.py:2021) | Async completion / veto |
| [guiPlayAudio](plugin/__init__.py:2035) | — |
| [guiUndo](plugin/__init__.py:2046) | Async completion |
| [guiDeckOverview](plugin/__init__.py:2052) | — |
| [guiDeckBrowser](plugin/__init__.py:2065) | — |
| [guiDeckReview](plugin/__init__.py:2070) | — |
| [guiImportFile](plugin/__init__.py:2079) | Async completion |
| [guiExitAnki](plugin/__init__.py:2121) | Timer lifetime risk |
| [guiCheckDatabase](plugin/__init__.py:2128) | Async completion |

### Statistics and review history (7)

| Action | Findings / notes |
| --- | --- |
| [getNumCardsReviewedToday](plugin/__init__.py:520) | I09 |
| [getNumCardsReviewedByDay](plugin/__init__.py:524) | I09 |
| [getCollectionStatsHTML](plugin/__init__.py:530) | Legacy report limitation |
| [cardReviews](plugin/__init__.py:1638) | I18, FSRS factor semantics |
| [getReviewsOfCards](plugin/__init__.py:1647) | FSRS factor semantics |
| [getLatestReviewID](plugin/__init__.py:1681) | I18 |
| [insertReviews](plugin/__init__.py:1689) | I17 |

### Packages (2)

| Action | Findings / notes |
| --- | --- |
| [exportPackage](plugin/__init__.py:2171) | Legacy compatibility wrapper |
| [importPackage](plugin/__init__.py:2186) | I04, Legacy compatibility wrapper |

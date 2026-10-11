# Legacy API translation and integration dispositions

**Status: specification only; no legacy action has been rewritten by these documents.**
This map covers the 122 `@util.api()` methods in the current source at commit
`2a076b2`, plus its versioned decorator aliases. The source contains no such
aliases today. Keep the dispatcher's latest-applicable-alias rule when later
aliases are introduced. The new contract is [API_V1.md](API_V1.md), with schemas
in [api-v1.schema.json](api-v1.schema.json).

## Compatibility rules

Preserve parameter spelling/defaults, the configured API key and origin rules,
including transport-supplied requestPermission context. Default omitted legacy
version to 4. Versions <=4 return a bare successful result; versions >=5 return
`{result, error: null}`. Exceptions at **every** version return
`{result: null, error: message}`. Continue accepting legacy version numbers under
the old dispatch rules; URL major 1 is not legacy version 7. Errors remain strings
on the old wire even when services use typed errors. Do not promise identical
Python exception text. Domain bug corrections below are intentional exceptions.

Convert legacy numeric/string IDs to validated decimal IDs and results back to
legacy numbers. Convert timestamps to Unix seconds for mod and IDs to numeric
milliseconds for revlog. Raw type/queue/due/left and legacy model/config records
are projections from verified adapter snapshots, not new writable public records.
Snapshot conversion may use native reads, but no adapter bypasses domain mutation
services. Retain baseline backend extension keys privately when translating a
legacy dictionary; reject unmappable requested changes instead of silently dropping
them. Reconstruct legacy template/field metadata and order with these snapshots.

Current legacy notification/read error quirks do not justify bypassing validation.
Authentication applies to each nested multi request as it does now; never inject
the outer key or version into a nested request that omitted it. Permission exemptions
are scoped to the exact action and actual origin. Keep legacy banner/preflight
behavior at the root. requestPermission approval returns {permission: "granted",
requireApikey: boolean, version: configured apiVersion}; denied replies contain {permission: "denied"}
as the current action does. Use the shared permission decision then project these
legacy properties; do not expose secrets.

### Completion and multi

Accepted legacy replies retain historical timing where actions opened a dialog or
started work. Track their underlying operation internally without returning a new
handle or changing the response shape. Standalone callers cannot observe a later
failure retroactively; logs/UI retain it. New clients use operation handles.
Other legacy calls wait for final shared-service results without blocking Qt.

multi has a completion barrier for each item, including accepted calls. An accepted
success that later fails/cancels becomes a legacy error in that item's multi reply;
continue subsequent items in order. Profile switching is allowed in legacy multi,
and successful switching rebinds subsequent legacy requests to the destination.
Failed/cancelled switching leaves the current session in use. The new api.execute
prohibits profile switching to keep its session contract simple. Nested multi is
flattened through a sequential continuation, preserving nested result shape and
credential checks; no nested blocking event loop. Limit nesting to 16 levels and
total actions to 100; malformed/over-limit batches error before execution.
guiExitAnki must be the last executable item (including nested items); otherwise
reject the batch before work. Flush the complete batch reply before close begins.
No batch implies database or media atomicity.

### Common note and media translation

Map modelName/deckName to name references; match old creation/conversion field
names case-insensitively only when there is one unambiguous native field. Ignore
unknown fields where the old action did; otherwise error. Translate options:
allowDuplicate → duplicates.allow (false by default); duplicateScope=None/collection
→ collection, deck → deck; duplicateScopeOptions.deckName supplies the scope deck,
otherwise use the creation deck; checkChildren/across-model flags map directly.
Reject unknown scope values. Run native empty/cloze checks for every duplicate scope.

For canAdd* calls construct only prospective field references for audio/video/picture
entries; do not download, write, replace or trash files. Eligibility checks validate
the content/draft using placeholders but do not promise remote media availability.
Reported errors use detailed native field/cloze reasons. For actual creation/update,
retain legacy data > path > url precedence and skipHash as incoming MD5 comparison.
deleteExisting=true → explicit replacement; false → native rename. Source read failure
must not trash the existing file. Render picture references as escaped img src and
audio/video as escaped sound references in the listed fields, using actual filenames.
Media acquisition failure fails the action rather than embedding error text into
note fields. This is a deliberate correctness exception to the old addMedia behavior.

Legacy note writes stage all acquisition outside the collection media directory,
then revalidate against the pinned session. Back up explicit replacements, install
media, and commit the native note mutation under serialized admission/editor
coordination. On failure before collection commit, remove only installed new files
owned by this operation and restore backups; never delete a file another accepted
operation changed. No concurrent API-owned media writes run during this interval.
Record the staging manifest in a temporary directory and recover interrupted
replacement work before admitting new writes. If cleanup fails, return an error
describing leftover/restoration failures; do not claim filesystem atomicity or crash
rollback. After collection commit, keep media even if HTTP delivery fails. Native
undo reverses collection data, not media files. Third-party media writes/sync require
native coordination or a conflict, never guessed ownership. This staging is internal
legacy orchestration; new calls keep media and collection writes separate.

addNotes preflights every item including within-batch duplicates, stages media,
then calls notes.createMany atomic=true. One coherent native undo operation covers
collection changes/defaults; no compensating note deletion is permitted. Media has
the separately stated recovery/cleanup guarantee, not cross-resource atomicity.

### Conversion and expert-write exceptions

updateNoteModel has no mapping parameters. Derive mappings only when field/template
names uniquely match (case-insensitive for legacy fields), or when the native
conversion suggestion is unambiguous with matching normal/cloze structure. Unmatched
target fields start empty and are then populated from supplied fields. Unmatched
source templates are explicitly removed by native conversion, never kept with invalid
ordinals. Reject ambiguous/reordered-by-index-only or unsupported cross-kind mappings
with compatibilityError instead of assigning mid directly. Preflight supplied fields,
tags and editor conflicts before converting; preserve omitted tags. Conversion and
subsequent content update may be grouped into one undo entry, but are not claimed
atomic across backend calls; report committed conversion if the second stage fails.

setSpecificValueOfCard first validates card is scalar, keys/newValues are equal-length
arrays, and no duplicate key is present. Recognized safe translations are:

| Legacy key | New path/meaning |
| --- | --- |
| factor | advanced.cards.update sm2EasePermille |
| ivl | advanced.cards.update intervalDays |
| reps, lapses | advanced.cards.update repetitions, lapses |
| custom_data | advanced.cards.update customData |
| did | cards.move to an existing normal deck ID, only with warning_check=true |
| flags | cards.setFlags, user flag 0–7; reject backend reserved-bit writes |

Legacy protected ivl/reps/lapses require warning_check=true before translation.
Unknown keys and id/nid/ord/queue/type/due/left/odid/odue/mod/usn are rejected with
compatibilityError even when warning_check=true; these are not coherent independent
writes. Do not combine did or flags with metadata patches, or with each other, because no
atomicity exists across the operations. Return compatibilityError before writes for
such combinations. The old arbitrary setattr escape hatch is intentionally removed.

modelFieldsOnTemplates preserves its established projection: ignore FrontSide;
on the answer side omit fields already referenced on the question side. The new
getTemplateUsage reports all real question/answer field references, not this lossy
projection. Preserve template order and use the native template parser.

## Complete action map

Every source signature appears below. Targets separated by semicolons are composed
shared services; the table does not imply multiple HTTP round trips. Effects/errors
and undo are inherited from those services. Accepted/final timing is specified per
action. I04 applies to all collection mutations even when not repeated in each row.

| Legacy action and exact parameters | New service(s) | Translation | Legacy result | Completion | Corrections / exceptions |
| --- | --- | --- | --- | --- | --- |
| `version()` | `api.describe` | No arguments; legacy version remains configured apiVersion (6), not new URL major 1. | Integer 6/configured value. | completed | — |
| `requestPermission(origin, allowed)` | `access.requestPermission` | Ignore caller origin/allowed; use actual transport context. Preserve bypass and persisted approval/ignore decisions. | {permission, requireApikey, version} when granted; denied has permission only. | permission decision | — |
| `getProfiles()` | `profiles.list` | No arguments. | Array of profile name strings. | completed | — |
| `getActiveProfile()` | `profiles.getActive` | No arguments. | Name or null. | completed | — |
| `loadProfile(name)` | `profiles.switch` | name → name; unknown name returns false without starting work. | true when accepted; false for missing profile. | accepted; multi awaits final | Session-scoped callback replaces visibility polling; cancellation is terminal internally. |
| `sync()` | `collection.sync` | No arguments; includeMedia uses existing profile setting; require Anki sync auth before acceptance. | null when accepted. | accepted; multi awaits final | I19: one sync workflow; no preliminary blocking sync. Later failures are tracked internally, not returned retroactively. |
| `multi(actions)` | `api.execute` | Use the legacy sequential executor, retaining each nested action/version/key; await shared-service completion before the next item. | Array of legacy replies in input order; preserve each nested version envelope. | all nested operations final | No atomicity. Legacy profile switching is allowed with a barrier; new api.execute prohibits it. Shutdown ends execution as described below. |
| `getNumCardsReviewedToday()` | `statistics.getToday` | No arguments. | Integer count. | completed | I09: exclude manual/rescheduled history; native day boundaries. |
| `getNumCardsReviewedByDay()` | `statistics.getReviewDays` | No arguments. | Array of [day string, integer count] descending by day. | completed | I09: native graph aggregation, including rollover/DST. |
| `getCollectionStatsHTML(wholeCollection=True)` | `statistics.getHtml` | wholeCollection=true omits deck; false captures selected deck explicitly. | HTML string; remains legacyReport, not modern FSRS graphs. | completed | — |
| `deckNames()` | `decks.list` | No arguments. | Array of names. | completed | — |
| `deckNamesAndIds()` | `decks.list` | No arguments. | Object mapping name to numeric ID. | completed | — |
| `getDecks(cards)` | `cards.getMany` | cards → ids; group resolved current decks by name. | Object mapping deck name to input numeric card IDs. | completed | I18: missing cards/decks raise a legacy error rather than masquerading as Default. |
| `createDeck(deck)` | `decks.create` | deck → name; exact existing deck returns existing ID. | Numeric deck ID. | completed | — |
| `changeDeck(cards, deck)` | `decks.get`; `decks.create`; `cards.move` | Resolve deck, explicitly create when absent (legacy write behavior), then cards → ids and deck reference. | null; missing card item errors become a legacy error. | completed | I02: native move invariants and filtered-destination rejection; report partial changes if any item fails. |
| `deleteDecks(decks, cardsToo=False)` | `decks.delete` | Require cardsToo=true; convert decks to name references; skip missing names as legacy; deleteCards=true. | null. | completed | Preserve rejection of cardsToo=false; do not quietly delete cards. |
| `getDeckConfig(deck)` | `decks.get`; `deckPresets.get` | Resolve name then preset; missing name returns false. Project current baseline legacy config from adapter snapshot. | Legacy preset dictionary or false. | completed | — |
| `saveDeckConfig(config)` | `deckPresets.update` | Resolve config.id; merge legacy known values into typed preset settings, preserving untouched backend extensions privately. | Boolean; missing preset/validation/native failure returns false. | final operation | I20: one coordinated update. No metadata writes from client mod/usn; optional FSRS full rescheduling defaults false. |
| `setDeckConfigId(decks, configId)` | `deckPresets.assign` | decks → name references; configId → preset id. Preflight all references; missing references return false. | true only when all assignments succeed; otherwise false. | final operation | I20: native dependent-card updates. Partial runtime failure remains observable and must be logged. |
| `cloneDeckConfigId(name, cloneFrom='1')` | `deckPresets.create` | name → name; cloneFrom (default "1") → id reference; missing source returns false. | Numeric new preset ID or false. | completed | — |
| `removeDeckConfigId(configId)` | `deckPresets.delete` | configId → id reference; use Default preset as explicit replacement if in use. | Boolean; false for missing/default/nondeletable preset. | final operation | — |
| `getDeckStats(decks)` | `decks.getCounts` | Resolve each supplied name without creation; counts use native due-tree hierarchy. | Object keyed by numeric deck ID strings; values preserve deck_id/name/new_count/learn_count/review_count/total_in_deck. | completed | I18: unknown deck raises; deck count unchanged. |
| `storeMediaFile(filename, data=None, path=None, url=None, skipHash=None, deleteExisting=True)` | `media.store` | Translate filename/source/hash/collision using the staging rules below; retain legacy data > path > url precedence. | Actual filename; null when incoming bytes match skipHash. | final operation | Media failure is an error; replacement occurs only after successful acquisition. |
| `retrieveMediaFile(filename)` | `media.get` | Normalize legacy basename using Anki NFC/illegal-name rules, then get. | Base64 string; false for absent file. | completed | — |
| `getMediaFilesNames(pattern='*')` | `media.list` | pattern defaults "*"; legacy path components are rejected. | Array of basenames. | completed | Traversal outside media directory is not preserved. |
| `deleteMediaFile(filename)` | `media.delete` | filename → normalized basename. | null; absent file is a no-op. | completed | — |
| `getMediaDirPath()` | `media.getDirectory` | No arguments. | Absolute local path string. | completed | — |
| `addNote(note)` | `notes.create`; `media.store` | Translate note(s) using the common note/media policy below. | Numeric note ID. | completed | I12–I14: native validation; pure canAdd checks; no compensating deletion; media guarantee is separate. |
| `canAddNote(note)` | `notes.validate` | Translate note(s) using the common note/media policy below. | Boolean. | completed | I12–I14: native validation; pure canAdd checks; no compensating deletion; media guarantee is separate. |
| `canAddNoteWithErrorDetail(note)` | `notes.validate` | Translate note(s) using the common note/media policy below. | {canAdd: true} or {canAdd: false, error: message}. | completed | I12–I14: native validation; pure canAdd checks; no compensating deletion; media guarantee is separate. |
| `updateNoteFields(note)` | `notes.update`; `media.store` | note.id → id; translate fields (ignore unknown names as legacy), stage media, then one fields patch. | null. | completed | I04: post-write notification and undo; editorConflict replaces silent overwrite. |
| `updateNote(note)` | `notes.update`; `media.store` | Require fields or tags; combine provided fields and tags into a single patch after validation/media staging. | null. | completed | I04: tags validation cannot leave fields partially updated. |
| `updateNoteModel(note)` | `notes.planConversion`; `notes.convert`; `notes.update` | Use explicit conversion policy below; translate modelName/fields/tags; preserve omitted tags. | null. | completed | I01: native conversion; ambiguous mappings return compatibilityError; post-conversion content failure may leave conversion committed and must be reported. |
| `updateNoteTags(note, tags)` | `notes.update` | note → id; string tags becomes one-element list; validate string array; patch.tags replaces set. | null. | completed | — |
| `getNoteTags(note)` | `notes.get` | note → id. | Tag string array. | completed | — |
| `addTags(notes, tags, add=True)` | `tags.add`; `tags.remove` | notes → noteIds; split legacy whitespace tag string with native parsing; add=false selects remove. | null. | completed | — |
| `removeTags(notes, tags)` | `tags.remove` | Same legacy whitespace tag parsing. | null. | completed | — |
| `getTags()` | `tags.list` | No arguments. | Tag string array. | completed | — |
| `clearUnusedTags()` | `tags.deleteUnused` | No arguments. | null. | completed | — |
| `replaceTags(notes, tag_to_replace, replace_with_tag)` | `tags.replace` | notes → noteIds; tag_to_replace → from; replace_with_tag → to; skip missing notes as legacy. | null. | completed | — |
| `replaceTagsInAllNotes(tag_to_replace, replace_with_tag)` | `tags.replace` | allNotes=true, explicit from/to. | null. | completed | — |
| `setEaseFactors(cards, easeFactors)` | `advanced.cards.update` | Zip cards/easeFactors after requiring equal lengths; patch sm2EasePermille; never treat as FSRS difficulty. | Per-card booleans; false for missing or rejected cards. | completed | Reject mismatched lengths before writes; native undo/notifications replace skip_undo_entry. |
| `setSpecificValueOfCard(card, keys, newValues, warning_check=False)` | `advanced.cards.update`; `cards.move`; `cards.setFlags` | Use the expert-field translation table below; reject unsafe fields without modifying anything. | Preserve false for invalid shape/protected writes without warning_check; [true] on success; [[false, message]] on native failure. | completed | warning_check=true does not permit identity/sync/queue corruption; return compatibilityError for untranslatable protected writes. |
| `getEaseFactors(cards)` | `cards.getMany` | cards → ids; project stored sm2EasePermille; missing card raises as legacy. | Integer array in input order. | completed | — |
| `suspend(cards, suspend=True)` | `cards.setSuspended` | cards → ids; suspend defaults true → suspended; any missing card becomes a legacy error. | true if any distinct card changed, else false. | completed | I22: do not mutate request list while iterating. |
| `unsuspend(cards)` | `cards.setSuspended` | suspended=false. | true if any distinct card changed, else false. | completed | I22 documented return correction: old null becomes boolean. |
| `suspended(card)` | `cards.get` | card → id; queue=suspended. | Boolean. | completed | — |
| `areSuspended(cards)` | `cards.getMany` | cards → ids; map queue; missing card → null. | Array of booleans/null. | completed | — |
| `areDue(cards)` | `scheduling.getDue` | For each card use includeLearnAhead=false; project dueNow, or available for unsuspended/unburied new cards. | Boolean array; missing card raises. | completed | I10: queue-aware, no revlog dependency or suspended-new positives. |
| `getIntervals(cards, complete=False)` | `scheduling.get`; `reviews.list` | complete=false uses current interval: new=0, native scheduled seconds for learning/relearning, stored days for review. complete=true reads ordered nonmanual history. | Signed legacy values (negative seconds, positive days); complete history arrays; new cards remain scalar 0. | completed | I11: explicitly current state vs ordered history; missing history returns [] in complete mode instead of IndexError. |
| `modelNames()` | `noteTypes.list` | No arguments. | Name string array. | completed | — |
| `createModel(modelName, inOrderFields, cardTemplates, css=None, isCloze=False)` | `noteTypes.create` | modelName → name; inOrderFields → field configs; cardTemplates Name/Front/Back → template configs, missing Name gets Card N; css=None uses native default CSS; isCloze selects kind. | Legacy note-type dictionary projected from baseline adapter snapshot. | completed | — |
| `modelNamesAndIds()` | `noteTypes.list` | No arguments. | Object mapping name to numeric ID. | completed | — |
| `findModelsById(modelIds)` | `noteTypes.get` | Resolve each modelIds entry, fail whole request when missing. | Array of legacy note-type dictionaries. | completed | — |
| `findModelsByName(modelNames)` | `noteTypes.get` | Resolve each modelNames entry, fail whole request when missing. | Array of legacy note-type dictionaries. | completed | — |
| `modelNameFromId(modelId)` | `noteTypes.get` | modelId → id reference. | Name string. | completed | — |
| `modelFieldNames(modelName)` | `noteTypes.get` | modelName → name reference. | Field names in ordinal order. | completed | — |
| `modelFieldDescriptions(modelName)` | `noteTypes.get` | modelName → name reference. | Field description strings in ordinal order; missing description → empty string. | completed | — |
| `modelFieldFonts(modelName)` | `noteTypes.get` | modelName → name reference. | Object mapping field name to {font, size}. | completed | — |
| `modelFieldsOnTemplates(modelName)` | `noteTypes.getTemplateUsage` | modelName → name reference; retain answer-side exclusion policy below. | Object mapping template name to [questionFields, answerFields]. | completed | — |
| `modelTemplates(modelName)` | `noteTypes.get` | modelName → name reference. | Object mapping template name to {Front, Back}. | completed | — |
| `modelStyling(modelName)` | `noteTypes.get` | modelName → name reference. | {css}. | completed | — |
| `updateModelTemplates(model)` | `noteTypes.editStructure` | model.name → reference; existing model.templates keys → updateTemplate edits. Preserve ignoring missing template names and falsey Front/Back values. | null. | completed | — |
| `updateModelStyling(model)` | `noteTypes.update` | model.name → reference; patch.css=model.css. | null. | completed | — |
| `findAndReplaceInModels(modelName, findText, replaceText, front=True, back=True, css=True)` | `noteTypes.replaceText` | findText/replaceText → find/replace; truthy modelName selects one type, otherwise allNoteTypes=true; front/back/css select targets. All false is a no-op. | Count of changed note types. | completed | — |
| `modelTemplateRename(modelName, oldTemplateName, newTemplateName)` | `noteTypes.editStructure` | updateTemplate by oldTemplateName with patch.name=newTemplateName. | null. | completed | — |
| `modelTemplateReposition(modelName, templateName, index)` | `noteTypes.editStructure` | moveTemplate by templateName, target index. | null. | completed | — |
| `modelTemplateAdd(modelName, template)` | `noteTypes.get`; `noteTypes.editStructure` | template Name/Front/Back → config; existing name uses updateTemplate, otherwise addTemplate. | null. | completed | I15: persist both paths once; no cached-only update. |
| `modelTemplateRemove(modelName, templateName)` | `noteTypes.editStructure` | removeTemplate by templateName. | null. | completed | — |
| `modelFieldRename(modelName, oldFieldName, newFieldName)` | `noteTypes.editStructure` | updateField by oldFieldName with patch.name=newFieldName. | null. | completed | — |
| `modelFieldReposition(modelName, fieldName, index)` | `noteTypes.editStructure` | moveField by fieldName, target index. | null. | completed | — |
| `modelFieldAdd(modelName, fieldName, index=None)` | `noteTypes.get`; `noteTypes.editStructure` | Add only when absent; if index supplied, move existing/new field to index. Default insertion is append. | null. | completed | — |
| `modelFieldRemove(modelName, fieldName)` | `noteTypes.editStructure` | removeField by fieldName. | null. | completed | — |
| `modelFieldSetFont(modelName, fieldName, font)` | `noteTypes.editStructure` | updateField patch.fontFamily=font; require string. | null. | completed | — |
| `modelFieldSetFontSize(modelName, fieldName, fontSize)` | `noteTypes.editStructure` | updateField patch.fontSize=fontSize; validate native positive integer. | null. | completed | — |
| `modelFieldSetDescription(modelName, fieldName, description)` | `noteTypes.editStructure` | updateField patch.description=description. | true; false when capability is absent. | completed | — |
| `deckNameFromId(deckId)` | `decks.get` | deckId → id reference. | Name string. | completed | I18: nonexistent ID raises without Default fallback. |
| `findNotes(query=None)` | `notes.search` | query=None returns []; otherwise exhaust all pages. | Array of numeric note IDs. | completed | — |
| `findCards(query=None)` | `cards.search` | query=None returns []; otherwise exhaust pages. | Numeric card ID array. | completed | — |
| `cardsInfo(cards)` | `cards.getMany`; `cards.render`; `notes.get`; `noteTypes.get`; `scheduling.predict` | Compose old card view from shared service records; convert typed due back to native stored integer. | Legacy card records including cardId/fields/fieldOrder/question/answer/modelName/ord/deckName/css/factor/interval/note/type/queue/due/reps/lapses/left/mod/nextReviews/flags; missing card is {}. | completed | I08: nextReviews remains labelled/default scheduler prediction, not retained reviewer custom states. |
| `cardsModTime(cards)` | `cards.getMany` | cards → ids; modifiedAt → Unix seconds. | Array of {cardId, mod}; missing card is {}. | completed | — |
| `forgetCards(cards)` | `scheduling.reset` | restorePosition=true, resetCounts=false, log=true. | null. | completed | — |
| `relearnCards(cards)` | `scheduling.predict`; `scheduling.answer` | Preflight all IDs as unsuspended/unburied, nonfiltered review cards; get fresh states and answer again with elapsedMs=0. | null; top-level error for incompatible state. | completed | I03: real failed review increments lapse/review history and uses native FSRS transitions; no raw queue writes. |
| `answerCards(answers)` | `scheduling.predict`; `scheduling.answerMany`; `reviewer.answer` | Translate cardId and ease 1/2/3/4 → again/hard/good/easy; acquire tokens per item at execution; active GUI card uses retained reviewer states and requires answer side. | Boolean array; missing cards are false; invalid ease/state produces legacy error. | final answers | I04: completion/notifications awaited; reviewer veto is not success. |
| `cardReviews(deck, startID)` | `reviews.list` | deck → name reference; startID=0 omits afterId, otherwise afterId string; membership=current, includeManual=true; exhaust pages. | Arrays [id,cid,usn,ease,ivl,lastIvl,factor,time,type] with numeric legacy encodings. | completed | I18: missing deck errors without creation; deterministic ID order; factor meaning preserved. |
| `getReviewsOfCards(cards)` | `reviews.list` | cards → cardIds; includeManual=true; exhaust pages then group. | Object keyed by numeric card-ID strings with arrays of {id,usn,ease,ivl,lastIvl,factor,time,type}; no history yields []. | completed | — |
| `setDueDate(cards, days)` | `scheduling.setDueDate` | cards → cardIds; preserve native days string. | true on successful completion; item failure becomes legacy error. | completed | — |
| `reloadCollection()` | `collection.refresh` | target=cachesAndWindows. | null. | completed | I21: actual cache/window refresh, never collection reopen or no-op reset. |
| `getLatestReviewID(deck)` | `reviews.getLatestId` | deck → name reference; membership=current. | Numeric ID, or 0 for null. | completed | I18: no read-side deck creation. |
| `insertReviews(reviews)` | `advanced.reviews.import` | Rows [id,cid,usn,ease,ivl,lastIvl,factor,time,type] → typed history; reject malformed rows, ignore client usn and use local -1; signed interval units converted explicitly. | null after import final; empty input is no-op. | final operation | I17: validated/bound/transactional history-only import; clears undo; no implicit card answer/reschedule. |
| `notesInfo(notes=None, query=None)` | `notes.search`; `notes.getMany`; `noteTypes.get`; `collection.get` | Require notes or query; query takes precedence when both supplied; exhaust search pages, then get and project. | Legacy note records with noteId/profile/tags/fields {value,order}/modelName/mod/cards; missing note is {}. | completed | I22: existing cardless note returns cards: []. |
| `notesModTime(notes)` | `notes.getMany` | notes → ids; modifiedAt → Unix seconds. | Array of {noteId, mod}; missing note is {}. | completed | — |
| `deleteNotes(notes)` | `notes.delete` | notes → ids; ignore notFound item errors as native legacy removal does. | null. | completed | — |
| `removeEmptyNotes()` | `notes.findEmpty`; `noteTypes.deleteUnused` | Do not run either operation automatically; caller must migrate to explicit criteria/resource IDs. | Legacy error. | completed | I16: always compatibilityError; unused note types and notes remain intact. |
| `cardsToNotes(cards)` | `cards.getMany` | cards → ids; omit missing cards; deduplicate note IDs preserving first appearance. | Array of numeric note IDs. | completed | — |
| `guiBrowse(query=None, reorderCards=None)` | `browser.open`; `cards.search` | query optional; reorderCards.columnId/order → sort.column/direction. Preserve browser query if omitted; query=None result remains []. | Numeric card IDs from the provided query after exhausting search pages. | browser ready | I23: preserve explicit sort direction regardless of selected/default column. |
| `guiEditNote(note)` | `editors.openNote` | note → noteId. | null when accepted. | accepted; multi awaits editor ready | — |
| `guiSelectNote(note)` | `browser.select` | Despite its name, note is a CARD ID; cardIds=[note]. | Boolean; false if browser closed. | selection final | Preserve documented/deprecated card-ID meaning; do not reinterpret as note ID. |
| `guiSelectCard(card)` | `browser.select` | cardIds=[card]. | Boolean; false if browser closed. | selection final | — |
| `guiSelectedNotes()` | `browser.getSelection` | No arguments. | Numeric selected note IDs; closed browser yields []. | completed | — |
| `guiAddNoteSetData(note, append=False)` | `editors.updateDraft`; `media.store` | Find actual visible Add variant; translate note deck/model/fields/tags and inline media; append selects append mode. | true after draft completion; closed dialog retains {error: "Add Note dialog is not open", code: 1}. | draft final | I06/I07: explicit deck wins after note type; both editor variants, dirty-content conflicts. |
| `guiAddCards(note=None)` | `editors.openAdd`; `media.store` | Optional note translates draft values without duplicate eligibility checks; populate chosen deck/type together. | Numeric 0 for unsaved draft, explicitly not a future persisted note ID. | accepted; multi awaits draft ready | I05/I07: active editor variant; reject dirty-draft replacement rather than wrong-target saves. |
| `guiReviewActive()` | `reviewer.get` | No arguments. | active boolean. | completed | — |
| `guiCurrentCard()` | `reviewer.get`; `notes.get`; `noteTypes.get` | Require active reviewer; compose legacy rendered/field/deck/template record from retained active states. | Legacy current-card object with button numbers 1–4 and nextReviews labels in offered-button order. | completed | I08: prediction labels match reviewer custom states, not fresh defaults. |
| `guiStartCardTimer()` | `reviewer.get`; `reviewer.startTimer` | Acquire current token; inactive returns false. | Boolean. | completed | — |
| `guiShowQuestion()` | `reviewer.get`; `reviewer.showQuestion` | Acquire current token; inactive returns false. | Boolean. | completed | — |
| `guiShowAnswer()` | `reviewer.get`; `reviewer.showAnswer` | Acquire current token; inactive returns false. | Boolean. | completed | — |
| `guiAnswerCard(ease)` | `reviewer.get`; `reviewer.answer` | ease → offered rating; inactive/not answer side/invalid button returns false. | true when answer is accepted; false for rejected preconditions. | accepted; multi awaits final | Hook veto/async failure is a terminal internal failure; multi must observe it before proceeding. |
| `guiPlayAudio()` | `reviewer.get`; `reviewer.playAudio` | Acquire current token; inactive returns false. | Boolean. | completed | — |
| `guiUndo()` | `collection.undo` | No arguments. | true when accepted. | accepted; multi awaits final | — |
| `guiDeckOverview(name)` | `application.navigate` | view=deckOverview; deck={name}; missing deck returns false. | Boolean. | navigation final | — |
| `guiDeckBrowser()` | `application.navigate` | view=deckBrowser. | null. | navigation final | — |
| `guiDeckReview(name)` | `application.navigate` | view=review; deck={name}; missing deck returns false. | Boolean. | navigation final | — |
| `guiImportFile(path=None)` | `application.importFile` | Omit path when null for chooser, otherwise path → path. | null when accepted. | accepted; multi awaits import final | — |
| `guiExitAnki()` | `application.exit` | No arguments; retain close callback until fired. | null after response is flushed, then request native close. | accepted; process may exit | Do not claim actual shutdown completion; user can cancel native close. |
| `guiCheckDatabase()` | `collection.checkIntegrity` | No arguments. | true when accepted. | accepted; multi awaits final | — |
| `addNotes(notes)` | `notes.createMany`; `media.store` | Translate note(s) using the common note/media policy below. Set atomic=true. | Array of numeric IDs; top-level legacy error on any failed atomic batch. | completed | I12–I14: native validation; pure canAdd checks; no compensating deletion; media guarantee is separate. |
| `canAddNotes(notes)` | `notes.validateMany` | Translate note(s) using the common note/media policy below. | Array of booleans. | completed | I12–I14: native validation; pure canAdd checks; no compensating deletion; media guarantee is separate. |
| `canAddNotesWithErrorDetail(notes)` | `notes.validateMany` | Translate note(s) using the common note/media policy below. | Array of canAdd/error objects. | completed | I12–I14: native validation; pure canAdd checks; no compensating deletion; media guarantee is separate. |
| `exportPackage(deck, path, includeSched=False)` | `packages.export` | deck → name reference; path unchanged; includeSched → includeScheduling; missing deck returns false. | true after export; false for missing deck. | final operation | — |
| `importPackage(path)` | `packages.import` | path unchanged. | true after import; false when collection absent as legacy. | final operation | — |
| `apiReflect(scopes=None, actions=None)` | `api.describe` | Validate scopes as an array and actions as optional array exactly as legacy. Reflect legacy registry, filtering optional action names. | {scopes: ["actions"], actions: [...]} when requested; otherwise {scopes: []}. | completed | — |

## Integration issue dispositions and required regressions

These are design fixes and future test requirements, not completed runtime fixes.
L01–L04 identify the additional lifecycle bullets in INTEGRATION_ISSUES.md.

| Finding | Owner | Required behavior | Acceptance scenario |
| --- | --- | --- | --- |
| I01 | notes.planConversion / notes.convert | Use native conversion with explicit maps; omitted tags preserved. | Two-to-one templates, reordered templates, normal/cloze, ambiguous legacy map, omitted tags, undo and sync. |
| I02 | cards.move | Use Collection.set_deck and its returned changes. | Different learning steps/FSRS presets, moving out of filtered deck, reject filtered target. |
| I03 | scheduling.answer | Legacy relearn is a real Again review; reject incompatible states. | Review, learning, suspended, filtered and FSRS cards; correct due/steps/lapses/history/mod/usn and incremental sync. |
| I04 | All collection write services / editor coordinator | Native serialized ops; completion follows post-write notifications; dirty editors conflict. | Browser/custom/Svelte editor/reviewer open, pending JS edits, clean reload, next request, undo menu, no silent overwrite. |
| I05 | editors.openAdd | Coordinated note/deck setter; unsaved draft has null new ID, legacy 0. | Existing Add deck A with requested B; differing type; actual saved card deck and no fabricated note ID. |
| I06 | editors.updateDraft | Apply type before explicit deck through dialog adapter. | New type default deck differs from requested deck; explicit deck wins. |
| I07 | Editor variant adapters | Target actual visible legacy/Svelte Add editor; discovery advertises support. | Both experiment settings; no accidental second legacy dialog; correct async draft state. |
| I08 | reviewer.get / scheduling.predict | Retained GUI custom states vs labelled default predictions. | Custom scheduling changes one interval; current-card labels/answer agree; stored-card prediction remains separately identified. |
| I09 | statistics services | Use native stats filtering/day aggregation. | Counts unchanged by manual reset/due changes; rollover, timezone and DST boundaries. |
| I10 | scheduling.getDue | Queue-aware current due/availability; explicit learn-ahead. | Suspended/buried new and learning, day learning, filtered preview, manual reschedule, no history. |
| I11 | scheduling.get / reviews.list | Separate current interval and ordered historical intervals with units. | No-history review, manual due change, out-of-order imported IDs, learning/relearning history and complete legacy projection. |
| I12 | notes.validate / note mutation preflight | Native HTML/NFC/cloze checks plus scoped full-value duplicate comparison and empty-question detection. | HTML-only/NFC-equivalent content, all cloze error reasons, filtered home decks, required empty second field, checksum collision. |
| I13 | notes.validate / validateMany | No media acquisition, write, replacement or trash during prediction. | All canAdd variants with URL/path/data and duplicate/empty rejection; unchanged files, trash, defaults and undo. |
| I14 | notes.createMany atomic / legacy staging | Native batch transaction; one undo; separately recover media changes. | Valid+invalid note, within-batch duplicates, replaced media, defaults, backend failure, cleanup failure, undo and sync. |
| I15 | noteTypes.editStructure | Persist existing-template update and new-template insertion through the same path. | Python reread, backend render, cache invalidation, close/reopen and existing-card identity. |
| I16 | Legacy compatibilityError / notes.findEmpty / noteTypes.deleteUnused | Never infer destructive cleanup from removeEmptyNotes. | Old call errors without mutation; unused custom types survive; explicit criteria distinguish empty fields/questions/cardless notes. |
| I17 | advanced.reviews.import | Typed whole-batch validation, bound transaction, local unsynced metadata, explicit history-only semantics. | Malformed/injection-like rows, duplicate IDs, rollback, undo clearing, post-write notifications, upload, FSRS memory unchanged until explicit recompute. |
| I18 | Reference resolution / read services | No implicit deck creation or Default fallback. | Misspelled name, nonexistent deck/card ID, unchanged deck count across stats/history/lookups. |
| I19 | collection.sync | One coordinated background/UI sync; operation completion covers requested media stage. | Normal/no-change, endpoint migration, full-sync choice, auth failure, cancel, media failure, responsive UI, no duplicate sync. |
| I20 | deckPresets.update / assign | Coordinated update requests preserve globals and native step/order/FSRS dependent changes. | Learning step changes, preset assignment, FSRS parameters/retention with both reschedule choices, new order, untouched globals/custom scheduler. |
| I21 | collection.refresh | Explicit windows or cachesAndWindows; never deprecated Collection.reset. | Stale browser refresh and model cache invalidation independently; no profile/session change. |
| I22 | notes.getMany / cards.setSuspended | Cardless notes return empty cards; no request-list mutation; corrected unsuspend boolean. | Cardless note, repeated IDs, multiple already suspended/restored cards; idempotent changed=false; legacy envelopes. |
| I23 | browser.open | Explicit direction applied after column selection. | Ascending/descending numeric column both newly selected and already active. |
| L01 | application.exit | Flush acceptance before retained close callback. | Response received, real close occurs, user cancellation leaves app open; exit inside legacy multi is last. |
| L02 | profiles.switch | Native completion callback and session invalidation, no visibility polling. | Cancel close/sync; subsequent requests during switch; destination ready; queued old-session work rejected; multi rebinds only on success. |
| L03 | reviewer.answer / collection.undo / checkIntegrity / application.importFile | Track actual async success, cancellation and reviewer veto. | Production background timing, hook veto, cancelled import/check/undo, barriers and standalone accepted response compatibility. |
| L04 | Editor history | Scope history to profile session and clear on unload. | Different profiles/imported copies with matching note IDs; no cross-profile navigation. |

## Implementation gates

- Require one mapping per decorated action and each versioned alias; compare exact
  parameter defaults against source without importing the plugin. Changes to the source
  must update this matrix and the coverage check.
- Add legacy request/result fixtures from tests and README, preserving bare v4
  successes and error envelopes across versions. Document all intentional exceptions
  above in the release notes before runtime rollout.
- Check every mapped target exists in the v1 registry and every finding/lifecycle
  risk has a regression. Known unavailable advanced/editor capabilities must return
  explicit unsupportedCapability/legacy errors, not silently bypass services.
- Rebuild Anki integration tests in temporary profiles; baseline tests need real
  GUI/async execution and cannot be replaced by stand-ins. Do not package with the
  destructive package.sh as a validation step.

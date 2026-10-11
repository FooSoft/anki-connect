# Anki-Connect legacy API

This is the compatibility reference for existing Anki-Connect applications.
The root endpoint and API version 6 remain available alongside the new API.
Existing clients keep their action names, parameter names, authentication, and
response envelopes. New integrations should use [API v1](API_V1.md).

## Quick start

Anki Desktop must be running with the add-on enabled. Send UTF-8 JSON to
`POST http://127.0.0.1:8765/`:

```bash
curl --request POST http://127.0.0.1:8765/ \
  --header 'Content-Type: application/json' \
  --data '{"action":"deckNames","version":6,"params":{}}'
```

```json
{"result":["Default"],"error":null}
```

Each request has an `action`, `version`, optional `params` object, and optional
`key`. Use version 6 for current clients. Legacy entity IDs are JSON numbers,
unlike v1's decimal strings. Paths refer to the machine running Anki.

### Python client

```python
import json
import urllib.request

ENDPOINT = "http://127.0.0.1:8765/"
API_KEY = None  # Set to the configured apiKey, if enabled.


def invoke(action, **params):
    body = {"action": action, "version": 6, "params": params}
    if API_KEY is not None:
        body["key"] = API_KEY
    request = urllib.request.Request(
        ENDPOINT, json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request) as response:
        reply = json.load(response)
    if reply["error"] is not None:
        raise RuntimeError(reply["error"])
    return reply["result"]


print(invoke("deckNames"))
```

### JavaScript client

```javascript
const endpoint = "http://127.0.0.1:8765/";
const apiKey = null; // Set to the configured apiKey, if enabled.

async function invoke(action, params = {}) {
  const body = {action, version: 6, params};
  if (apiKey !== null) body.key = apiKey;
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const reply = await response.json();
  if (reply.error !== null) throw new Error(reply.error);
  return reply.result;
}

async function main() {
  console.log(await invoke("deckNames"));
}
main().catch(console.error);
```

## Authentication and response versions

Set `apiKey` in Anki's add-on configuration to enable authentication, then include
that value as the request body's `key`. `requestPermission` is exempt; its returned
`requireApikey` indicates whether a key is required, but it never returns the key.
Origin checks apply separately using the configured origin lists.

For versions 5 and 6, successful requests return `{"result":...,"error":null}`.
Failures return `{"result":null,"error":"message"}`. Error messages are strings;
applications should not depend on exact wording.

Omitting `version` selects version 4. Successful calls at version 4 or below
return a bare result, without the envelope. Exceptions at every version retain
the `result`/`error` envelope. Prefer an explicit version 6.

## Compatibility and completion

The legacy API remains supported; migrating an existing application is optional.
Both endpoints use the same collection services. Some unsafe historical behavior
now fails explicitly or follows corrected native behavior:

- Arbitrary card database writes are restricted. Use supported flags, moves,
  scheduling commands, or validated metadata instead.
- `removeEmptyNotes` returns a compatibility error. Use v1 `notes.findEmpty` with
  an explicit criterion and delete specific note IDs after reviewing the result.
- Unsupported preset changes fail instead of being silently ignored.
- Affected open editors must be closed before collection writes, even when saved.
- `relearnCards` performs real failed reviews and requires compatible review cards.
  It changes lapse counts and history.

The action entries describe their results and completion timing. **Accepted**
means work has started; later failure or cancellation is visible in Anki, rather
than retroactively changing the HTTP response. Use v1 operation handles when your
application needs to observe final completion.

`multi` executes items in order and waits for their final outcomes, including
accepted GUI work. It continues after item errors and preserves each item's own
version and key; the outer request does not supply missing credentials or versions
to children. It provides no database or media transaction. Profile switching is
allowed; subsequent actions use the destination after a successful switch.
Nesting is limited to 16 levels and 100 total request nodes, counting containers.
`guiExitAnki` must be the last executable item, including nested items.

Each action below links to its v1 equivalent. Native tests cover both protocols;
GUI and network behavior also require separate integration testing.

## Action reference

Each example is a complete request body. Save it as `request.json` and send it with:

```bash
curl --request POST http://127.0.0.1:8765/ \
  --header 'Content-Type: application/json' --data-binary @request.json
```

Add `"key":"your-configured-key"` to the body when authentication is enabled.
Replace sample IDs, names, paths, and URLs with real resources. Examples are
individual calls, rather than a sequence to execute. Actions can change or delete
collection data; read their behavior before using them. The parameter signatures
show every accepted argument and its default. Media data is base64 encoded.

- **Card:** [getEaseFactors](#geteasefactors), [setEaseFactors](#seteasefactors), [setSpecificValueOfCard](#setspecificvalueofcard), [suspend](#suspend), [unsuspend](#unsuspend), [suspended](#suspended), [areSuspended](#aresuspended), [areDue](#aredue), [getIntervals](#getintervals), [findCards](#findcards), [cardsToNotes](#cardstonotes), [cardsModTime](#cardsmodtime), [cardsInfo](#cardsinfo), [forgetCards](#forgetcards), [relearnCards](#relearncards), [answerCards](#answercards), [setDueDate](#setduedate).
- **Deck:** [deckNames](#decknames), [deckNamesAndIds](#decknamesandids), [getDecks](#getdecks), [createDeck](#createdeck), [changeDeck](#changedeck), [deleteDecks](#deletedecks), [getDeckConfig](#getdeckconfig), [saveDeckConfig](#savedeckconfig), [setDeckConfigId](#setdeckconfigid), [cloneDeckConfigId](#clonedeckconfigid), [removeDeckConfigId](#removedeckconfigid), [getDeckStats](#getdeckstats), [deckNameFromId](#decknamefromid).
- **Graphical:** [guiBrowse](#guibrowse), [guiSelectCard](#guiselectcard), [guiSelectedNotes](#guiselectednotes), [guiAddCards](#guiaddcards), [guiEditNote](#guieditnote), [guiAddNoteSetData](#guiaddnotesetdata), [guiCurrentCard](#guicurrentcard), [guiStartCardTimer](#guistartcardtimer), [guiShowQuestion](#guishowquestion), [guiShowAnswer](#guishowanswer), [guiAnswerCard](#guianswercard), [guiUndo](#guiundo), [guiDeckOverview](#guideckoverview), [guiDeckBrowser](#guideckbrowser), [guiDeckReview](#guideckreview), [guiImportFile](#guiimportfile), [guiExitAnki](#guiexitanki), [guiCheckDatabase](#guicheckdatabase), [guiPlayAudio](#guiplayaudio), [guiSelectNote](#guiselectnote), [guiReviewActive](#guireviewactive).
- **Media:** [storeMediaFile](#storemediafile), [retrieveMediaFile](#retrievemediafile), [getMediaFilesNames](#getmediafilesnames), [getMediaDirPath](#getmediadirpath), [deleteMediaFile](#deletemediafile).
- **Miscellaneous:** [requestPermission](#requestpermission), [version](#version), [apiReflect](#apireflect), [sync](#sync), [getProfiles](#getprofiles), [getActiveProfile](#getactiveprofile), [loadProfile](#loadprofile), [multi](#multi), [exportPackage](#exportpackage), [importPackage](#importpackage), [reloadCollection](#reloadcollection).
- **Model:** [modelNames](#modelnames), [modelNamesAndIds](#modelnamesandids), [findModelsById](#findmodelsbyid), [findModelsByName](#findmodelsbyname), [modelFieldNames](#modelfieldnames), [modelFieldDescriptions](#modelfielddescriptions), [modelFieldFonts](#modelfieldfonts), [modelFieldsOnTemplates](#modelfieldsontemplates), [createModel](#createmodel), [modelTemplates](#modeltemplates), [modelStyling](#modelstyling), [updateModelTemplates](#updatemodeltemplates), [updateModelStyling](#updatemodelstyling), [findAndReplaceInModels](#findandreplaceinmodels), [modelTemplateRename](#modeltemplaterename), [modelTemplateReposition](#modeltemplatereposition), [modelTemplateAdd](#modeltemplateadd), [modelTemplateRemove](#modeltemplateremove), [modelFieldRename](#modelfieldrename), [modelFieldReposition](#modelfieldreposition), [modelFieldAdd](#modelfieldadd), [modelFieldRemove](#modelfieldremove), [modelFieldSetFont](#modelfieldsetfont), [modelFieldSetFontSize](#modelfieldsetfontsize), [modelFieldSetDescription](#modelfieldsetdescription), [modelNameFromId](#modelnamefromid).
- **Note:** [addNote](#addnote), [addNotes](#addnotes), [canAddNotes](#canaddnotes), [canAddNotesWithErrorDetail](#canaddnoteswitherrordetail), [updateNoteFields](#updatenotefields), [updateNote](#updatenote), [updateNoteModel](#updatenotemodel), [updateNoteTags](#updatenotetags), [getNoteTags](#getnotetags), [addTags](#addtags), [removeTags](#removetags), [getTags](#gettags), [clearUnusedTags](#clearunusedtags), [replaceTags](#replacetags), [replaceTagsInAllNotes](#replacetagsinallnotes), [findNotes](#findnotes), [notesInfo](#notesinfo), [notesModTime](#notesmodtime), [deleteNotes](#deletenotes), [removeEmptyNotes](#removeemptynotes), [canAddNote](#canaddnote), [canAddNoteWithErrorDetail](#canaddnotewitherrordetail).
- **Statistic:** [getNumCardsReviewedToday](#getnumcardsreviewedtoday), [getNumCardsReviewedByDay](#getnumcardsreviewedbyday), [getCollectionStatsHTML](#getcollectionstatshtml), [cardReviews](#cardreviews), [getReviewsOfCards](#getreviewsofcards), [getLatestReviewID](#getlatestreviewid), [insertReviews](#insertreviews).

### Note input and inline media

Creation uses `deckName`, `modelName`, `fields` (HTML strings), and optional `tags`.
`options.allowDuplicate` defaults to false. `options.duplicateScope` accepts
`collection` (default) or `deck`; other values fail. For deck scope,
`duplicateScopeOptions.deckName` chooses the duplicate-check deck, otherwise the
creation deck is used. `checkChildren` and `checkAllModels` default to false.

The optional `audio`, `video`, and `picture` properties accept one media object or
an array. Each object needs `filename` and exactly one of `data`, `path`, or `url`.
Its `fields` array names fields to append the reference to. `skipHash` is an
optional MD5 digest of incoming bytes to skip. Acquisitions happen before owned
media writes; media rollback is separate from the collection transaction.
Eligibility checks do not download or write files.

## Card Actions

### `getEaseFactors`

Return each card’s stored SM-2 ease factor in permille, in input order.

**Parameters:** `getEaseFactors(cards)`

**Returns:** Integer array in input order.

**Completion:** completed.

**v1 equivalent:** [cards.getMany](API_V1.md#cardsgetmany).

**Example request**

```json
{
  "action": "getEaseFactors",
  "version": 6,
  "params": {
    "cards": [
      1483959291685,
      1483959293217
    ]
  }
}
```

### `setEaseFactors`

Set SM-2 ease factors in permille, one value per card. Returns a boolean array in input order. This does not set FSRS difficulty.

**Parameters:** `setEaseFactors(cards, easeFactors)`

**Returns:** Per-card booleans; false for missing or rejected cards.

**Completion:** completed.

**Behavior:** Reject mismatched lengths before writes; native undo/notifications replace skip_undo_entry.

**v1 equivalent:** [advanced.cards.update](API_V1.md#advancedcardsupdate).

**Example request**

```json
{
  "action": "setEaseFactors",
  "version": 6,
  "params": {
    "cards": [
      1483959291685,
      1483959293217
    ],
    "easeFactors": [
      4100,
      3900
    ]
  }
}
```

### `setSpecificValueOfCard`

Update supported card properties. `card` is a scalar ID; `keys` and `newValues` must be equal-length arrays with no duplicate keys. Supported keys are `flags`, `did`, `factor`, `ivl`, `reps`, `lapses`, and `custom_data`. `did`, `ivl`, `reps`, and `lapses` require `warning_check=true`. Flags and deck moves cannot be combined with each other or metadata patches. Raw ownership, queue, type, due, and sync metadata writes are rejected.

**Parameters:** `setSpecificValueOfCard(card, keys, newValues, warning_check=False)`

**Returns:** `false` for invalid shape or protected writes without `warning_check`; `[true]` on success; `[[false, message]]` on native failure.

**Completion:** completed.

**Behavior:** warning_check=true does not permit identity/sync/queue corruption; return compatibilityError for untranslatable protected writes.

**v1 equivalent:** [advanced.cards.update](API_V1.md#advancedcardsupdate), [cards.move](API_V1.md#cardsmove), [cards.setFlags](API_V1.md#cardssetflags).

**Example request**

```json
{
  "action": "setSpecificValueOfCard",
  "version": 6,
  "params": {
    "card": 1700000000002,
    "keys": [
      "flags"
    ],
    "newValues": [
      "1"
    ]
  }
}
```

### `suspend`

Suspend cards by card ID; returns `true` if successful (at least one card wasn't already suspended) or `false`
otherwise.

**Parameters:** `suspend(cards, suspend=True)`

**Returns:** true if any distinct card changed, else false.

**Completion:** completed.

**Behavior:** do not mutate request list while iterating.

**v1 equivalent:** [cards.setSuspended](API_V1.md#cardssetsuspended).

**Example request**

```json
{
  "action": "suspend",
  "version": 6,
  "params": {
    "cards": [
      1483959291685,
      1483959293217
    ]
  }
}
```

### `unsuspend`

Unsuspend cards by card ID; returns `true` if successful (at least one card was previously suspended) or `false`
otherwise.

**Parameters:** `unsuspend(cards)`

**Returns:** true if any distinct card changed, else false.

**Completion:** completed.

**Behavior:** Returns a boolean; the historical implementation returned null.

**v1 equivalent:** [cards.setSuspended](API_V1.md#cardssetsuspended).

**Example request**

```json
{
  "action": "unsuspend",
  "version": 6,
  "params": {
    "cards": [
      1483959291685,
      1483959293217
    ]
  }
}
```

### `suspended`

Check if card is suspended by its ID. Returns `true` if suspended, `false` otherwise.

**Parameters:** `suspended(card)`

**Returns:** Boolean.

**Completion:** completed.

**v1 equivalent:** [cards.get](API_V1.md#cardsget).

**Example request**

```json
{
  "action": "suspended",
  "version": 6,
  "params": {
    "card": 1483959293217
  }
}
```

### `areSuspended`

Returns an array indicating whether each of the given cards is suspended (in the same order). If card doesn't
exist returns `null`.

**Parameters:** `areSuspended(cards)`

**Returns:** Array of booleans/null.

**Completion:** completed.

**v1 equivalent:** [cards.getMany](API_V1.md#cardsgetmany).

**Example request**

```json
{
  "action": "areSuspended",
  "version": 6,
  "params": {
    "cards": [
      1483959291685,
      1483959293217,
      1234567891234
    ]
  }
}
```

### `areDue`

Return whether each card is currently due using native queue timing. Unsuspended, unburied new cards are available; suspended and buried cards are not due.

**Parameters:** `areDue(cards)`

**Returns:** Boolean array; missing card raises.

**Completion:** completed.

**Behavior:** queue-aware, no revlog dependency or suspended-new positives.

**v1 equivalent:** [scheduling.getDue](API_V1.md#schedulinggetdue).

**Example request**

```json
{
  "action": "areDue",
  "version": 6,
  "params": {
    "cards": [
      1483959291685,
      1483959293217
    ]
  }
}
```

### `getIntervals`

Return current scheduling intervals, or ordered nonmanual history when `complete=true`. Negative values represent seconds and positive values represent days. New cards return scalar `0`, including in complete mode.

**Parameters:** `getIntervals(cards, complete=False)`

**Returns:** Signed legacy values (negative seconds, positive days); complete history arrays; new cards remain scalar 0.

**Completion:** completed.

**Behavior:** explicitly current state vs ordered history; missing history returns [] in complete mode instead of IndexError.

**v1 equivalent:** [scheduling.get](API_V1.md#schedulingget), [reviews.list](API_V1.md#reviewslist).

**Example request**

```json
{
  "action": "getIntervals",
  "version": 6,
  "params": {
    "cards": [
      1502298033753,
      1502298036657
    ]
  }
}
```

### `findCards`

Returns an array of card IDs for a given query. Functionally identical to `guiBrowse` but doesn't use the GUI for
better performance.

**Parameters:** `findCards(query=None)`

**Returns:** Numeric card ID array.

**Completion:** completed.

**v1 equivalent:** [cards.search](API_V1.md#cardssearch).

**Example request**

```json
{
  "action": "findCards",
  "version": 6,
  "params": {
    "query": "deck:current"
  }
}
```

### `cardsToNotes`

Return distinct note IDs for the supplied cards, preserving first appearance and omitting missing cards.

**Parameters:** `cardsToNotes(cards)`

**Returns:** Array of numeric note IDs.

**Completion:** completed.

**v1 equivalent:** [cards.getMany](API_V1.md#cardsgetmany).

**Example request**

```json
{
  "action": "cardsToNotes",
  "version": 6,
  "params": {
    "cards": [
      1502098034045,
      1502098034048,
      1502298033753
    ]
  }
}
```

### `cardsModTime`

Return each card’s modification time in Unix seconds. Missing cards produce empty objects.

**Parameters:** `cardsModTime(cards)`

**Returns:** Array of {cardId, mod}; missing card is {}.

**Completion:** completed.

**v1 equivalent:** [cards.getMany](API_V1.md#cardsgetmany).

**Example request**

```json
{
  "action": "cardsModTime",
  "version": 6,
  "params": {
    "cards": [
      1498938915662,
      1502098034048
    ]
  }
}
```

### `cardsInfo`

Returns a list of objects containing for each card ID the card fields, front and back sides including CSS, note
type, the note that the card belongs to, and deck name, last modification timestamp as well as ease and interval.

**Parameters:** `cardsInfo(cards)`

**Returns:** Legacy card records including cardId/fields/fieldOrder/question/answer/modelName/ord/deckName/css/factor/interval/note/type/queue/due/reps/lapses/left/mod/nextReviews/flags; missing card is {}.

**Completion:** completed.

**Behavior:** nextReviews remains labelled/default scheduler prediction, not retained reviewer custom states.

**v1 equivalent:** [cards.getMany](API_V1.md#cardsgetmany), [cards.render](API_V1.md#cardsrender), [notes.get](API_V1.md#notesget), [noteTypes.get](API_V1.md#notetypesget), [scheduling.predict](API_V1.md#schedulingpredict).

**Example request**

```json
{
  "action": "cardsInfo",
  "version": 6,
  "params": {
    "cards": [
      1498938915662,
      1502098034048
    ]
  }
}
```

### `forgetCards`

Forget cards, making the cards new again.

**Parameters:** `forgetCards(cards)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [scheduling.reset](API_V1.md#schedulingreset).

**Example request**

```json
{
  "action": "forgetCards",
  "version": 6,
  "params": {
    "cards": [
      1498938915662,
      1502098034048
    ]
  }
}
```

### `relearnCards`

Perform an Again answer on each supplied card using the native scheduler. All cards must be unsuspended, unburied, nonfiltered review cards. This records failed reviews and updates lapse counts; incompatible input is rejected before work.

**Parameters:** `relearnCards(cards)`

**Returns:** null; top-level error for incompatible state.

**Completion:** completed.

**Behavior:** real failed review increments lapse/review history and uses native FSRS transitions; no raw queue writes.

**v1 equivalent:** [scheduling.predict](API_V1.md#schedulingpredict), [scheduling.answer](API_V1.md#schedulinganswer).

**Example request**

```json
{
  "action": "relearnCards",
  "version": 6,
  "params": {
    "cards": [
      1498938915662,
      1502098034048
    ]
  }
}
```

### `answerCards`

Answer cards using ease `1` (Again), `2` (Hard), `3` (Good), or `4` (Easy). Returns one boolean per answer. For the active GUI card, the answer side must be shown and native reviewer states are used.

**Parameters:** `answerCards(answers)`

**Returns:** Boolean array; missing cards are false; invalid ease/state produces legacy error.

**Completion:** final answers.

**Behavior:** completion/notifications awaited; reviewer veto is not success.

**v1 equivalent:** [scheduling.predict](API_V1.md#schedulingpredict), [scheduling.answerMany](API_V1.md#schedulinganswermany), [reviewer.answer](API_V1.md#revieweranswer).

**Example request**

```json
{
  "action": "answerCards",
  "version": 6,
  "params": {
    "answers": [
      {
        "cardId": 1498938915662,
        "ease": 2
      },
      {
        "cardId": 1502098034048,
        "ease": 4
      }
    ]
  }
}
```

### `setDueDate`

Set native due dates using Anki’s days syntax: `0` means today, `1!` means tomorrow with interval reset to one day, and `3-7` chooses a day in that range. New cards become review cards.

**Parameters:** `setDueDate(cards, days)`

**Returns:** true on successful completion; item failure becomes legacy error.

**Completion:** completed.

**v1 equivalent:** [scheduling.setDueDate](API_V1.md#schedulingsetduedate).

**Example request**

```json
{
  "action": "setDueDate",
  "version": 6,
  "params": {
    "cards": [
      1498938915662,
      1502098034048
    ],
    "days": "3-7"
  }
}
```

## Deck Actions

### `deckNames`

Gets the complete list of deck names for the current user.

**Parameters:** `deckNames()`

**Returns:** Array of names.

**Completion:** completed.

**v1 equivalent:** [decks.list](API_V1.md#deckslist).

**Example request**

```json
{
  "action": "deckNames",
  "version": 6,
  "params": {}
}
```

### `deckNamesAndIds`

Gets the complete list of deck names and their respective IDs for the current user.

**Parameters:** `deckNamesAndIds()`

**Returns:** Object mapping name to numeric ID.

**Completion:** completed.

**v1 equivalent:** [decks.list](API_V1.md#deckslist).

**Example request**

```json
{
  "action": "deckNamesAndIds",
  "version": 6,
  "params": {}
}
```

### `getDecks`

Accepts an array of card IDs and returns an object with each deck name as a key, and its value an array of the given
cards which belong to it.

**Parameters:** `getDecks(cards)`

**Returns:** Object mapping deck name to input numeric card IDs.

**Completion:** completed.

**Behavior:** missing cards/decks raise a legacy error rather than masquerading as Default.

**v1 equivalent:** [cards.getMany](API_V1.md#cardsgetmany).

**Example request**

```json
{
  "action": "getDecks",
  "version": 6,
  "params": {
    "cards": [
      1502298036657,
      1502298033753,
      1502032366472
    ]
  }
}
```

### `createDeck`

Create a new empty deck. Will not overwrite a deck that exists with the same name.

**Parameters:** `createDeck(deck)`

**Returns:** Numeric deck ID.

**Completion:** completed.

**v1 equivalent:** [decks.create](API_V1.md#deckscreate).

**Example request**

```json
{
  "action": "createDeck",
  "version": 6,
  "params": {
    "deck": "Japanese::Tokyo"
  }
}
```

### `changeDeck`

Moves cards with the given IDs to a different deck, creating the deck if it doesn't exist yet.

**Parameters:** `changeDeck(cards, deck)`

**Returns:** null; missing card item errors become a legacy error.

**Completion:** completed.

**Behavior:** native move invariants and filtered-destination rejection; report partial changes if any item fails.

**v1 equivalent:** [decks.get](API_V1.md#decksget), [decks.create](API_V1.md#deckscreate), [cards.move](API_V1.md#cardsmove).

**Example request**

```json
{
  "action": "changeDeck",
  "version": 6,
  "params": {
    "cards": [
      1502098034045,
      1502098034048,
      1502298033753
    ],
    "deck": "Japanese::JLPT N3"
  }
}
```

### `deleteDecks`

Deletes decks with the given names.
The argument `cardsToo` *must* be specified and set to `true`.

**Parameters:** `deleteDecks(decks, cardsToo=False)`

**Returns:** null.

**Completion:** completed.

**Behavior:** Preserve rejection of cardsToo=false; do not quietly delete cards.

**v1 equivalent:** [decks.delete](API_V1.md#decksdelete).

**Example request**

```json
{
  "action": "deleteDecks",
  "version": 6,
  "params": {
    "decks": [
      "Japanese::JLPT N5",
      "Easy Spanish"
    ],
    "cardsToo": true
  }
}
```

### `getDeckConfig`

Gets the configuration group object for the given deck.

**Parameters:** `getDeckConfig(deck)`

**Returns:** Legacy preset dictionary or false.

**Completion:** completed.

**v1 equivalent:** [decks.get](API_V1.md#decksget), [deckPresets.get](API_V1.md#deckpresetsget).

**Example request**

```json
{
  "action": "getDeckConfig",
  "version": 6,
  "params": {
    "deck": "Default"
  }
}
```

### `saveDeckConfig`

Patch a legacy preset dictionary identified by `config.id`. Supply changed settings; omitted settings are preserved. Unsupported changes fail. Client `mod` and `usn` metadata are not writable. Returns a boolean.

**Parameters:** `saveDeckConfig(config)`

**Returns:** Boolean; missing preset/validation/native failure returns false.

**Completion:** final operation.

**Behavior:** one coordinated update. No metadata writes from client mod/usn; optional FSRS full rescheduling defaults false.

**v1 equivalent:** [deckPresets.update](API_V1.md#deckpresetsupdate).

**Example request**

```json
{
  "action": "saveDeckConfig",
  "version": 6,
  "params": {
    "config": {
      "id": 1,
      "new": {
        "perDay": 20
      }
    }
  }
}
```

### `setDeckConfigId`

Changes the configuration group for the given decks to the one with the given ID. Returns `true` on success or
`false` if the given configuration group or any of the given decks do not exist.

**Parameters:** `setDeckConfigId(decks, configId)`

**Returns:** true only when all assignments succeed; otherwise false.

**Completion:** final operation.

**Behavior:** native dependent-card updates. Partial runtime failure remains observable and must be logged.

**v1 equivalent:** [deckPresets.assign](API_V1.md#deckpresetsassign).

**Example request**

```json
{
  "action": "setDeckConfigId",
  "version": 6,
  "params": {
    "decks": [
      "Default"
    ],
    "configId": 1
  }
}
```

### `cloneDeckConfigId`

Creates a new configuration group with the given name, cloning from the group with the given ID, or from the default
group if this is unspecified. Returns the ID of the new configuration group, or `false` if the specified group to
clone from does not exist.

**Parameters:** `cloneDeckConfigId(name, cloneFrom='1')`

**Returns:** Numeric new preset ID or false.

**Completion:** completed.

**v1 equivalent:** [deckPresets.create](API_V1.md#deckpresetscreate).

**Example request**

```json
{
  "action": "cloneDeckConfigId",
  "version": 6,
  "params": {
    "name": "Copy of Default",
    "cloneFrom": 1
  }
}
```

### `removeDeckConfigId`

Removes the configuration group with the given ID, returning `true` if successful, or `false` if attempting to
remove either the default configuration group (ID = 1) or a configuration group that does not exist.

**Parameters:** `removeDeckConfigId(configId)`

**Returns:** Boolean; false for missing/default/nondeletable preset.

**Completion:** final operation.

**v1 equivalent:** [deckPresets.delete](API_V1.md#deckpresetsdelete).

**Example request**

```json
{
  "action": "removeDeckConfigId",
  "version": 6,
  "params": {
    "configId": 1502972374573
  }
}
```

### `getDeckStats`

Gets statistics such as total cards and cards due for the given decks.

**Parameters:** `getDeckStats(decks)`

**Returns:** Object keyed by numeric deck ID strings; values preserve deck_id/name/new_count/learn_count/review_count/total_in_deck.

**Completion:** completed.

**Behavior:** unknown deck raises; deck count unchanged.

**v1 equivalent:** [decks.getCounts](API_V1.md#decksgetcounts).

**Example request**

```json
{
  "action": "getDeckStats",
  "version": 6,
  "params": {
    "decks": [
      "Japanese::JLPT N5",
      "Easy Spanish"
    ]
  }
}
```

### `deckNameFromId`

Return the name of an existing deck by its numeric ID.

**Parameters:** `deckNameFromId(deckId)`

**Returns:** Name string.

**Completion:** completed.

**Behavior:** nonexistent ID raises without Default fallback.

**v1 equivalent:** [decks.get](API_V1.md#decksget).

**Example request**

```json
{
  "action": "deckNameFromId",
  "version": 6,
  "params": {
    "deckId": 1
  }
}
```

## Graphical Actions

### `guiBrowse`

Open the browser and optionally search with Anki syntax. `reorderCards` is an object with `columnId` and `order` (`ascending` or `descending`). Omitted query preserves the existing search and returns an empty array.

**Parameters:** `guiBrowse(query=None, reorderCards=None)`

**Returns:** Numeric card IDs from the provided query after exhausting search pages.

**Completion:** browser ready.

**Behavior:** preserve explicit sort direction regardless of selected/default column.

**v1 equivalent:** [browser.open](API_V1.md#browseropen), [cards.search](API_V1.md#cardssearch).

**Example request**

```json
{
  "action": "guiBrowse",
  "version": 6,
  "params": {
    "query": "deck:current",
    "reorderCards": {
      "order": "descending",
      "columnId": "noteCrt"
    }
  }
}
```

### `guiSelectCard`

Finds the open instance of the *Card Browser* dialog and selects a card given a card identifier.
Returns `true` if the *Card Browser* is open, `false` otherwise.

**Parameters:** `guiSelectCard(card)`

**Returns:** Boolean; false if browser closed.

**Completion:** selection final.

**v1 equivalent:** [browser.select](API_V1.md#browserselect).

**Example request**

```json
{
  "action": "guiSelectCard",
  "version": 6,
  "params": {
    "card": 1494723142483
  }
}
```

### `guiSelectedNotes`

Finds the open instance of the *Card Browser* dialog and returns an array of identifiers of the notes that are
selected. Returns an empty list if the browser is not open.

**Parameters:** `guiSelectedNotes()`

**Returns:** Numeric selected note IDs; closed browser yields [].

**Completion:** completed.

**v1 equivalent:** [browser.getSelection](API_V1.md#browsergetselection).

**Example request**

```json
{
  "action": "guiSelectedNotes",
  "version": 6,
  "params": {}
}
```

### `guiAddCards`

Open or activate the configured Add editor and optionally populate a note draft. Returns `0` for an unsaved draft; this is not a future note ID. Dirty draft replacement is rejected. Both legacy and Svelte Add editors are supported.

**Parameters:** `guiAddCards(note=None)`

**Returns:** Numeric 0 for unsaved draft, explicitly not a future persisted note ID.

**Completion:** accepted; multi awaits draft ready.

**Behavior:** Uses the active editor variant and rejects replacement of an unsaved draft.

**v1 equivalent:** [editors.openAdd](API_V1.md#editorsopenadd), [media.store](API_V1.md#mediastore).

**Example request**

```json
{
  "action": "guiAddCards",
  "version": 6,
  "params": {
    "note": {
      "deckName": "Default",
      "modelName": "Cloze",
      "fields": {
        "Text": "The capital of Romania is {{c1::Bucharest}}",
        "Extra": "Romania is a country in Europe"
      },
      "tags": [
        "countries"
      ],
      "picture": [
        {
          "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/13/EU-Romania.svg/285px-EU-Romania.svg.png",
          "filename": "romania.png",
          "fields": [
            "Extra"
          ]
        }
      ]
    }
  }
}
```

### `guiEditNote`

Open the custom editor for a note, with card preview, browser access, and navigation through editor history.

**Parameters:** `guiEditNote(note)`

**Returns:** null when accepted.

**Completion:** accepted; multi awaits editor ready.

**v1 equivalent:** [editors.openNote](API_V1.md#editorsopennote).

**Example request**

```json
{
  "action": "guiEditNote",
  "version": 6,
  "params": {
    "note": 1649198355435
  }
}
```

### `guiAddNoteSetData`

Update a visible Add draft. Fields and tags replace supplied values by default; `append=true` concatenates field text and unions tags. Deck and note type always replace. Inline media follows the note media rules below.

**Parameters:** `guiAddNoteSetData(note, append=False)`

**Returns:** true after draft completion; closed dialog retains {error: "Add Note dialog is not open", code: 1}.

**Completion:** draft final.

**Behavior:** An explicit deck takes precedence over the note type default. Both editor variants reject conflicting draft changes.

**v1 equivalent:** [editors.updateDraft](API_V1.md#editorsupdatedraft), [media.store](API_V1.md#mediastore).

**Example request**

```json
{
  "action": "guiAddNoteSetData",
  "version": 6,
  "params": {
    "note": {
      "deckName": "Default",
      "modelName": "Basic",
      "fields": {
        "Front": "Hello",
        "Back": "World"
      },
      "tags": [
        "new",
        "api"
      ]
    }
  }
}
```

### `guiCurrentCard`

Returns information about the current card or `null` if not in review mode.

**Parameters:** `guiCurrentCard()`

**Returns:** Legacy current-card object with button numbers 1–4 and nextReviews labels in offered-button order.

**Completion:** completed.

**Behavior:** prediction labels match reviewer custom states, not fresh defaults.

**v1 equivalent:** [reviewer.get](API_V1.md#reviewerget), [notes.get](API_V1.md#notesget), [noteTypes.get](API_V1.md#notetypesget).

**Example request**

```json
{
  "action": "guiCurrentCard",
  "version": 6,
  "params": {}
}
```

### `guiStartCardTimer`

Starts or resets the `timerStarted` value for the current card. This is useful for deferring the start time to when
it is displayed via the API, allowing the recorded time taken to answer the card to be more accurate when calling
`guiAnswerCard`.

**Parameters:** `guiStartCardTimer()`

**Returns:** Boolean.

**Completion:** completed.

**v1 equivalent:** [reviewer.get](API_V1.md#reviewerget), [reviewer.startTimer](API_V1.md#reviewerstarttimer).

**Example request**

```json
{
  "action": "guiStartCardTimer",
  "version": 6,
  "params": {}
}
```

### `guiShowQuestion`

Shows question text for the current card; returns `true` if in review mode or `false` otherwise.

**Parameters:** `guiShowQuestion()`

**Returns:** Boolean.

**Completion:** completed.

**v1 equivalent:** [reviewer.get](API_V1.md#reviewerget), [reviewer.showQuestion](API_V1.md#reviewershowquestion).

**Example request**

```json
{
  "action": "guiShowQuestion",
  "version": 6,
  "params": {}
}
```

### `guiShowAnswer`

Shows answer text for the current card; returns `true` if in review mode or `false` otherwise.

**Parameters:** `guiShowAnswer()`

**Returns:** Boolean.

**Completion:** completed.

**v1 equivalent:** [reviewer.get](API_V1.md#reviewerget), [reviewer.showAnswer](API_V1.md#reviewershowanswer).

**Example request**

```json
{
  "action": "guiShowAnswer",
  "version": 6,
  "params": {}
}
```

### `guiAnswerCard`

Submit an offered answer button for the active reviewer. The answer side must be displayed. A standalone success acknowledges acceptance; `multi` observes final completion and hook vetoes.

**Parameters:** `guiAnswerCard(ease)`

**Returns:** true when answer is accepted; false for rejected preconditions.

**Completion:** accepted; multi awaits final.

**Behavior:** Hook veto/async failure is a terminal internal failure; multi must observe it before proceeding.

**v1 equivalent:** [reviewer.get](API_V1.md#reviewerget), [reviewer.answer](API_V1.md#revieweranswer).

**Example request**

```json
{
  "action": "guiAnswerCard",
  "version": 6,
  "params": {
    "ease": 1
  }
}
```

### `guiUndo`

Request native undo. A standalone success acknowledges acceptance; `multi` observes final completion.

**Parameters:** `guiUndo()`

**Returns:** true when accepted.

**Completion:** accepted; multi awaits final.

**v1 equivalent:** [collection.undo](API_V1.md#collectionundo).

**Example request**

```json
{
  "action": "guiUndo",
  "version": 6,
  "params": {}
}
```

### `guiDeckOverview`

Opens the *Deck Overview* dialog for the deck with the given name; returns `true` if succeeded or `false` otherwise.

**Parameters:** `guiDeckOverview(name)`

**Returns:** Boolean.

**Completion:** navigation final.

**v1 equivalent:** [application.navigate](API_V1.md#applicationnavigate).

**Example request**

```json
{
  "action": "guiDeckOverview",
  "version": 6,
  "params": {
    "name": "Default"
  }
}
```

### `guiDeckBrowser`

Opens the *Deck Browser* dialog.

**Parameters:** `guiDeckBrowser()`

**Returns:** null.

**Completion:** navigation final.

**v1 equivalent:** [application.navigate](API_V1.md#applicationnavigate).

**Example request**

```json
{
  "action": "guiDeckBrowser",
  "version": 6,
  "params": {}
}
```

### `guiDeckReview`

Starts review for the deck with the given name; returns `true` if succeeded or `false` otherwise.

**Parameters:** `guiDeckReview(name)`

**Returns:** Boolean.

**Completion:** navigation final.

**v1 equivalent:** [application.navigate](API_V1.md#applicationnavigate).

**Example request**

```json
{
  "action": "guiDeckReview",
  "version": 6,
  "params": {
    "name": "Default"
  }
}
```

### `guiImportFile`

Open Anki’s interactive import workflow. Omit `path` to choose a file, or supply a path on the machine running Anki. Use forward slashes for Windows paths.

**Parameters:** `guiImportFile(path=None)`

**Returns:** null when accepted.

**Completion:** accepted; multi awaits import final.

**v1 equivalent:** [application.importFile](API_V1.md#applicationimportfile).

**Example request**

```json
{
  "action": "guiImportFile",
  "version": 6,
  "params": {
    "path": "C:/Users/Desktop/cards.txt"
  }
}
```

### `guiExitAnki`

Acknowledge a close request, flush the HTTP reply, then request normal Anki shutdown. Native dialogs may prevent exit.

**Parameters:** `guiExitAnki()`

**Returns:** null after response is flushed, then request native close.

**Completion:** accepted; process may exit.

**Behavior:** Do not claim actual shutdown completion; user can cancel native close.

**v1 equivalent:** [application.exit](API_V1.md#applicationexit).

**Example request**

```json
{
  "action": "guiExitAnki",
  "version": 6,
  "params": {}
}
```

### `guiCheckDatabase`

Start Anki’s database check and repair workflow. The standalone reply acknowledges acceptance; `multi` waits for completion.

**Parameters:** `guiCheckDatabase()`

**Returns:** true when accepted.

**Completion:** accepted; multi awaits final.

**v1 equivalent:** [collection.checkIntegrity](API_V1.md#collectioncheckintegrity).

**Example request**

```json
{
  "action": "guiCheckDatabase",
  "version": 6,
  "params": {}
}
```

### `guiPlayAudio`

Plays any Audio for the current side of the current card; returns `true` if succeeded or `false` otherwise.

**Parameters:** `guiPlayAudio()`

**Returns:** Boolean.

**Completion:** completed.

**v1 equivalent:** [reviewer.get](API_V1.md#reviewerget), [reviewer.playAudio](API_V1.md#reviewerplayaudio).

**Example request**

```json
{
  "action": "guiPlayAudio",
  "version": 6,
  "params": {}
}
```

### `guiSelectNote`

Select a card in an already open browser. Despite the historical name, `note` is a **card ID**. Prefer `guiSelectCard`.

**Parameters:** `guiSelectNote(note)`

**Returns:** Boolean; false if browser closed.

**Completion:** selection final.

**Behavior:** Preserve documented/deprecated card-ID meaning; do not reinterpret as note ID.

**v1 equivalent:** [browser.select](API_V1.md#browserselect).

**Example request**

```json
{
  "action": "guiSelectNote",
  "version": 6,
  "params": {
    "note": 1700000000002
  }
}
```

### `guiReviewActive`

Return whether the GUI reviewer is active.

**Parameters:** `guiReviewActive()`

**Returns:** active boolean.

**Completion:** completed.

**v1 equivalent:** [reviewer.get](API_V1.md#reviewerget).

**Example request**

```json
{
  "action": "guiReviewActive",
  "version": 6,
  "params": {}
}
```

## Media Actions

### `storeMediaFile`

Store media from exactly one of `data` (base64), `path` (local file), or `url` (HTTP/HTTPS). The result is the actual filename, which may be normalized or renamed. `deleteExisting=true` explicitly replaces a collision after acquisition succeeds; false uses native renaming. `skipHash` is the incoming bytes’ MD5 digest: a match returns null and promises no stored file.

**Parameters:** `storeMediaFile(filename, data=None, path=None, url=None, skipHash=None, deleteExisting=True)`

**Returns:** Actual filename; null when incoming bytes match skipHash.

**Completion:** final operation.

**Behavior:** Media failure is an error; replacement occurs only after successful acquisition.

**v1 equivalent:** [media.store](API_V1.md#mediastore).

**Example request**

```json
{
  "action": "storeMediaFile",
  "version": 6,
  "params": {
    "filename": "hello.txt",
    "data": "SGVsbG8h"
  }
}
```

### `retrieveMediaFile`

Retrieves the base64-encoded contents of the specified file, returning `false` if the file does not exist.

**Parameters:** `retrieveMediaFile(filename)`

**Returns:** Base64 string; false for absent file.

**Completion:** completed.

**v1 equivalent:** [media.get](API_V1.md#mediaget).

**Example request**

```json
{
  "action": "retrieveMediaFile",
  "version": 6,
  "params": {
    "filename": "_hello.txt"
  }
}
```

### `getMediaFilesNames`

Gets the names of media files matched the pattern. Returning all names by default.

**Parameters:** `getMediaFilesNames(pattern='*')`

**Returns:** Array of basenames.

**Completion:** completed.

**Behavior:** Traversal outside media directory is not preserved.

**v1 equivalent:** [media.list](API_V1.md#medialist).

**Example request**

```json
{
  "action": "getMediaFilesNames",
  "version": 6,
  "params": {
    "pattern": "_hell*.txt"
  }
}
```

### `getMediaDirPath`

Gets the full path to the `collection.media` folder of the currently opened profile.

**Parameters:** `getMediaDirPath()`

**Returns:** Absolute local path string.

**Completion:** completed.

**v1 equivalent:** [media.getDirectory](API_V1.md#mediagetdirectory).

**Example request**

```json
{
  "action": "getMediaDirPath",
  "version": 6,
  "params": {}
}
```

### `deleteMediaFile`

Deletes the specified file inside the media folder.

**Parameters:** `deleteMediaFile(filename)`

**Returns:** null; absent file is a no-op.

**Completion:** completed.

**v1 equivalent:** [media.delete](API_V1.md#mediadelete).

**Example request**

```json
{
  "action": "deleteMediaFile",
  "version": 6,
  "params": {
    "filename": "_hello.txt"
  }
}
```

## Miscellaneous Actions

### `requestPermission`

Request permission for the actual HTTP origin. The transport supplies `origin` and `allowed`; omit them from the request. Approval may display an Anki dialog. The reply never includes the API key.

**Parameters:** `requestPermission(origin, allowed)`

`origin` and `allowed` in the internal signature are supplied by the HTTP transport.

**Returns:** {permission, requireApikey, version} when granted; denied has permission only.

**Completion:** permission decision.

**v1 equivalent:** [access.requestPermission](API_V1.md#accessrequestpermission).

**Example request**

```json
{
  "action": "requestPermission",
  "version": 6,
  "params": {}
}
```

### `version`

Return the configured legacy API version, normally `6`. This is separate from the v1 endpoint version.

**Parameters:** `version()`

**Returns:** Integer 6/configured value.

**Completion:** completed.

**v1 equivalent:** [api.describe](API_V1.md#apidescribe).

**Example request**

```json
{
  "action": "version",
  "version": 6,
  "params": {}
}
```

### `apiReflect`

List supported legacy actions. `scopes` currently supports `"actions"`. Omit `actions` to list all actions, or supply names to filter the list.

**Parameters:** `apiReflect(scopes=None, actions=None)`

**Returns:** {scopes: ["actions"], actions: [...]} when requested; otherwise {scopes: []}.

**Completion:** completed.

**v1 equivalent:** [api.describe](API_V1.md#apidescribe).

**Example request**

```json
{
  "action": "apiReflect",
  "version": 6,
  "params": {
    "scopes": [
      "actions",
      "invalidType"
    ],
    "actions": [
      "apiReflect",
      "invalidMethod"
    ]
  }
}
```

### `sync`

Start one coordinated AnkiWeb sync using the active profile’s credentials and media-sync setting. A standalone reply acknowledges acceptance; `multi` waits for completion.

**Parameters:** `sync()`

**Returns:** null when accepted.

**Completion:** accepted; multi awaits final.

**Behavior:** one sync workflow; no preliminary blocking sync. Later failures are tracked internally, not returned retroactively.

**v1 equivalent:** [collection.sync](API_V1.md#collectionsync).

**Example request**

```json
{
  "action": "sync",
  "version": 6,
  "params": {}
}
```

### `getProfiles`

Retrieve the list of profiles.

**Parameters:** `getProfiles()`

**Returns:** Array of profile name strings.

**Completion:** completed.

**v1 equivalent:** [profiles.list](API_V1.md#profileslist).

**Example request**

```json
{
  "action": "getProfiles",
  "version": 6,
  "params": {}
}
```

### `getActiveProfile`

Retrieve the active profile.

**Parameters:** `getActiveProfile()`

**Returns:** Name or null.

**Completion:** completed.

**v1 equivalent:** [profiles.getActive](API_V1.md#profilesgetactive).

**Example request**

```json
{
  "action": "getActiveProfile",
  "version": 6,
  "params": {}
}
```

### `loadProfile`

Switch to an existing profile. A standalone reply acknowledges acceptance; `multi` waits until the destination collection is ready.

**Parameters:** `loadProfile(name)`

**Returns:** true when accepted; false for missing profile.

**Completion:** accepted; multi awaits final.

**Behavior:** Session-scoped callback replaces visibility polling; cancellation is terminal internally.

**v1 equivalent:** [profiles.switch](API_V1.md#profilesswitch).

**Example request**

```json
{
  "action": "loadProfile",
  "version": 6,
  "params": {
    "name": "user1"
  }
}
```

### `multi`

Run the nested requests in order, waiting for each final outcome. Results preserve each nested request’s response version. See the completion rules above.

**Parameters:** `multi(actions)`

**Returns:** Array of legacy replies in input order; preserve each nested version envelope.

**Completion:** all nested operations final.

**Behavior:** No atomicity. Legacy profile switching is allowed with a barrier; new api.execute prohibits it. Shutdown ends execution as described below.

**v1 equivalent:** [api.execute](API_V1.md#apiexecute).

**Example request**

```json
{
  "action": "multi",
  "version": 6,
  "params": {
    "actions": [
      {
        "action": "deckNames",
        "version": 6
      },
      {
        "action": "findNotes",
        "version": 6,
        "params": {
          "query": "deck:Default"
        }
      }
    ]
  }
}
```

### `exportPackage`

Exports a given deck in `.apkg` format. Returns `true` if successful or `false` otherwise. The optional property
`includeSched` (default is `false`) can be specified to include the cards' scheduling data.

**Parameters:** `exportPackage(deck, path, includeSched=False)`

**Returns:** true after export; false for missing deck.

**Completion:** final operation.

**v1 equivalent:** [packages.export](API_V1.md#packagesexport).

**Example request**

```json
{
  "action": "exportPackage",
  "version": 6,
  "params": {
    "deck": "Default",
    "path": "/data/Deck.apkg",
    "includeSched": true
  }
}
```

### `importPackage`

Imports a file in `.apkg` format into the collection. Returns `true` if successful or `false` otherwise.
Note that the file path is relative to Anki's collection.media folder, not to the client.

**Parameters:** `importPackage(path)`

**Returns:** true after import; false when collection absent as legacy.

**Completion:** final operation.

**v1 equivalent:** [packages.import](API_V1.md#packagesimport).

**Example request**

```json
{
  "action": "importPackage",
  "version": 6,
  "params": {
    "path": "/data/Deck.apkg"
  }
}
```

### `reloadCollection`

Refresh supported collection caches and windows. This does not close or reopen the collection.

**Parameters:** `reloadCollection()`

**Returns:** null.

**Completion:** completed.

**Behavior:** actual cache/window refresh, never collection reopen or no-op reset.

**v1 equivalent:** [collection.refresh](API_V1.md#collectionrefresh).

**Example request**

```json
{
  "action": "reloadCollection",
  "version": 6,
  "params": {}
}
```

## Model Actions

### `modelNames`

Gets the complete list of model names for the current user.

**Parameters:** `modelNames()`

**Returns:** Name string array.

**Completion:** completed.

**v1 equivalent:** [noteTypes.list](API_V1.md#notetypeslist).

**Example request**

```json
{
  "action": "modelNames",
  "version": 6,
  "params": {}
}
```

### `modelNamesAndIds`

Gets the complete list of model names and their corresponding IDs for the current user.

**Parameters:** `modelNamesAndIds()`

**Returns:** Object mapping name to numeric ID.

**Completion:** completed.

**v1 equivalent:** [noteTypes.list](API_V1.md#notetypeslist).

**Example request**

```json
{
  "action": "modelNamesAndIds",
  "version": 6,
  "params": {}
}
```

### `findModelsById`

Gets a list of models  for the provided model IDs from the current user.

**Parameters:** `findModelsById(modelIds)`

**Returns:** Array of legacy note-type dictionaries.

**Completion:** completed.

**v1 equivalent:** [noteTypes.get](API_V1.md#notetypesget).

**Example request**

```json
{
  "action": "findModelsById",
  "version": 6,
  "params": {
    "modelIds": [
      1704387367119,
      1704387398570
    ]
  }
}
```

### `findModelsByName`

Gets a list of models for the provided model names from the current user.

**Parameters:** `findModelsByName(modelNames)`

**Returns:** Array of legacy note-type dictionaries.

**Completion:** completed.

**v1 equivalent:** [noteTypes.get](API_V1.md#notetypesget).

**Example request**

```json
{
  "action": "findModelsByName",
  "version": 6,
  "params": {
    "modelNames": [
      "Basic",
      "Basic (and reversed card)"
    ]
  }
}
```

### `modelFieldNames`

Gets the complete list of field names for the provided model name.

**Parameters:** `modelFieldNames(modelName)`

**Returns:** Field names in ordinal order.

**Completion:** completed.

**v1 equivalent:** [noteTypes.get](API_V1.md#notetypesget).

**Example request**

```json
{
  "action": "modelFieldNames",
  "version": 6,
  "params": {
    "modelName": "Basic"
  }
}
```

### `modelFieldDescriptions`

Gets the complete list of field descriptions (the text seen in the gui editor when a field is empty) for the provided model name.

**Parameters:** `modelFieldDescriptions(modelName)`

**Returns:** Field description strings in ordinal order; missing description → empty string.

**Completion:** completed.

**v1 equivalent:** [noteTypes.get](API_V1.md#notetypesget).

**Example request**

```json
{
  "action": "modelFieldDescriptions",
  "version": 6,
  "params": {
    "modelName": "Basic"
  }
}
```

### `modelFieldFonts`

Gets the complete list of fonts along with their font sizes.

**Parameters:** `modelFieldFonts(modelName)`

**Returns:** Object mapping field name to {font, size}.

**Completion:** completed.

**v1 equivalent:** [noteTypes.get](API_V1.md#notetypesget).

**Example request**

```json
{
  "action": "modelFieldFonts",
  "version": 6,
  "params": {
    "modelName": "Basic"
  }
}
```

### `modelFieldsOnTemplates`

Returns an object indicating the fields on the question and answer side of each card template for the given model
name. The question side is given first in each array.

**Parameters:** `modelFieldsOnTemplates(modelName)`

**Returns:** Object mapping template name to [questionFields, answerFields].

**Completion:** completed.

**v1 equivalent:** [noteTypes.getTemplateUsage](API_V1.md#notetypesgettemplateusage).

**Example request**

```json
{
  "action": "modelFieldsOnTemplates",
  "version": 6,
  "params": {
    "modelName": "Basic (and reversed card)"
  }
}
```

### `createModel`

Creates a new model to be used in Anki. User must provide the `modelName`, `inOrderFields` and `cardTemplates` to be
used in the model. There are optional fields `css` and `isCloze`. If not specified, `css` will use the default Anki css and `isCloze` will be equal to `false`. If `isCloze` is `true` then model will be created as Cloze.

Optionally the `Name` field can be provided for each entry of `cardTemplates`. By default the
card names will be `Card 1`, `Card 2`, and so on.

**Parameters:** `createModel(modelName, inOrderFields, cardTemplates, css=None, isCloze=False)`

**Returns:** Legacy note-type dictionary projected from baseline adapter snapshot.

**Completion:** completed.

**v1 equivalent:** [noteTypes.create](API_V1.md#notetypescreate).

**Example request**

```json
{
  "action": "createModel",
  "version": 6,
  "params": {
    "modelName": "newModelName",
    "inOrderFields": [
      "Field1",
      "Field2",
      "Field3"
    ],
    "css": "Optional CSS with default to builtin css",
    "isCloze": false,
    "cardTemplates": [
      {
        "Name": "My Card 1",
        "Front": "Front html {{Field1}}",
        "Back": "Back html  {{Field2}}"
      }
    ]
  }
}
```

### `modelTemplates`

Returns an object indicating the template content for each card connected to the provided model by name.

**Parameters:** `modelTemplates(modelName)`

**Returns:** Object mapping template name to {Front, Back}.

**Completion:** completed.

**v1 equivalent:** [noteTypes.get](API_V1.md#notetypesget).

**Example request**

```json
{
  "action": "modelTemplates",
  "version": 6,
  "params": {
    "modelName": "Basic (and reversed card)"
  }
}
```

### `modelStyling`

Gets the CSS styling for the provided model by name.

**Parameters:** `modelStyling(modelName)`

**Returns:** {css}.

**Completion:** completed.

**v1 equivalent:** [noteTypes.get](API_V1.md#notetypesget).

**Example request**

```json
{
  "action": "modelStyling",
  "version": 6,
  "params": {
    "modelName": "Basic (and reversed card)"
  }
}
```

### `updateModelTemplates`

Update supplied template sides by name. Unmentioned templates and sides are preserved; missing template names and empty side values are ignored for legacy compatibility.

**Parameters:** `updateModelTemplates(model)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [noteTypes.editStructure](API_V1.md#notetypeseditstructure).

**Example request**

```json
{
  "action": "updateModelTemplates",
  "version": 6,
  "params": {
    "model": {
      "name": "Custom",
      "templates": {
        "Card 1": {
          "Front": "{{Question}}?",
          "Back": "{{Answer}}!"
        }
      }
    }
  }
}
```

### `updateModelStyling`

Modify the CSS styling of an existing model by name.

**Parameters:** `updateModelStyling(model)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [noteTypes.update](API_V1.md#notetypesupdate).

**Example request**

```json
{
  "action": "updateModelStyling",
  "version": 6,
  "params": {
    "model": {
      "name": "Custom",
      "css": "p { color: blue; }"
    }
  }
}
```

### `findAndReplaceInModels`

Find and replace string in existing model by model name. Customise to replace in front, back or css by setting to true/false.

**Parameters:** `findAndReplaceInModels(modelName, findText, replaceText, front=True, back=True, css=True)`

**Returns:** Count of changed note types.

**Completion:** completed.

**v1 equivalent:** [noteTypes.replaceText](API_V1.md#notetypesreplacetext).

**Example request**

```json
{
  "action": "findAndReplaceInModels",
  "version": 6,
  "params": {
    "modelName": "Basic",
    "findText": "font-size: 20px",
    "replaceText": "font-size: 24px",
    "front": false,
    "back": false,
    "css": true
  }
}
```

### `modelTemplateRename`

Renames a template in an existing model.

**Parameters:** `modelTemplateRename(modelName, oldTemplateName, newTemplateName)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [noteTypes.editStructure](API_V1.md#notetypeseditstructure).

**Example request**

```json
{
  "action": "modelTemplateRename",
  "version": 6,
  "params": {
    "modelName": "Basic",
    "oldTemplateName": "Card 1",
    "newTemplateName": "Card 1 renamed"
  }
}
```

### `modelTemplateReposition`

Repositions a template in an existing model.

The value of `index` starts at 0. For example, an index of `0` puts the template in the first position, and an index of `2` puts the template in the third position.

**Parameters:** `modelTemplateReposition(modelName, templateName, index)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [noteTypes.editStructure](API_V1.md#notetypeseditstructure).

**Example request**

```json
{
  "action": "modelTemplateReposition",
  "version": 6,
  "params": {
    "modelName": "Basic",
    "templateName": "Card 1",
    "index": 1
  }
}
```

### `modelTemplateAdd`

Add a template, or update it when a template with that name already exists. Template records use `Name`, `Front`, and `Back`.

**Parameters:** `modelTemplateAdd(modelName, template)`

**Returns:** null.

**Completion:** completed.

**Behavior:** persist both paths once; no cached-only update.

**v1 equivalent:** [noteTypes.get](API_V1.md#notetypesget), [noteTypes.editStructure](API_V1.md#notetypeseditstructure).

**Example request**

```json
{
  "action": "modelTemplateAdd",
  "version": 6,
  "params": {
    "modelName": "Basic",
    "template": {
      "Name": "Card 3",
      "Front": "Front html {{Field1}}",
      "Back": "Back html {{Field2}}"
    }
  }
}
```

### `modelTemplateRemove`

Removes a template from an existing model.

**Parameters:** `modelTemplateRemove(modelName, templateName)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [noteTypes.editStructure](API_V1.md#notetypeseditstructure).

**Example request**

```json
{
  "action": "modelTemplateRemove",
  "version": 6,
  "params": {
    "modelName": "Basic",
    "templateName": "Card 1"
  }
}
```

### `modelFieldRename`

Rename the field name of a given model.

**Parameters:** `modelFieldRename(modelName, oldFieldName, newFieldName)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [noteTypes.editStructure](API_V1.md#notetypeseditstructure).

**Example request**

```json
{
  "action": "modelFieldRename",
  "version": 6,
  "params": {
    "modelName": "Basic",
    "oldFieldName": "Front",
    "newFieldName": "FrontRenamed"
  }
}
```

### `modelFieldReposition`

Reposition the field within the field list of a given model.

The value of `index` starts at 0. For example, an index of `0` puts the field in the first position, and an index of `2` puts the field in the third position.

**Parameters:** `modelFieldReposition(modelName, fieldName, index)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [noteTypes.editStructure](API_V1.md#notetypeseditstructure).

**Example request**

```json
{
  "action": "modelFieldReposition",
  "version": 6,
  "params": {
    "modelName": "Basic",
    "fieldName": "Back",
    "index": 0
  }
}
```

### `modelFieldAdd`

Creates a new field within a given model.

Optionally, the `index` value can be provided, which works exactly the same as the index in `modelFieldReposition`. By default, the field is added to the end of the field list.

**Parameters:** `modelFieldAdd(modelName, fieldName, index=None)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [noteTypes.get](API_V1.md#notetypesget), [noteTypes.editStructure](API_V1.md#notetypeseditstructure).

**Example request**

```json
{
  "action": "modelFieldAdd",
  "version": 6,
  "params": {
    "modelName": "Basic",
    "fieldName": "NewField",
    "index": 0
  }
}
```

### `modelFieldRemove`

Deletes a field within a given model.

**Parameters:** `modelFieldRemove(modelName, fieldName)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [noteTypes.editStructure](API_V1.md#notetypeseditstructure).

**Example request**

```json
{
  "action": "modelFieldRemove",
  "version": 6,
  "params": {
    "modelName": "Basic",
    "fieldName": "Front"
  }
}
```

### `modelFieldSetFont`

Sets the font for a field within a given model.

**Parameters:** `modelFieldSetFont(modelName, fieldName, font)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [noteTypes.editStructure](API_V1.md#notetypeseditstructure).

**Example request**

```json
{
  "action": "modelFieldSetFont",
  "version": 6,
  "params": {
    "modelName": "Basic",
    "fieldName": "Front",
    "font": "Courier"
  }
}
```

### `modelFieldSetFontSize`

Sets the font size for a field within a given model.

**Parameters:** `modelFieldSetFontSize(modelName, fieldName, fontSize)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [noteTypes.editStructure](API_V1.md#notetypeseditstructure).

**Example request**

```json
{
  "action": "modelFieldSetFontSize",
  "version": 6,
  "params": {
    "modelName": "Basic",
    "fieldName": "Front",
    "fontSize": 10
  }
}
```

### `modelFieldSetDescription`

Set the editor placeholder description of a field. Returns false if the runtime lacks the required capability.

**Parameters:** `modelFieldSetDescription(modelName, fieldName, description)`

**Returns:** true; false when capability is absent.

**Completion:** completed.

**v1 equivalent:** [noteTypes.editStructure](API_V1.md#notetypeseditstructure).

**Example request**

```json
{
  "action": "modelFieldSetDescription",
  "version": 6,
  "params": {
    "modelName": "Basic",
    "fieldName": "Front",
    "description": "example field description"
  }
}
```

### `modelNameFromId`

Return the name of an existing note type by its numeric ID.

**Parameters:** `modelNameFromId(modelId)`

**Returns:** Name string.

**Completion:** completed.

**v1 equivalent:** [noteTypes.get](API_V1.md#notetypesget).

**Example request**

```json
{
  "action": "modelNameFromId",
  "version": 6,
  "params": {
    "modelId": 1700000000000
  }
}
```

## Note Actions

### `addNote`

Create a note and return its numeric ID. Invalid content or missing references return an error. See the note input and media conventions below.

**Parameters:** `addNote(note)`

**Returns:** Numeric note ID.

**Completion:** completed.

**Behavior:** Uses native validation. Eligibility checks do not download media or change the collection. Note creation uses a native transaction; media recovery is separate.

**v1 equivalent:** [notes.create](API_V1.md#notescreate), [media.store](API_V1.md#mediastore).

**Example request**

```json
{
  "action": "addNote",
  "version": 6,
  "params": {
    "note": {
      "deckName": "Default",
      "modelName": "Basic",
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

### `addNotes`

Create all supplied notes in one native atomic collection batch. Any failed preflight rejects the batch; successful creation returns numeric IDs in input order. Third-party hook I/O and media are outside the collection transaction.

**Parameters:** `addNotes(notes)`

**Returns:** Array of numeric IDs; top-level legacy error on any failed atomic batch.

**Completion:** completed.

**Behavior:** Uses native validation. Eligibility checks do not download media or change the collection. Note creation uses a native transaction; media recovery is separate.

**v1 equivalent:** [notes.createMany](API_V1.md#notescreatemany), [media.store](API_V1.md#mediastore).

**Example request**

```json
{
  "action": "addNotes",
  "version": 6,
  "params": {
    "notes": [
      {
        "deckName": "College::PluginDev",
        "modelName": "non_existent_model",
        "fields": {
          "Front": "front",
          "Back": "bak"
        }
      },
      {
        "deckName": "College::PluginDev",
        "modelName": "Basic",
        "fields": {
          "Front": "front",
          "Back": "bak"
        }
      }
    ]
  }
}
```

### `canAddNotes`

Accepts an array of objects which define parameters for candidate notes (see `addNote`) and returns an array of
booleans indicating whether or not the parameters at the corresponding index could be used to create a new note.

**Parameters:** `canAddNotes(notes)`

**Returns:** Array of booleans.

**Completion:** completed.

**Behavior:** Uses native validation. Eligibility checks do not download media or change the collection. Note creation uses a native transaction; media recovery is separate.

**v1 equivalent:** [notes.validateMany](API_V1.md#notesvalidatemany).

**Example request**

```json
{
  "action": "canAddNotes",
  "version": 6,
  "params": {
    "notes": [
      {
        "deckName": "Default",
        "modelName": "Basic",
        "fields": {
          "Front": "front content",
          "Back": "back content"
        },
        "tags": [
          "yomichan"
        ]
      }
    ]
  }
}
```

### `canAddNotesWithErrorDetail`

Accepts an array of objects which define parameters for candidate notes (see `addNote`) and returns an array of
objects with fields `canAdd` and `error`.

* `canAdd` indicates whether or not the parameters at the corresponding index could be used to create a new note.
* `error` contains an explanation of why a note cannot be added.

**Parameters:** `canAddNotesWithErrorDetail(notes)`

**Returns:** Array of canAdd/error objects.

**Completion:** completed.

**Behavior:** Uses native validation. Eligibility checks do not download media or change the collection. Note creation uses a native transaction; media recovery is separate.

**v1 equivalent:** [notes.validateMany](API_V1.md#notesvalidatemany).

**Example request**

```json
{
  "action": "canAddNotesWithErrorDetail",
  "version": 6,
  "params": {
    "notes": [
      {
        "deckName": "Default",
        "modelName": "Basic",
        "fields": {
          "Front": "front content",
          "Back": "back content"
        },
        "tags": [
          "yomichan"
        ]
      },
      {
        "deckName": "Default",
        "modelName": "Basic",
        "fields": {
          "Front": "front content 2",
          "Back": "back content 2"
        },
        "tags": [
          "yomichan"
        ]
      }
    ]
  }
}
```

### `updateNoteFields`

Update supplied fields of the note identified by `note.id`, with optional inline media. Unknown field names are ignored for legacy compatibility. An affected open editor causes an error rather than a silent overwrite.

**Parameters:** `updateNoteFields(note)`

**Returns:** null.

**Completion:** completed.

**Behavior:** post-write notification and undo; editorConflict replaces silent overwrite.

**v1 equivalent:** [notes.update](API_V1.md#notesupdate), [media.store](API_V1.md#mediastore).

**Example request**

```json
{
  "action": "updateNoteFields",
  "version": 6,
  "params": {
    "note": {
      "id": 1514547547030,
      "fields": {
        "Front": "new front content",
        "Back": "new back content"
      },
      "audio": [
        {
          "url": "https://assets.languagepod101.com/dictionary/japanese/audiomp3.php?kanji=猫&kana=ねこ",
          "filename": "yomichan_ねこ_猫.mp3",
          "skipHash": "7e2c2f954ef6051373ba916f000168dc",
          "fields": [
            "Front"
          ]
        }
      ]
    }
  }
}
```

### `updateNote`

Apply supplied fields and tags together in one note update. Omitted fields or tags are preserved; supplied tags replace the set. At least one must be provided. Fields must be supplied to attach inline media. Validation prevents a tags error from leaving fields partially updated.

**Parameters:** `updateNote(note)`

**Returns:** null.

**Completion:** completed.

**Behavior:** tags validation cannot leave fields partially updated.

**v1 equivalent:** [notes.update](API_V1.md#notesupdate), [media.store](API_V1.md#mediastore).

**Example request**

```json
{
  "action": "updateNote",
  "version": 6,
  "params": {
    "note": {
      "id": 1514547547030,
      "fields": {
        "Front": "new front content",
        "Back": "new back content"
      },
      "tags": [
        "new",
        "tags"
      ]
    }
  }
}
```

### `updateNoteModel`

Update the model, fields, and tags of an existing note.
This allows you to change the note's model, update its fields with new content, and set new tags.

**Parameters:** `updateNoteModel(note)`

**Returns:** null.

**Completion:** completed.

**Behavior:** native conversion; ambiguous mappings return compatibilityError; post-conversion content failure may leave conversion committed and must be reported.

**v1 equivalent:** [notes.planConversion](API_V1.md#notesplanconversion), [notes.convert](API_V1.md#notesconvert), [notes.update](API_V1.md#notesupdate).

**Example request**

```json
{
  "action": "updateNoteModel",
  "version": 6,
  "params": {
    "note": {
      "id": 1514547547030,
      "modelName": "NewModel",
      "fields": {
        "NewField1": "new field 1",
        "NewField2": "new field 2",
        "NewField3": "new field 3"
      },
      "tags": [
        "new",
        "updated",
        "tags"
      ]
    }
  }
}
```

### `updateNoteTags`

Set a note's tags by note ID. Old tags will be removed.

**Parameters:** `updateNoteTags(note, tags)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [notes.update](API_V1.md#notesupdate).

**Example request**

```json
{
  "action": "updateNoteTags",
  "version": 6,
  "params": {
    "note": 1483959289817,
    "tags": [
      "european-languages"
    ]
  }
}
```

### `getNoteTags`

Get a note's tags by note ID.

**Parameters:** `getNoteTags(note)`

**Returns:** Tag string array.

**Completion:** completed.

**v1 equivalent:** [notes.get](API_V1.md#notesget).

**Example request**

```json
{
  "action": "getNoteTags",
  "version": 6,
  "params": {
    "note": 1483959289817
  }
}
```

### `addTags`

Adds tags to notes by note ID.

**Parameters:** `addTags(notes, tags, add=True)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [tags.add](API_V1.md#tagsadd), [tags.remove](API_V1.md#tagsremove).

**Example request**

```json
{
  "action": "addTags",
  "version": 6,
  "params": {
    "notes": [
      1483959289817,
      1483959291695
    ],
    "tags": "european-languages"
  }
}
```

### `removeTags`

Remove tags from notes by note ID.

**Parameters:** `removeTags(notes, tags)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [tags.remove](API_V1.md#tagsremove).

**Example request**

```json
{
  "action": "removeTags",
  "version": 6,
  "params": {
    "notes": [
      1483959289817,
      1483959291695
    ],
    "tags": "european-languages"
  }
}
```

### `getTags`

Gets the complete list of tags for the current user.

**Parameters:** `getTags()`

**Returns:** Tag string array.

**Completion:** completed.

**v1 equivalent:** [tags.list](API_V1.md#tagslist).

**Example request**

```json
{
  "action": "getTags",
  "version": 6,
  "params": {}
}
```

### `clearUnusedTags`

Clears all the unused tags in the notes for the current user.

**Parameters:** `clearUnusedTags()`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [tags.deleteUnused](API_V1.md#tagsdeleteunused).

**Example request**

```json
{
  "action": "clearUnusedTags",
  "version": 6,
  "params": {}
}
```

### `replaceTags`

Replace tags in notes by note ID.

**Parameters:** `replaceTags(notes, tag_to_replace, replace_with_tag)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [tags.replace](API_V1.md#tagsreplace).

**Example request**

```json
{
  "action": "replaceTags",
  "version": 6,
  "params": {
    "notes": [
      1483959289817,
      1483959291695
    ],
    "tag_to_replace": "european-languages",
    "replace_with_tag": "french-languages"
  }
}
```

### `replaceTagsInAllNotes`

Replace tags in all the notes for the current user.

**Parameters:** `replaceTagsInAllNotes(tag_to_replace, replace_with_tag)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [tags.replace](API_V1.md#tagsreplace).

**Example request**

```json
{
  "action": "replaceTagsInAllNotes",
  "version": 6,
  "params": {
    "tag_to_replace": "european-languages",
    "replace_with_tag": "french-languages"
  }
}
```

### `findNotes`

Returns an array of note IDs for a given query. Query syntax is [documented here](https://docs.ankiweb.net/searching.html).

**Parameters:** `findNotes(query=None)`

**Returns:** Array of numeric note IDs.

**Completion:** completed.

**v1 equivalent:** [notes.search](API_V1.md#notessearch).

**Example request**

```json
{
  "action": "findNotes",
  "version": 6,
  "params": {
    "query": "deck:current"
  }
}
```

### `notesInfo`

Returns a list of objects containing for each note ID the note fields, tags, note type, modification time,the cards belonging to
the note and the profile where the note was created.

**Parameters:** `notesInfo(notes=None, query=None)`

**Returns:** Legacy note records with noteId/profile/tags/fields {value,order}/modelName/mod/cards; missing note is {}.

**Completion:** completed.

**Behavior:** existing cardless note returns cards: [].

**v1 equivalent:** [notes.search](API_V1.md#notessearch), [notes.getMany](API_V1.md#notesgetmany), [noteTypes.get](API_V1.md#notetypesget), [collection.get](API_V1.md#collectionget).

**Example request**

```json
{
  "action": "notesInfo",
  "version": 6,
  "params": {
    "notes": [
      1502298033753
    ]
  }
}
```

### `notesModTime`

Returns a list of objects containings for each note ID the modification time.

**Parameters:** `notesModTime(notes)`

**Returns:** Array of {noteId, mod}; missing note is {}.

**Completion:** completed.

**v1 equivalent:** [notes.getMany](API_V1.md#notesgetmany).

**Example request**

```json
{
  "action": "notesModTime",
  "version": 6,
  "params": {
    "notes": [
      1502298033753
    ]
  }
}
```

### `deleteNotes`

Deletes notes with the given ids. If a note has several cards associated with it, all associated cards will be deleted.

**Parameters:** `deleteNotes(notes)`

**Returns:** null.

**Completion:** completed.

**v1 equivalent:** [notes.delete](API_V1.md#notesdelete).

**Example request**

```json
{
  "action": "deleteNotes",
  "version": 6,
  "params": {
    "notes": [
      1502298033753
    ]
  }
}
```

### `removeEmptyNotes`

Return a compatibility error without deleting notes or unused note types. Use v1 `notes.findEmpty` with an explicit criterion, then delete reviewed IDs.

**Parameters:** `removeEmptyNotes()`

**Returns:** Legacy error.

**Completion:** completed.

**Behavior:** always compatibilityError; unused note types and notes remain intact.

**v1 equivalent:** [notes.findEmpty](API_V1.md#notesfindempty), [noteTypes.deleteUnused](API_V1.md#notetypesdeleteunused).

**Example request**

```json
{
  "action": "removeEmptyNotes",
  "version": 6,
  "params": {}
}
```

### `canAddNote`

Check whether a note can be added. Returns a boolean without downloading or storing its media.

**Parameters:** `canAddNote(note)`

**Returns:** Boolean.

**Completion:** completed.

**Behavior:** Uses native validation. Eligibility checks do not download media or change the collection. Note creation uses a native transaction; media recovery is separate.

**v1 equivalent:** [notes.validate](API_V1.md#notesvalidate).

**Example request**

```json
{
  "action": "canAddNote",
  "version": 6,
  "params": {
    "note": {
      "deckName": "Default",
      "modelName": "Basic",
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

### `canAddNoteWithErrorDetail`

Check whether a note can be added and return an eligibility result with an error explanation when rejected.

**Parameters:** `canAddNoteWithErrorDetail(note)`

**Returns:** {canAdd: true} or {canAdd: false, error: message}.

**Completion:** completed.

**Behavior:** Uses native validation. Eligibility checks do not download media or change the collection. Note creation uses a native transaction; media recovery is separate.

**v1 equivalent:** [notes.validate](API_V1.md#notesvalidate).

**Example request**

```json
{
  "action": "canAddNoteWithErrorDetail",
  "version": 6,
  "params": {
    "note": {
      "deckName": "Default",
      "modelName": "Basic",
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

## Statistic Actions

### `getNumCardsReviewedToday`

Gets the count of cards that have been reviewed in the current day (with day start time as configured by user in anki)

**Parameters:** `getNumCardsReviewedToday()`

**Returns:** Integer count.

**Completion:** completed.

**Behavior:** exclude manual/rescheduled history; native day boundaries.

**v1 equivalent:** [statistics.getToday](API_V1.md#statisticsgettoday).

**Example request**

```json
{
  "action": "getNumCardsReviewedToday",
  "version": 6,
  "params": {}
}
```

### `getNumCardsReviewedByDay`

Gets the number of cards reviewed as a list of pairs of `(dateString, number)`

**Parameters:** `getNumCardsReviewedByDay()`

**Returns:** Array of [day string, integer count] descending by day.

**Completion:** completed.

**Behavior:** native graph aggregation, including rollover/DST.

**v1 equivalent:** [statistics.getReviewDays](API_V1.md#statisticsgetreviewdays).

**Example request**

```json
{
  "action": "getNumCardsReviewedByDay",
  "version": 6,
  "params": {}
}
```

### `getCollectionStatsHTML`

Gets the collection statistics report

**Parameters:** `getCollectionStatsHTML(wholeCollection=True)`

**Returns:** HTML string; remains legacyReport, not modern FSRS graphs.

**Completion:** completed.

**v1 equivalent:** [statistics.getHtml](API_V1.md#statisticsgethtml).

**Example request**

```json
{
  "action": "getCollectionStatsHTML",
  "version": 6,
  "params": {
    "wholeCollection": true
  }
}
```

### `cardReviews`

Read review history for the named deck after exclusive `startID` (Unix milliseconds; `0` includes all history). Rows are `[id, cid, usn, ease, ivl, lastIvl, factor, time, type]`, ordered by review ID.

**Parameters:** `cardReviews(deck, startID)`

**Returns:** Arrays [id,cid,usn,ease,ivl,lastIvl,factor,time,type] with numeric legacy encodings.

**Completion:** completed.

**Behavior:** missing deck errors without creation; deterministic ID order; factor meaning preserved.

**v1 equivalent:** [reviews.list](API_V1.md#reviewslist).

**Example request**

```json
{
  "action": "cardReviews",
  "version": 6,
  "params": {
    "deck": "default",
    "startID": 1594194095740
  }
}
```

### `getReviewsOfCards`

Return review history grouped by card ID. Entries contain `id`, `usn`, `ease`, `ivl`, `lastIvl`, `factor`, `time`, and `type`; cards without history have empty arrays. IDs are Unix milliseconds, duration is milliseconds, and signed intervals encode seconds or days.

**Parameters:** `getReviewsOfCards(cards)`

**Returns:** Object keyed by numeric card-ID strings with arrays of {id,usn,ease,ivl,lastIvl,factor,time,type}; no history yields [].

**Completion:** completed.

**v1 equivalent:** [reviews.list](API_V1.md#reviewslist).

**Example request**

```json
{
  "action": "getReviewsOfCards",
  "version": 6,
  "params": {
    "cards": [
      "1653613948202"
    ]
  }
}
```

### `getLatestReviewID`

Return the latest matching review ID in Unix milliseconds, or `0` when the deck has no history. A missing deck is an error.

**Parameters:** `getLatestReviewID(deck)`

**Returns:** Numeric ID, or 0 for null.

**Completion:** completed.

**Behavior:** no read-side deck creation.

**v1 equivalent:** [reviews.getLatestId](API_V1.md#reviewsgetlatestid).

**Example request**

```json
{
  "action": "getLatestReviewID",
  "version": 6,
  "params": {
    "deck": "default"
  }
}
```

### `insertReviews`

Import historical rows `[id, cid, usn, ease, ivl, lastIvl, factor, time, type]` in one validated transaction. Review IDs are Unix milliseconds. Client `usn` is ignored and stored as local unsynced metadata. This clears undo and does not answer cards or change their current scheduling.

**Parameters:** `insertReviews(reviews)`

**Returns:** null after import final; empty input is no-op.

**Completion:** final operation.

**Behavior:** validated/bound/transactional history-only import; clears undo; no implicit card answer/reschedule.

**v1 equivalent:** [advanced.reviews.import](API_V1.md#advancedreviewsimport).

**Example request**

```json
{
  "action": "insertReviews",
  "version": 6,
  "params": {
    "reviews": [
      [
        1594194095746,
        1485369733217,
        -1,
        3,
        4,
        -60,
        2500,
        6157,
        0
      ],
      [
        1594201393292,
        1485369902086,
        -1,
        1,
        -60,
        -60,
        0,
        4846,
        0
      ]
    ]
  }
}
```

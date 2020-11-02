# Note Actions

*   **addNote**

    Creates a note using the given deck and model, with the provided field values and tags. Returns the identifier of
    the created note created on success, and `null` on failure.

    AnkiConnect can download audio files and embed them in newly created notes. The corresponding `audio` note member is
    optional and can be omitted. If you choose to include it, it should contain a single object or an array of objects
    with mandatory `url` and `filename` fields. The `skipHash` field can be optionally provided to skip the inclusion of
    downloaded files with an MD5 hash that matches the provided value. This is useful for avoiding the saving of error
    pages and stub files. The `fields` member is a list of fields that should play audio when the card is displayed in
    Anki. The `allowDuplicate` member inside `options` group can be set to true to enable adding duplicate cards.
    Normally duplicate cards can not be added and trigger exception.

    The `duplicateScope` member inside `options` can be used to specify the scope for which duplicates are checked.
    A value of `"deckName"` will only check for duplicates in the target deck; any other value will check the entire collection.
    The `duplicateScopeOptions` object can be used to specify some additional settings. `duplicateScopeOptions.deckName`
    will specify which deck to use for checking duplicates in. If undefined or `null`, the target deck will be used.
    `duplicateScopeOptions.checkChildren` will change whether or not duplicate cards are checked in child decks;
    the default value is `false`.

    *Sample request*:
    ```json
    {
        "action": "addNote",
        "version": 6,
        "params": {
            "note": {
                "deckName": "Default",
                "modelName": "Basic",
                "fields": {
                    "Front": "front content",
                    "Back": "back content"
                },
                "options": {
                    "allowDuplicate": false,
                    "duplicateScope": "deck",
                    "duplicateScopeOptions": {
                        "deckName": "Default",
                        "checkChildren": false
                    }
                },
                "tags": [
                    "yomichan"
                ],
                "audio": [{
                    "url": "https://assets.languagepod101.com/dictionary/japanese/audiomp3.php?kanji=猫&kana=ねこ",
                    "filename": "yomichan_ねこ_猫.mp3",
                    "skipHash": "7e2c2f954ef6051373ba916f000168dc",
                    "fields": [
                        "Front"
                    ]
                }]
            }
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": 1496198395707,
        "error": null
    }
    ```

*   **addNotes**

    Creates multiple notes using the given deck and model, with the provided field values and tags. Returns an array of
    identifiers of the created notes (notes that could not be created will have a `null` identifier). Please see the
    documentation for `addNote` for an explanation of objects in the `notes` array.

    *Sample request*:
    ```json
    {
        "action": "addNotes",
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
                    ],
                    "audio": [{
                        "url": "https://assets.languagepod101.com/dictionary/japanese/audiomp3.php?kanji=猫&kana=ねこ",
                        "filename": "yomichan_ねこ_猫.mp3",
                        "skipHash": "7e2c2f954ef6051373ba916f000168dc",
                        "fields": [
                            "Front"
                        ]
                    }]
                }
            ]
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": [1496198395707, null],
        "error": null
    }
    ```

*   **canAddNotes**

    Accepts an array of objects which define parameters for candidate notes (see `addNote`) and returns an array of
    booleans indicating whether or not the parameters at the corresponding index could be used to create a new note.

    *Sample request*:
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

    *Sample result*:
    ```json
    {
        "result": [true],
        "error": null
    }
    ```

*   **updateNoteFields**

    Modify the fields of an exist note. You can also include audio files which will be added to the note with an
    optional `audio` property. Please see the documentation for `addNote` for an explanation of objects in the `audio` array.

    *Sample request*:
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
                "audio": [{
                    "url": "https://assets.languagepod101.com/dictionary/japanese/audiomp3.php?kanji=猫&kana=ねこ",
                    "filename": "yomichan_ねこ_猫.mp3",
                    "skipHash": "7e2c2f954ef6051373ba916f000168dc",
                    "fields": [
                        "Front"
                    ]
                }]
            }
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": null,
        "error": null
    }
    ```

*   **addTags**

    Adds tags to notes by note ID.

    *Sample request*:
    ```json
    {
        "action": "addTags",
        "version": 6,
        "params": {
            "notes": [1483959289817, 1483959291695],
            "tags": "european-languages"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": null,
        "error": null
    }
    ```

*   **removeTags**

    Remove tags from notes by note ID.

    *Sample request*:
    ```json
    {
        "action": "removeTags",
        "version": 6,
        "params": {
            "notes": [1483959289817, 1483959291695],
            "tags": "european-languages"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": null,
        "error": null
    }
    ```

*   **getTags**

    Gets the complete list of tags for the current user.

    *Sample request*:
    ```json
    {
        "action": "getTags",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result": ["european-languages", "idioms"],
        "error": null
    }
    ```

*   **findNotes**

    Returns an array of note IDs for a given query. Same query syntax as `guiBrowse`.

    *Sample request*:
    ```json
    {
        "action": "findNotes",
        "version": 6,
        "params": {
            "query": "deck:current"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": [1483959289817, 1483959291695],
        "error": null
    }
    ```

*   **notesInfo**

    Returns a list of objects containing for each note ID the note fields, tags, note type and the cards belonging to
    the note.

    *Sample request*:
    ```json
    {
        "action": "notesInfo",
        "version": 6,
        "params": {
            "notes": [1502298033753]
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": [
            {
                "noteId":1502298033753,
                "modelName": "Basic",
                "tags":["tag","another_tag"],
                "fields": {
                    "Front": {"value": "front content", "order": 0},
                    "Back": {"value": "back content", "order": 1}
                }
            }
        ],
        "error": null
    }
    ```


*   **deleteNotes**

    Deletes notes with the given ids. If a note has several cards associated with it, all associated cards will be deleted.

    *Sample request*:
    ```json
    {
        "action": "deleteNotes",
        "version": 6,
        "params": {
            "notes": [1502298033753]
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": null,
        "error": null
    }
    ```

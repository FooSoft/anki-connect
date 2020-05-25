# Graphical Actions

*   **guiBrowse**

    Invokes the *Card Browser* dialog and searches for a given query. Returns an array of identifiers of the cards that
    were found.

    *Sample request*:
    ```json
    {
        "action": "guiBrowse",
        "version": 6,
        "params": {
            "query": "deck:current"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": [1494723142483, 1494703460437, 1494703479525],
        "error": null
    }
    ```

*   **guiAddCards**

    Invokes the *Add Cards* dialog, presets the note using the given deck and model, with the provided field values and tags.
    Invoking it multiple times closes the old window and _reopen the window_ with the new provided values.

    The `closeAfterAdding` member inside `options` group can be set to true to create a dialog that closes upon adding the note.
    Invoking the action mutliple times with this option will create _multiple windows_.

    The result is the ID of the note which would be added, if the user chose to confirm the *Add Cards* dialogue.

    *Sample request*:
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
                "options": {
                    "closeAfterAdding": true
                },
                "tags": [
                  "countries"
                ]
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

*   **guiCurrentCard**

    Returns information about the current card or `null` if not in review mode.

    *Sample request*:
    ```json
    {
        "action": "guiCurrentCard",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result": {
            "answer": "back content",
            "question": "front content",
            "deckName": "Default",
            "modelName": "Basic",
            "fieldOrder": 0,
            "fields": {
                "Front": {"value": "front content", "order": 0},
                "Back": {"value": "back content", "order": 1}
            },
            "template": "Forward",
            "cardId": 1498938915662,
            "buttons": [1, 2, 3],
            "nextReviews": ["<1m", "<10m", "4d"]
        },
        "error": null
    }
    ```

*   **guiStartCardTimer**

    Starts or resets the `timerStarted` value for the current card. This is useful for deferring the start time to when
    it is displayed via the API, allowing the recorded time taken to answer the card to be more accurate when calling
    `guiAnswerCard`.

    *Sample request*:
    ```json
    {
        "action": "guiStartCardTimer",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result": true,
        "error": null
    }
    ```

*   **guiShowQuestion**

    Shows question text for the current card; returns `true` if in review mode or `false` otherwise.

    *Sample request*:
    ```json
    {
        "action": "guiShowQuestion",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result": true,
        "error": null
    }
    ```

*   **guiShowAnswer**

    Shows answer text for the current card; returns `true` if in review mode or `false` otherwise.

    *Sample request*:
    ```json
    {
        "action": "guiShowAnswer",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result": true,
        "error": null
    }
    ```

*   **guiAnswerCard**

    Answers the current card; returns `true` if succeeded or `false` otherwise. Note that the answer for the current
    card must be displayed before before any answer can be accepted by Anki.

    *Sample request*:
    ```json
    {
        "action": "guiAnswerCard",
        "version": 6,
        "params": {
            "ease": 1
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": true,
        "error": null
    }
    ```

*   **guiDeckOverview**

    Opens the *Deck Overview* dialog for the deck with the given name; returns `true` if succeeded or `false` otherwise.

    *Sample request*:
    ```json
    {
        "action": "guiDeckOverview",
        "version": 6,
        "params": {
            "name": "Default"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": true,
        "error": null
    }
    ```

*   **guiDeckBrowser**

    Opens the *Deck Browser* dialog.

    *Sample request*:
    ```json
    {
        "action": "guiDeckBrowser",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result": null,
        "error": null
    }
    ```

*   **guiDeckReview**

    Starts review for the deck with the given name; returns `true` if succeeded or `false` otherwise.

    *Sample request*:
    ```json
    {
        "action": "guiDeckReview",
        "version": 6,
        "params": {
            "name": "Default"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": true,
        "error": null
    }
    ```

*   **guiExitAnki**

    Schedules a request to gracefully close Anki. This operation is asynchronous, so it will return immediately and
    won't wait until the Anki process actually terminates.

    *Sample request*:
    ```json
    {
        "action": "guiExitAnki",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result": null,
        "error": null
    }
    ```

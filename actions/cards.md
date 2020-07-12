# Card Actions

*   **getEaseFactors**

    Returns an array with the ease factor for each of the given cards (in the same order).

    *Sample request*:
    ```json
    {
        "action": "getEaseFactors",
        "version": 6,
        "params": {
            "cards": [1483959291685, 1483959293217]
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": [4100, 3900],
        "error": null
    }
    ```

*   **setEaseFactors**

    Sets ease factor of cards by card ID; returns `true` if successful (all cards existed) or `false` otherwise.

    *Sample request*:
    ```json
    {
        "action": "setEaseFactors",
        "version": 6,
        "params": {
            "cards": [1483959291685, 1483959293217],
            "easeFactors": [4100, 3900]
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": [true, true],
        "error": null
    }
    ```

*   **suspend**

    Suspend cards by card ID; returns `true` if successful (at least one card wasn't already suspended) or `false`
    otherwise.

    *Sample request*:
    ```json
    {
        "action": "suspend",
        "version": 6,
        "params": {
            "cards": [1483959291685, 1483959293217]
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

*   **unsuspend**

    Unsuspend cards by card ID; returns `true` if successful (at least one card was previously suspended) or `false`
    otherwise.

    *Sample request*:
    ```json
    {
        "action": "unsuspend",
        "version": 6,
        "params": {
            "cards": [1483959291685, 1483959293217]
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

*   **areSuspended**

    Returns an array indicating whether each of the given cards is suspended (in the same order).

    *Sample request*:
    ```json
    {
        "action": "areSuspended",
        "version": 6,
        "params": {
            "cards": [1483959291685, 1483959293217]
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": [false, true],
        "error": null
    }
    ```

*   **areDue**

    Returns an array indicating whether each of the given cards is due (in the same order). *Note*: cards in the
    learning queue with a large interval (over 20 minutes) are treated as not due until the time of their interval has
    passed, to match the way Anki treats them when reviewing.

    *Sample request*:
    ```json
    {
        "action": "areDue",
        "version": 6,
        "params": {
            "cards": [1483959291685, 1483959293217]
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": [false, true],
        "error": null
    }
    ```

*   **getIntervals**

    Returns an array of the most recent intervals for each given card ID, or a 2-dimensional array of all the intervals
    for each given card ID when `complete` is `true`. Negative intervals are in seconds and positive intervals in days.

    *Sample request 1*:
    ```json
    {
        "action": "getIntervals",
        "version": 6,
        "params": {
            "cards": [1502298033753, 1502298036657]
        }
    }
    ```

    *Sample result 1*:
    ```json
    {
        "result": [-14400, 3],
        "error": null
    }
    ```

    *Sample request 2*:
    ```json
    {
        "action": "getIntervals",
        "version": 6,
        "params": {
            "cards": [1502298033753, 1502298036657],
            "complete": true
        }
    }
    ```

    *Sample result 2*:
    ```json
    {
        "result": [
            [-120, -180, -240, -300, -360, -14400],
            [-120, -180, -240, -300, -360, -14400, 1, 3]
        ],
        "error": null
    }
    ```

*   **findCards**

    Returns an array of card IDs for a given query. Functionally identical to `guiBrowse` but doesn't use the GUI for
    better performance.

    *Sample request*:
    ```json
    {
        "action": "findCards",
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

*   **cardsToNotes**

    Returns an unordered array of note IDs for the given card IDs. For cards with the same note, the ID is only given
    once in the array.

    *Sample request*:
    ```json
    {
        "action": "cardsToNotes",
        "version": 6,
        "params": {
            "cards": [1502098034045, 1502098034048, 1502298033753]
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": [1502098029797, 1502298025183],
        "error": null
    }
    ```

*   **cardsInfo**

    Returns a list of objects containing for each card ID the card fields, front and back sides including CSS, note
    type, the note that the card belongs to, and deck name, as well as ease and interval.

    *Sample request*:
    ```json
    {
        "action": "cardsInfo",
        "version": 6,
        "params": {
            "cards": [1498938915662, 1502098034048]
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": [
            {
                "answer": "back content",
                "question": "front content",
                "deckName": "Default",
                "modelName": "Basic",
                "fieldOrder": 1,
                "fields": {
                    "Front": {"value": "front content", "order": 0},
                    "Back": {"value": "back content", "order": 1}
                },
                "css":"p {font-family:Arial;}",
                "cardId": 1498938915662,
                "interval": 16,
                "note":1502298033753,
                "ord": 1,
                "type": 0,
                "queue": 0,
                "due": 1,
                "reps": 1,
                "lapses": 0,
                "left": 6
            },
            {
                "answer": "back content",
                "question": "front content",
                "deckName": "Default",
                "modelName": "Basic",
                "fieldOrder": 0,
                "fields": {
                    "Front": {"value": "front content", "order": 0},
                    "Back": {"value": "back content", "order": 1}
                },
                "css":"p {font-family:Arial;}",
                "cardId": 1502098034048,
                "interval": 23,
                "note":1502298033753,
                "ord": 1,
                "type": 0,
                "queue": 0,
                "due": 1,
                "reps": 1,
                "lapses": 0,
                "left": 6
            }
        ],
        "error": null
    }
    ```

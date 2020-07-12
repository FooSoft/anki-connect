# Miscellaneous Actions

*   **version**

    Gets the version of the API exposed by this plugin. Currently versions `1` through `6` are defined.

    This should be the first call you make to make sure that your application and AnkiConnect are able to communicate
    properly with each other. New versions of AnkiConnect are backwards compatible; as long as you are using actions
    which are available in the reported AnkiConnect version or earlier, everything should work fine.

    *Sample request*:
    ```json
    {
        "action": "version",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result": 6,
        "error": null
    }
    ```

*   **sync**

    Synchronizes the local Anki collections with AnkiWeb.

    *Sample request*:
    ```json
    {
        "action": "sync",
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

*   **getProfiles**

    Retrieve the list of profiles.

    *Sample request*:
    ```json
    {
        "action": "getProfiles",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result": ["User 1"],
        "error": null
    }
    ```

*   **loadProfile**

    Selects the profile specified in request.

    *Sample request*:
    ```json
    {
        "action": "loadProfile",
        "params": {
            "name": "user1"
        },
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

*   **multi**

    Performs multiple actions in one request, returning an array with the response of each action (in the given order).

    *Sample request*:
    ```json
    {
        "action": "multi",
        "version": 6,
        "params": {
            "actions": [
                {"action": "deckNames"},
                {
                    "action": "browse",
                    "params": {"query": "deck:current"}
                }
            ]
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": [
            {"result": "Default", "error": null},
            {"result": [1494723142483, 1494703460437, 1494703479525], "error": null}
        ],
        "error": null
    }
    ```

*   **exportPackage**

    Exports a given deck in `.apkg` format. Returns `true` if successful or `false` otherwise. The optional property
    `includeSched` (default is `false`) can be specified to include the cards' scheduling data.

    *Sample request*:
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

    *Sample result*:
    ```json
    {
        "result": true,
        "error": null
    }
    ```

*   **importPackage**

    Imports a file in `.apkg` format into the collection. Returns `true` if successful or `false` otherwise.
    Note that the file path is relative to Anki's collection.media folder, not to the client.

    *Sample request*:
    ```json
    {
        "action": "importPackage",
        "version": 6,
        "params": {
            "path": "/data/Deck.apkg"
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

*   **reloadCollection**

    Tells anki to reload all data from the database.
    
    *Sample request*:
    ```json
    {
        "action": "reloadCollection",
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
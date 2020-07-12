# Deck Actions

*   **deckNames**

    Gets the complete list of deck names for the current user.

    *Sample request*:
    ```json
    {
        "action": "deckNames",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result": ["Default"],
        "error": null
    }
    ```

*   **deckNamesAndIds**

    Gets the complete list of deck names and their respective IDs for the current user.

    *Sample request*:
    ```json
    {
        "action": "deckNamesAndIds",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result": {"Default": 1},
        "error": null
    }
    ```

*   **getDecks**

    Accepts an array of card IDs and returns an object with each deck name as a key, and its value an array of the given
    cards which belong to it.

    *Sample request*:
    ```json
    {
        "action": "getDecks",
        "version": 6,
        "params": {
            "cards": [1502298036657, 1502298033753, 1502032366472]
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": {
            "Default": [1502032366472],
            "Japanese::JLPT N3": [1502298036657, 1502298033753]
        },
        "error": null
    }
    ```

*   **createDeck**

    Create a new empty deck. Will not overwrite a deck that exists with the same name.

    *Sample request*:
    ```json
    {
        "action": "createDeck",
        "version": 6,
        "params": {
            "deck": "Japanese::Tokyo"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": 1519323742721,
        "error": null
    }
    ```
*   **changeDeck**

    Moves cards with the given IDs to a different deck, creating the deck if it doesn't exist yet.

    *Sample request*:
    ```json
    {
        "action": "changeDeck",
        "version": 6,
        "params": {
            "cards": [1502098034045, 1502098034048, 1502298033753],
            "deck": "Japanese::JLPT N3"
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

*   **deleteDecks**

    Deletes decks with the given names. If `cardsToo` is `true` (defaults to `false` if unspecified), the cards within
    the deleted decks will also be deleted; otherwise they will be moved to the default deck.

    *Sample request*:
    ```json
    {
        "action": "deleteDecks",
        "version": 6,
        "params": {
            "decks": ["Japanese::JLPT N5", "Easy Spanish"],
            "cardsToo": true
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

*   **getDeckConfig**

    Gets the configuration group object for the given deck.

    *Sample request*:
    ```json
    {
        "action": "getDeckConfig",
        "version": 6,
        "params": {
            "deck": "Default"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": {
            "lapse": {
                "leechFails": 8,
                "delays": [10],
                "minInt": 1,
                "leechAction": 0,
                "mult": 0
            },
            "dyn": false,
            "autoplay": true,
            "mod": 1502970872,
            "id": 1,
            "maxTaken": 60,
            "new": {
                "bury": true,
                "order": 1,
                "initialFactor": 2500,
                "perDay": 20,
                "delays": [1, 10],
                "separate": true,
                "ints": [1, 4, 7]
            },
            "name": "Default",
            "rev": {
                "bury": true,
                "ivlFct": 1,
                "ease4": 1.3,
                "maxIvl": 36500,
                "perDay": 100,
                "minSpace": 1,
                "fuzz": 0.05
            },
            "timer": 0,
            "replayq": true,
            "usn": -1
        },
        "error": null
    }
    ```

*   **saveDeckConfig**

    Saves the given configuration group, returning `true` on success or `false` if the ID of the configuration group is
    invalid (such as when it does not exist).

    *Sample request*:
    ```json
    {
        "action": "saveDeckConfig",
        "version": 6,
        "params": {
            "config": {
                "lapse": {
                    "leechFails": 8,
                    "delays": [10],
                    "minInt": 1,
                    "leechAction": 0,
                    "mult": 0
                },
                "dyn": false,
                "autoplay": true,
                "mod": 1502970872,
                "id": 1,
                "maxTaken": 60,
                "new": {
                    "bury": true,
                    "order": 1,
                    "initialFactor": 2500,
                    "perDay": 20,
                    "delays": [1, 10],
                    "separate": true,
                    "ints": [1, 4, 7]
                },
                "name": "Default",
                "rev": {
                    "bury": true,
                    "ivlFct": 1,
                    "ease4": 1.3,
                    "maxIvl": 36500,
                    "perDay": 100,
                    "minSpace": 1,
                    "fuzz": 0.05
                },
                "timer": 0,
                "replayq": true,
                "usn": -1
            }
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

*   **setDeckConfigId**

    Changes the configuration group for the given decks to the one with the given ID. Returns `true` on success or
    `false` if the given configuration group or any of the given decks do not exist.

    *Sample request*:
    ```json
    {
        "action": "setDeckConfigId",
        "version": 6,
        "params": {
            "decks": ["Default"],
            "configId": 1
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

*   **cloneDeckConfigId**

    Creates a new configuration group with the given name, cloning from the group with the given ID, or from the default
    group if this is unspecified. Returns the ID of the new configuration group, or `false` if the specified group to
    clone from does not exist.

    *Sample request*:
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

    *Sample result*:
    ```json
    {
        "result": 1502972374573,
        "error": null
    }
    ```

*   **removeDeckConfigId**

    Removes the configuration group with the given ID, returning `true` if successful, or `false` if attempting to
    remove either the default configuration group (ID = 1) or a configuration group that does not exist.

    *Sample request*:
    ```json
    {
        "action": "removeDeckConfigId",
        "version": 6,
        "params": {
            "configId": 1502972374573
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

*   **updateCompleteDeck**

    Pastes all transmitted data into the database and reloads the collection. 
    You can send a deckName and corresponding cards, notes & models. 
    All cards are assumed to belong to the given deck.
    All notes referenced by given cards should be present. 
    All models referenced by given notes should be present.

    *Sample request*:
    ```json
    {
        "action": "updateCompleteDeck",
        "version": 6,
        "params": {
            "data":  {
                "deck": "test3",
                "cards": {
                     "1485369472028": {
                         "id": 1485369472028,
                         "nid": 1485369340204,
                         "ord": 0,
                         "type": 0,
                         "queue": 0,
                         "due": 1186031,
                         "factor": 0,
                         "ivl": 0,
                         "reps": 0,
                         "lapses": 0,
                         "left": 0
                     }
                },
                "notes": {
                    "1485369340204": {
                        "id": 1485369340204,
                        "mid": 1375786181313,
                        "fields": [
                            "frontValue",
                            "backValue"
                        ],
                        "tags": [
                            "aTag"
                        ]
                    }
                },
                "models": {
                    "1375786181313": {
                        "id": 1375786181313,
                        "name": "anotherModel",
                        "fields": [
                            "Front",
                            "Back"
                        ],
                        "templateNames": [
                            "Card 1"
                        ]
                    }
                }
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
# AnkiConnect

AnkiConnect enables external applications such as [Yomichan](https://foosoft.net/projects/yomichan/) to communicate with
[Anki](https://apps.ankiweb.net/) over a simple HTTP API. Its capabilities include executing queries against the user's
card deck, automatically creating new cards, and more. AnkiConnect is compatible with the latest stable (2.1.x) releases
of Anki; older versions (2.0.x and below) are no longer supported.

## Installation

The installation process is similar to other Anki plugins and can be accomplished in three steps:

1.  Open the `Install Add-on` dialog by selecting `Tools` | `Add-ons` | `Get Add-ons...` in Anki.
2.  Input [2055492159](https://ankiweb.net/shared/info/2055492159) into the text box labeled `Code` and press the `OK` button to proceed.
3.  Restart Anki when prompted to do so in order to complete the installation of AnkiConnect.

Anki must be kept running in the background in order for other applications to be able to use AnkiConnect. You can
verify that AnkiConnect is running at any time by accessing `localhost:8765` in your browser. If the server is running,
you will see the message `AnkiConnect` displayed in your browser window.

### Notes for Windows Users

Windows users may see a firewall nag dialog box appear on Anki startup. This occurs because AnkiConnect runs a local
HTTP server in order to enable other applications to connect to it. The host application, Anki, must be unblocked for
this plugin to function correctly.

### Notes for macOS Users

Starting with [Mac OS X Mavericks](https://en.wikipedia.org/wiki/OS_X_Mavericks), a feature named *App Nap* has been
introduced to the operating system. This feature causes certain applications which are open (but not visible) to be
placed in a suspended state. As this behavior causes AnkiConnect to stop working while you have another window in the
foreground, App Nap should be disabled for Anki:

1.  Start the Terminal application.
2.  Execute the following commands in the terminal window:
    ```bash
    defaults write net.ankiweb.dtop NSAppSleepDisabled -bool true
    defaults write net.ichi2.anki NSAppSleepDisabled -bool true
    defaults write org.qt-project.Qt.QtWebEngineCore NSAppSleepDisabled -bool true
    ```
3.  Restart Anki.

## Application Interface for Developers

AnkiConnect exposes internal Anki features to external applications via an easy to use API. After being installed, this
plugin will start an HTTP server on port 8765 whenever Anki is launched. Other applications (including browser
extensions) can then communicate with it via HTTP requests.

By default, AnkiConnect will only bind the HTTP server to the `127.0.0.1` IP address, so that you will only be able to
access it from the same host on which it is running. If you need to access it over a network, you can set the
environment variable `ANKICONNECT_BIND_ADDRESS` to change the binding address. For example, you can set it to `0.0.0.0`
in order to bind it to all network interfaces on your host.

### Sample Invocation

Every request consists of a JSON-encoded object containing an `action`, a `version`, contextual `params`, and a `key`
value used for authentication (which is optional and can be omitted by default). AnkiConnect will respond with an object
containing two fields: `result` and `error`. The `result` field contains the return value of the executed API, and the
`error` field is a description of any exception thrown during API execution (the value `null` is used if execution
completed successfully).

*Sample successful response*:
```json
{"result": ["Default", "Filtered Deck 1"], "error": null}
```

*Samples of failed responses*:
```json
{"result": null, "error": "unsupported action"}
```
```json
{"result": null, "error": "guiBrowse() got an unexpected keyword argument 'foobar'"}
```

For compatibility with clients designed to work with older versions of AnkiConnect, failing to provide a `version` field
in the request will make the version default to 4. Furthermore, when the provided version is level 4 or below, the API
response will only contain the value of the `result`; no `error` field is available for error handling.

You can use whatever language or tool you like to issue request to AnkiConnect, but a couple of simple examples are
included below as reference.

#### Curl

```bash
curl localhost:8765 -X POST -d "{\"action\": \"deckNames\", \"version\": 6}"
```

#### Python

```python
import json
import urllib.request

def request(action, **params):
    return {'action': action, 'params': params, 'version': 6}

def invoke(action, **params):
    requestJson = json.dumps(request(action, **params)).encode('utf-8')
    response = json.load(urllib.request.urlopen(urllib.request.Request('http://localhost:8765', requestJson)))
    if len(response) != 2:
        raise Exception('response has an unexpected number of fields')
    if 'error' not in response:
        raise Exception('response is missing required error field')
    if 'result' not in response:
        raise Exception('response is missing required result field')
    if response['error'] is not None:
        raise Exception(response['error'])
    return response['result']

invoke('createDeck', deck='test1')
result = invoke('deckNames')
print('got list of decks: {}'.format(result))
```

#### JavaScript

```javascript
function invoke(action, version, params={}) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.addEventListener('error', () => reject('failed to issue request'));
        xhr.addEventListener('load', () => {
            try {
                const response = JSON.parse(xhr.responseText);
                if (Object.getOwnPropertyNames(response).length != 2) {
                    throw 'response has an unexpected number of fields';
                }
                if (!response.hasOwnProperty('error')) {
                    throw 'response is missing required error field';
                }
                if (!response.hasOwnProperty('result')) {
                    throw 'response is missing required result field';
                }
                if (response.error) {
                    throw response.error;
                }
                resolve(response.result);
            } catch (e) {
                reject(e);
            }
        });

        xhr.open('POST', 'http://127.0.0.1:8765');
        xhr.send(JSON.stringify({action, version, params}));
    });
}

await invoke('createDeck', 6, {deck: 'test1'});
const result = await invoke('deckNames', 6);
console.log(`got list of decks: ${result}`);
```

### Hey, could you add a new action to support $FEATURE?

The primary goal for AnkiConnect was to support real-time flash card creation from the
[Yomichan](https://foosoft.net/projects/yomichan/) browser extension. The current API provides all the required actions
to make this happen. I recognise that the role of AnkiConnect has evolved from this original vision, and I am happy to
review new feature requests.

With that said, *this project operates on a self-serve model*. If you would like a new feature, create a PR. I'll review
it and if it looks good, it will be merged in. *Requests to add new features without accompanying PRs will not be
serviced*. Make sure that your PRs meet the following criteria:

*   Attempt to match style of the surrounding code.
*   Have accompanying documentation with examples.
*   Have accompanying tests that verify operation.
*   Implement features useful in other applications.

### Supported Actions

Documentation for currently supported actions is split up by category and is referenced below. Note that deprecated APIs
will continue to function despite not being listed on this page as long as your request is labeled with a version number
corresponding to when the API was available for use.

* [Card Actions](#card-actions)
* [Deck Actions](#deck-actions)
* [Graphical Actions](#graphical-actions)
* [Media Actions](#media-actions)
* [Miscellaneous Actions](#miscellaneous-actions)
* [Model Actions](#model-actions)
* [Note Actions](#note-actions)
* [Statistic Actions](#statistic-actions)

#### Card Actions

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

*   **suspended**

    Check if card is suspended by its ID. Returns `true` if suspended, `false` otherwise.

    *Sample request*:
    ```json
    {
        "action": "suspended",
        "version": 6,
        "params": {
            "card": 1483959293217
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

    Returns an array indicating whether each of the given cards is suspended (in the same order). If card doesn't
    exist returns `null`.

    *Sample request*:
    ```json
    {
        "action": "areSuspended",
        "version": 6,
        "params": {
            "cards": [1483959291685, 1483959293217, 1234567891234]
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": [false, true, null],
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

*   **forgetCards**

    Forget cards, making the cards new again.

    *Sample request*:
    ```json
    {
        "action": "forgetCards",
        "version": 6,
        "params": {
            "cards": [1498938915662, 1502098034048]
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

*   **relearnCards**

    Make cards be "relearning".

    *Sample request*:
    ```json
    {
        "action": "relearnCards",
        "version": 6,
        "params": {
            "cards": [1498938915662, 1502098034048]
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

#### Deck Actions

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
    You can send a deckName and corresponding cards, notes and models.
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

#### Graphical Actions

*   **guiBrowse**

    Invokes the *Card Browser* dialog and searches for a given query. Returns an array of identifiers of the cards that
    were found. Query syntax is [documented here](https://docs.ankiweb.net/#/searching).

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

    Audio, video, and picture files can be embedded into the fields via the `audio`, `video`, and `picture` keys, respectively.
    Refer to the documentation of `addNote` and `storeMediaFile` for an explanation of these fields.

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
                ],
                "picture": [{
                    "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/13/EU-Romania.svg/285px-EU-Romania.svg.png",
                    "filename": "romania.png",
                    "fields": [
                        "Extra"
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

*   **guiCheckDatabase**

    Requests a database check, but returns immediately without waiting for the check to complete. Therefore, the action will always return `true` even if errors are detected during the database check.

    *Sample request*:
    ```json
    {
        "action": "guiCheckDatabase",
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

#### Media Actions

*   **storeMediaFile**

    Stores a file with the specified base64-encoded contents inside the media folder. Alternatively you can specify a
    absolute file path, or a url from where the file shell be downloaded. If more than one of `data`, `path` and `url` are provided, the `data` field will be used first, then `path`, and finally `url`. To prevent Anki from removing files not used by any cards (e.g. for configuration files), prefix the filename with an underscore. These files are still synchronized to AnkiWeb.
    Any existing file with the same name is deleted by default. Set `deleteExisting` to false to prevent that
    by [letting Anki give the new file a non-conflicting name](https://github.com/ankitects/anki/blob/aeba725d3ea9628c73300648f748140db3fdd5ed/rslib/src/media/files.rs#L194).

    *Sample request*:
    ```json
    {
        "action": "storeMediaFile",
        "version": 6,
        "params": {
            "filename": "_hello.txt",
            "data": "SGVsbG8sIHdvcmxkIQ=="
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": "_hello.txt",
        "error": null
    }
    ```

    *Content of `_hello.txt`*:
    ```
    Hello world!
    ```

    *Sample request*:
    ```json
    {
        "action": "storeMediaFile",
        "version": 6,
        "params": {
            "filename": "_hello.txt",
            "path": "/path/to/file"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": "_hello.txt",
        "error": null
    }
    ```

    *Sample request*:
    ```json
    {
        "action": "storeMediaFile",
        "version": 6,
        "params": {
            "filename": "_hello.txt",
            "url": "https://url.to.file"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": "_hello.txt",
        "error": null
    }
    ```

*   **retrieveMediaFile**

    Retrieves the base64-encoded contents of the specified file, returning `false` if the file does not exist.

    *Sample request*:
    ```json
    {
        "action": "retrieveMediaFile",
        "version": 6,
        "params": {
            "filename": "_hello.txt"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": "SGVsbG8sIHdvcmxkIQ==",
        "error": null
    }
    ```

*   **getMediaFilesNames**

    Gets the names of media files matched the pattern. Returning all names by default.

    *Sample request*:
    ```json
    {
        "action": "getMediaFilesNames",
        "version": 6,
        "params": {
            "pattern": "_hell*.txt"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": ["_hello.txt"],
        "error": null
    }
    ```

*   **deleteMediaFile**

    Deletes the specified file inside the media folder.

    *Sample request*:
    ```json
    {
        "action": "deleteMediaFile",
        "version": 6,
        "params": {
            "filename": "_hello.txt"
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

#### Miscellaneous Actions

*   **requestPermission**

    Request permission to use the API exposed by this plugin. Only request coming from origin listed in the
    `webCorsOriginList` option are allowed to use the Api. Calling this method will display a popup asking the user
    if he want to allow your origin to use the Api. This is the only method that can be called even if the origin of
    the request isn't in the `webCorsOriginList` list. It also doesn't require the api key. Calling this method will
    not display the popup if the origin is already trusted.

    This should be the first call you make to make sure that your application and AnkiConnect are able to communicate
    properly with each other. New versions of AnkiConnect are backwards compatible; as long as you are using actions
    which are available in the reported AnkiConnect version or earlier, everything should work fine.

    *Sample request*:
    ```json
    {
        "action": "requestPermission",
        "version": 6
    }
    ```

    *Samples results*:
    ```json
    {
        "result": {
            "permission": "granted",
            "requireApiKey": false,
            "version": 6
        },
        "error": null
    }
    ```
    ```json
    {
        "result": {
            "permission": "denied"
        },
        "error": null
    }
    ```

*   **version**

    Gets the version of the API exposed by this plugin. Currently versions `1` through `6` are defined.

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

#### Model Actions

*   **modelNames**

    Gets the complete list of model names for the current user.

    *Sample request*:
    ```json
    {
        "action": "modelNames",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result": ["Basic", "Basic (and reversed card)"],
        "error": null
    }
    ```

*   **modelNamesAndIds**

    Gets the complete list of model names and their corresponding IDs for the current user.

    *Sample request*:
    ```json
    {
        "action": "modelNamesAndIds",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result": {
            "Basic": 1483883011648,
            "Basic (and reversed card)": 1483883011644,
            "Basic (optional reversed card)": 1483883011631,
            "Cloze": 1483883011630
        },
        "error": null
    }
    ```

*   **modelFieldNames**

    Gets the complete list of field names for the provided model name.

    *Sample request*:
    ```json
    {
        "action": "modelFieldNames",
        "version": 6,
        "params": {
            "modelName": "Basic"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": ["Front", "Back"],
        "error": null
    }
    ```

*   **modelFieldsOnTemplates**

    Returns an object indicating the fields on the question and answer side of each card template for the given model
    name. The question side is given first in each array.

    *Sample request*:
    ```json
    {
        "action": "modelFieldsOnTemplates",
        "version": 6,
        "params": {
            "modelName": "Basic (and reversed card)"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": {
            "Card 1": [["Front"], ["Back"]],
            "Card 2": [["Back"], ["Front"]]
        },
        "error": null
    }
    ```

*   **createModel**

    Creates a new model to be used in Anki. User must provide the `modelName`, `inOrderFields` and `cardTemplates` to be
    used in the model. There are optinal fields `css` and `isCloze`. If not specified, `css` will use the default Anki css and `isCloze` will be equal to `False`. If `isCloze` is `True` then model will be created as Cloze.

    Optionally the `Name` field can be provided for each entry of `cardTemplates`. By default the
    card names will be `Card 1`, `Card 2`, and so on.

    *Sample request*
    ```json
    {
        "action": "createModel",
        "version": 6,
        "params": {
            "modelName": "newModelName",
            "inOrderFields": ["Field1", "Field2", "Field3"],
            "css": "Optional CSS with default to builtin css",
            "isCloze": False,
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

    *Sample result*
    ```json
    {
        "result":{
            "sortf":0,
            "did":1,
            "latexPre":"\\documentclass[12pt]{article}\n\\special{papersize=3in,5in}\n\\usepackage[utf8]{inputenc}\n\\usepackage{amssymb,amsmath}\n\\pagestyle{empty}\n\\setlength{\\parindent}{0in}\n\\begin{document}\n",
            "latexPost":"\\end{document}",
            "mod":1551462107,
            "usn":-1,
            "vers":[

            ],
            "type":0,
            "css":".card {\n font-family: arial;\n font-size: 20px;\n text-align: center;\n color: black;\n background-color: white;\n}\n",
            "name":"TestApiModel",
            "flds":[
                {
                    "name":"Field1",
                    "ord":0,
                    "sticky":false,
                    "rtl":false,
                    "font":"Arial",
                    "size":20,
                    "media":[

                    ]
                },
                {
                    "name":"Field2",
                    "ord":1,
                    "sticky":false,
                    "rtl":false,
                    "font":"Arial",
                    "size":20,
                    "media":[

                    ]
                }
            ],
            "tmpls":[
                {
                    "name":"My Card 1",
                    "ord":0,
                    "qfmt":"",
                    "afmt":"This is the back of the card {{Field2}}",
                    "did":null,
                    "bqfmt":"",
                    "bafmt":""
                }
            ],
            "tags":[

            ],
            "id":"1551462107104",
            "req":[
                [
                    0,
                    "none",
                    [

                    ]
                ]
            ]
        },
        "error":null
    }
    ```

*   **modelTemplates**

    Returns an object indicating the template content for each card connected to the provided model by name.

    *Sample request*:
    ```json
    {
        "action": "modelTemplates",
        "version": 6,
        "params": {
            "modelName": "Basic (and reversed card)"
        }
    }
    ```

    *Sample result*
    ```json
    {
        "result": {
            "Card 1": {
                "Front": "{{Front}}",
                "Back": "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}"
            },
            "Card 2": {
                "Front": "{{Back}}",
                "Back": "{{FrontSide}}\n\n<hr id=answer>\n\n{{Front}}"
            }
        },
        "error": null
    }
    ```

*   **modelStyling**

    Gets the CSS styling for the provided model by name.

    *Sample request*:
    ```json
    {
        "action": "modelStyling",
        "version": 6,
        "params": {
            "modelName": "Basic (and reversed card)"
        }
    }
    ```

    *Sample result*
    ```json
    {
        "result": {
            "css": ".card {\n font-family: arial;\n font-size: 20px;\n text-align: center;\n color: black;\n background-color: white;\n}\n"
        },
        "error": null
    }
    ```

*   **updateModelTemplates**

    Modify the templates of an existing model by name. Only specifies cards and specified sides will be modified.
    If an existing card or side is not included in the request, it will be left unchanged.

    *Sample request*:
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

    *Sample result*:
    ```json
    {
        "result": null,
        "error": null
    }
    ```

*   **updateModelStyling**

    Modify the CSS styling of an existing model by name.

    *Sample request*:
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

    *Sample result*:
    ```json
    {
        "result": null,
        "error": null
    }
    ```

*   **findAndReplaceInModels**

    Find and replace string in existing model by model name. Customise to replace in front, back or css by setting to true/false.

    *Sample request*:
    ```json
    {
        "action": "findAndReplaceInModels",
        "version": 6,
        "params": {
            "model": {
                "modelName": "",
                "findText": "text_to_replace",
                "replaceText": "replace_with_text",
                "front": true,
                "back": true,
                "css": true
            }
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": 1,
        "error": null
    }
    ```

#### Note Actions

*   **addNote**

    Creates a note using the given deck and model, with the provided field values and tags. Returns the identifier of
    the created note created on success, and `null` on failure.

    AnkiConnect can download audio, video, and picture files and embed them in newly created notes. The corresponding `audio`, `video`, and `picture` note members are
    optional and can be omitted. If you choose to include any of them, they should contain a single object or an array of objects
    with the mandatory `filename` field and one of `data`, `path` or `url`. Refer to the documentation of `storeMediaFile` for an explanation of these fields.
    The `skipHash` field can be optionally provided to skip the inclusion of files with an MD5 hash that matches the provided value.
    This is useful for avoiding the saving of error pages and stub files.
    The `fields` member is a list of fields that should play audio or video, or show a picture when the card is displayed in
    Anki. The `allowDuplicate` member inside `options` group can be set to true to enable adding duplicate cards.
    Normally duplicate cards can not be added and trigger exception.

    The `duplicateScope` member inside `options` can be used to specify the scope for which duplicates are checked.
    A value of `"deck"` will only check for duplicates in the target deck; any other value will check the entire collection.

    The `duplicateScopeOptions` object can be used to specify some additional settings:

    * `duplicateScopeOptions.deckName` will specify which deck to use for checking duplicates in. If undefined or `null`, the target deck will be used.
    * `duplicateScopeOptions.checkChildren` will change whether or not duplicate cards are checked in child decks. The default value is `false`.
    * `duplicateScopeOptions.checkAllModels` specifies whether duplicate checks are performed across all note types. The default value is `false`.

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
                        "checkChildren": false,
                        "checkAllModels": false
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
                }],
                "video": [{
                    "url": "https://cdn.videvo.net/videvo_files/video/free/2015-06/small_watermarked/Contador_Glam_preview.mp4",
                    "filename": "countdown.mp4",
                    "skipHash": "4117e8aab0d37534d9c8eac362388bbe",
                    "fields": [
                        "Back"
                    ]
                }],
                "picture": [{
                    "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c7/A_black_cat_named_Tilly.jpg/220px-A_black_cat_named_Tilly.jpg",
                    "filename": "black_cat.jpg",
                    "skipHash": "8d6e4646dfae812bf39651b59d7429ce",
                    "fields": [
                        "Back"
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
                    }],
                    "video": [{
                        "url": "https://cdn.videvo.net/videvo_files/video/free/2015-06/small_watermarked/Contador_Glam_preview.mp4",
                        "filename": "countdown.mp4",
                        "skipHash": "4117e8aab0d37534d9c8eac362388bbe",
                        "fields": [
                            "Back"
                        ]
                    }],
                    "picture": [{
                        "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c7/A_black_cat_named_Tilly.jpg/220px-A_black_cat_named_Tilly.jpg",
                        "filename": "black_cat.jpg",
                        "skipHash": "8d6e4646dfae812bf39651b59d7429ce",
                        "fields": [
                            "Back"
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

    Modify the fields of an exist note. You can also include audio, video, or picture files which will be added to the note with an
    optional `audio`, `video`, or `picture` property. Please see the documentation for `addNote` for an explanation of objects in the `audio`, `video`, or `picture` array.

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

*   **clearUnusedTags**

    Clears all the unused tags in the notes for the current user.

    *Sample request*:
    ```json
    {
        "action": "clearUnusedTags",
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

*   **replaceTags**

    Replace tags in notes by note ID.

    *Sample request*:
    ```json
    {
        "action": "replaceTags",
        "version": 6,
        "params": {
            "notes": [1483959289817, 1483959291695],
            "tag_to_replace": "european-languages",
            "replace_with_tag": "french-languages"
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

*   **replaceTagsInAllNotes**

    Replace tags in all the notes for the current user.

    *Sample request*:
    ```json
    {
        "action": "replaceTagsInAllCards",
        "version": 6,
        "params": {
            "tag_to_replace": "european-languages",
            "replace_with_tag": "french-languages"
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

*   **findNotes**

    Returns an array of note IDs for a given query. Query syntax is [documented here](https://docs.ankiweb.net/#/searching).

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

*   **removeEmptyNotes**

    Removes all the empty notes for the current user.

    *Sample request*:
    ```json
    {
        "action": "removeEmptyNotes",
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

#### Statistic Actions

*   **getNumCardsReviewedToday**

    Gets the count of cards that have been reviewed in the current day (with day start time as configured by user in anki)

    *Sample request*:
    ```json
    {
        "action": "getNumCardsReviewedToday",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result": 0,
        "error": null
    }
    ```

*   **getNumCardsReviewedByDay**

    Gets the number of cards reviewed as a list of pairs of `(dateString, number)`

    *Sample request*:
    ```json
    {
        "action": "getNumCardsReviewedByDay",
        "version": 6
    }
    ```

    *Sample result*:
    ```json
    {
        "result":  [
            ["2021-02-28", 124],
            ["2021-02-27", 261]
        ],
        "error": null
    }
    ```

*   **getCollectionStatsHTML**

    Gets the collection statistics report

    *Sample request*:
    ```json
    {
        "action": "getCollectionStatsHTML",
        "version": 6,
        "params": {
            "wholeCollection": true
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "error": null,
        "result": "<center> lots of HTML here </center>"
    }
    ```

*   **cardReviews**

    Requests all card reviews for a specified deck after a certain time.
    `startID` is the latest unix time not included in the result.
    Returns a list of 9-tuples `(reviewTime, cardID, usn, buttonPressed, newInterval, previousInterval, newFactor, reviewDuration, reviewType)`

    *Sample request*:
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

    *Sample result*:
    ```json
    {
        "result": [
            [1594194095746, 1485369733217, -1, 3,   4, -60, 2500, 6157, 0],
            [1594201393292, 1485369902086, -1, 1, -60, -60,    0, 4846, 0]
        ],
        "error": null
    }
    ```

*   **getLatestReviewID**

    Returns the unix time of the latest review for the given deck. 0 if no review has ever been made for the deck.

    *Sample request*:
    ```json
    {
        "action": "getLatestReviewID",
        "version": 6,
        "params": {
            "deck": "default"
        }
    }
    ```

    *Sample result*:
    ```json
    {
        "result": 1594194095746,
        "error": null
    }
    ```

*   **insertReviews**

    Inserts the given reviews into the database. Required format: list of 9-tuples `(reviewTime, cardID, usn, buttonPressed, newInterval, previousInterval, newFactor, reviewDuration, reviewType)`

    *Sample request*:
    ```json
    {
        "action": "insertReviews",
        "version": 6,
        "params": {
            "reviews": [
                [1594194095746, 1485369733217, -1, 3,   4, -60, 2500, 6157, 0],
                [1594201393292, 1485369902086, -1, 1, -60, -60,    0, 4846, 0]
            ]
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

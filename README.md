# AnkiConnect #

The AnkiConnect plugin enables external applications such as [Yomichan](https://foosoft.net/projects/yomichan/) to communicate with
[Anki](https://apps.ankiweb.net/) over a network interface. This software makes it possible to execute queries against
the user's card deck, automatically create new vocabulary and Kanji flash cards, and more. AnkiConnect is compatible
with the latest stable (2.0.x) and alpha (2.1.x) releases of Anki and works on Linux, Windows, and Mac OS X.

## Table of Contents ##

* [Installation](https://foosoft.net/projects/anki-connect/#installation)
    *   [Notes for Windows Users](https://foosoft.net/projects/anki-connect/#notes-for-windows-users)
    *   [Notes for Mac OS X Users](https://foosoft.net/projects/anki-connect/#notes-for-mac-os-x-users)
* [Application Interface for Developers](https://foosoft.net/projects/anki-connect/#application-interface-for-developers)
    *   [Sample Invocation](https://foosoft.net/projects/anki-connect/#sample-invocation)
    *   [Supported Actions](https://foosoft.net/projects/anki-connect/#supported-actions)
        *   [Miscellaneous](https://foosoft.net/projects/anki-connect/#miscellaneous)
        *   [Decks](https://foosoft.net/projects/anki-connect/#decks)
        *   [Models](https://foosoft.net/projects/anki-connect/#models)
        *   [Notes](https://foosoft.net/projects/anki-connect/#notes)
        *   [Cards](https://foosoft.net/projects/anki-connect/#cards)
        *   [Media](https://foosoft.net/projects/anki-connect/#media)
        *   [Graphical](https://foosoft.net/projects/anki-connect/#graphical)
* [License](https://foosoft.net/projects/anki-connect/#license)

## Installation ##

The installation process is similar to that of other Anki plugins and can be accomplished in three steps:

1.  Open the *Install Add-on* dialog by selecting *Tools* &gt; *Add-ons* &gt; *Browse &amp; Install* in Anki.
2.  Input *[2055492159](https://ankiweb.net/shared/info/2055492159)* into the text box labeled *Code* and press the *OK* button to proceed.
3.  Restart Anki when prompted to do so in order to complete the installation of AnkiConnect.

Anki must be kept running in the background in order for other applications to be able to use AnkiConnect. You can
verify that AnkiConnect is running at any time by accessing [localhost:8765](http://localhost:8765) in your browser. If
the server is running, you should see the message *AnkiConnect v.6* displayed in your browser window.

### Notes for Windows Users ###

Windows users may see a firewall nag dialog box appear on Anki startup. This occurs because AnkiConnect hosts a local
server in order to enable other applications to connect to it. The host application, Anki, must be unblocked for this
plugin to function correctly.

### Notes for Mac OS X Users ###

Starting with [Mac OS X Mavericks](https://en.wikipedia.org/wiki/OS_X_Mavericks), a feature named *App Nap* has been
introduced to the operating system. This feature causes certain applications which are open (but not visible) to be
placed in a suspended state. As this behavior causes AnkiConnect to stop working while you have another window in the
foreground, App Nap should be disabled for Anki:

1.  Start the Terminal application.
2.  Execute the following command in the terminal window:

    ```
    defaults write net.ichi2.anki NSAppSleepDisabled -bool true
    ```
3.  Restart Anki.

## Application Interface for Developers ##

AnkiConnect exposes Anki features to external applications via an easy to use
[RESTful](https://en.wikipedia.org/wiki/Representational_state_transfer) API. After it is installed, this plugin will
initialize a minimal HTTP sever running on port 8765 every time Anki executes. Other applications (including browser
extensions) can then communicate with it via HTTP POST requests.

By default, AnkiConnect will only bind the HTTP server to the `127.0.0.1` IP address, so that you will only be able to
access it from the same host on which it is running. If you need to access it over a network, you can set the
environment variable `ANKICONNECT_BIND_ADDRESS` to change the binding address. For example, you can set it to `0.0.0.0`
in order to bind it to all network interfaces on your host.

### Sample Invocation ###

Every request consists of a JSON-encoded object containing an `action`, a `version`, and a set of contextual `params`. A
simple example of a modern JavaScript application communicating with the extension is illustrated below:

```javascript
function ankiConnectInvoke(action, version, params={}) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.addEventListener('error', () => reject('failed to connect to AnkiConnect'));
        xhr.addEventListener('load', () => {
            try {
                const response = JSON.parse(xhr.responseText);
                if (response.error) {
                    throw response.error;
                } else {
                    if (response.hasOwnProperty('result')) {
                        resolve(response.result);
                    } else {
                        reject('failed to get results from AnkiConnect');
                    }
                }
            } catch (e) {
                reject(e);
            }
        });

        xhr.open('POST', 'http://127.0.0.1:8765');
        xhr.send(JSON.stringify({action, version, params}));
    });
}

try {
    const result = await ankiConnectInvoke('deckNames', 6);
    console.log(`got list of decks: ${result}`);
} catch (e) {
    console.log(`error getting decks: ${e}`);
}
```

Or using [`curl`](https://curl.haxx.se) from the command line:

```bash
curl localhost:8765 -X POST -d "{\"action\": \"deckNames\", \"version\": 6}"
```

AnkiConnect will respond with an object containing two fields: `result` and `error`. The `result` field contains the
return value of the executed API, and the `error` field is a description of any exception thrown during API execution
(the value `null` is used if execution completed successfully).

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

### Supported Actions ###

Below is a comprehensive list of currently supported actions. Note that deprecated APIs will continue to function
despite not being listed on this page as long as your request is labeled with a version number corresponding to when the
API was available for use.

This page currently documents **version 6** of the API. Make sure to include this version number in your requests to
guarantee that your application continues to function properly in the future.

#### Miscellaneous ####

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

*   **upgrade**

    Displays a confirmation dialog box in Anki asking the user if they wish to upgrade AnkiConnect to the latest version
    from the project's [master branch](https://raw.githubusercontent.com/FooSoft/anki-connect/master/AnkiConnect.py) on
    GitHub. Returns a boolean value indicating if the plugin was upgraded or not.

    *Sample request*:
    ```json
    {
        "action": "upgrade",
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

*   **sync**

    Synchronizes the local anki collections with ankiweb.

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

#### Decks ####

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

#### Models ####

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

#### Notes ####

*   **addNote**

    Creates a note using the given deck and model, with the provided field values and tags. Returns the identifier of
    the created note created on success, and `null` on failure.

    AnkiConnect can download audio files and embed them in newly created notes. The corresponding `audio` note member is
    optional and can be omitted. If you choose to include it, the `url` and `filename` fields must be also defined. The
    `skipHash` field can be optionally provided to skip the inclusion of downloaded files with an MD5 hash that matches
    the provided value. This is useful for avoiding the saving of error pages and stub files. The `fields` member is a
    list of fields that should play audio when the card is displayed in Anki.

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
                "tags": [
                    "yomichan"
                ],
                "audio": {
                    "url": "https://assets.languagepod101.com/dictionary/japanese/audiomp3.php?kanji=猫&kana=ねこ",
                    "filename": "yomichan_ねこ_猫.mp3",
                    "skipHash": "7e2c2f954ef6051373ba916f000168dc",
                    "fields": [
                        "Front"
                    ]
                }
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
                    "audio": {
                        "url": "https://assets.languagepod101.com/dictionary/japanese/audiomp3.php?kanji=猫&kana=ねこ",
                        "filename": "yomichan_ねこ_猫.mp3",
                        "skipHash": "7e2c2f954ef6051373ba916f000168dc",
                        "fields": [
                            "Front"
                        ]
                    }
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

    Modify the fields of an exist note.

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


#### Cards ####

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
                "note":1502298033753
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
                "note":1502298033753
            }
        ],
        "error": null
    }
    ```

#### Media ####

*   **storeMediaFile**

    Stores a file with the specified base64-encoded contents inside the media folder. To prevent Anki from removing
    files not used by any cards (e.g. for configuration files), prefix the filename with an underscore. These files are
    still synchronized to AnkiWeb.

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
        "result": null,
        "error": null
    }
    ```

    *Content of `_hello.txt`*:
    ```
    Hello world!
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

#### Graphical ####

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

    Invokes the *Add Cards* dialog.

    *Sample request*:
    ```json
    {
        "action": "guiAddCards",
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
            "buttons": [1, 2, 3]
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

## License ##

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

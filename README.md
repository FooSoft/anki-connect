# AnkiConnect #

The AnkiConnect plugin enables external applications such as [Yomichan](https://foosoft.net/projects/yomichan/) to communicate with
[Anki](https://apps.ankiweb.net/) over a network interface. This software makes it possible to execute queries against
the user's card deck, automatically create new vocabulary and Kanji flash cards, and more. AnkiConnect is compatible
with the latest stable (2.0.x) and alpha (2.1.x) releases of Anki and works on Linux, Windows, and Mac OS X.

## Installation ##

The installation process is similar to that of other Anki plugins and can be accomplished in three steps:

1.  Open the *Install Add-on* dialog by selecting *Tools* &gt; *Add-ons* &gt; *Browse &amp; Install* in Anki.
2.  Input *[2055492159](https://ankiweb.net/shared/info/2055492159)* into the text box labeled *Code* and press the *OK* button to proceed.
3.  Restart Anki when prompted to do so in order to complete the installation of AnkiConnect.

Anki must be kept running in the background in order for other applications to be able to use AnkiConnect. You can
verify that AnkiConnect is running at any time by accessing [localhost:8765](http://localhost:8765) in your browser. If
the server is running, you should see the message *AnkiConnect v.3* displayed in your browser window.

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

### Sample Invocation ###

Every request consists of a JSON-encoded object containing an *action*, and a set of contextual *parameters*. A simple
example of a JavaScript application communicating with the extension is illustrated below:

```JavaScript
function ankiInvoke(action, params={}) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.addEventListener('loadend', () => {
            if (xhr.responseText) {
                resolve(JSON.parse(xhr.responseText));
            } else {
                reject('unable to connect to plugin');
            }
        });

        xhr.open('POST', 'http://127.0.0.1:8765');
        xhr.send(JSON.stringify({action, params}));
    });
}

ankiInvoke('version').then(response => {
    window.alert(`detected API version: ${response}`);
}).catch(error => {
    window.alert(`could not get API version: ${error}`);
});
```

Or using [`curl`](https://curl.haxx.se):

```
curl localhost:8765 -X POST -d '{"action": "version"}'
```

### Supported Actions ###

Below is a list of currently supported actions. Requests with invalid actions or parameters will a return `null` result.

*   **version**

    Gets the version of the API exposed by this plugin. Currently versions `1` through `4` are defined.

    This should be the first call you make to make sure that your application and AnkiConnect are able to communicate
    properly with each other. New versions of AnkiConnect are backwards compatible; as long as you are using actions
    which are available in the reported AnkiConnect version or earlier, everything should work fine.

    *Sample request*:
    ```
    {
        "action": "version"
    }
    ```

    *Sample response*:
    ```
    4
    ```

*   **multi**

    Performs multiple actions in one request, returning an array with the response of each action (in the given order).

    *Sample request*:
    ```
    {
        "action": "multi",
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

    *Sample response*:
    ```
    [
        ["Default"],
        [1494723142483, 1494703460437, 1494703479525]
    ]
    ```

*   **storeFile**

    Stores a file with the specified base64-encoded contents inside the media folder. Returns `true` upon success or
    `false` if attempting to write a file outside the media folder.

    Note: to prevent Anki from removing files not used by any cards (e.g. for configuration files), prefix the filename
    with an underscore. These files are still synchronized to AnkiWeb.

    *Sample request*:
    ```
    {
        "action": "storeFile",
        "params": {
            "filename": "_hello.txt",
            "data": "SGVsbG8sIHdvcmxkIQ=="
        }
    }
    ```

    *Sample response*:
    ```
    true
    ```

    *Content of `_hello.txt`*:
    ```
    Hello world!
    ```

*   **retrieveFile**

    Retrieves the base64-encoded contents of the specified file, returning `false` if the file does not exist or if
    attempting to read a file outside the media folder.

    *Sample request*:
    ```
    {
        "action": "retrieveFile",
        "params": {
            "filename": "_hello.txt"
        }
    }
    ```

    *Sample response*:
    ```
    "SGVsbG8sIHdvcmxkIQ=="
    ```

*   **deleteFile**

    Deletes the specified file inside the media folder, returning `true` if successful, or `false` if the file does not
    exist or if attempting to delete a file outside the media folder.

    *Sample request*:
    ```
    {
        "action": "deleteFile",
        "params": {
            "filename": "_hello.txt"
        }
    }
    ```

    *Sample response*:
    ```
    true
    ```

*   **deckNames**

    Gets the complete list of deck names for the current user.

    *Sample request*:
    ```
    {
        "action": "deckNames"
    }
    ```

    *Sample response*:
    ```
    [
        "Default"
    ]
    ```

*   **deckNamesAndIds**

    Gets the complete list of deck names and their respective IDs for the current user.

    *Sample request*:
    ```
    {
        "action": "deckNamesAndIds"
    }
    ```

    *Sample response*:
    ```
    {
        "Default": 1
    }
    ```

*   **modelNames**

    Gets the complete list of model names for the current user.

    *Sample request*:
    ```
    {
        "action": "modelNames"
    }
    ```

    *Sample response*:
    ```
    [
        "Basic",
        "Basic (and reversed card)"
    ]
    ```

*   **modelFieldNames**

    Gets the complete list of field names for the provided model name.

    *Sample request*:
    ```
    {
        "action": "modelFieldNames",
        "params": {
            "modelName": "Basic"
        }
    }
    ```

    *Sample response*:
    ```
    [
        "Front",
        "Back"
    ]
    ```

*   **getDeckConfig**

    Gets the config group object for the given deck.

    *Sample request*:
    ```
    {
        "action": "getDeckConfig",
        "params": {
            "deck": "Default"
        }
    }
    ```

    *Sample response*:
    ```
    {
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
    ```

*   **saveDeckConfig**

    Saves the given config group, returning `true` on success or `false` if the ID of the config group is invalid (i.e.
    it does not exist).

    *Sample request*:
    ```
    {
        "action": "saveDeckConfig",
        "params": {
            "config": (config group object)
        }
    }
    ```

    *Sample response*:
    ```
    true
    ```

*   **setDeckConfigId**

    Changes the configuration group for the given decks to the one with the given ID. Returns `true` on success or
    `false` if the given configuration group or any of the given decks do not exist.

    *Sample request*:
    ```
    {
        "action": "setDeckConfigId",
        "params": {
            "decks": ["Default"],
            "configId": 1
        }
    }
    ```

    *Sample response*:
    ```
    true
    ```

*   **cloneDeckConfigId**

    Creates a new config group with the given name, cloning from the group with the given ID, or from the default group
    if this is unspecified. Returns the ID of the new config group, or `false` if the specified group to clone from does
    not exist.

    *Sample request*:
    ```
    {
        "action": "cloneDeckConfigId",
        "params": {
            "name": "Copy of Default",
            "cloneFrom": 1
        }
    }
    ```

    *Sample response*:
    ```
    1502972374573
    ```

*   **removeDeckConfigId**

    Removes the config group with the given ID, returning `true` if successful, or `false` if attempting to remove
    either the default config group (ID = 1) or a config group that does not exist.

    *Sample request*:
    ```
    {
        "action": "removeDeckConfigId",
        "params": {
            "configId": 1502972374573
        }
    }
    ```

    *Sample response*:
    ```
    true
    ```

*   **addNote**

    Creates a note using the given deck and model, with the provided field values and tags. Returns the identifier of
    the created note created on success, and `null` on failure.

    AnkiConnect can download audio files and embed them in newly created notes. The corresponding *audio* note member is
    optional and can be omitted. If you choose to include it, the *url* and *filename* fields must be also defined. The
    *skipHash* field can be optionally provided to skip the inclusion of downloaded files with an MD5 hash that matches
    the provided value. This is useful for avoiding the saving of error pages and stub files.

    *Sample request*:
    ```
    {
        "action": "addNote",
        "params": {
            "note": {
                "deckName": "Default",
                "modelName": "Basic",
                "fields": {
                    "Front": "front content",
                    "Back": "back content",
                },
                "tags": [
                    "yomichan",
                ],
                "audio": {
                    "url": "https://assets.languagepod101.com/dictionary/japanese/audiomp3.php?kanji=猫&kana=ねこ",
                    "filename": "yomichan_ねこ_猫.mp3",
                    "skipHash": "7e2c2f954ef6051373ba916f000168dc"
                }
            }
        }
    }
    ```

    *Sample response*:
    ```
    1496198395707
    ```

*   **addNotes**

    Creates multiple notes using the given deck and model, with the provided field values and tags. Returns an array of
    identifiers of the created notes (notes that could not be created will have a `null` identifier). Please see the
    documentation for `addNote` for an explanation of objects in the `notes` array.

    *Sample request*:
    ```
    {
        "action": "addNotes",
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
                        "skipHash": "7e2c2f954ef6051373ba916f000168dc"
                    }
                }
            ]
        }
    }
    ```

    *Sample response*:
    ```
    [
        1496198395707,
        null
    ]
    ```

*   **canAddNotes**

    Accepts an array of objects which define parameters for candidate notes (see `addNote`) and returns an array of
    booleans indicating whether or not the parameters at the corresponding index could be used to create a new note.

    *Sample request*:
    ```
    {
        "action": "canAddNotes",
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

    *Sample response*:
    ```
    [
        true
    ]
    ```

*   **addTags**

    Adds tags to notes by note ID.

    *Sample request*:
    ```
    {
        "action": "addTags",
        "params": {
            "notes": [1483959289817, 1483959291695],
            "tags": "european-languages"
        }
    }
    ```

    *Sample response*:
    ```
    null
    ```

*   **removeTags**

    Remove tags from notes by note ID.

    *Sample request*:
    ```
    {
        "action": "removeTags",
        "params": {
            "notes": [1483959289817, 1483959291695],
            "tags": "european-languages"
        }
    }
    ```

    *Sample response*:
    ```
    null
    ```

*   **suspend**

    Suspend cards by card ID; returns `true` if successful (at least one card wasn't already suspended) or `false`
    otherwise.

    *Sample request*:
    ```
    {
        "action": "suspend",
        "params": {
            "cards": [1483959291685, 1483959293217]
        }
    }
    ```

    *Sample response*:
    ```
    true
    ```

*   **unsuspend**

    Unsuspend cards by card ID; returns `true` if successful (at least one card was previously suspended) or `false`
    otherwise.

    *Sample request*:
    ```
    {
        "action": "unsuspend",
        "params": {
            "cards": [1483959291685, 1483959293217]
        }
    }
    ```

    *Sample response*:
    ```
    true
    ```

*   **areSuspended**

    Returns an array indicating whether each of the given cards is suspended (in the same order).

    *Sample request*:
    ```
    {
        "action": "areSuspended",
        "params": {
            "cards": [1483959291685, 1483959293217]
        }
    }
    ```

    *Sample response*:
    ```
    [false, true]
    ```

*   **areDue**

    Returns an array indicating whether each of the given cards is due (in the same order). Note: cards in the learning
    queue with a large interval (over 20 minutes) are treated as not due until the time of their interval has passed, to
    match the way Anki treats them when reviewing.

    *Sample request*:
    ```
    {
        "action": "areDue",
        "params": {
            "cards": [1483959291685, 1483959293217]
        }
    }
    ```

    *Sample response*:
    ```
    [false, true]
    ```

*   **getIntervals**

    Returns an array of the most recent intervals for each given card ID, or a 2-dimensional array of all the intervals
    for each given card ID when `complete` is `true`. (Negative intervals are in seconds and positive intervals in days.)

    *Sample request 1*:
    ```
    {
        "action": "getIntervals",
        "params": {
            "cards": [1502298033753, 1502298036657]
        }
    }
    ```

    *Sample response 1*:
    ```
    [-14400, 3]
    ```

    *Sample request 2*:
    ```
    {
        "action": "getIntervals",
        "params": {
            "cards": [1502298033753, 1502298036657],
            "complete": true
        }
    }
    ```

    *Sample response 2*:
    ```
    [
        [-120, -180, -240, -300, -360, -14400],
        [-120, -180, -240, -300, -360, -14400, 1, 3]
    ]
    ```


*   **findNotes**

    Returns an array of note IDs for a given query (same query syntax as **guiBrowse**).

    *Sample request*:
    ```
    {
        "action": "findNotes",
        "params": {
            "query": "deck:current"
        }
    }
    ```

    *Sample response*:
    ```
    [
        1483959289817,
        1483959291695
    ]
    ```

*   **findCards**

    Returns an array of card IDs for a given query (functionally identical to **guiBrowse** but doesn't use the GUI
    for better performance).

    *Sample request*:
    ```
    {
        "action": "findCards",
        "params": {
            "query": "deck:current"
        }
    }
    ```

    *Sample response*:
    ```
    [
        1494723142483,
        1494703460437,
        1494703479525
    ]
    ```

*   **getDecks**

    Accepts an array of card IDs and returns an object with each deck name as a key, and its value an array of the given
    cards which belong to it.

    *Sample request*:
    ```
    {
        "action": "getDecks",
        "params": {
            "cards": [1502298036657, 1502298033753, 1502032366472]
        }
    }
    ```

    *Sample response*:
    ```
    {
        "Default": [1502032366472],
        "Japanese::JLPT N3": [1502298036657, 1502298033753]
    }
    ```


*   **changeDeck**

    Moves cards with the given IDs to a different deck, creating the deck if it doesn't exist yet.

    *Sample request*:
    ```
    {
        "action": "changeDeck",
        "params": {
            "cards": [1502098034045, 1502098034048, 1502298033753],
            "deck": "Japanese::JLPT N3"
        }
    }
    ```

    *Sample response*:
    ```
    null
    ```

*   **deleteDecks**

    Deletes decks with the given names. If `cardsToo` is `true` (defaults to `false` if unspecified), the cards within
    the deleted decks will also be deleted; otherwise they will be moved to the default deck.

    *Sample request*:
    ```
    {
        "action": "deleteDecks",
        "params": {
            "decks": ["Japanese::JLPT N5", "Easy Spanish"],
            "cardsToo": true
        }
    }
    ```

    *Sample response*:
    ```
    null
    ```

*   **cardsToNotes**

    Returns an (unordered) array of note IDs for the given card IDs. For cards with the same note, the ID is only
    given once in the array.

    *Sample request*:
    ```
    {
        "action": "cardsToNotes",
        "params": {
            "cards": [1502098034045, 1502098034048, 1502298033753]
        }
    }
    ```

    *Sample response*:
    ```
    [
        1502098029797,
        1502298025183
    ]
    ```

*   **guiBrowse**

    Invokes the card browser and searches for a given query. Returns an array of identifiers of the cards that were found.

    *Sample request*:
    ```
    {
        "action": "guiBrowse",
        "params": {
            "query": "deck:current"
        }
    }
    ```

    *Sample response*:
    ```
    [
        1494723142483,
        1494703460437,
        1494703479525
    ]
    ```

*   **guiAddCards**

    Invokes the AddCards dialog.

    *Sample request*:
    ```
    {
        "action": "guiAddCards"
    }
    ```

    *Sample response*:
    ```
    null
    ```

*   **guiCurrentCard**

    Returns information about the current card or `null` if not in review mode.

    *Sample request*:
    ```
    {
        "action": "guiCurrentCard"
    }
    ```

    *Sample response*:
    ```
    {
        "answer": "back content",
        "question": "front content",
        "deckName": "Default",
        "modelName": "Basic",
        "fieldOrder": 0,
        "fields": {
            "Front": {
                "value": "front content",
                "order": 0
            },
            "Back": {
                "value": "back content",
                "order": 1
            }
        },
        "cardId": 1498938915662,
        "buttons": [1, 2, 3]
    }
    ```

*   **guiStartCardTimer**

    Starts or resets the 'timerStarted' value for the current card. This is useful for deferring the start time to when it is displayed via the API, allowing the recorded time taken to answer the card to be more accurate when calling guiAnswerCard.

    *Sample request*:
    ```
    {
        "action": "guiStartCardTimer"
    }
    ```

    *Sample response*:
    ```
    true
    ```

*   **guiShowQuestion**

    Shows question text for the current card; returns `true` if in review mode or `false` otherwise.

    *Sample request*:
    ```
    {
        "action": "guiShowQuestion"
    }
    ```

    *Sample response*:
    ```
    true
    ```

*   **guiShowAnswer**

    Shows answer text for the current card; returns `true` if in review mode or `false` otherwise.

    *Sample request*:
    ```
    {
        "action": "guiShowAnswer"
    }
    ```

    *Sample response*:
    ```
    true
    ```

*   **guiAnswerCard**

    Answers the current card; returns `true` if succeeded or `false` otherwise. Note that the answer for the current
    card must be displayed before before any answer can be accepted by Anki.

    *Sample request*:
    ```
    {
        "action": "guiAnswerCard",
        "params": {
            "ease": 1
        }
    }
    ```

    *Sample response*:
    ```
    true
    ```

*   **guiDeckOverview**

    Opens the Deck Overview screen for the deck with the given name; returns `true` if succeeded or `false` otherwise.

    *Sample request*:
    ```
    {
        "action": "guiDeckOverview",
		"params": {
			"name": "Default"
		}
    }
    ```

    *Sample response*:
    ```
    true
    ```

*   **guiDeckBrowser**

    Opens the Deck Browser screen.

    *Sample request*:
    ```
    {
        "action": "guiDeckBrowser"
    }
    ```

    *Sample response*:
    ```
    null
    ```

*   **guiDeckReview**

    Starts review for the deck with the given name; returns `true` if succeeded or `false` otherwise.

    *Sample request*:
    ```
    {
        "action": "guiDeckReview",
		"params": {
			"name": "Default"
		}
    }
    ```

    *Sample response*:
    ```
    true
    ```

*   **upgrade**

    Displays a confirmation dialog box in Anki asking the user if they wish to upgrade AnkiConnect to the latest version
    from the project's [master branch](https://raw.githubusercontent.com/FooSoft/anki-connect/master/AnkiConnect.py) on
    GitHub. Returns a boolean value indicating if the plugin was upgraded or not.

    *Sample request*:
    ```
    {
        "action": "upgrade"
    }
    ```

    *Sample response*:
    ```
    true
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

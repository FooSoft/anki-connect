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
    properly with each other. New versions of AnkiConnect will backwards compatible; as long as you are using actions
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
    null
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

GPL

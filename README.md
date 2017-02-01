# AnkiConnect #

The AnkiConnect plugin enables external applications such as [Yomichan for Chrome](https://foosoft.net/projects/yomichan-chrome/) to
communicate with Anki over a remote API. This makes it possible to execute queries against the user's card deck,
automatically create new vocabulary and Kanji flash cards, and more. AnkiConnect is compatible with latest stable and
alpha versions of Anki.

## Requirements ##

* [Anki](http://ankisrs.net/)

## Installation ##

AnkiConnect can be downloaded from its [Anki shared addon page](https://ankiweb.net/shared/info/2055492159) or enabled
through the [Yomichan](https://foosoft.net/projects/yomichan) plugin if you have it installed. Once AnkiConnect is installed it is ready
for use; no further configuration is required. Windows users may have to take additional steps to make Windows Firewall
allows AnkiConnect to listen for incoming connections on TCP port 8765.

## Limitations on Mac OS X ##

While it is possible to use this plugin on this operating system, there is a known issue in which it is required that
the Anki application window to be on screen for card creation to work properly. The cause is apparently that Mac OS X
suspends graphical applications running in the background, thus preventing Anki from responding to Yomichan queries.

Until this problem is resolved, users of this Mac OS X will have to keep both the browser window and Anki on-screen.
Sorry for the lameness; I am researching a fix for this issue.

## API ##

Ankiconnect accepts HTTP POST request with POST body in JSON format, and then return an id(version id/ note id) or a list(decks, models and fields) as response data.

### Request URI:
```JavaScript
var uri = http://127.0.0.1:8765
```

### Request Method:
**HTTP POST**

### JS call example:
```JavaScript
var xhr = $.post(uri, postdata, (response, status) => {});
```

### POST body & response
#### Check Version:
```JavaScript
var postdata = {action: "version", params: {}}
var response = "1" //current anki connect version
```

#### Retrieve deck name list:
```JavaScript
var postdata = {action: "deckNames", params: {}}
var response = ["test deck 1","test deck 2"] //all decks name list
```

#### Retrieve model name list:
```JavaScript
var postdata = {action: "modelNames", params: {}}
var response = ["basic","basic (and reversed card)"] //all models name list
```

#### Retrieve fields list for specified model:
```JavaScript
var postdata = {action: "modelFieldNames", params: {modelName: "basic"}}
var response = ["front","back"] //fields name list
```

#### Check if can add note or not (empty or duplicated card )
```JavaScript
var postdata = {
    action: "canAddNotes",
    params: {
        notes: [
            {deckName: "test deck 1", modelName: "basic", fields: {...}, tags:[]},
            {deckName: "test deck 1", modelName: "basic", fields: {...}, tags:[]},
            {deckName: "test deck 1", modelName: "basic", fields: {...}, tags:[]} 
            // for fields:{...}, please check below for detail.
        ]
    }
}
var response = [true, true, true] // a list of result, say if this note can be added or not.
```

#### Add note
```JavaScript
var postdata = {
    action: "addNote",
    params: {
        deckName: "test deck 1", 
        modelName: "basic", 
        note: {
            fields: {
                front: "front content", 
                back: "back content"
            },
            tags: ["tag1","tag2"]
        }
    }
}
var response = note id(success) or null(fail)
```

## License ##

GPL

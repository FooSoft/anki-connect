# Media Actions

*   **storeMediaFile**

    Stores a file with the specified base64-encoded contents inside the media folder. Alternatively you can specify a
    absolute file path, or a url from where the file shell be downloaded. If more than one of `data`, `path` and `url` are provided, the `data` field will be used first, then `path`, and finally `url`. To prevent Anki from removing files not used by any cards (e.g. for configuration files), prefix the filename with an underscore. These files are still synchronized to AnkiWeb.

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
        "result": null,
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
        "result": null,
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

# Model Actions

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
    used in the model. Optionally the `Name` field can be provided for each entry of `cardTemplates`. By default the
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

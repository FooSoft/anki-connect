# Statistic Actions

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

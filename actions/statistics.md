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

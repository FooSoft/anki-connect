#!/usr/bin/env python

import os
import tempfile
import unittest
import util


class TestStats(unittest.TestCase):
    def setUp(self):
        util.invoke('createDeck', deck='test')
        note = {'deckName': 'test', 'modelName': 'Basic', 'fields': {'Front': 'front1', 'Back': 'back1'}, 'tags': ['tag1']}
        self.noteId = util.invoke('addNote', note=note)

    def tearDown(self):
        util.invoke('deleteDecks', decks=['test'], cardsToo=True)

    def runTest(self):
        # getNumCardsReviewedToday
        result = util.invoke('getNumCardsReviewedToday')
        self.assertIsInstance(result, int)

        # collectionStats
        result = util.invoke('getCollectionStatsHTML')
        self.assertIsInstance(result, str)

        # no reviews for new deck
        self.assertEqual(len(util.invoke("cardReviews", deck="test", startID=0)), 0)
        self.assertEqual(util.invoke("getLatestReviewID", deck="test"), 0)

        # add reviews
        cardId = int(util.invoke('findCards', query='deck:test')[0])
        latestID = 123456  # small enough to not interfere with existing reviews
        util.invoke("insertReviews", reviews=[
            [latestID-1, cardId, -1, 3,   4, -60, 2500, 6157, 0],
            [latestID,   cardId, -1, 1, -60, -60,    0, 4846, 0]
        ])
        self.assertEqual(len(util.invoke("cardReviews", deck="test", startID=0)), 2)
        self.assertEqual(util.invoke("getLatestReviewID", deck="test"), latestID)


if __name__ == '__main__':
    unittest.main()

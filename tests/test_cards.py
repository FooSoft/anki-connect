#!/usr/bin/env python

import unittest
import util


class TestCards(unittest.TestCase):
    def setUp(self):
        util.invoke('createDeck', deck='test')
        note = {'deckName': 'test', 'modelName': 'Basic', 'fields': {'Front': 'front1', 'Back': 'back1'}, 'tags': ['tag1']}
        self.noteId = util.invoke('addNote', note=note)


    def tearDown(self):
        util.invoke('deleteDecks', decks=['test'], cardsToo=True)


    def runTest(self):
        # findCards
        cardIds = util.invoke('findCards', query='deck:test')
        self.assertEqual(len(cardIds), 1)

        # setEaseFactors
        EASE_TO_TRY = 4200
        easeFactors = [EASE_TO_TRY for card in cardIds]
        couldGetEaseFactors = util.invoke('setEaseFactors', cards=cardIds, easeFactors=easeFactors)
        self.assertEqual([True for card in cardIds], couldGetEaseFactors)

        # getEaseFactors
        easeFactorsFound = util.invoke('getEaseFactors', cards=cardIds)
        self.assertEqual(easeFactors, easeFactorsFound)

        # suspend
        util.invoke('suspend', cards=cardIds)

        # areSuspended (part 1)
        suspendedStates = util.invoke('areSuspended', cards=cardIds)
        self.assertEqual(len(cardIds), len(suspendedStates))
        self.assertNotIn(False, suspendedStates)

        # unsuspend
        util.invoke('unsuspend', cards=cardIds)

        # areSuspended (part 2)
        suspendedStates = util.invoke('areSuspended', cards=cardIds)
        self.assertEqual(len(cardIds), len(suspendedStates))
        self.assertNotIn(True, suspendedStates)

        # areDue
        dueStates = util.invoke('areDue', cards=cardIds)
        self.assertEqual(len(cardIds), len(dueStates))
        self.assertNotIn(False, dueStates)

        # getIntervals
        util.invoke('getIntervals', cards=cardIds, complete=True)
        util.invoke('getIntervals', cards=cardIds, complete=False)

        # cardsToNotes
        noteIds = util.invoke('cardsToNotes', cards=cardIds)
        self.assertEqual(len(noteIds), len(cardIds))
        self.assertIn(self.noteId, noteIds)

        # cardsInfo
        cardsInfo = util.invoke('cardsInfo', cards=cardIds)
        self.assertEqual(len(cardsInfo), len(cardIds))
        for i, cardInfo in enumerate(cardsInfo):
            self.assertEqual(cardInfo['cardId'], cardIds[i])


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python

import unittest
import util


class TestCards(unittest.TestCase):
    def setUp(self):
        util.invoke('createDeck', deck='test')
        note = {
            'deckName': 'test',
            'modelName': 'Basic',
            'fields': {'Front': 'front1', 'Back': 'back1'},
            'tags': ['tag1'],
            'options': {
                'allowDuplicate': True
            }
        }
        self.noteId = util.invoke('addNote', note=note)


    def tearDown(self):
        util.invoke('deleteDecks', decks=['test'], cardsToo=True)


    def runTest(self):
        incorrectId = 1234

        # findCards
        cardIds = util.invoke('findCards', query='deck:test')
        self.assertEqual(len(cardIds), 1)

        # setEaseFactors
        EASE_TO_TRY = 4200
        easeFactors = [EASE_TO_TRY for card in cardIds]
        couldGetEaseFactors = util.invoke('setEaseFactors', cards=cardIds, easeFactors=easeFactors)
        self.assertEqual([True for card in cardIds], couldGetEaseFactors)
        couldGetEaseFactors = util.invoke('setEaseFactors', cards=[incorrectId], easeFactors=[EASE_TO_TRY])
        self.assertEqual([False], couldGetEaseFactors)

        # getEaseFactors
        easeFactorsFound = util.invoke('getEaseFactors', cards=cardIds)
        self.assertEqual(easeFactors, easeFactorsFound)
        easeFactorsFound = util.invoke('getEaseFactors', cards=[incorrectId])
        self.assertEqual([None], easeFactorsFound)

        # suspend
        util.invoke('suspend', cards=cardIds)
        self.assertRaises(Exception, lambda: util.invoke('suspend', cards=[incorrectId]))

        # areSuspended (part 1)
        suspendedStates = util.invoke('areSuspended', cards=cardIds)
        self.assertEqual(len(cardIds), len(suspendedStates))
        self.assertNotIn(False, suspendedStates)
        self.assertEqual([None], util.invoke('areSuspended', cards=[incorrectId]))

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
        cardsInfo = util.invoke('cardsInfo', cards=[incorrectId])
        self.assertEqual(len(cardsInfo), 1)
        self.assertDictEqual(cardsInfo[0], dict())

        # forgetCards
        util.invoke('forgetCards', cards=cardIds)

        # relearnCards
        util.invoke('relearnCards', cards=cardIds)

if __name__ == '__main__':
    unittest.main()

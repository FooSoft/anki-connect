#!/usr/bin/env python

import unittest
import util


class TestDecks(unittest.TestCase):
    def runTest(self):
        # deckNames (part 1)
        deckNames = util.invoke('deckNames')
        self.assertIn('Default', deckNames)

        # deckNamesAndIds
        result = util.invoke('deckNamesAndIds')
        self.assertIn('Default', result)
        self.assertEqual(result['Default'], 1)

        # createDeck
        util.invoke('createDeck', deck='test')

        # deckNames (part 2)
        deckNames = util.invoke('deckNames')
        self.assertIn('test', deckNames)

        # deleteDecks
        util.invoke('deleteDecks', decks=['test'])

        # deckNames (part 3)
        deckNames = util.invoke('deckNames')
        self.assertNotIn('test', deckNames)


if __name__ == '__main__':
    unittest.main()

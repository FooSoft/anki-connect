#!/usr/bin/env python

import unittest
import util


class TestNotes(unittest.TestCase):
    def setUp(self):
        util.invoke('createDeck', deck='test')


    def tearDown(self):
        util.invoke('deleteDecks', decks=['test'], cardsToo=True)


    def test_bug164(self):
        note = {'deckName': 'test', 'modelName': 'Basic', 'fields': {'Front': ' Whitespace\n', 'Back': ''}, 'options': { 'allowDuplicate': False, 'duplicateScope': 'deck'}}
        util.invoke('addNote', note=note)
        self.assertRaises(Exception, lambda: util.invoke('addNote', note=note))


if __name__ == '__main__':
    unittest.main()

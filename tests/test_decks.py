#!/usr/bin/env python

import unittest
import util


class TestDeckNames(unittest.TestCase):
    def runTest(self):
        result = util.invoke('deckNames')
        self.assertIn('Default', result)


class TestDeckNamesAndIds(unittest.TestCase):
    def runTest(self):
        result = util.invoke('deckNamesAndIds')
        self.assertIn('Default', result)
        self.assertEqual(result['Default'], 1)


class TestCreateDeck(unittest.TestCase):
    def tearDown(self):
        util.invoke('deleteDecks', decks=['test'])


    def runTest(self):
        util.invoke('createDeck', deck='test')
        self.assertIn('test', util.invoke('deckNames'))


class TestDeleteDecks(unittest.TestCase):
    def setUp(self):
        util.invoke('createDeck', deck='test')


    def runTest(self):
        util.invoke('deleteDecks', decks=['test'])
        self.assertNotIn('test', util.invoke('deckNames'))


if __name__ == '__main__':
    unittest.main()

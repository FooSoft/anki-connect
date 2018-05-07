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


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python

import unittest
import util


class TestMisc(unittest.TestCase):
    def runTest(self):
        # version
        self.assertEqual(util.invoke('version'), 6)

        # sync
        util.invoke('sync')

        # multi
        actions = [util.request('version'), util.request('version'), util.request('version')]
        results = util.invoke('multi', actions=actions)
        self.assertEqual(len(results), len(actions))
        for result in results:
            self.assertIsNone(result['error'])
            self.assertEqual(result['result'], 6)

        # getNumCardsReviewedToday
        result = util.invoke('getNumCardsReviewedToday')
        self.assertIsInstance(result, int)


if __name__ == '__main__':
    unittest.main()

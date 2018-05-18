#!/usr/bin/env python

import unittest
import util


class TestMisc(unittest.TestCase):
    def runTest(self):
        # version
        self.assertEqual(util.invoke('version'), 5)

        # upgrade
        util.invoke('upgrade')

        # sync
        util.invoke('sync')

        # multi
        actions = [util.request('version'), util.request('version'), util.request('version')]
        results = util.invoke('multi', actions=actions)
        self.assertEqual(len(results), len(actions))
        for result in results:
            self.assertIsNone(result['error'])
            self.assertEqual(result['result'], 5)


if __name__ == '__main__':
    unittest.main()

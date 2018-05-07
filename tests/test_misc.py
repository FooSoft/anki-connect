#!/usr/bin/env python

import unittest
import util


class TestVersion(unittest.TestCase):
    def runTest(self):
        result = util.invoke('version')
        self.assertEqual(result, 5)


class TestUpgrade(unittest.TestCase):
    def runTest(self):
        util.invoke('upgrade')


class TestSync(unittest.TestCase):
    def runTest(self):
        util.invoke('sync')


class TestMulti(unittest.TestCase):
    def runTest(self):
        result = util.invoke(
            'multi', {
                'actions': [
                    util.request('version'),
                    util.request('version'),
                    util.request('version')
                ]
            }
        )

        self.assertEqual(len(result), 3)
        for response in result:
            self.assertIsNone(response['error'])
            self.assertEqual(response['result'], 5)


if __name__ == '__main__':
    unittest.main()

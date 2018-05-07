#!/usr/bin/env python

import unittest
import util


class TestVersion(unittest.TestCase):
    def test_version(self):
        result = util.invokeNoError('version')
        self.assertEqual(result, 5)


    def test_upgrade(self):
        util.invokeNoError('upgrade')


    def test_sync(self):
        util.invokeNoError('sync')


    def test_multi(self):
        result = util.invokeNoError(
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

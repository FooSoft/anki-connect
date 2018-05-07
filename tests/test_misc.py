#!/usr/bin/env python

import unittest
import util


class TestMisc(unittest.TestCase):
    def test_version(self):
        result = util.invoke('version')
        self.assertEqual(result, 5)


    def test_upgrade(self):
        util.invoke('upgrade')


    def test_sync(self):
        util.invoke('sync')


    def test_multi(self):
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

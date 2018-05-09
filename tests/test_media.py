#!/usr/bin/env python

import unittest
import util


class TestMedia(unittest.TestCase):
    def runTest(self):
        filename = '_test.txt'
        data = 'test'

        # storeMediaFile
        util.invoke('storeMediaFile', filename='_test.txt', data=data)

        # retrieveMediaFile (part 1)
        media = util.invoke('retrieveMediaFile', filename=filename)
        self.assertEqual(media, data)

        # deleteMediaFile
        util.invoke('deleteMediaFile', filename=filename)

        # retrieveMediaFile (part 2)
        media = util.invoke('retrieveMediaFile', filename=filename)
        self.assertFalse(media)


if __name__ == '__main__':
    unittest.main()

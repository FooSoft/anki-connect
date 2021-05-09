#!/usr/bin/env python

import unittest
import util


class TestMedia(unittest.TestCase):
    def runTest(self):
        filename = '_test.txt'
        data = 'test'

        # storeMediaFile
        util.invoke('storeMediaFile', filename=filename, data=data)
        filename2 = util.invoke('storeMediaFile', filename=filename, data='testtest', deleteExisting=False)
        self.assertNotEqual(filename2, filename)

        # retrieveMediaFile (part 1)
        media = util.invoke('retrieveMediaFile', filename=filename)
        self.assertEqual(media, data)

        names = util.invoke('getMediaFilesNames', pattern='_tes*.txt')
        self.assertEqual(set(names), set([filename, filename2]))

        # deleteMediaFile
        util.invoke('deleteMediaFile', filename=filename)

        # retrieveMediaFile (part 2)
        media = util.invoke('retrieveMediaFile', filename=filename)
        self.assertFalse(media)


if __name__ == '__main__':
    unittest.main()

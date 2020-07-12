#!/usr/bin/env python

import os
import tempfile
import unittest
import util


class TestMisc(unittest.TestCase):
    def runTest(self):
        # version
        self.assertEqual(util.invoke('version'), 6)

        # sync
        util.invoke('sync')

        # getProfiles
        profiles = util.invoke('getProfiles')
        self.assertIsInstance(profiles, list)
        self.assertGreater(len(profiles), 0)

        # loadProfile
        util.invoke('loadProfile', name=profiles[0])

        # multi
        actions = [util.request('version'), util.request('version'), util.request('version')]
        results = util.invoke('multi', actions=actions)
        self.assertEqual(len(results), len(actions))
        for result in results:
            self.assertIsNone(result['error'])
            self.assertEqual(result['result'], 6)

        # exportPackage
        fd, newname = tempfile.mkstemp(prefix='testexport', suffix='.apkg')
        os.close(fd)
        os.unlink(newname)
        result = util.invoke('exportPackage', deck='Default', path=newname)
        self.assertTrue(result)
        self.assertTrue(os.path.exists(newname))

        # importPackage
        deckName = 'importTest'
        fd, newname = tempfile.mkstemp(prefix='testimport', suffix='.apkg')
        os.close(fd)
        os.unlink(newname)
        util.invoke('createDeck', deck=deckName)
        note = {'deckName': deckName, 'modelName': 'Basic', 'fields': {'Front': 'front1', 'Back': 'back1'}, 'tags': ''}
        noteId = util.invoke('addNote', note=note)
        util.invoke('exportPackage', deck=deckName, path=newname)
        util.invoke('deleteDecks', decks=[deckName], cardsToo=True)
        util.invoke('importPackage', path=newname)
        deckNames = util.invoke('deckNames')
        self.assertIn(deckName, deckNames)

        # reloadCollection
        util.invoke("reloadCollection")


if __name__ == '__main__':
    unittest.main()

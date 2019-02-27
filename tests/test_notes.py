#!/usr/bin/env python

import unittest
import util


class TestNotes(unittest.TestCase):
    def setUp(self):
        util.invoke('createDeck', deck='test')


    def tearDown(self):
        util.invoke('deleteDecks', decks=['test'], cardsToo=True)


    def runTest(self):
        # addNote
        note = {'deckName': 'test', 'modelName': 'Basic', 'fields': {'Front': 'front1', 'Back': 'back1'}, 'tags': ['tag1']}
        noteId = util.invoke('addNote', note=note)
        self.assertRaises(Exception, lambda: util.invoke('addNote', note=note))

        # addTags
        util.invoke('addTags', notes=[noteId], tags='tag2')

        # notesInfo (part 1)
        noteInfos = util.invoke('notesInfo', notes=[noteId])
        self.assertEqual(len(noteInfos), 1)
        noteInfo = noteInfos[0]
        self.assertEqual(noteInfo['noteId'], noteId)
        self.assertSetEqual(set(noteInfo['tags']), {'tag1', 'tag2'})
        self.assertEqual(noteInfo['fields']['Front']['value'], 'front1')
        self.assertEqual(noteInfo['fields']['Back']['value'], 'back1')

        # getTags
        allTags = util.invoke('getTags')
        self.assertIn('tag1', allTags)
        self.assertIn('tag2', allTags)

        # removeTags
        util.invoke('removeTags', notes=[noteId], tags='tag2')

        # updateNoteFields
        noteUpdate = {'id': noteId, 'fields': {'Front': 'front2', 'Back': 'back2'}}
        util.invoke('updateNoteFields', note=noteUpdate)

        # notesInfo (part 2)
        noteInfos = util.invoke('notesInfo', notes=[noteId])
        self.assertEqual(len(noteInfos), 1)
        noteInfo = noteInfos[0]
        self.assertSetEqual(set(noteInfo['tags']), {'tag1'})
        self.assertIn('tag1', noteInfo['tags'])
        self.assertNotIn('tag2', noteInfo['tags'])
        self.assertEqual(noteInfo['fields']['Front']['value'], 'front2')
        self.assertEqual(noteInfo['fields']['Back']['value'], 'back2')

        notes = [
            {'deckName': 'test', 'modelName': 'Basic', 'fields': {'Front': 'front3', 'Back': 'back3'}, 'tags': ['tag']},
            {'deckName': 'test', 'modelName': 'Basic', 'fields': {'Front': 'front4', 'Back': 'back4'}, 'tags': ['tag']}
        ]

        # canAddNotes (part 1)
        noteStates = util.invoke('canAddNotes', notes=notes)
        self.assertEqual(len(noteStates), len(notes))
        self.assertNotIn(False, noteStates)

        # addNotes (part 1)
        noteIds = util.invoke('addNotes', notes=notes)
        self.assertEqual(len(noteIds), len(notes))
        for noteId in noteIds:
            self.assertNotEqual(noteId, None)

        # canAddNotes (part 2)
        noteStates = util.invoke('canAddNotes', notes=notes)
        self.assertNotIn(True, noteStates)
        self.assertEqual(len(noteStates), len(notes))

        # addNotes (part 2)
        noteIds = util.invoke('addNotes', notes=notes)
        self.assertEqual(len(noteIds), len(notes))
        for noteId in noteIds:
            self.assertEqual(noteId, None)

        # findNotes
        noteIds = util.invoke('findNotes', query='deck:test')
        self.assertEqual(len(noteIds), len(notes) + 1)

        # deleteNotes
        util.invoke('deleteNotes', notes=noteIds)
        noteIds = util.invoke('findNotes', query='deck:test')
        self.assertEqual(len(noteIds), 0)

if __name__ == '__main__':
    unittest.main()

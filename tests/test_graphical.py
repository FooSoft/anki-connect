#!/usr/bin/env python

import unittest
import util


class TestGui(unittest.TestCase):
    def runTest(self):
        # guiBrowse
        util.invoke('guiBrowse', query='deck:Default')

        # guiAddCards
        util.invoke('guiAddCards')

        # guiAddCards with preset
        util.invoke('createDeck', deck='test')

        note = {
            'deckName': 'test',
            'modelName': 'Basic',
            'fields': {
                'Front': 'front1',
                'Back': 'back1'
            },
            'tags': ['tag1'],
        }
        util.invoke('guiAddCards', note=note)

        # guiAddCards with preset and closeAfterAdding
        util.invoke('guiAddCards', note={
            **note,
            'options': { 'closeAfterAdding': True },
        })

        util.invoke('guiAddCards', note={
            **note,
            'picture': [{
                'url': 'https://via.placeholder.com/150.png',
                'filename': 'placeholder.png',
                'fields': ['Front'],
            }]
        })

        # guiCurrentCard
        # util.invoke('guiCurrentCard')

        # guiStartCardTimer
        util.invoke('guiStartCardTimer')

        # guiShowQuestion
        util.invoke('guiShowQuestion')

        # guiShowAnswer
        util.invoke('guiShowAnswer')

        # guiAnswerCard
        util.invoke('guiAnswerCard', ease=1)

        # guiDeckOverview
        util.invoke('guiDeckOverview', name='Default')

        # guiDeckBrowser
        util.invoke('guiDeckBrowser')

        # guiDatabaseCheck
        util.invoke('guiDatabaseCheck')

        # guiExitAnki
        # util.invoke('guiExitAnki')


if __name__ == '__main__':
    unittest.main()

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
        note = {'deckName': 'test', 'modelName': 'Basic', 'fields': {'Front': 'front1', 'Back': 'back1'}, 'tags': ['tag1']}
        util.invoke('guiAddCards', note=note)

        # guiAddCards with preset and closeAfterAdding
        noteWithOption = {'deckName': 'test', 'modelName': 'Basic', 'fields': {'Front': 'front1', 'Back': 'back1'}, 'options': { 'closeAfterAdding': True }, 'tags': ['tag1']}
        util.invoke('guiAddCards', note=noteWithOption)

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

        # guiExitAnki
        # util.invoke('guiExitAnki')


if __name__ == '__main__':
    unittest.main()

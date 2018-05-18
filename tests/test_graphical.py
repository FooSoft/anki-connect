#!/usr/bin/env python

import unittest
import util


class TestGui(unittest.TestCase):
    def runTest(self):
        # guiBrowse
        util.invoke('guiBrowse', query='deck:Default')

        # guiAddCards
        util.invoke('guiAddCards')

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

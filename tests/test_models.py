#!/usr/bin/env python

import unittest
import util


class TestModels(unittest.TestCase):
    def runTest(self):
        # modelNames
        modelNames = util.invoke('modelNames')
        self.assertGreater(len(modelNames), 0)

        # modelNamesAndIds
        modelNamesAndIds = util.invoke('modelNamesAndIds')
        self.assertGreater(len(modelNames), 0)

        # modelFieldNames
        modelFields = util.invoke('modelFieldNames', modelName=modelNames[0])

        # modelFieldsOnTemplates
        modelFieldsOnTemplates = util.invoke('modelFieldsOnTemplates', modelName=modelNames[0])


if __name__ == '__main__':
    unittest.main()

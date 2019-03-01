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

        # createModel with css
        newModel = util.invoke('createModel', modelName='testModel', inOrderFields=['field1', 'field2'], cardTemplates=[{'Front':'field1','Back':'field2'}], css='some random css')

        # createModel without css
        newModel = util.invoke('createModel', modelName='testModel-second', inOrderFields=['field1', 'field2'], cardTemplates=[{'Front':'field1','Back':'field2'}])

if __name__ == '__main__':
    unittest.main()

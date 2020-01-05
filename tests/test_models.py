#!/usr/bin/env python

import unittest
import util
import uuid


MODEL_1_NAME = str(uuid.uuid4())
MODEL_2_NAME = str(uuid.uuid4())

CSS = 'some random css'
NEW_CSS = 'new random css'

CARD_1_TEMPLATE = {'Front': 'field1', 'Back': 'field2'}
NEW_CARD_1_TEMPLATE = {'Front': 'question: field1', 'Back': 'answer: field2'}


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
        newModel = util.invoke('createModel', modelName=MODEL_1_NAME, inOrderFields=['field1', 'field2'], cardTemplates=[CARD_1_TEMPLATE], css=CSS)

        # createModel without css
        newModel = util.invoke('createModel', modelName=MODEL_2_NAME, inOrderFields=['field1', 'field2'], cardTemplates=[CARD_1_TEMPLATE])

        # modelStyling: get model 1 css
        css = util.invoke('modelStyling', modelName=MODEL_1_NAME)
        self.assertEqual({'css': CSS}, css)

        # modelTemplates: get model 1 templates
        templates = util.invoke('modelTemplates', modelName=MODEL_1_NAME)
        self.assertEqual({'Card 1': CARD_1_TEMPLATE}, templates)

        # updateModelStyling: change and verify model css
        util.invoke('updateModelStyling', model={'name': MODEL_1_NAME, 'css': NEW_CSS})
        new_css = util.invoke('modelStyling', modelName=MODEL_1_NAME)
        self.assertEqual({'css': NEW_CSS}, new_css)

        # updateModelTemplates: change and verify model 1 templates
        util.invoke('updateModelTemplates', model={'name': MODEL_1_NAME, 'templates': {'Card 1': NEW_CARD_1_TEMPLATE}})
        templates = util.invoke('modelTemplates', modelName=MODEL_1_NAME)
        self.assertEqual({'Card 1': NEW_CARD_1_TEMPLATE}, templates)


if __name__ == '__main__':
    unittest.main()

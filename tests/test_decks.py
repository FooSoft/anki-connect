# -*- coding: utf-8 -*-
import unittest
from unittest import TestCase
from util import callAnkiConnectEndpoint

class TestDeckNames(TestCase):

    def test_deckNames(self):
        response = callAnkiConnectEndpoint({'action': 'deckNames'})
        self.assertEqual(['Default'], response)

class TestGetDeckConfig(TestCase):
    
    def test_getDeckConfig(self):
        response = callAnkiConnectEndpoint({'action': 'getDeckConfig', 'params': {'deck': 'Default'}})
        self.assertDictContainsSubset({'name': 'Default', 'replayq': True}, response)
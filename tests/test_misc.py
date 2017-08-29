# -*- coding: utf-8 -*-
import unittest
from unittest import TestCase
from util import callAnkiConnectEndpoint

class TestVersion(TestCase):

    def test_version(self):
        response = callAnkiConnectEndpoint({'action': 'version'})
        self.assertEqual(4, response)
#!/usr/bin/env python

import os
import tempfile
import unittest

import util


class TestExport(unittest.TestCase):
    def runTest(self):
        fd, newname = tempfile.mkstemp(prefix="testexport", suffix=".apkg")
        os.close(fd)
        os.unlink(newname)
        success = util.invoke('exportPackage', deck='Default', path=newname)
        self.assertTrue(success)
        self.assertTrue(os.path.exists(newname))


if __name__ == '__main__':
    unittest.main()

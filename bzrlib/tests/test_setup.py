""" test for setup.py build process """

import os
import sys
import subprocess
import shutil

from bzrlib.tests import TestCase


class TestSetup(TestCase):

    def setUp(self):
        pass

    def test_build(self):
        """ test cmd `python setup.py build` """
        # run setup.py build as subproces and catch return code
        p = subprocess.Popen([sys.executable, 'setup.py', 'build'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        s = p.communicate()
        self.assertEqual(0, p.returncode, '`python setup.py build` fails')

    def tearDown(self):
        """ cleanup build directory """
        shutil.rmtree(u'build')

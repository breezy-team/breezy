""" test for setup.py build process """

import os
import shutil

from bzrlib.tests import TestCase


class TestSetup(TestCase):

    def setUp(self):
        pass

    def test_build(self):
        """ test cmd `python setup.py build` """
        # run setup.py build as subproces and catch return code
        p = os.popen("python setup.py build")
        s = p.readlines()
        res = p.close()
        self.assertEqual(res, None, '`python setup.py build` fails')

    def tearDown(self):
        """ cleanup build directory """
        shutil.rmtree(u'build')

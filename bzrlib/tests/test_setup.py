""" test for setup.py build process """

import os
import sys
import subprocess
import shutil
from tempfile import TemporaryFile

from bzrlib.tests import TestCase


# TODO: ideally run this in a separate directory, so as not to clobber the
# real build directory

class TestSetup(TestCase):

    def test_build(self):
        """ test cmd `python setup.py build`
        
        This typically catches new subdirectories which weren't added to setup.py
        """
        self.log('test_build running in %s' % os.getcwd())
        try:
            # run setup.py build as subproces and catch return code
            out_file = TemporaryFile()
            err_file = TemporaryFile()
            p = subprocess.Popen([sys.executable, 'setup.py', 'build'],
                                 stdout=out_file, stderr=err_file)
            s = p.communicate()
            self.assertEqual(0, p.returncode, '`python setup.py build` fails')
        finally:
            if os.path.exists('build'):
                shutil.rmtree(u'build')

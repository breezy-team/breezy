# Copyright (C) 2005, 2006 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

""" test for setup.py build process """

import os
import sys
import subprocess
import shutil
from tempfile import TemporaryFile

from bzrlib.tests import TestCase
import bzrlib.osutils as osutils

# TODO: ideally run this in a separate directory, so as not to clobber the
# real build directory

class TestSetup(TestCase):

    def test_build(self):
        """ test cmd `python setup.py build`

        This tests that the build process and man generator run correctly.
        It also can catch new subdirectories that weren't added to setup.py.
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
                osutils.rmtree(u'build')

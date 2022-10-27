# Copyright (C) 2005, 2006, 2008-2011 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Test for setup.py build process"""

from distutils import version
import os
import sys
import subprocess

import breezy
from .. import tests

# TODO: Run bzr from the installed copy to see if it works.  Really we need to
# run something that exercises every module, just starting it may not detect
# some missing modules.
#
# TODO: Check that the version numbers are in sync.  (Or avoid this...)


class TestSetup(tests.TestCaseInTempDir):

    def test_build_and_install(self):
        """ test cmd `python setup.py build`

        This tests that the build process and man generator run correctly.
        It also can catch new subdirectories that weren't added to setup.py.
        """
        # setup.py must be run from the root source directory, but the tests
        # are not necessarily invoked from there
        self.source_dir = os.path.dirname(os.path.dirname(breezy.__file__))
        if not os.path.isfile(os.path.join(self.source_dir, 'setup.py')):
            self.skipTest(
                'There is no setup.py file adjacent to the breezy directory')
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            # On GitHub CI, for some reason rustc can't be found.
            # Marking as known failing for now.
            self.knownFailure(
                'rustc can not be found in the GitHub actions environment')
        try:
            import distutils.sysconfig
            makefile_path = distutils.sysconfig.get_makefile_filename()
            if not os.path.exists(makefile_path):
                self.skipTest(
                    'You must have the python Makefile installed to run this'
                    ' test. Usually this can be found by installing'
                    ' "python-dev"')
        except ImportError:
            self.skipTest(
                'You must have distutils installed to run this test.'
                ' Usually this can be found by installing "python-dev"')
        self.log('test_build running from %s' % self.source_dir)
        build_dir = os.path.join(self.test_dir, "build")
        install_dir = os.path.join(self.test_dir, "install")
        self.run_setup([
            'build', '-b', build_dir,
            'install', '--root', install_dir])
        # Install layout is platform dependant
        self.assertPathExists(install_dir)
        self.run_setup(['clean', '-b', build_dir])

    def run_setup(self, args):
        args = [sys.executable, './setup.py', ] + args
        self.log('source base directory: %s', self.source_dir)
        self.log('args: %r', args)
        env = dict(os.environ)
        env['PYTHONPATH'] = ':'.join(sys.path)
        p = subprocess.Popen(args,
                             cwd=self.source_dir,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             env=env)
        stdout, stderr = p.communicate()
        self.log('stdout: %r', stdout)
        self.log('stderr: %r', stderr)
        self.assertEqual(0, p.returncode,
                         'invocation of %r failed' % args)


class TestDistutilsVersion(tests.TestCase):

    def test_version_with_string(self):
        # We really care about two pyrex specific versions and our ability to
        # detect them
        lv = version.LooseVersion
        self.assertTrue(lv("0.9.4.1") < lv('0.17.beta1'))
        self.assertTrue(lv("0.9.6.3") < lv('0.10'))

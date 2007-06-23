#    test_repack_tarball_extra.py -- Extra tests for repacking tarballs
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

from repack_tarball import repack_tarball

from bzrlib.errors import BzrCommandError
from bzrlib.tests import TestCaseInTempDir


class TestRepackTarballExtra(TestCaseInTempDir):

  def test_repack_tarball_errors_unkown_format(self):
    old_tarball = 'package-0.2.INVALID'
    f = open(old_tarball, 'w')
    f.close()
    self.failUnlessExists(old_tarball)
    self.assertRaises(BzrCommandError, repack_tarball, old_tarball,
                      'package_0.2.orig.tar.gz')


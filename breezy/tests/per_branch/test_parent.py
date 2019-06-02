# Copyright (C) 2005, 2006, 2007, 2009, 2010, 2011, 2016 Canonical Ltd
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


import sys

import breezy.errors
from breezy.osutils import getcwd
from breezy.tests import (
    TestCaseWithTransport,
    TestNotApplicable,
    TestSkipped,
    )
from breezy import urlutils


"""Tests for Branch parent URL"""


class TestParent(TestCaseWithTransport):

    def test_no_default_parent(self):
        """Branches should have no parent by default"""
        b = self.make_branch('.')
        self.assertEqual(None, b.get_parent())

    def test_set_get_parent(self):
        """Set, re-get and reset the parent"""
        b = self.make_branch('subdir')
        url = 'http://example.com/bzr/bzr.dev'
        b.set_parent(url)
        self.assertEqual(url, b.get_parent())
        self.assertEqual(url, b._get_parent_location())

        b.set_parent(None)
        self.assertEqual(None, b.get_parent())

        b.set_parent('../other_branch')

        expected_parent = urlutils.join(self.get_url('subdir'),
                                        '../other_branch')
        self.assertEqual(expected_parent, b.get_parent())
        path = urlutils.join(self.get_url('subdir'), '../yanb')
        b.set_parent(path)
        self.assertEqual('../yanb', b._get_parent_location())
        self.assertEqual(path, b.get_parent())

        self.assertRaises(urlutils.InvalidURL, b.set_parent, u'\xb5')
        b.set_parent(urlutils.escape(u'\xb5'))
        self.assertEqual('%C2%B5', b._get_parent_location())

        self.assertEqual(b.base + '%C2%B5', b.get_parent())

        # Handle the case for older style absolute local paths
        if sys.platform == 'win32':
            # TODO: jam 20060515 Do we want to special case Windows local
            #       paths as well? Nobody has complained about it.
            pass
        else:
            b.lock_write()
            b._set_parent_location('/local/abs/path')
            b.unlock()
            self.assertEqual('file:///local/abs/path', b.get_parent())

    def test_get_invalid_parent(self):
        b = self.make_branch('.')

        cwd = getcwd()
        n_dirs = len(cwd.split('/'))

        # Force the relative path to be something invalid
        # This should attempt to go outside the filesystem
        path = ('../' * (n_dirs + 5)) + 'foo'
        b.lock_write()
        b._set_parent_location(path)
        b.unlock()

        # With an invalid branch parent, just return None
        self.assertRaises(breezy.errors.InaccessibleParent, b.get_parent)

    def test_win32_set_parent_on_another_drive(self):
        if sys.platform != 'win32':
            raise TestSkipped('windows-specific test')
        b = self.make_branch('.')
        base_url = b.controldir.transport.abspath('.')
        if not base_url.startswith('file:///'):
            raise TestNotApplicable('this test should be run with local base')
        base = urlutils.local_path_from_url(base_url)
        other = 'file:///D:/path'
        if base[0] != 'C':
            other = 'file:///C:/path'
        b.set_parent(other)
        self.assertEqual(other, b._get_parent_location())

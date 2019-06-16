# Copyright (C) 2006, 2009, 2010 Canonical Ltd
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
#

"""Tests of the 'brz ignored' command."""

from breezy.tests import TestCaseWithTransport


class TestIgnored(TestCaseWithTransport):

    def test_ignored_added_file(self):
        """'brz ignored' should not list versioned files."""
        # this test can go in favour of a more general ui test at some point
        # as it is actually testing the internals layer and should not be.
        # There are no other 'ignored' tests though, so it should be retained
        # until some are written.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo.pyc'])
        # ensure that foo.pyc is ignored
        self.build_tree_contents([('.bzrignore', b'foo.pyc')])
        self.assertTrue(tree.is_ignored('foo.pyc'))
        # now add it and check the ui does not show it.
        tree.add('foo.pyc')
        out, err = self.run_bzr('ignored')
        self.assertEqual('', out)
        self.assertEqual('', err)

    def test_ignored_directory(self):
        """Test --directory option"""
        tree = self.make_branch_and_tree('a')
        self.build_tree_contents([('a/README', b'contents'),
                                  ('a/.bzrignore', b'README')])
        out, err = self.run_bzr(['ignored', '--directory=a'])
        self.assertStartsWith(out, 'README')

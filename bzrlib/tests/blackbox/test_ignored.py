# Copyright (C) 2006 by Canonical Ltd
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
#

"""Tests of the 'bzr ignored' command."""

from bzrlib.tests.blackbox import ExternalBase


class TestIgnored(ExternalBase):
        
    def test_ignored_added_file(self):
        """'bzr ignored' should not list versioned files."""
        # this test can go in favour of a more general ui test at some point
        # as it is actually testing the internals layer and should not be.
        # There are no other 'ignored' tests though, so it should be retained
        # until some are written.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo.pyc'])
        # ensure that foo.pyc is ignored
        self.build_tree_contents([('.bzrignore', 'foo.pyc')])
        self.assertTrue(tree.is_ignored('foo.pyc'))
        # now add it and check the ui does not show it.
        tree.add('foo.pyc')
        out, err = self.run_bzr('ignored')
        self.assertEqual('', out)
        self.assertEqual('', err)

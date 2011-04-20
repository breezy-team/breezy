# Copyright (C) 2010 Canonical Ltd
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


"""Black-box tests for bzr rmbranch."""

from bzrlib import (
    bzrdir,
    )
from bzrlib.tests import (
    TestCaseWithTransport,
    )


class TestRemoveBranch(TestCaseWithTransport):

    def example_branch(self, path='.'):
        tree = self.make_branch_and_tree(path)
        self.build_tree_contents([(path + '/hello', 'foo')])
        tree.add('hello')
        tree.commit(message='setup')
        self.build_tree_contents([(path + '/goodbye', 'baz')])
        tree.add('goodbye')
        tree.commit(message='setup')

    def test_remove_local(self):
        # Remove a local branch.
        self.example_branch('a')
        self.run_bzr('rmbranch a')
        dir = bzrdir.BzrDir.open('a')
        self.assertFalse(dir.has_branch())
        self.failUnlessExists('a/hello')
        self.failUnlessExists('a/goodbye')

    def test_no_branch(self):
        # No branch in the current directory. 
        self.make_repository('a')
        self.run_bzr_error(['Not a branch'],
            'rmbranch a')

    def test_no_arg(self):
        # location argument defaults to current directory
        self.example_branch('a')
        self.run_bzr('rmbranch', working_dir='a')
        dir = bzrdir.BzrDir.open('a')
        self.assertFalse(dir.has_branch())

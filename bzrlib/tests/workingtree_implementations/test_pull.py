# (C) 2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

from cStringIO import StringIO
import os

import bzrlib
import bzrlib.branch
from bzrlib.branch import Branch
import bzrlib.bzrdir as bzrdir
from bzrlib.bzrdir import BzrDir
import bzrlib.errors as errors
from bzrlib.errors import NotBranchError, NotVersionedError
from bzrlib.osutils import basename
from bzrlib.tests import TestSkipped
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib.trace import mutter
from bzrlib.transport import get_transport
import bzrlib.workingtree as workingtree
from bzrlib.workingtree import (TreeEntry, TreeDirectory, TreeFile, TreeLink,
                                WorkingTree)


class TestPull(TestCaseWithWorkingTree):

    def get_pullable_trees(self):
        self.build_tree(['from/', 'from/file', 'to/'])
        tree = self.make_branch_and_tree('from')
        tree.add('file')
        tree.commit('foo', rev_id='A')
        tree_b = self.make_branch_and_tree('to')
        return tree, tree_b
 
    def test_pull(self):
        tree_a, tree_b = self.get_pullable_trees()
        tree_b.pull(tree_a.branch)
        self.failUnless(tree_b.branch.repository.has_revision('A'))
        self.assertEqual('A', tree_b.last_revision())

    def test_pull_overwrites(self):
        tree_a, tree_b = self.get_pullable_trees()
        tree_b.commit('foo', rev_id='B')
        self.assertEqual(['B'], tree_b.branch.revision_history())
        tree_b.pull(tree_a.branch, overwrite=True)
        self.failUnless(tree_b.branch.repository.has_revision('A'))
        self.failUnless(tree_b.branch.repository.has_revision('B'))
        self.assertEqual('A', tree_b.last_revision())

    def test_pull_merges_tree_content(self):
        tree_a, tree_b = self.get_pullable_trees()
        tree_b.pull(tree_a.branch)
        self.assertFileEqual('contents of from/file\n', 'to/file')


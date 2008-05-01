# Copyright (C) 2005 Canonical Ltd
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


from StringIO import StringIO

from bzrlib import config
from bzrlib.revisionspec import RevisionSpec
from bzrlib.status import show_pending_merges, show_tree_status
from bzrlib.tests import TestCaseWithTransport


class TestStatus(TestCaseWithTransport):

    def test_pending_none(self):
        # Test whether show_pending_merges works in a tree with no commits
        tree = self.make_branch_and_tree('a')
        tree.commit('empty commit')
        tree2 = self.make_branch_and_tree('b')
        # set a left most parent that is not a present commit
        tree2.add_parent_tree_id('some-ghost', allow_leftmost_as_ghost=True)
        # do a merge
        tree2.merge_from_branch(tree.branch)
        output = StringIO()
        tree2.lock_read()
        try:
            show_pending_merges(tree2, output)
        finally:
            tree2.unlock()
        self.assertContainsRe(output.getvalue(), 'empty commit')

    def test_multiple_pending(self):
        config.GlobalConfig().set_user_option('email', 'Joe Foo <joe@foo.com>')
        tree = self.make_branch_and_tree('a')
        tree.commit('commit 1', timestamp=1196796819, timezone=0)
        tree2 = tree.bzrdir.clone('b').open_workingtree()
        tree.commit('commit 2', timestamp=1196796819, timezone=0)
        tree2.commit('commit 2b', timestamp=1196796819, timezone=0)
        tree3 = tree2.bzrdir.clone('c').open_workingtree()
        tree2.commit('commit 3b', timestamp=1196796819, timezone=0)
        tree3.commit('commit 3c', timestamp=1196796819, timezone=0)
        tree.merge_from_branch(tree2.branch)
        tree.merge_from_branch(tree3.branch)
        output = StringIO()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        show_pending_merges(tree, output)
        # Even though 2b is in the ancestry of 3c, it should only be displayed
        # under the first merge parent.
        self.assertEqualDiff('pending merges:\n'
                             '  Joe Foo 2007-12-04 commit 3b\n'
                             '    Joe Foo 2007-12-04 commit 2b\n'
                             '  Joe Foo 2007-12-04 commit 3c\n',
                             output.getvalue())

    def test_with_pending_ghost(self):
        """Test when a pending merge is itself a ghost"""
        tree = self.make_branch_and_tree('a')
        tree.commit('first')
        tree.add_parent_tree_id('a-ghost-revision')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        output = StringIO()
        show_pending_merges(tree, output)
        self.assertEqualDiff('pending merges:\n'
                             '  (ghost) a-ghost-revision\n',
                             output.getvalue())

    def test_pending_with_ghosts(self):
        """Test when a pending merge's ancestry includes ghosts."""
        config.GlobalConfig().set_user_option('email', 'Joe Foo <joe@foo.com>')
        tree = self.make_branch_and_tree('a')
        tree.commit('empty commit')
        tree2 = tree.bzrdir.clone('b').open_workingtree()
        tree2.commit('a non-ghost', timestamp=1196796819, timezone=0)
        tree2.add_parent_tree_id('a-ghost-revision')
        tree2.commit('commit with ghost', timestamp=1196796819, timezone=0)
        tree2.commit('another non-ghost', timestamp=1196796819, timezone=0)
        tree.merge_from_branch(tree2.branch)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        output = StringIO()
        show_pending_merges(tree, output)
        self.assertEqualDiff('pending merges:\n'
                             '  Joe Foo 2007-12-04 another non-ghost\n'
                             '    Joe Foo 2007-12-04 commit with ghost\n'
                             '    (ghost) a-ghost-revision\n'
                             '    Joe Foo 2007-12-04 a non-ghost\n',
                             output.getvalue())

    def tests_revision_to_revision(self):
        """doing a status between two revision trees should work."""
        tree = self.make_branch_and_tree('.')
        r1_id = tree.commit('one', allow_pointless=True)
        r2_id = tree.commit('two', allow_pointless=True)
        r2_tree = tree.branch.repository.revision_tree(r2_id)
        output = StringIO()
        show_tree_status(tree, to_file=output,
                     revision=[RevisionSpec.from_string("revid:%s" % r1_id),
                               RevisionSpec.from_string("revid:%s" % r2_id)])
        # return does not matter as long as it did not raise.

    def test_pending_specific_files(self):
        """With a specific file list, pending merges are not shown."""
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/a', 'content of a\n')])
        tree.add('a')
        r1_id = tree.commit('one')
        alt = tree.bzrdir.sprout('alt').open_workingtree()
        self.build_tree_contents([('alt/a', 'content of a\nfrom alt\n')])
        alt_id = alt.commit('alt')
        tree.merge_from_branch(alt.branch)
        output = StringIO()
        show_tree_status(tree, to_file=output)
        self.assertContainsRe(output.getvalue(), 'pending merges:')
        output = StringIO()
        show_tree_status(tree, to_file=output, specific_files=['a'])
        self.assertNotContainsRe(output.getvalue(), 'pending merges:')

# Copyright (C) 2005, 2006 Canonical Ltd
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

from bzrlib import branch, bzrdir, errors, ui, workingtree
from bzrlib.errors import (NotBranchError, NotVersionedError, 
                           UnsupportedOperation)
from bzrlib.osutils import pathjoin, getcwd, has_symlinks
from bzrlib.tests import TestSkipped, TestCase
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib.trace import mutter
from bzrlib.workingtree import (TreeEntry, TreeDirectory, TreeFile, TreeLink,
                                WorkingTree)


class CapturingUIFactory(ui.UIFactory):
    """A UI Factory for testing - capture the updates made through it."""

    def __init__(self):
        super(CapturingUIFactory, self).__init__()
        self._calls = []
        self.depth = 0

    def clear(self):
        """See progress.ProgressBar.clear()."""

    def clear_term(self):
        """See progress.ProgressBar.clear_term()."""

    def finished(self):
        """See progress.ProgressBar.finished()."""
        self.depth -= 1

    def note(self, fmt_string, *args, **kwargs):
        """See progress.ProgressBar.note()."""

    def progress_bar(self):
        return self
    
    def nested_progress_bar(self):
        self.depth += 1
        return self

    def update(self, message, count=None, total=None):
        """See progress.ProgressBar.update()."""
        if self.depth == 1:
            self._calls.append(("update", count, total))


class TestCapturingUI(TestCase):

    def test_nested_ignore_depth_beyond_one(self):
        # we only want to capture the first level out progress, not
        # want sub-components might do. So we have nested bars ignored.
        factory = CapturingUIFactory()
        pb1 = factory.nested_progress_bar()
        pb1.update('foo', 0, 1)
        pb2 = factory.nested_progress_bar()
        pb2.update('foo', 0, 1)
        pb2.finished()
        pb1.finished()
        self.assertEqual([("update", 0, 1)], factory._calls)


class TestCommit(TestCaseWithWorkingTree):

    def test_commit_sets_last_revision(self):
        tree = self.make_branch_and_tree('tree')
        tree.commit('foo', rev_id='foo', allow_pointless=True)
        self.assertEqual('foo', tree.last_revision())

    def test_commit_local_unbound(self):
        # using the library api to do a local commit on unbound branches is 
        # also an error
        tree = self.make_branch_and_tree('tree')
        self.assertRaises(errors.LocalRequiresBoundBranch,
                          tree.commit,
                          'foo',
                          local=True)
 
    def test_local_commit_ignores_master(self):
        # a --local commit does not require access to the master branch
        # at all, or even for it to exist.
        # we test this by setting up a bound branch and then corrupting
        # the master.
        master = self.make_branch('master')
        tree = self.make_branch_and_tree('tree')
        try:
            tree.branch.bind(master)
        except errors.UpgradeRequired:
            # older format.
            return
        master.bzrdir.transport.put('branch-format', StringIO('garbage'))
        del master
        # check its corrupted.
        self.assertRaises(errors.UnknownFormatError,
                          bzrdir.BzrDir.open,
                          'master')
        tree.commit('foo', rev_id='foo', local=True)
 
    def test_local_commit_does_not_push_to_master(self):
        # a --local commit does not require access to the master branch
        # at all, or even for it to exist.
        # we test that even when its available it does not push to it.
        master = self.make_branch('master')
        tree = self.make_branch_and_tree('tree')
        try:
            tree.branch.bind(master)
        except errors.UpgradeRequired:
            # older format.
            return
        tree.commit('foo', rev_id='foo', local=True)
        self.failIf(master.repository.has_revision('foo'))
        self.assertEqual(None, master.last_revision())
        

class TestCommitProgress(TestCaseWithWorkingTree):
    
    def restoreDefaults(self):
        ui.ui_factory = self.old_ui_factory

    def test_commit_progress_steps(self):
        # during commit we one progress update for every entry in the 
        # inventory, and then one for the inventory, and one for the
        # inventory, and one for the revision insertions.
        # first we need a test commit to do. Lets setup a branch with 
        # 3 files, and alter one in a selected-file commit. This exercises
        # a number of cases quickly. We should also test things like 
        # selective commits which excludes newly added files.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b', 'c'])
        tree.add(['a', 'b', 'c'])
        tree.commit('first post')
        f = file('b', 'wt')
        f.write('new content')
        f.close()
        # set a progress bar that captures the calls so we can see what is 
        # emitted
        self.old_ui_factory = ui.ui_factory
        self.addCleanup(self.restoreDefaults)
        factory = CapturingUIFactory()
        ui.ui_factory = factory
        # TODO RBC 20060421 it would be nice to merge the reporter output
        # into the factory for this test - just make the test ui factory
        # pun as a reporter. Then we can check the ordering is right.
        tree.commit('second post', specific_files=['b'])
        # 9 steps: 1 for rev, 2 for inventory, 1 for finishing. 2 for root
        # and 6 for inventory files.
        # 2 steps don't trigger an update, as 'a' and 'c' are not 
        # committed.
        self.assertEqual(
            [("update", 0, 9),
             ("update", 1, 9),
             ("update", 2, 9),
             ("update", 3, 9),
             ("update", 4, 9),
             ("update", 5, 9),
             ("update", 6, 9),
             ("update", 7, 9)],
            factory._calls
           )

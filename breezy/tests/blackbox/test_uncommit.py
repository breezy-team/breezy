# Copyright (C) 2005-2011, 2013, 2016 Canonical Ltd
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

"""Test the uncommit command."""

import os

from breezy import uncommit
from breezy.bzr.bzrdir import BzrDirMetaFormat1
from breezy.errors import BoundBranchOutOfDate
from breezy.tests import TestCaseWithTransport
from breezy.tests.script import (
    run_script,
    ScriptRunner,
    )


class TestUncommit(TestCaseWithTransport):

    def create_simple_tree(self):
        wt = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/b', 'tree/c'])
        wt.add(['a', 'b', 'c'])
        wt.commit('initial commit', rev_id=b'a1')

        self.build_tree_contents([('tree/a', b'new contents of a\n')])
        wt.commit('second commit', rev_id=b'a2')

        return wt

    def test_uncommit(self):
        """Test uncommit functionality."""
        wt = self.create_simple_tree()

        os.chdir('tree')
        out, err = self.run_bzr('uncommit --dry-run --force')
        self.assertContainsRe(out, 'Dry-run')
        self.assertNotContainsRe(out, 'initial commit')
        self.assertContainsRe(out, 'second commit')

        # Nothing has changed
        self.assertEqual([b'a2'], wt.get_parent_ids())

        # Uncommit, don't prompt
        out, err = self.run_bzr('uncommit --force')
        self.assertNotContainsRe(out, 'initial commit')
        self.assertContainsRe(out, 'second commit')

        # This should look like we are back in revno 1
        self.assertEqual([b'a1'], wt.get_parent_ids())
        out, err = self.run_bzr('status')
        self.assertEqual(out, 'modified:\n  a\n')

    def test_uncommit_interactive(self):
        """Uncommit seeks confirmation, and doesn't proceed without it."""
        wt = self.create_simple_tree()
        os.chdir('tree')
        run_script(self, """
        $ brz uncommit
        ...
        The above revision(s) will be removed.
        2>Uncommit these revisions? ([y]es, [n]o): no
        <n
        Canceled
        """)
        self.assertEqual([b'a2'], wt.get_parent_ids())

    def test_uncommit_no_history(self):
        wt = self.make_branch_and_tree('tree')
        out, err = self.run_bzr('uncommit --force', retcode=1)
        self.assertEqual('', err)
        self.assertEqual('No revisions to uncommit.\n', out)

    def test_uncommit_checkout(self):
        wt = self.create_simple_tree()
        checkout_tree = wt.branch.create_checkout('checkout')

        self.assertEqual([b'a2'], checkout_tree.get_parent_ids())

        os.chdir('checkout')
        out, err = self.run_bzr('uncommit --dry-run --force')
        self.assertContainsRe(out, 'Dry-run')
        self.assertNotContainsRe(out, 'initial commit')
        self.assertContainsRe(out, 'second commit')

        self.assertEqual([b'a2'], checkout_tree.get_parent_ids())

        out, err = self.run_bzr('uncommit --force')
        self.assertNotContainsRe(out, 'initial commit')
        self.assertContainsRe(out, 'second commit')

        # uncommit in a checkout should uncommit the parent branch
        # (but doesn't effect the other working tree)
        self.assertEqual([b'a1'], checkout_tree.get_parent_ids())
        self.assertEqual(b'a1', wt.branch.last_revision())
        self.assertEqual([b'a2'], wt.get_parent_ids())

    def test_uncommit_bound(self):
        os.mkdir('a')
        a = BzrDirMetaFormat1().initialize('a')
        a.create_repository()
        a.create_branch()
        t_a = a.create_workingtree()
        t_a.commit('commit 1')
        t_a.commit('commit 2')
        t_a.commit('commit 3')
        b = t_a.branch.create_checkout('b').branch
        uncommit.uncommit(b)
        self.assertEqual(b.last_revision_info()[0], 2)
        self.assertEqual(t_a.branch.last_revision_info()[0], 2)
        # update A's tree to not have the uncommitted revision referenced.
        t_a.update()
        t_a.commit('commit 3b')
        self.assertRaises(BoundBranchOutOfDate, uncommit.uncommit, b)
        b.pull(t_a.branch)
        uncommit.uncommit(b)

    def test_uncommit_bound_local(self):
        t_a = self.make_branch_and_tree('a')
        rev_id1 = t_a.commit('commit 1')
        rev_id2 = t_a.commit('commit 2')
        rev_id3 = t_a.commit('commit 3')
        b = t_a.branch.create_checkout('b').branch

        out, err = self.run_bzr(['uncommit', '--local', 'b', '--force'])
        self.assertEqual(rev_id3, t_a.last_revision())
        self.assertEqual((3, rev_id3), t_a.branch.last_revision_info())
        self.assertEqual((2, rev_id2), b.last_revision_info())

    def test_uncommit_revision(self):
        wt = self.create_simple_tree()

        os.chdir('tree')
        out, err = self.run_bzr('uncommit -r1 --force')

        self.assertNotContainsRe(out, 'initial commit')
        self.assertContainsRe(out, 'second commit')
        self.assertEqual([b'a1'], wt.get_parent_ids())
        self.assertEqual(b'a1', wt.branch.last_revision())

    def test_uncommit_neg_1(self):
        wt = self.create_simple_tree()
        os.chdir('tree')
        out, err = self.run_bzr('uncommit -r -1', retcode=1)
        self.assertEqual('No revisions to uncommit.\n', out)

    def test_uncommit_merges(self):
        wt = self.create_simple_tree()

        tree2 = wt.controldir.sprout('tree2').open_workingtree()

        tree2.commit('unchanged', rev_id=b'b3')
        tree2.commit('unchanged', rev_id=b'b4')

        wt.merge_from_branch(tree2.branch)
        wt.commit('merge b4', rev_id=b'a3')

        self.assertEqual([b'a3'], wt.get_parent_ids())

        os.chdir('tree')
        out, err = self.run_bzr('uncommit --force')

        self.assertEqual([b'a2', b'b4'], wt.get_parent_ids())

    def test_uncommit_pending_merge(self):
        wt = self.create_simple_tree()
        tree2 = wt.controldir.sprout('tree2').open_workingtree()
        tree2.commit('unchanged', rev_id=b'b3')

        wt.branch.fetch(tree2.branch)
        wt.set_pending_merges([b'b3'])

        os.chdir('tree')
        out, err = self.run_bzr('uncommit --force')
        self.assertEqual([b'a1', b'b3'], wt.get_parent_ids())

    def test_uncommit_multiple_merge(self):
        wt = self.create_simple_tree()

        tree2 = wt.controldir.sprout('tree2').open_workingtree()
        tree2.commit('unchanged', rev_id=b'b3')

        tree3 = wt.controldir.sprout('tree3').open_workingtree()
        tree3.commit('unchanged', rev_id=b'c3')

        wt.merge_from_branch(tree2.branch)
        wt.commit('merge b3', rev_id=b'a3')

        wt.merge_from_branch(tree3.branch)
        wt.commit('merge c3', rev_id=b'a4')

        self.assertEqual([b'a4'], wt.get_parent_ids())

        os.chdir('tree')
        out, err = self.run_bzr('uncommit --force -r 2')

        self.assertEqual([b'a2', b'b3', b'c3'], wt.get_parent_ids())

    def test_uncommit_merge_plus_pending(self):
        wt = self.create_simple_tree()

        tree2 = wt.controldir.sprout('tree2').open_workingtree()
        tree2.commit('unchanged', rev_id=b'b3')
        tree3 = wt.controldir.sprout('tree3').open_workingtree()
        tree3.commit('unchanged', rev_id=b'c3')

        wt.branch.fetch(tree2.branch)
        wt.set_pending_merges([b'b3'])
        wt.commit('merge b3', rev_id=b'a3')

        wt.merge_from_branch(tree3.branch)

        self.assertEqual([b'a3', b'c3'], wt.get_parent_ids())

        os.chdir('tree')
        out, err = self.run_bzr('uncommit --force -r 2')

        self.assertEqual([b'a2', b'b3', b'c3'], wt.get_parent_ids())

    def test_uncommit_shows_log_with_revision_id(self):
        wt = self.create_simple_tree()

        script = ScriptRunner()
        script.run_script(self, """
$ cd tree
$ brz uncommit --force
    2 ...
      second commit
...
The above revision(s) will be removed.
You can restore the old tip by running:
  brz pull . -r revid:a2
""")

    def test_uncommit_shows_pull_with_location(self):
        wt = self.create_simple_tree()

        script = ScriptRunner()
        script.run_script(self, """
$ brz uncommit --force tree
    2 ...
      second commit
...
The above revision(s) will be removed.
You can restore the old tip by running:
  brz pull -d tree tree -r revid:a2
""")

    def test_uncommit_octopus_merge(self):
        # Check that uncommit keeps the pending merges in the same order
        # though it will also filter out ones in the ancestry
        wt = self.create_simple_tree()

        tree2 = wt.controldir.sprout('tree2').open_workingtree()
        tree3 = wt.controldir.sprout('tree3').open_workingtree()

        tree2.commit('unchanged', rev_id=b'b3')
        tree3.commit('unchanged', rev_id=b'c3')

        wt.merge_from_branch(tree2.branch)
        wt.merge_from_branch(tree3.branch, force=True)
        wt.commit('merge b3, c3', rev_id=b'a3')

        tree2.commit('unchanged', rev_id=b'b4')
        tree3.commit('unchanged', rev_id=b'c4')

        wt.merge_from_branch(tree3.branch)
        wt.merge_from_branch(tree2.branch, force=True)
        wt.commit('merge b4, c4', rev_id=b'a4')

        self.assertEqual([b'a4'], wt.get_parent_ids())

        os.chdir('tree')
        out, err = self.run_bzr('uncommit --force -r 2')

        self.assertEqual([b'a2', b'c4', b'b4'], wt.get_parent_ids())

    def test_uncommit_nonascii(self):
        tree = self.make_branch_and_tree('tree')
        tree.commit(u'\u1234 message')
        out, err = self.run_bzr('uncommit --force tree', encoding='ascii')
        self.assertContainsRe(out, r'\? message')

    def test_uncommit_removes_tags(self):
        tree = self.make_branch_and_tree('tree')
        revid = tree.commit('message')
        tree.branch.tags.set_tag("atag", revid)
        out, err = self.run_bzr('uncommit --force tree')
        self.assertEqual({}, tree.branch.tags.get_tag_dict())

    def test_uncommit_keep_tags(self):
        tree = self.make_branch_and_tree('tree')
        revid = tree.commit('message')
        tree.branch.tags.set_tag("atag", revid)
        out, err = self.run_bzr('uncommit --keep-tags --force tree')
        self.assertEqual({"atag": revid}, tree.branch.tags.get_tag_dict())


class TestInconsistentDelta(TestCaseWithTransport):
    # See https://bugs.launchpad.net/bzr/+bug/855155
    # See https://bugs.launchpad.net/bzr/+bug/1100385
    # brz uncommit may result in error
    # 'An inconsistent delta was supplied involving'

    def test_inconsistent_delta(self):
        # Script taken from https://bugs.launchpad.net/bzr/+bug/855155/comments/26
        wt = self.make_branch_and_tree('test')
        self.build_tree(['test/a/', 'test/a/b', 'test/a/c'])
        wt.add(['a', 'a/b', 'a/c'])
        wt.commit('initial commit', rev_id=b'a1')
        wt.remove(['a/b', 'a/c'])
        wt.commit('remove b and c', rev_id=b'a2')
        self.run_bzr("uncommit --force test")

# Copyright (C) 2010-2018 Jelmer Vernooij <jelmer@jelmer.uk>
# Copyright (C) 2011 Canonical Ltd.
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

"""Tests for Git working trees."""

from __future__ import absolute_import

import os
import stat

from dulwich.objects import (
    Blob,
    Tree,
    ZERO_SHA,
    )

from .... import conflicts as _mod_conflicts
from ..workingtree import (
    FLAG_STAGEMASK,
    changes_between_git_tree_and_working_copy,
    )
from ....tests import TestCaseWithTransport


class GitWorkingTreeTests(TestCaseWithTransport):

    def setUp(self):
        super(GitWorkingTreeTests, self).setUp()
        self.tree = self.make_branch_and_tree('.', format="git")

    def test_conflict_list(self):
        self.assertIsInstance(
                self.tree.conflicts(),
                _mod_conflicts.ConflictList)

    def test_add_conflict(self):
        self.build_tree(['conflicted'])
        self.tree.add(['conflicted'])
        with self.tree.lock_tree_write():
            self.tree.index['conflicted'] = self.tree.index['conflicted'][:9] + (FLAG_STAGEMASK, )
            self.tree._index_dirty = True
        conflicts = self.tree.conflicts()
        self.assertEqual(1, len(conflicts))

    def test_revert_empty(self):
        self.build_tree(['a'])
        self.tree.add(['a'])
        self.assertTrue(self.tree.is_versioned('a'))
        self.tree.revert(['a'])
        self.assertFalse(self.tree.is_versioned('a'))


class ChangesBetweenGitTreeAndWorkingCopyTests(TestCaseWithTransport):

    def setUp(self):
        super(ChangesBetweenGitTreeAndWorkingCopyTests, self).setUp()
        self.wt = self.make_branch_and_tree('.', format='git')

    def expectDelta(self, expected_changes,
                    expected_extras=None, want_unversioned=False):
        store = self.wt.branch.repository._git.object_store
        try:
            tree_id = store[self.wt.branch.repository._git.head()].tree
        except KeyError:
            tree_id = None
        with self.wt.lock_read():
            changes, extras = changes_between_git_tree_and_working_copy(
                store, tree_id, self.wt, want_unversioned=want_unversioned)
            self.assertEqual(expected_changes, list(changes))
        if expected_extras is None:
            expected_extras = set()
        self.assertEqual(set(expected_extras), set(extras))

    def test_empty(self):
        self.expectDelta(
            [((None, ''), (None, stat.S_IFDIR), (None, Tree().id))])

    def test_added_file(self):
        self.build_tree(['a'])
        self.wt.add(['a'])
        a = Blob.from_string('contents of a\n')
        t = Tree()
        t.add("a", stat.S_IFREG | 0o644, a.id)
        self.expectDelta(
            [((None, ''), (None, stat.S_IFDIR), (None, t.id)),
             ((None, 'a'), (None, stat.S_IFREG | 0o644), (None, a.id))])

    def test_added_unknown_file(self):
        self.build_tree(['a'])
        t = Tree()
        self.expectDelta(
            [((None, ''), (None, stat.S_IFDIR), (None, t.id))])
        a = Blob.from_string('contents of a\n')
        t = Tree()
        t.add("a", stat.S_IFREG | 0o644, a.id)
        self.expectDelta(
            [((None, ''), (None, stat.S_IFDIR), (None, t.id)),
             ((None, 'a'), (None, stat.S_IFREG | 0o644), (None, a.id))],
            ['a'],
            want_unversioned=True)

    def test_missing_added_file(self):
        self.build_tree(['a'])
        self.wt.add(['a'])
        os.unlink('a')
        a = Blob.from_string('contents of a\n')
        t = Tree()
        t.add("a", 0, ZERO_SHA)
        self.expectDelta(
            [((None, ''), (None, stat.S_IFDIR), (None, t.id)),
             ((None, 'a'), (None, 0), (None, ZERO_SHA))],
            [])

    def test_missing_versioned_file(self):
        self.build_tree(['a'])
        self.wt.add(['a'])
        self.wt.commit('')
        os.unlink('a')
        a = Blob.from_string('contents of a\n')
        oldt = Tree()
        oldt.add("a", stat.S_IFREG | 0o644, a.id)
        newt = Tree()
        newt.add("a", 0, ZERO_SHA)
        self.expectDelta(
                [(('', ''), (stat.S_IFDIR, stat.S_IFDIR), (oldt.id, newt.id)),
                 (('a', 'a'), (stat.S_IFREG|0o644, 0), (a.id, ZERO_SHA))])

    def test_versioned_replace_by_dir(self):
        self.build_tree(['a'])
        self.wt.add(['a'])
        self.wt.commit('')
        os.unlink('a')
        os.mkdir('a')
        olda = Blob.from_string('contents of a\n')
        oldt = Tree()
        oldt.add("a", stat.S_IFREG | 0o644, olda.id)
        newt = Tree()
        newa = Tree()
        newt.add("a", stat.S_IFDIR, newa.id)
        self.expectDelta([
            (('', ''),
            (stat.S_IFDIR, stat.S_IFDIR),
            (oldt.id, newt.id)),
            (('a', 'a'), (stat.S_IFREG | 0o644, stat.S_IFDIR), (olda.id, newa.id))
            ], want_unversioned=False)
        self.expectDelta([
            (('', ''),
            (stat.S_IFDIR, stat.S_IFDIR),
            (oldt.id, newt.id)),
            (('a', 'a'), (stat.S_IFREG | 0o644, stat.S_IFDIR), (olda.id, newa.id))
            ], want_unversioned=True)

    def test_extra(self):
        self.build_tree(['a'])
        newa = Blob.from_string('contents of a\n')
        newt = Tree()
        newt.add("a", stat.S_IFREG | 0o644, newa.id)
        self.expectDelta([
            ((None, ''),
            (None, stat.S_IFDIR),
            (None, newt.id)),
            ((None, 'a'), (None, stat.S_IFREG | 0o644), (None, newa.id))
            ], ['a'], want_unversioned=True)

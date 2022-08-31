# Copyright (C) 2007-2010 Canonical Ltd
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

"""Tests for interface conformance of canonical paths of trees."""


from breezy import (
    tests,
    )
from breezy.tests.per_workingtree import (
    TestCaseWithWorkingTree,
    )
from breezy.tests import (
    features,
    )


class TestCanonicalPaths(TestCaseWithWorkingTree):

    def _make_canonical_test_tree(self, commit=True):
        # make a tree used by all the 'canonical' tests below.
        work_tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/dir/', 'tree/dir/file'])
        work_tree.add(['dir', 'dir/file'])
        if commit:
            work_tree.commit('commit 1')
        # XXX: this isn't actually guaranteed to return the class we want to
        # test -- mbp 2010-02-12
        return work_tree

    def test_canonical_path(self):
        work_tree = self._make_canonical_test_tree()
        if features.CaseInsensitiveFilesystemFeature.available():
            self.assertEqual('dir/file',
                             work_tree.get_canonical_path('Dir/File'))
        else:
            self.assertEqual('Dir/File',
                             work_tree.get_canonical_path('Dir/File'))

    def test_canonical_path_before_commit(self):
        work_tree = self._make_canonical_test_tree(False)
        if features.CaseInsensitiveFilesystemFeature.available():
            self.assertEqual('dir/file',
                             work_tree.get_canonical_path('Dir/File'))
        else:
            self.assertEqual('Dir/File',
                             work_tree.get_canonical_path('Dir/File'))

    def test_canonical_path_dir(self):
        # check it works when asked for just the directory portion.
        work_tree = self._make_canonical_test_tree()
        if features.CaseInsensitiveFilesystemFeature.available():
            self.assertEqual('dir', work_tree.get_canonical_path('Dir'))
        else:
            self.assertEqual('Dir', work_tree.get_canonical_path('Dir'))

    def test_canonical_path_root(self):
        work_tree = self._make_canonical_test_tree()
        self.assertEqual('', work_tree.get_canonical_path(''))
        self.assertEqual('', work_tree.get_canonical_path('/'))

    def test_canonical_path_invalid_all(self):
        work_tree = self._make_canonical_test_tree()
        self.assertEqual('foo/bar',
                         work_tree.get_canonical_path('foo/bar'))

    def test_canonical_invalid_child(self):
        work_tree = self._make_canonical_test_tree()
        if features.CaseInsensitiveFilesystemFeature.available():
            self.assertEqual('dir/None',
                             work_tree.get_canonical_path('Dir/None'))
        else:
            self.assertEqual('Dir/None',
                             work_tree.get_canonical_path('Dir/None'))

    def test_canonical_tree_name_mismatch(self):
        # see <https://bugs.launchpad.net/bzr/+bug/368931>
        # some of the trees we want to use can only exist on a disk, not in
        # memory - therefore we can only test this if the filesystem is
        # case-sensitive.
        self.requireFeature(features.case_sensitive_filesystem_feature)
        work_tree = self.make_branch_and_tree('.')
        self.build_tree(['test/', 'test/file', 'Test'])
        work_tree.add(['test/', 'test/file', 'Test'])

        self.assertEqual(['test', 'Test', 'test/file', 'Test/file'],
                         list(work_tree.get_canonical_paths(
                             ['test', 'Test', 'test/file', 'Test/file'])))

        test_revid = work_tree.commit('commit')
        test_tree = work_tree.branch.repository.revision_tree(test_revid)
        test_tree.lock_read()
        self.addCleanup(test_tree.unlock)

        self.assertEqual(['', 'Test', 'test', 'test/file'],
                         [p for p, e in test_tree.iter_entries_by_dir()])

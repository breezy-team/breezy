# Copyright (C) 2020 Jelmer Vernooij <jelmer@jelmer.uk>
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

from . import (
    TestCaseWithTransport,
    )

from ..workspace import (
    PendingChanges,
    check_clean_tree,
    )


class CheckCleanTreeTests(TestCaseWithTransport):

    def make_test_tree(self, format=None):
        tree = self.make_branch_and_tree('.', format=format)
        self.build_tree_contents([
            ('debian/', ),
            ('debian/control', """\
Source: blah
Vcs-Git: https://example.com/blah
Testsuite: autopkgtest

Binary: blah
Arch: all

"""),
            ('debian/changelog', 'Some contents')])
        tree.add(['debian', 'debian/changelog', 'debian/control'])
        tree.commit('Initial thingy.')
        return tree

    def test_pending_changes(self):
        tree = self.make_test_tree()
        self.build_tree_contents([('debian/changelog', 'blah')])
        with tree.lock_write():
            self.assertRaises(
                PendingChanges, check_clean_tree, tree)

    def test_pending_changes_bzr_empty_dir(self):
        # See https://bugs.debian.org/914038
        tree = self.make_test_tree(format='bzr')
        self.build_tree_contents([('debian/upstream/', )])
        with tree.lock_write():
            self.assertRaises(
                PendingChanges, check_clean_tree, tree)

    def test_pending_changes_git_empty_dir(self):
        # See https://bugs.debian.org/914038
        tree = self.make_test_tree(format='git')
        self.build_tree_contents([('debian/upstream/', )])
        with tree.lock_write():
            check_clean_tree(tree)

    def test_pending_changes_git_dir_with_ignored(self):
        # See https://bugs.debian.org/914038
        tree = self.make_test_tree(format='git')
        self.build_tree_contents([
            ('debian/upstream/', ),
            ('debian/upstream/blah', ''),
            ('.gitignore', 'blah\n'),
            ])
        tree.add('.gitignore')
        tree.commit('add gitignore')
        with tree.lock_write():
            check_clean_tree(tree)

    def test_extra(self):
        tree = self.make_test_tree()
        self.build_tree_contents([('debian/foo', 'blah')])
        with tree.lock_write():
            self.assertRaises(
                PendingChanges, check_clean_tree,
                tree)

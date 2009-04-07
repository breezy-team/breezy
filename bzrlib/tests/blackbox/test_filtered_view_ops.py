# Copyright (C) 2008 Canonical Ltd
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

"""Tests that an enabled view is reported and impacts expected commands."""

import os

from bzrlib import bzrdir
from bzrlib.tests import TestCaseWithTransport
from bzrlib.workingtree import WorkingTree


class TestViewFileOperations(TestCaseWithTransport):

    def make_abc_tree_with_ab_view(self):
        # we need to use a specific format because the default format
        # doesn't support views yet
        format = bzrdir.format_registry.make_bzrdir('development6-rich-root')
        wt = TestCaseWithTransport.make_branch_and_tree(self, '.',
            format=format)
        self.build_tree(['a', 'b', 'c'])
        wt.views.set_view('my', ['a', 'b'])
        return wt

    def test_view_on_status(self):
        wt = self.make_abc_tree_with_ab_view()
        out, err = self.run_bzr('status')
        self.assertEquals('Ignoring files outside view. View is a, b\n', err)
        self.assertEquals('unknown:\n  a\n  b\n', out)

    def test_view_on_status_selected(self):
        wt = self.make_abc_tree_with_ab_view()
        out, err = self.run_bzr('status a')
        self.assertEquals('', err)
        self.assertEquals('unknown:\n  a\n', out)
        out, err = self.run_bzr('status c', retcode=3)
        self.assertEquals('bzr: ERROR: Specified file "c" is outside the '
                          'current view: a, b\n', err)
        self.assertEquals('', out)

    def test_view_on_add(self):
        wt = self.make_abc_tree_with_ab_view()
        out, err = self.run_bzr('add')
        self.assertEquals('Ignoring files outside view. View is a, b\n', err)
        self.assertEquals('adding a\nadding b\n', out)

    def test_view_on_add_selected(self):
        wt = self.make_abc_tree_with_ab_view()
        out, err = self.run_bzr('add a')
        self.assertEquals('', err)
        self.assertEquals('adding a\n', out)
        out, err = self.run_bzr('add c', retcode=3)
        self.assertEquals('bzr: ERROR: Specified file "c" is outside the '
                          'current view: a, b\n', err)
        self.assertEquals('', out)

    def test_view_on_diff(self):
        wt = self.make_abc_tree_with_ab_view()
        self.run_bzr('add')
        out, err = self.run_bzr('diff', retcode=1)
        self.assertEquals('*** Ignoring files outside view. View is a, b\n', err)

    def test_view_on_diff_selected(self):
        wt = self.make_abc_tree_with_ab_view()
        self.run_bzr('add')
        out, err = self.run_bzr('diff a', retcode=1)
        self.assertEquals('', err)
        self.assertStartsWith(out, "=== added file 'a'\n")
        out, err = self.run_bzr('diff c', retcode=3)
        self.assertEquals('bzr: ERROR: Specified file "c" is outside the '
                          'current view: a, b\n', err)
        self.assertEquals('', out)

    def test_view_on_commit(self):
        wt = self.make_abc_tree_with_ab_view()
        self.run_bzr('add')
        out, err = self.run_bzr('commit -m "testing commit"')
        err_lines = err.splitlines()
        self.assertEquals('Ignoring files outside view. View is a, b', err_lines[0])
        self.assertStartsWith(err_lines[1], 'Committing to:')
        self.assertEquals('added a', err_lines[2])
        self.assertEquals('added b', err_lines[3])
        self.assertEquals('Committed revision 1.', err_lines[4])
        self.assertEquals('', out)

    def test_view_on_commit_selected(self):
        wt = self.make_abc_tree_with_ab_view()
        self.run_bzr('add')
        out, err = self.run_bzr('commit -m "file in view" a')
        err_lines = err.splitlines()
        self.assertStartsWith(err_lines[0], 'Committing to:')
        self.assertEquals('added a', err_lines[1])
        self.assertEquals('Committed revision 1.', err_lines[2])
        self.assertEquals('', out)
        out, err = self.run_bzr('commit -m "file out of view" c', retcode=3)
        self.assertEquals('bzr: ERROR: Specified file "c" is outside the '
                          'current view: a, b\n', err)
        self.assertEquals('', out)

    def test_view_on_remove_selected(self):
        wt = self.make_abc_tree_with_ab_view()
        self.run_bzr('add')
        out, err = self.run_bzr('remove --keep a')
        self.assertEquals('removed a\n', err)
        self.assertEquals('', out)
        out, err = self.run_bzr('remove --keep c', retcode=3)
        self.assertEquals('bzr: ERROR: Specified file "c" is outside the '
                          'current view: a, b\n', err)
        self.assertEquals('', out)

    def test_view_on_revert(self):
        wt = self.make_abc_tree_with_ab_view()
        self.run_bzr('add')
        out, err = self.run_bzr('revert')
        err_lines = err.splitlines()
        self.assertEquals('Ignoring files outside view. View is a, b', err_lines[0])
        self.assertEquals('-   a', err_lines[1])
        self.assertEquals('-   b', err_lines[2])
        self.assertEquals('', out)

    def test_view_on_revert_selected(self):
        wt = self.make_abc_tree_with_ab_view()
        self.run_bzr('add')
        out, err = self.run_bzr('revert a')
        self.assertEquals('-   a\n', err)
        self.assertEquals('', out)
        out, err = self.run_bzr('revert c', retcode=3)
        self.assertEquals('bzr: ERROR: Specified file "c" is outside the '
                          'current view: a, b\n', err)
        self.assertEquals('', out)

    def test_view_on_ls(self):
        wt = self.make_abc_tree_with_ab_view()
        self.run_bzr('add')
        out, err = self.run_bzr('ls')
        out_lines = out.splitlines()
        self.assertEquals('Ignoring files outside view. View is a, b\n', err)
        self.assertEquals('a', out_lines[0])
        self.assertEquals('b', out_lines[1])


class TestViewTreeOperationss(TestCaseWithTransport):

    def make_abc_tree_and_clone_with_ab_view(self):
        # we need to use a specific format because the default format
        # doesn't support views yet
        format = bzrdir.format_registry.make_bzrdir('development6-rich-root')
        # Build the first tree
        wt1 = TestCaseWithTransport.make_branch_and_tree(self, 'tree_1',
            format=format)
        self.build_tree(['tree_1/a', 'tree_1/b', 'tree_1/c'])
        wt1.add(['a', 'b', 'c'])
        wt1.commit("adding a b c")
        # Build the second tree and give it a view
        wt2 = wt1.bzrdir.sprout('tree_2').open_workingtree()
        wt2.views.set_view('my', ['a', 'b'])
        # Commit a change to the first tree
        self.build_tree_contents([
            ('tree_1/a', 'changed a\n'),
            ('tree_1/c', 'changed c\n'),
            ])
        wt1.commit("changing a c")
        return wt1, wt2

    def test_view_on_pull(self):
        tree_1, tree_2 = self.make_abc_tree_and_clone_with_ab_view()
        out, err = self.run_bzr('pull -d tree_2 tree_1')
        self.assertEqualDiff(
            "Operating on whole tree but only reporting on 'my' view.\n"
            " M  a\n"
            "All changes applied successfully.\n", err)
        self.assertEqualDiff("Now on revision 2.\n", out)

    def test_view_on_update(self):
        tree_1, tree_2 = self.make_abc_tree_and_clone_with_ab_view()
        os.chdir("tree_2")
        self.run_bzr("bind ../tree_1")
        out, err = self.run_bzr('update')
        self.assertEqualDiff(
            "Operating on whole tree but only reporting on 'my' view.\n"
            " M  a\n"
            "All changes applied successfully.\n"
            "Updated to revision 2.\n", err)
        self.assertEqualDiff("", out)

    def test_view_on_merge(self):
        tree_1, tree_2 = self.make_abc_tree_and_clone_with_ab_view()
        out, err = self.run_bzr('merge -d tree_2 tree_1')
        self.assertEqualDiff(
            "Operating on whole tree but only reporting on 'my' view.\n"
            " M  a\n"
            "All changes applied successfully.\n", err)
        self.assertEqualDiff("", out)

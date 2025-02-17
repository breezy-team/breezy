# Copyright (C) 2008, 2009, 2010, 2012, 2016 Canonical Ltd
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

from breezy import osutils, tests


class TestViewFileOperations(tests.TestCaseWithTransport):
    def make_abc_tree_with_ab_view(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(["a", "b", "c"])
        wt.views.set_view("my", ["a", "b"])
        return wt

    def test_view_on_status(self):
        self.make_abc_tree_with_ab_view()
        out, err = self.run_bzr("status")
        self.assertEqual("Ignoring files outside view. View is a, b\n", err)
        self.assertEqual("unknown:\n  a\n  b\n", out)

    def test_view_on_status_selected(self):
        self.make_abc_tree_with_ab_view()
        out, err = self.run_bzr("status a")
        self.assertEqual("", err)
        self.assertEqual("unknown:\n  a\n", out)
        out, err = self.run_bzr("status c", retcode=3)
        self.assertEqual(
            'brz: ERROR: Specified file "c" is outside the current view: a, b\n', err
        )
        self.assertEqual("", out)

    def test_view_on_add(self):
        self.make_abc_tree_with_ab_view()
        out, err = self.run_bzr("add")
        self.assertEqual("Ignoring files outside view. View is a, b\n", err)
        self.assertEqual("adding a\nadding b\n", out)

    def test_view_on_add_selected(self):
        self.make_abc_tree_with_ab_view()
        out, err = self.run_bzr("add a")
        self.assertEqual("", err)
        self.assertEqual("adding a\n", out)
        out, err = self.run_bzr("add c", retcode=3)
        self.assertEqual(
            'brz: ERROR: Specified file "c" is outside the current view: a, b\n', err
        )
        self.assertEqual("", out)

    def test_view_on_diff(self):
        self.make_abc_tree_with_ab_view()
        self.run_bzr("add")
        out, err = self.run_bzr("diff --color=never", retcode=1)
        self.assertEqual("*** Ignoring files outside view. View is a, b\n", err)

    def test_view_on_diff_selected(self):
        self.make_abc_tree_with_ab_view()
        self.run_bzr("add")
        out, err = self.run_bzr("diff --color=never a", retcode=1)
        self.assertEqual("", err)
        self.assertStartsWith(out, "=== added file 'a'\n")
        out, err = self.run_bzr("diff --color=never c", retcode=3)
        self.assertEqual(
            'brz: ERROR: Specified file "c" is outside the current view: a, b\n', err
        )
        self.assertEqual("", out)

    def test_view_on_commit(self):
        self.make_abc_tree_with_ab_view()
        self.run_bzr("add")
        out, err = self.run_bzr('commit -m "testing commit"')
        err_lines = err.splitlines()
        self.assertEqual("Ignoring files outside view. View is a, b", err_lines[0])
        self.assertStartsWith(err_lines[1], "Committing to:")
        # TODO(jelmer): Should 'added ' output for commit be sorted?
        self.assertIn("added a", [err_lines[2], err_lines[3]])
        self.assertIn("added b", [err_lines[2], err_lines[3]])
        self.assertEqual("Committed revision 1.", err_lines[4])
        self.assertEqual("", out)

    def test_view_on_commit_selected(self):
        self.make_abc_tree_with_ab_view()
        self.run_bzr("add")
        out, err = self.run_bzr('commit -m "file in view" a')
        err_lines = err.splitlines()
        self.assertStartsWith(err_lines[0], "Committing to:")
        self.assertEqual("added a", err_lines[1])
        self.assertEqual("Committed revision 1.", err_lines[2])
        self.assertEqual("", out)
        out, err = self.run_bzr('commit -m "file out of view" c', retcode=3)
        self.assertEqual(
            'brz: ERROR: Specified file "c" is outside the current view: a, b\n', err
        )
        self.assertEqual("", out)

    def test_view_on_remove_selected(self):
        self.make_abc_tree_with_ab_view()
        self.run_bzr("add")
        out, err = self.run_bzr("remove --keep a")
        self.assertEqual("removed a\n", err)
        self.assertEqual("", out)
        out, err = self.run_bzr("remove --keep c", retcode=3)
        self.assertEqual(
            'brz: ERROR: Specified file "c" is outside the current view: a, b\n', err
        )
        self.assertEqual("", out)

    def test_view_on_revert(self):
        self.make_abc_tree_with_ab_view()
        self.run_bzr("add")
        out, err = self.run_bzr("revert")
        err_lines = err.splitlines()
        self.assertEqual("Ignoring files outside view. View is a, b", err_lines[0])
        self.assertEqual("-   a", err_lines[1])
        self.assertEqual("-   b", err_lines[2])
        self.assertEqual("", out)

    def test_view_on_revert_selected(self):
        self.make_abc_tree_with_ab_view()
        self.run_bzr("add")
        out, err = self.run_bzr("revert a")
        self.assertEqual("-   a\n", err)
        self.assertEqual("", out)
        out, err = self.run_bzr("revert c", retcode=3)
        self.assertEqual(
            'brz: ERROR: Specified file "c" is outside the current view: a, b\n', err
        )
        self.assertEqual("", out)

    def test_view_on_ls(self):
        self.make_abc_tree_with_ab_view()
        self.run_bzr("add")
        out, err = self.run_bzr("ls")
        out_lines = out.splitlines()
        self.assertEqual("Ignoring files outside view. View is a, b\n", err)
        self.assertEqual("a", out_lines[0])
        self.assertEqual("b", out_lines[1])


class TestViewTreeOperations(tests.TestCaseWithTransport):
    def make_abc_tree_and_clone_with_ab_view(self):
        # Build the first tree
        wt1 = self.make_branch_and_tree("tree_1")
        self.build_tree(["tree_1/a", "tree_1/b", "tree_1/c"])
        wt1.add(["a", "b", "c"])
        wt1.commit("adding a b c")
        # Build the second tree and give it a view
        wt2 = wt1.controldir.sprout("tree_2").open_workingtree()
        wt2.views.set_view("my", ["a", "b"])
        # Commit a change to the first tree
        self.build_tree_contents(
            [
                ("tree_1/a", b"changed a\n"),
                ("tree_1/c", b"changed c\n"),
            ]
        )
        wt1.commit("changing a c")
        return wt1, wt2

    def test_view_on_pull(self):
        tree_1, tree_2 = self.make_abc_tree_and_clone_with_ab_view()
        out, err = self.run_bzr("pull -d tree_2 tree_1")
        self.assertEqualDiff(
            "Operating on whole tree but only reporting on 'my' view.\n"
            " M  a\n"
            "All changes applied successfully.\n",
            err,
        )
        self.assertEqualDiff("Now on revision 2.\n", out)

    def test_view_on_update(self):
        tree_1, tree_2 = self.make_abc_tree_and_clone_with_ab_view()
        self.run_bzr("bind ../tree_1", working_dir="tree_2")
        out, err = self.run_bzr("update", working_dir="tree_2")
        self.assertEqualDiff(
            f"""Operating on whole tree but only reporting on 'my' view.
 M  a
All changes applied successfully.
Updated to revision 2 of branch {osutils.pathjoin(self.test_dir, "tree_1")}
""",
            err,
        )
        self.assertEqual("", out)

    def test_view_on_merge(self):
        tree_1, tree_2 = self.make_abc_tree_and_clone_with_ab_view()
        out, err = self.run_bzr("merge -d tree_2 tree_1")
        self.assertEqualDiff(
            "Operating on whole tree but only reporting on 'my' view.\n"
            " M  a\n"
            "All changes applied successfully.\n",
            err,
        )
        self.assertEqual("", out)

# Copyright (C) 2008, 2009, 2010 Canonical Ltd
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

import os

from breezy import shelf
from breezy.tests import TestCaseWithTransport
from breezy.tests.script import ScriptRunner


class TestShelveList(TestCaseWithTransport):
    def test_no_shelved_changes(self):
        tree = self.make_branch_and_tree(".")
        err = self.run_bzr("shelve --list")[1]
        self.assertEqual("No shelved changes.\n", err)

    def make_creator(self, tree):
        creator = shelf.ShelfCreator(tree, tree.basis_tree(), [])
        self.addCleanup(creator.finalize)
        return creator

    def test_shelve_one(self):
        tree = self.make_branch_and_tree(".")
        creator = self.make_creator(tree)
        shelf_id = tree.get_shelf_manager().shelve_changes(creator, "Foo")
        out, err = self.run_bzr("shelve --list", retcode=1)
        self.assertEqual("", err)
        self.assertEqual("  1: Foo\n", out)

    def test_shelve_list_via_directory(self):
        tree = self.make_branch_and_tree("tree")
        creator = self.make_creator(tree)
        shelf_id = tree.get_shelf_manager().shelve_changes(creator, "Foo")
        out, err = self.run_bzr("shelve -d tree --list", retcode=1)
        self.assertEqual("", err)
        self.assertEqual("  1: Foo\n", out)

    def test_shelve_no_message(self):
        tree = self.make_branch_and_tree(".")
        creator = self.make_creator(tree)
        shelf_id = tree.get_shelf_manager().shelve_changes(creator)
        out, err = self.run_bzr("shelve --list", retcode=1)
        self.assertEqual("", err)
        self.assertEqual("  1: <no message>\n", out)

    def test_shelf_order(self):
        tree = self.make_branch_and_tree(".")
        creator = self.make_creator(tree)
        tree.get_shelf_manager().shelve_changes(creator, "Foo")
        creator = self.make_creator(tree)
        tree.get_shelf_manager().shelve_changes(creator, "Bar")
        out, err = self.run_bzr("shelve --list", retcode=1)
        self.assertEqual("", err)
        self.assertEqual("  2: Bar\n  1: Foo\n", out)

    def test_shelve_destroy(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["file"])
        tree.add("file")
        self.run_bzr("shelve --all --destroy")
        self.assertPathDoesNotExist("file")
        self.assertIs(None, tree.get_shelf_manager().last_shelf())

    def test_unshelve_keep(self):
        # https://bugs.launchpad.net/bzr/+bug/492091
        tree = self.make_branch_and_tree(".")
        # shelve apparently unhappy working with a tree with no root yet
        tree.commit("make root")
        self.build_tree(["file"])

        sr = ScriptRunner()
        sr.run_script(
            self,
            """
$ brz add file
adding file
$ brz shelve --all -m Foo
2>Selected changes:
2>-D  file
2>Changes shelved with id "1".
$ brz shelve --list
  1: Foo
$ brz unshelve --keep
2>Using changes with id "1".
2>Message: Foo
2>+N  file
2>All changes applied successfully.
$ brz shelve --list
  1: Foo
$ cat file
contents of file
""",
        )


class TestUnshelvePreview(TestCaseWithTransport):
    def test_non_ascii(self):
        """Test that we can show a non-ascii diff that would result from unshelving"""
        init_content = "Initial: \u0418\u0437\u043d\u0430\u0447\n".encode()
        more_content = "More: \u0415\u0449\u0451\n".encode()
        next_content = init_content + more_content
        diff_part = b"@@ -1,1 +1,2 @@\n %s+%s" % (init_content, more_content)

        tree = self.make_branch_and_tree(".")
        self.build_tree_contents([("a_file", init_content)])
        tree.add("a_file")
        tree.commit(message="committed")
        self.build_tree_contents([("a_file", next_content)])
        self.run_bzr(["shelve", "--all"])
        out, err = self.run_bzr_raw(["unshelve", "--preview"], encoding="latin-1")

        self.assertContainsString(out, diff_part)


class TestShelveRelpath(TestCaseWithTransport):
    def test_shelve_in_subdir(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/file", "tree/dir/"])
        tree.add("file")
        os.chdir("tree/dir")
        self.run_bzr("shelve --all ../file")

    def test_shelve_via_directory(self):
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/file", "tree/dir/"])
        tree.add("file")
        self.run_bzr("shelve -d tree/dir --all ../file")


class TestShelveUnshelve(TestCaseWithTransport):
    def test_directory(self):
        """Test --directory option"""
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/a", b"initial\n")])
        tree.add("a")
        tree.commit(message="committed")
        self.build_tree_contents([("tree/a", b"initial\nmore\n")])
        self.run_bzr("shelve -d tree --all")
        self.assertFileEqual(b"initial\n", "tree/a")
        self.run_bzr("unshelve --directory tree")
        self.assertFileEqual(b"initial\nmore\n", "tree/a")

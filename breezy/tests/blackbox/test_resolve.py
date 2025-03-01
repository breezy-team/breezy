# Copyright (C) 2010, 2011 Canonical Ltd
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

from breezy import tests
from breezy.bzr import conflicts as _mod_bzr_conflicts
from breezy.tests import KnownFailure, script
from breezy.tests.blackbox import test_conflicts


class TestResolve(script.TestCaseWithTransportAndScript):
    def setUp(self):
        super().setUp()
        test_conflicts.make_tree_with_conflicts(self, "branch", "other")

    def test_resolve_one_by_one(self):
        self.run_script("""\
$ cd branch
$ brz conflicts
Text conflict in my_other_file
Path conflict: mydir3 / mydir2
Text conflict in myfile
$ brz resolve myfile
2>1 conflict resolved, 2 remaining
$ brz resolve my_other_file
2>1 conflict resolved, 1 remaining
$ brz resolve mydir2
2>1 conflict resolved, 0 remaining
""")

    def test_resolve_all(self):
        self.run_script("""\
$ cd branch
$ brz resolve --all
2>3 conflicts resolved, 0 remaining
$ brz conflicts
""")

    def test_resolve_from_subdir(self):
        self.run_script("""\
$ mkdir branch/subdir
$ cd branch/subdir
$ brz resolve ../myfile
2>1 conflict resolved, 2 remaining
""")

    def test_resolve_via_directory_option(self):
        self.run_script("""\
$ brz resolve -d branch myfile
2>1 conflict resolved, 2 remaining
""")

    def test_resolve_all_via_directory_option(self):
        self.run_script("""\
$ brz resolve -d branch --all
2>3 conflicts resolved, 0 remaining
$ brz conflicts -d branch
""")

    def test_bug_842575_manual_rm(self):
        self.run_script("""\
$ brz init -q trunk
$ echo original > trunk/foo
$ brz add -q trunk/foo
$ brz commit -q -m first trunk
$ brz checkout -q trunk tree
$ brz rm -q trunk/foo
$ brz commit -q -m second trunk
$ echo modified > tree/foo
$ brz update tree
2>RM  foo => foo.THIS
2>Contents conflict in foo
2>1 conflicts encountered.
2>Updated to revision 2 of branch ...
$ rm tree/foo.BASE tree/foo.THIS
$ brz resolve --all -d tree
2>1 conflict resolved, 0 remaining
""")
        try:
            self.run_script("""\
$ brz status tree
""")
        except AssertionError:
            raise KnownFailure("bug #842575")

    def test_bug_842575_take_other(self):
        self.run_script("""\
$ brz init -q trunk
$ echo original > trunk/foo
$ brz add -q trunk/foo
$ brz commit -q -m first trunk
$ brz checkout -q --lightweight trunk tree
$ brz rm -q trunk/foo
$ brz ignore -d trunk foo
$ brz commit -q -m second trunk
$ echo modified > tree/foo
$ brz update tree
2>+N  .bzrignore
2>RM  foo => foo.THIS
2>Contents conflict in foo
2>1 conflicts encountered.
2>Updated to revision 2 of branch ...
$ brz resolve --take-other --all -d tree
2>1 conflict resolved, 0 remaining
""")
        try:
            self.run_script("""\
$ brz status tree
$ echo mustignore > tree/foo
$ brz status tree
""")
        except AssertionError:
            raise KnownFailure("bug 842575")


class TestBug788000(script.TestCaseWithTransportAndScript):
    def test_bug_788000(self):
        self.run_script(
            """\
$ brz init a
$ mkdir a/dir
$ echo foo > a/dir/file
$ brz add a/dir
$ cd a
$ brz commit -m one
$ cd ..
$ brz branch a b
$ echo bar > b/dir/file
$ cd a
$ rm -r dir
$ brz commit -m two
$ cd ../b
""",
            null_output_matches_anything=True,
        )

        self.run_script("""\
$ brz pull
Using saved parent location:...
Now on revision 2.
2>RM  dir/file => dir/file.THIS
2>Conflict: can't delete dir because it is not empty.  Not deleting.
2>Conflict because dir is not versioned, but has versioned children...
2>Contents conflict in dir/file
2>3 conflicts encountered.
""")
        self.run_script("""\
$ brz resolve --take-other
2>deleted dir/file.THIS
2>deleted dir
2>3 conflicts resolved, 0 remaining
""")


class TestResolveAuto(tests.TestCaseWithTransport):
    def test_auto_resolve(self):
        """Text conflicts can be resolved automatically."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree_contents([("tree/file", b"<<<<<<<\na\n=======\n>>>>>>>\n")])
        tree.add("file", ids=b"file_id")
        self.assertEqual(tree.kind("file"), "file")
        file_conflict = _mod_bzr_conflicts.TextConflict("file", file_id=b"file_id")
        tree.set_conflicts([file_conflict])
        note = self.run_bzr("resolve", retcode=1, working_dir="tree")[1]
        self.assertContainsRe(note, "0 conflicts auto-resolved.")
        self.assertContainsRe(note, "Remaining conflicts:\nText conflict in file")
        self.build_tree_contents([("tree/file", b"a\n")])
        note = self.run_bzr("resolve", working_dir="tree")[1]
        self.assertContainsRe(note, "All conflicts resolved.")

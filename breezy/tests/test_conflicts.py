# Copyright (C) 2005-2011 Canonical Ltd
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
from typing import Any, Callable

from .. import conflicts, option, osutils, tests, transform
from ..bzr import conflicts as bzr_conflicts
from . import scenarios, script

load_tests = scenarios.load_tests_apply_scenarios


# TODO: Test commit with some added, and added-but-missing files
# RBC 20060124 is that not tested in test_commit.py ?

# The order of 'path' here is important - do not let it
# be a sorted list.
# u'\xe5' == a with circle
# '\xc3\xae' == u'\xee' == i with hat
# So these are u'path' and 'id' only with a circle and a hat. (shappo?)
example_conflicts = [
    bzr_conflicts.MissingParent("Not deleting", "p\xe5thg", b"\xc3\xaedg"),
    bzr_conflicts.ContentsConflict("p\xe5tha", None, b"\xc3\xaeda"),
    bzr_conflicts.TextConflict("p\xe5tha"),
    bzr_conflicts.PathConflict("p\xe5thb", "p\xe5thc", b"\xc3\xaedb"),
    bzr_conflicts.DuplicateID(
        "Unversioned existing file",
        "p\xe5thc",
        "p\xe5thc2",
        b"\xc3\xaedc",
        b"\xc3\xaedc",
    ),
    bzr_conflicts.DuplicateEntry(
        "Moved existing file to", "p\xe5thdd.moved", "p\xe5thd", b"\xc3\xaedd", None
    ),
    bzr_conflicts.ParentLoop(
        "Cancelled move", "p\xe5the", "p\xe5th2e", None, b"\xc3\xaed2e"
    ),
    bzr_conflicts.UnversionedParent("Versioned directory", "p\xe5thf", b"\xc3\xaedf"),
    bzr_conflicts.NonDirectoryParent("Created directory", "p\xe5thg", b"\xc3\xaedg"),
]


def vary_by_conflicts():
    for conflict in example_conflicts:
        yield (conflict.__class__.__name__, {"conflict": conflict})


class TestConflicts(tests.TestCaseWithTransport):
    def test_resolve_conflict_dir(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree_contents(
            [
                ("hello", b"hello world4"),
                ("hello.THIS", b"hello world2"),
                ("hello.BASE", b"hello world1"),
            ]
        )
        os.mkdir("hello.OTHER")
        tree.add("hello", ids=b"q")
        l = conflicts.ConflictList([bzr_conflicts.TextConflict("hello")])
        l.remove_files(tree)

    def test_select_conflicts(self):
        tree = self.make_branch_and_tree(".")
        clist = conflicts.ConflictList

        def check_select(not_selected, selected, paths, **kwargs):
            self.assertEqual(
                (not_selected, selected),
                tree_conflicts.select_conflicts(tree, paths, **kwargs),
            )

        foo = bzr_conflicts.ContentsConflict("foo")
        bar = bzr_conflicts.ContentsConflict("bar")
        tree_conflicts = clist([foo, bar])

        check_select(clist([bar]), clist([foo]), ["foo"])
        check_select(clist(), tree_conflicts, [""], ignore_misses=True, recurse=True)

        foobaz = bzr_conflicts.ContentsConflict("foo/baz")
        tree_conflicts = clist([foobaz, bar])

        check_select(
            clist([bar]), clist([foobaz]), ["foo"], ignore_misses=True, recurse=True
        )

        qux = bzr_conflicts.PathConflict("qux", "foo/baz")
        tree_conflicts = clist([qux])

        check_select(tree_conflicts, clist(), ["foo"], ignore_misses=True, recurse=True)
        check_select(tree_conflicts, clist(), ["foo"], ignore_misses=True)

    def test_resolve_conflicts_recursive(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["dir/", "dir/hello"])
        tree.add(["dir", "dir/hello"])

        dirhello = [bzr_conflicts.TextConflict("dir/hello")]
        tree.set_conflicts(dirhello)

        conflicts.resolve(tree, ["dir"], recursive=False, ignore_misses=True)
        self.assertEqual(dirhello, tree.conflicts())

        conflicts.resolve(tree, ["dir"], recursive=True, ignore_misses=True)
        self.assertEqual(conflicts.ConflictList([]), tree.conflicts())


class TestPerConflict(tests.TestCase):
    scenarios = scenarios.multiply_scenarios(vary_by_conflicts())

    def test_stringification(self):
        text = str(self.conflict)
        self.assertContainsString(text, self.conflict.path)
        self.assertContainsString(text.lower(), "conflict")
        self.assertContainsString(repr(self.conflict), self.conflict.__class__.__name__)


class TestConflictList(tests.TestCase):
    def test_stanzas_roundtrip(self):
        stanzas_iter = bzr_conflicts.ConflictList(example_conflicts).to_stanzas()
        processed = bzr_conflicts.ConflictList.from_stanzas(stanzas_iter)
        self.assertEqual(example_conflicts, processed)

    def test_stringification(self):
        for text, o in zip(
            bzr_conflicts.ConflictList(example_conflicts).to_strings(),
            example_conflicts,
        ):
            self.assertEqual(text, str(o))


# FIXME: The shell-like tests should be converted to real whitebox tests... or
# moved to a blackbox module -- vila 20100205

# FIXME: test missing for multiple conflicts


# FIXME: Tests missing for DuplicateID conflict type
class TestResolveConflicts(script.TestCaseWithTransportAndScript):
    preamble: str  # The setup script set by daughter classes

    def setUp(self):
        super().setUp()
        self.run_script(self.preamble)


def mirror_scenarios(base_scenarios):
    """Return a list of mirrored scenarios.

    Each scenario in base_scenarios is duplicated switching the roles of 'this'
    and 'other'
    """
    scenarios = []
    for common, (lname, ldict), (rname, rdict) in base_scenarios:
        a = tests.multiply_scenarios(
            [(lname, {"_this": ldict})], [(rname, {"_other": rdict})]
        )
        b = tests.multiply_scenarios(
            [(rname, {"_this": rdict})], [(lname, {"_other": ldict})]
        )
        # Inject the common parameters in all scenarios
        for _name, d in a + b:
            d.update(common)
        scenarios.extend(a + b)
    return scenarios


# FIXME: Get rid of parametrized (in the class name) once we delete
# TestResolveConflicts -- vila 20100308
class TestParametrizedResolveConflicts(tests.TestCaseWithTransport):
    """This class provides a base to test single conflict resolution.

    Since all conflict objects are created with specific semantics for their
    attributes, each class should implement the necessary functions and
    attributes described below.

    Each class should define the scenarios that create the expected (single)
    conflict.

    Each scenario describes:
    * how to create 'base' tree (and revision)
    * how to create 'left' tree (and revision, parent rev 'base')
    * how to create 'right' tree (and revision, parent rev 'base')
    * how to check that changes in 'base'->'left' have been taken
    * how to check that changes in 'base'->'right' have been taken

    From each base scenario, we generate two concrete scenarios where:
    * this=left, other=right
    * this=right, other=left

    Then the test case verifies each concrete scenario by:
    * creating a branch containing the 'base', 'this' and 'other' revisions
    * creating a working tree for the 'this' revision
    * performing the merge of 'other' into 'this'
    * verifying the expected conflict was generated
    * resolving with --take-this or --take-other, and running the corresponding
      checks (for either 'base'->'this', or 'base'->'other')

    :cvar _conflict_type: The expected class of the generated conflict.

    :cvar _assert_conflict: A method receiving the working tree and the
        conflict object and checking its attributes.

    :cvar _base_actions: The branchbuilder actions to create the 'base'
        revision.

    :cvar _this: The dict related to 'base' -> 'this'. It contains at least:
      * 'actions': The branchbuilder actions to create the 'this'
          revision.
      * 'check': how to check the changes after resolution with --take-this.

    :cvar _other: The dict related to 'base' -> 'other'. It contains at least:
      * 'actions': The branchbuilder actions to create the 'other'
          revision.
      * 'check': how to check the changes after resolution with --take-other.
    """

    # Set by daughter classes
    _conflict_type: type[conflicts.Conflict]
    _assert_conflict: Callable[[Any, Any], Any]

    # Set by load_tests
    _base_actions = None
    _this = None
    _other = None

    scenarios: list[
        tuple[dict[str, Any], tuple[str, dict[str, Any]], tuple[str, dict[str, Any]]]
    ] = []
    """The scenario list for the conflict type defined by the class.

    Each scenario is of the form:
    (common, (left_name, left_dict), (right_name, right_dict))

    * common is a dict

    * left_name and right_name are the scenario names that will be combined

    * left_dict and right_dict are the attributes specific to each half of
      the scenario. They should include at least 'actions' and 'check' and
      will be available as '_this' and '_other' test instance attributes.

    Daughters classes are free to add their specific attributes as they see
    fit in any of the three dicts.

    This is a class method so that load_tests can find it.

    '_base_actions' in the common dict, 'actions' and 'check' in the left
    and right dicts use names that map to methods in the test classes. Some
    prefixes are added to these names to get the correspong methods (see
    _get_actions() and _get_check()). The motivation here is to avoid
    collisions in the class namespace.
    """

    def setUp(self):
        super().setUp()
        builder = self.make_branch_builder("trunk")
        builder.start_series()

        # Create an empty trunk
        builder.build_snapshot(
            None, [("add", ("", b"root-id", "directory", ""))], revision_id=b"start"
        )
        # Add a minimal base content
        base_actions = self._get_actions(self._base_actions)()
        builder.build_snapshot([b"start"], base_actions, revision_id=b"base")
        # Modify the base content in branch
        actions_other = self._get_actions(self._other["actions"])()
        builder.build_snapshot([b"base"], actions_other, revision_id=b"other")
        # Modify the base content in trunk
        actions_this = self._get_actions(self._this["actions"])()
        builder.build_snapshot([b"base"], actions_this, revision_id=b"this")
        # builder.get_branch() tip is now 'this'

        builder.finish_series()
        self.builder = builder

    def _get_actions(self, name):
        return getattr(self, "do_{}".format(name))

    def _get_check(self, name):
        return getattr(self, "check_{}".format(name))

    def _merge_other_into_this(self):
        b = self.builder.get_branch()
        wt = b.controldir.sprout("branch").open_workingtree()
        wt.merge_from_branch(b, b"other")
        return wt

    def assertConflict(self, wt):
        confs = wt.conflicts()
        self.assertLength(1, confs)
        c = confs[0]
        self.assertIsInstance(c, self._conflict_type)
        self._assert_conflict(wt, c)

    def _get_resolve_path_arg(self, wt, action):
        raise NotImplementedError(self._get_resolve_path_arg)

    def check_resolved(self, wt, action):
        path = self._get_resolve_path_arg(wt, action)
        conflicts.resolve(wt, [path], action=action)
        # Check that we don't have any conflicts nor unknown left
        self.assertLength(0, wt.conflicts())
        self.assertLength(0, list(wt.unknowns()))

    def test_resolve_taking_this(self):
        wt = self._merge_other_into_this()
        self.assertConflict(wt)
        self.check_resolved(wt, "take_this")
        check_this = self._get_check(self._this["check"])
        check_this()

    def test_resolve_taking_other(self):
        wt = self._merge_other_into_this()
        self.assertConflict(wt)
        self.check_resolved(wt, "take_other")
        check_other = self._get_check(self._other["check"])
        check_other()


class TestResolveTextConflicts(TestParametrizedResolveConflicts):
    _conflict_type = bzr_conflicts.TextConflict

    # Set by the scenarios
    # path and file-id for the file involved in the conflict
    _path = None
    _file_id = None

    scenarios = mirror_scenarios(
        [
            # File modified on both sides
            (
                {
                    "_base_actions": "create_file",
                    "_path": "file",
                    "_file_id": b"file-id",
                },
                (
                    "filed_modified_A",
                    {"actions": "modify_file_A", "check": "file_has_content_A"},
                ),
                (
                    "file_modified_B",
                    {"actions": "modify_file_B", "check": "file_has_content_B"},
                ),
            ),
            # File modified on both sides in dir
            (
                {
                    "_base_actions": "create_file_in_dir",
                    "_path": "dir/file",
                    "_file_id": b"file-id",
                },
                (
                    "filed_modified_A_in_dir",
                    {
                        "actions": "modify_file_A_in_dir",
                        "check": "file_in_dir_has_content_A",
                    },
                ),
                (
                    "file_modified_B",
                    {
                        "actions": "modify_file_B_in_dir",
                        "check": "file_in_dir_has_content_B",
                    },
                ),
            ),
        ]
    )

    def do_create_file(self, path="file"):
        return [("add", (path, b"file-id", "file", b"trunk content\n"))]

    def do_modify_file_A(self):
        return [("modify", ("file", b"trunk content\nfeature A\n"))]

    def do_modify_file_B(self):
        return [("modify", ("file", b"trunk content\nfeature B\n"))]

    def do_modify_file_A_in_dir(self):
        return [("modify", ("dir/file", b"trunk content\nfeature A\n"))]

    def do_modify_file_B_in_dir(self):
        return [("modify", ("dir/file", b"trunk content\nfeature B\n"))]

    def check_file_has_content_A(self, path="file"):
        self.assertFileEqual(
            b"trunk content\nfeature A\n", osutils.pathjoin("branch", path)
        )

    def check_file_has_content_B(self, path="file"):
        self.assertFileEqual(
            b"trunk content\nfeature B\n", osutils.pathjoin("branch", path)
        )

    def do_create_file_in_dir(self):
        return [
            ("add", ("dir", b"dir-id", "directory", "")),
        ] + self.do_create_file("dir/file")

    def check_file_in_dir_has_content_A(self):
        self.check_file_has_content_A("dir/file")

    def check_file_in_dir_has_content_B(self):
        self.check_file_has_content_B("dir/file")

    def _get_resolve_path_arg(self, wt, action):
        return self._path

    def assertTextConflict(self, wt, c):
        self.assertEqual(self._file_id, c.file_id)
        self.assertEqual(self._path, c.path)

    _assert_conflict = assertTextConflict


class TestResolveContentsConflict(TestParametrizedResolveConflicts):
    _conflict_type = bzr_conflicts.ContentsConflict

    # Set by the scenarios
    # path and file-id for the file involved in the conflict
    _path = None
    _file_id = None

    scenarios = mirror_scenarios(
        [
            # File modified/deleted
            (
                {
                    "_base_actions": "create_file",
                    "_path": "file",
                    "_file_id": b"file-id",
                },
                (
                    "file_modified",
                    {"actions": "modify_file", "check": "file_has_more_content"},
                ),
                (
                    "file_deleted",
                    {"actions": "delete_file", "check": "file_doesnt_exist"},
                ),
            ),
            # File renamed-modified/deleted
            (
                {
                    "_base_actions": "create_file",
                    "_path": "new-file",
                    "_file_id": b"file-id",
                },
                (
                    "file_renamed_and_modified",
                    {
                        "actions": "modify_and_rename_file",
                        "check": "file_renamed_and_more_content",
                    },
                ),
                (
                    "file_deleted",
                    {"actions": "delete_file", "check": "file_doesnt_exist"},
                ),
            ),
            # File modified/deleted in dir
            (
                {
                    "_base_actions": "create_file_in_dir",
                    "_path": "dir/file",
                    "_file_id": b"file-id",
                },
                (
                    "file_modified_in_dir",
                    {
                        "actions": "modify_file_in_dir",
                        "check": "file_in_dir_has_more_content",
                    },
                ),
                (
                    "file_deleted_in_dir",
                    {
                        "actions": "delete_file_in_dir",
                        "check": "file_in_dir_doesnt_exist",
                    },
                ),
            ),
        ]
    )

    def do_create_file(self):
        return [("add", ("file", b"file-id", "file", b"trunk content\n"))]

    def do_modify_file(self):
        return [("modify", ("file", b"trunk content\nmore content\n"))]

    def do_modify_and_rename_file(self):
        return [
            ("modify", ("new-file", b"trunk content\nmore content\n")),
            ("rename", ("file", "new-file")),
        ]

    def check_file_has_more_content(self):
        self.assertFileEqual(b"trunk content\nmore content\n", "branch/file")

    def check_file_renamed_and_more_content(self):
        self.assertFileEqual(b"trunk content\nmore content\n", "branch/new-file")

    def do_delete_file(self):
        return [("unversion", "file")]

    def do_delete_file_in_dir(self):
        return [("unversion", "dir/file")]

    def check_file_doesnt_exist(self):
        self.assertPathDoesNotExist("branch/file")

    def do_create_file_in_dir(self):
        return [
            ("add", ("dir", b"dir-id", "directory", "")),
            ("add", ("dir/file", b"file-id", "file", b"trunk content\n")),
        ]

    def do_modify_file_in_dir(self):
        return [("modify", ("dir/file", b"trunk content\nmore content\n"))]

    def check_file_in_dir_has_more_content(self):
        self.assertFileEqual(b"trunk content\nmore content\n", "branch/dir/file")

    def check_file_in_dir_doesnt_exist(self):
        self.assertPathDoesNotExist("branch/dir/file")

    def _get_resolve_path_arg(self, wt, action):
        return self._path

    def assertContentsConflict(self, wt, c):
        self.assertEqual(self._file_id, c.file_id)
        self.assertEqual(self._path, c.path)

    _assert_conflict = assertContentsConflict


class TestResolvePathConflict(TestParametrizedResolveConflicts):
    _conflict_type = bzr_conflicts.PathConflict

    def do_nothing(self):
        return []

    # Each side dict additionally defines:
    # - path path involved (can be '<deleted>')
    # - file-id involved
    scenarios = mirror_scenarios(
        [
            # File renamed/deleted
            (
                {"_base_actions": "create_file"},
                (
                    "file_renamed",
                    {
                        "actions": "rename_file",
                        "check": "file_renamed",
                        "path": "new-file",
                        "file_id": b"file-id",
                    },
                ),
                (
                    "file_deleted",
                    {
                        "actions": "delete_file",
                        "check": "file_doesnt_exist",
                        # PathConflicts deletion handling requires a special
                        # hard-coded value
                        "path": "<deleted>",
                        "file_id": b"file-id",
                    },
                ),
            ),
            # File renamed/deleted in dir
            (
                {"_base_actions": "create_file_in_dir"},
                (
                    "file_renamed_in_dir",
                    {
                        "actions": "rename_file_in_dir",
                        "check": "file_in_dir_renamed",
                        "path": "dir/new-file",
                        "file_id": b"file-id",
                    },
                ),
                (
                    "file_deleted",
                    {
                        "actions": "delete_file_in_dir",
                        "check": "file_in_dir_doesnt_exist",
                        # PathConflicts deletion handling requires a special
                        # hard-coded value
                        "path": "<deleted>",
                        "file_id": b"file-id",
                    },
                ),
            ),
            # File renamed/renamed differently
            (
                {"_base_actions": "create_file"},
                (
                    "file_renamed",
                    {
                        "actions": "rename_file",
                        "check": "file_renamed",
                        "path": "new-file",
                        "file_id": b"file-id",
                    },
                ),
                (
                    "file_renamed2",
                    {
                        "actions": "rename_file2",
                        "check": "file_renamed2",
                        "path": "new-file2",
                        "file_id": b"file-id",
                    },
                ),
            ),
            # Dir renamed/deleted
            (
                {"_base_actions": "create_dir"},
                (
                    "dir_renamed",
                    {
                        "actions": "rename_dir",
                        "check": "dir_renamed",
                        "path": "new-dir",
                        "file_id": b"dir-id",
                    },
                ),
                (
                    "dir_deleted",
                    {
                        "actions": "delete_dir",
                        "check": "dir_doesnt_exist",
                        # PathConflicts deletion handling requires a special
                        # hard-coded value
                        "path": "<deleted>",
                        "file_id": b"dir-id",
                    },
                ),
            ),
            # Dir renamed/renamed differently
            (
                {"_base_actions": "create_dir"},
                (
                    "dir_renamed",
                    {
                        "actions": "rename_dir",
                        "check": "dir_renamed",
                        "path": "new-dir",
                        "file_id": b"dir-id",
                    },
                ),
                (
                    "dir_renamed2",
                    {
                        "actions": "rename_dir2",
                        "check": "dir_renamed2",
                        "path": "new-dir2",
                        "file_id": b"dir-id",
                    },
                ),
            ),
        ]
    )

    def do_create_file(self):
        return [("add", ("file", b"file-id", "file", b"trunk content\n"))]

    def do_create_dir(self):
        return [("add", ("dir", b"dir-id", "directory", ""))]

    def do_rename_file(self):
        return [("rename", ("file", "new-file"))]

    def check_file_renamed(self):
        self.assertPathDoesNotExist("branch/file")
        self.assertPathExists("branch/new-file")

    def do_rename_file2(self):
        return [("rename", ("file", "new-file2"))]

    def check_file_renamed2(self):
        self.assertPathDoesNotExist("branch/file")
        self.assertPathExists("branch/new-file2")

    def do_rename_dir(self):
        return [("rename", ("dir", "new-dir"))]

    def check_dir_renamed(self):
        self.assertPathDoesNotExist("branch/dir")
        self.assertPathExists("branch/new-dir")

    def do_rename_dir2(self):
        return [("rename", ("dir", "new-dir2"))]

    def check_dir_renamed2(self):
        self.assertPathDoesNotExist("branch/dir")
        self.assertPathExists("branch/new-dir2")

    def do_delete_file(self):
        return [("unversion", "file")]

    def do_delete_file_in_dir(self):
        return [("unversion", "dir/file")]

    def check_file_doesnt_exist(self):
        self.assertPathDoesNotExist("branch/file")

    def do_delete_dir(self):
        return [("unversion", "dir")]

    def check_dir_doesnt_exist(self):
        self.assertPathDoesNotExist("branch/dir")

    def do_create_file_in_dir(self):
        return [
            ("add", ("dir", b"dir-id", "directory", "")),
            ("add", ("dir/file", b"file-id", "file", b"trunk content\n")),
        ]

    def do_rename_file_in_dir(self):
        return [("rename", ("dir/file", "dir/new-file"))]

    def check_file_in_dir_renamed(self):
        self.assertPathDoesNotExist("branch/dir/file")
        self.assertPathExists("branch/dir/new-file")

    def check_file_in_dir_doesnt_exist(self):
        self.assertPathDoesNotExist("branch/dir/file")

    def _get_resolve_path_arg(self, wt, action):
        tpath = self._this["path"]
        opath = self._other["path"]
        if tpath == "<deleted>":
            path = opath
        else:
            path = tpath
        return path

    def assertPathConflict(self, wt, c):
        tpath = self._this["path"]
        tfile_id = self._this["file_id"]
        opath = self._other["path"]
        ofile_id = self._other["file_id"]
        self.assertEqual(tfile_id, ofile_id)  # Sanity check
        self.assertEqual(tfile_id, c.file_id)
        self.assertEqual(tpath, c.path)
        self.assertEqual(opath, c.conflict_path)

    _assert_conflict = assertPathConflict


class TestResolvePathConflictBefore531967(TestResolvePathConflict):
    """Same as TestResolvePathConflict but a specific conflict object."""

    def assertPathConflict(self, wt, c):
        # We create a conflict object as it was created before the fix and
        # inject it into the working tree, the test will exercise the
        # compatibility code.
        old_c = bzr_conflicts.PathConflict("<deleted>", self._item_path, file_id=None)
        wt.set_conflicts([old_c])


class TestResolveDuplicateEntry(TestParametrizedResolveConflicts):
    _conflict_type = bzr_conflicts.DuplicateEntry

    scenarios = mirror_scenarios(
        [
            # File created with different file-ids
            (
                {"_base_actions": "nothing"},
                (
                    "filea_created",
                    {
                        "actions": "create_file_a",
                        "check": "file_content_a",
                        "path": "file",
                        "file_id": b"file-a-id",
                    },
                ),
                (
                    "fileb_created",
                    {
                        "actions": "create_file_b",
                        "check": "file_content_b",
                        "path": "file",
                        "file_id": b"file-b-id",
                    },
                ),
            ),
            # File created with different file-ids but deleted on one side
            (
                {"_base_actions": "create_file_a"},
                (
                    "filea_replaced",
                    {
                        "actions": "replace_file_a_by_b",
                        "check": "file_content_b",
                        "path": "file",
                        "file_id": b"file-b-id",
                    },
                ),
                (
                    "filea_modified",
                    {
                        "actions": "modify_file_a",
                        "check": "file_new_content",
                        "path": "file",
                        "file_id": b"file-a-id",
                    },
                ),
            ),
        ]
    )

    def do_nothing(self):
        return []

    def do_create_file_a(self):
        return [("add", ("file", b"file-a-id", "file", b"file a content\n"))]

    def check_file_content_a(self):
        self.assertFileEqual(b"file a content\n", "branch/file")

    def do_create_file_b(self):
        return [("add", ("file", b"file-b-id", "file", b"file b content\n"))]

    def check_file_content_b(self):
        self.assertFileEqual(b"file b content\n", "branch/file")

    def do_replace_file_a_by_b(self):
        return [
            ("unversion", "file"),
            ("add", ("file", b"file-b-id", "file", b"file b content\n")),
        ]

    def do_modify_file_a(self):
        return [("modify", ("file", b"new content\n"))]

    def check_file_new_content(self):
        self.assertFileEqual(b"new content\n", "branch/file")

    def _get_resolve_path_arg(self, wt, action):
        return self._this["path"]

    def assertDuplicateEntry(self, wt, c):
        tpath = self._this["path"]
        tfile_id = self._this["file_id"]
        opath = self._other["path"]
        self._other["file_id"]
        self.assertEqual(tpath, opath)  # Sanity check
        self.assertEqual(tfile_id, c.file_id)
        self.assertEqual(tpath + ".moved", c.path)
        self.assertEqual(tpath, c.conflict_path)

    _assert_conflict = assertDuplicateEntry


class TestResolveUnversionedParent(TestResolveConflicts):
    # FIXME: Add the reverse tests: dir deleted in trunk, file added in branch

    # FIXME: While this *creates* UnversionedParent conflicts, this really only
    # tests MissingParent resolution :-/
    preamble = """
$ brz init trunk
...
$ cd trunk
$ mkdir dir
$ brz add -q dir
$ brz commit -m 'Create trunk' -q
$ echo 'trunk content' >dir/file
$ brz add -q dir/file
$ brz commit -q -m 'Add dir/file in trunk'
$ brz branch -q . -r 1 ../branch
$ cd ../branch
$ brz rm dir -q
$ brz commit -q -m 'Remove dir in branch'
$ brz merge ../trunk
2>+N  dir/
2>+N  dir/file
2>Conflict adding files to dir.  Created directory.
2>Conflict because dir is not versioned, but has versioned children.  Versioned directory.
2>2 conflicts encountered.
"""

    def test_take_this(self):
        self.run_script("""
$ brz rm -q dir --no-backup
$ brz resolve dir
2>2 conflicts resolved, 0 remaining
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_take_other(self):
        self.run_script("""
$ brz resolve dir
2>2 conflicts resolved, 0 remaining
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")


class TestResolveMissingParent(TestResolveConflicts):
    preamble = """
$ brz init trunk
...
$ cd trunk
$ mkdir dir
$ echo 'trunk content' >dir/file
$ brz add -q
$ brz commit -m 'Create trunk' -q
$ echo 'trunk content' >dir/file2
$ brz add -q dir/file2
$ brz commit -q -m 'Add dir/file2 in branch'
$ brz branch -q . -r 1 ../branch
$ cd ../branch
$ brz rm -q dir/file --no-backup
$ brz rm -q dir
$ brz commit -q -m 'Remove dir/file'
$ brz merge ../trunk
2>+N  dir/
2>+N  dir/file2
2>Conflict adding files to dir.  Created directory.
2>Conflict because dir is not versioned, but has versioned children.  Versioned directory.
2>2 conflicts encountered.
"""

    def test_keep_them_all(self):
        self.run_script("""
$ brz resolve dir
2>2 conflicts resolved, 0 remaining
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_adopt_child(self):
        self.run_script("""
$ brz mv -q dir/file2 file2
$ brz rm -q dir --no-backup
$ brz resolve dir
2>2 conflicts resolved, 0 remaining
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_kill_them_all(self):
        self.run_script("""
$ brz rm -q dir --no-backup
$ brz resolve dir
2>2 conflicts resolved, 0 remaining
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_this(self):
        self.run_script("""
$ brz resolve --take-this dir
2>...
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_other(self):
        self.run_script("""
$ brz resolve --take-other dir
2>...
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")


class TestResolveDeletingParent(TestResolveConflicts):
    preamble = """
$ brz init trunk
...
$ cd trunk
$ mkdir dir
$ echo 'trunk content' >dir/file
$ brz add -q
$ brz commit -m 'Create trunk' -q
$ brz rm -q dir/file --no-backup
$ brz rm -q dir --no-backup
$ brz commit -q -m 'Remove dir/file'
$ brz branch -q . -r 1 ../branch
$ cd ../branch
$ echo 'branch content' >dir/file2
$ brz add -q dir/file2
$ brz commit -q -m 'Add dir/file2 in branch'
$ brz merge ../trunk
2>-D  dir/file
2>Conflict: can't delete dir because it is not empty.  Not deleting.
2>Conflict because dir is not versioned, but has versioned children.  Versioned directory.
2>2 conflicts encountered.
"""

    def test_keep_them_all(self):
        self.run_script("""
$ brz resolve dir
2>2 conflicts resolved, 0 remaining
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_adopt_child(self):
        self.run_script("""
$ brz mv -q dir/file2 file2
$ brz rm -q dir --no-backup
$ brz resolve dir
2>2 conflicts resolved, 0 remaining
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_kill_them_all(self):
        self.run_script("""
$ brz rm -q dir --no-backup
$ brz resolve dir
2>2 conflicts resolved, 0 remaining
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_this(self):
        self.run_script("""
$ brz resolve --take-this dir
2>2 conflicts resolved, 0 remaining
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_other(self):
        self.run_script("""
$ brz resolve --take-other dir
2>deleted dir/file2
2>deleted dir
2>2 conflicts resolved, 0 remaining
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")


class TestResolveParentLoop(TestParametrizedResolveConflicts):
    _conflict_type = bzr_conflicts.ParentLoop

    _this_args = None
    _other_args = None

    # Each side dict additionally defines:
    # - dir_id: the directory being moved
    # - target_id: The target directory
    # - xfail: whether the test is expected to fail if the action is
    #   involved as 'other'
    scenarios = mirror_scenarios(
        [
            # Dirs moved into each other
            (
                {"_base_actions": "create_dir1_dir2"},
                (
                    "dir1_into_dir2",
                    {
                        "actions": "move_dir1_into_dir2",
                        "check": "dir1_moved",
                        "dir_id": b"dir1-id",
                        "target_id": b"dir2-id",
                        "xfail": False,
                    },
                ),
                (
                    "dir2_into_dir1",
                    {
                        "actions": "move_dir2_into_dir1",
                        "check": "dir2_moved",
                        "dir_id": b"dir2-id",
                        "target_id": b"dir1-id",
                        "xfail": False,
                    },
                ),
            ),
            # Subdirs moved into each other
            (
                {"_base_actions": "create_dir1_4"},
                (
                    "dir1_into_dir4",
                    {
                        "actions": "move_dir1_into_dir4",
                        "check": "dir1_2_moved",
                        "dir_id": b"dir1-id",
                        "target_id": b"dir4-id",
                        "xfail": True,
                    },
                ),
                (
                    "dir3_into_dir2",
                    {
                        "actions": "move_dir3_into_dir2",
                        "check": "dir3_4_moved",
                        "dir_id": b"dir3-id",
                        "target_id": b"dir2-id",
                        "xfail": True,
                    },
                ),
            ),
        ]
    )

    def do_create_dir1_dir2(self):
        return [
            ("add", ("dir1", b"dir1-id", "directory", "")),
            ("add", ("dir2", b"dir2-id", "directory", "")),
        ]

    def do_move_dir1_into_dir2(self):
        return [("rename", ("dir1", "dir2/dir1"))]

    def check_dir1_moved(self):
        self.assertPathDoesNotExist("branch/dir1")
        self.assertPathExists("branch/dir2/dir1")

    def do_move_dir2_into_dir1(self):
        return [("rename", ("dir2", "dir1/dir2"))]

    def check_dir2_moved(self):
        self.assertPathDoesNotExist("branch/dir2")
        self.assertPathExists("branch/dir1/dir2")

    def do_create_dir1_4(self):
        return [
            ("add", ("dir1", b"dir1-id", "directory", "")),
            ("add", ("dir1/dir2", b"dir2-id", "directory", "")),
            ("add", ("dir3", b"dir3-id", "directory", "")),
            ("add", ("dir3/dir4", b"dir4-id", "directory", "")),
        ]

    def do_move_dir1_into_dir4(self):
        return [("rename", ("dir1", "dir3/dir4/dir1"))]

    def check_dir1_2_moved(self):
        self.assertPathDoesNotExist("branch/dir1")
        self.assertPathExists("branch/dir3/dir4/dir1")
        self.assertPathExists("branch/dir3/dir4/dir1/dir2")

    def do_move_dir3_into_dir2(self):
        return [("rename", ("dir3", "dir1/dir2/dir3"))]

    def check_dir3_4_moved(self):
        self.assertPathDoesNotExist("branch/dir3")
        self.assertPathExists("branch/dir1/dir2/dir3")
        self.assertPathExists("branch/dir1/dir2/dir3/dir4")

    def _get_resolve_path_arg(self, wt, action):
        # ParentLoop says: moving <conflict_path> into <path>. Cancelled move.
        # But since <path> doesn't exist in the working tree, we need to use
        # <conflict_path> instead, and that, in turn, is given by dir_id. Pfew.
        return wt.id2path(self._other["dir_id"])

    def assertParentLoop(self, wt, c):
        self.assertEqual(self._other["dir_id"], c.file_id)
        self.assertEqual(self._other["target_id"], c.conflict_file_id)
        # The conflict paths are irrelevant (they are deterministic but not
        # worth checking since they don't provide the needed information
        # anyway)
        if self._other["xfail"]:
            # It's a bit hackish to raise from here relying on being called for
            # both tests but this avoid overriding test_resolve_taking_other
            self.knownFailure(
                "ParentLoop doesn't carry enough info to resolve --take-other"
            )

    _assert_conflict = assertParentLoop


class TestResolveNonDirectoryParent(TestResolveConflicts):
    preamble = """
$ brz init trunk
...
$ cd trunk
$ brz mkdir foo
...
$ brz commit -m 'Create trunk' -q
$ echo "Boing" >foo/bar
$ brz add -q foo/bar
$ brz commit -q -m 'Add foo/bar'
$ brz branch -q . -r 1 ../branch
$ cd ../branch
$ rm -r foo
$ echo "Boo!" >foo
$ brz commit -q -m 'foo is now a file'
$ brz merge ../trunk
2>RK  foo => foo.new/
2>+N  foo.new/bar
# FIXME: The message is misleading, foo.new *is* a directory when the message
# is displayed -- vila 090916
2>Conflict: foo.new is not a directory, but has files in it.  Created directory.
2>1 conflicts encountered.
"""

    def test_take_this(self):
        self.run_script("""
$ brz rm -q foo.new --no-backup
# FIXME: Isn't it weird that foo is now unkown even if foo.new has been put
# aside ? -- vila 090916
$ brz add -q foo
$ brz resolve foo.new
2>1 conflict resolved, 0 remaining
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_take_other(self):
        self.run_script("""
$ brz rm -q foo --no-backup
$ brz mv -q foo.new foo
$ brz resolve foo
2>1 conflict resolved, 0 remaining
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_this(self):
        self.run_script("""
$ brz resolve --take-this foo.new
2>...
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")

    def test_resolve_taking_other(self):
        self.run_script("""
$ brz resolve --take-other foo.new
2>...
$ brz commit -q --strict -m 'No more conflicts nor unknown files'
""")


class TestMalformedTransform(script.TestCaseWithTransportAndScript):
    def test_bug_430129(self):
        # This is nearly like TestResolveNonDirectoryParent but with branch and
        # trunk switched. As such it should certainly produce the same
        # conflict.
        self.assertRaises(
            transform.MalformedTransform,
            self.run_script,
            """
$ brz init trunk
...
$ cd trunk
$ brz mkdir foo
...
$ brz commit -m 'Create trunk' -q
$ rm -r foo
$ echo "Boo!" >foo
$ brz commit -m 'foo is now a file' -q
$ brz branch -q . -r 1 ../branch -q
$ cd ../branch
$ echo "Boing" >foo/bar
$ brz add -q foo/bar -q
$ brz commit -m 'Add foo/bar' -q
$ brz merge ../trunk
2>brz: ERROR: Tree transform is malformed [('unversioned executability', 'new-1')]
""",
        )


class TestNoFinalPath(script.TestCaseWithTransportAndScript):
    def test_bug_805809(self):
        self.run_script("""
$ brz init trunk
Created a standalone tree (format: 2a)
$ cd trunk
$ echo trunk >file
$ brz add
adding file
$ brz commit -m 'create file on trunk'
2>Committing to: .../trunk/
2>added file
2>Committed revision 1.
# Create a debian branch based on trunk
$ cd ..
$ brz branch trunk -r 1 debian
2>Branched 1 revision.
$ cd debian
$ mkdir dir
$ brz add
adding dir
$ brz mv file dir
file => dir/file
$ brz commit -m 'rename file to dir/file for debian'
2>Committing to: .../debian/
2>added dir
2>renamed file => dir/file
2>Committed revision 2.
# Create an experimental branch with a new root-id
$ cd ..
$ brz init experimental
Created a standalone tree (format: 2a)
$ cd experimental
# Work around merging into empty branch not being supported
# (http://pad.lv/308562)
$ echo something >not-empty
$ brz add
adding not-empty
$ brz commit -m 'Add some content in experimental'
2>Committing to: .../experimental/
2>added not-empty
2>Committed revision 1.
# merge debian even without a common ancestor
$ brz merge ../debian -r0..2
2>+N  dir/
2>+N  dir/file
2>All changes applied successfully.
$ brz commit -m 'merging debian into experimental'
2>Committing to: .../experimental/
2>added dir
2>added dir/file
2>Committed revision 2.
# Create an ubuntu branch with yet another root-id
$ cd ..
$ brz init ubuntu
Created a standalone tree (format: 2a)
$ cd ubuntu
# Work around merging into empty branch not being supported
# (http://pad.lv/308562)
$ echo something >not-empty-ubuntu
$ brz add
adding not-empty-ubuntu
$ brz commit -m 'Add some content in experimental'
2>Committing to: .../ubuntu/
2>added not-empty-ubuntu
2>Committed revision 1.
# Also merge debian
$ brz merge ../debian -r0..2
2>+N  dir/
2>+N  dir/file
2>All changes applied successfully.
$ brz commit -m 'merging debian'
2>Committing to: .../ubuntu/
2>added dir
2>added dir/file
2>Committed revision 2.
# Now try to merge experimental
$ brz merge ../experimental
2>+N  not-empty
2>Path conflict: dir / dir
2>1 conflicts encountered.
""")


class TestResolveActionOption(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.options = [conflicts.ResolveActionOption()]
        self.parser = option.get_optparser(self.options)

    def parse(self, args):
        return self.parser.parse_args(args)

    def test_unknown_action(self):
        self.assertRaises(
            option.BadOptionValue, self.parse, ["--action", "take-me-to-the-moon"]
        )

    def test_done(self):
        opts, args = self.parse(["--action", "done"])
        self.assertEqual({"action": "done"}, opts)

    def test_take_this(self):
        opts, args = self.parse(["--action", "take-this"])
        self.assertEqual({"action": "take_this"}, opts)
        opts, args = self.parse(["--take-this"])
        self.assertEqual({"action": "take_this"}, opts)

    def test_take_other(self):
        opts, args = self.parse(["--action", "take-other"])
        self.assertEqual({"action": "take_other"}, opts)
        opts, args = self.parse(["--take-other"])
        self.assertEqual({"action": "take_other"}, opts)

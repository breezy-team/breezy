# Copyright (C) 2007-2010, 2016 Canonical Ltd
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
from io import StringIO

from .. import delta as _mod_delta
from .. import revision as _mod_revision
from .. import tests
from ..bzr.inventorytree import InventoryTreeChange


class InstrumentedReporter:
    def __init__(self):
        self.calls = []

    def report(self, path, versioned, renamed, copied, modified, exe_change, kind):
        self.calls.append(
            (path, versioned, renamed, copied, modified, exe_change, kind)
        )


class TestReportChanges(tests.TestCase):
    """Test the new change reporting infrastructure."""

    def assertReport(
        self,
        expected,
        file_id=b"fid",
        path="path",
        versioned_change="unchanged",
        renamed=False,
        copied=False,
        modified="unchanged",
        exe_change=False,
        kind=("file", "file"),
        old_path=None,
        unversioned_filter=None,
        view_info=None,
    ):
        expected_lines = None if expected is None else [expected]
        self.assertReportLines(
            expected_lines,
            file_id,
            path,
            versioned_change,
            renamed,
            copied,
            modified,
            exe_change,
            kind,
            old_path,
            unversioned_filter,
            view_info,
        )

    def assertReportLines(
        self,
        expected_lines,
        file_id=b"fid",
        path="path",
        versioned_change="unchanged",
        renamed=False,
        copied=False,
        modified="unchanged",
        exe_change=False,
        kind=("file", "file"),
        old_path=None,
        unversioned_filter=None,
        view_info=None,
    ):
        result = []

        def result_line(format, *args):
            result.append(format % args)

        reporter = _mod_delta._ChangeReporter(
            result_line, unversioned_filter=unversioned_filter, view_info=view_info
        )
        reporter.report(
            (old_path, path),
            versioned_change,
            renamed,
            copied,
            modified,
            exe_change,
            kind,
        )
        if expected_lines is not None:
            self.assertEqualDiff("\n".join(expected_lines), "\n".join(result))
        else:
            self.assertEqual([], result)

    def test_rename(self):
        self.assertReport("R   old => path", renamed=True, old_path="old")
        self.assertReport("    path")
        self.assertReport(
            "RN  old => path",
            renamed=True,
            old_path="old",
            modified="created",
            kind=(None, "file"),
        )

    def test_kind(self):
        self.assertReport(
            " K  path => path/",
            modified="kind changed",
            kind=("file", "directory"),
            old_path="path",
        )
        self.assertReport(
            " K  path/ => path",
            modified="kind changed",
            kind=("directory", "file"),
            old_path="old",
        )
        self.assertReport(
            "RK  old => path/",
            renamed=True,
            modified="kind changed",
            kind=("file", "directory"),
            old_path="old",
        )

    def test_new(self):
        self.assertReport(" N  path/", modified="created", kind=(None, "directory"))
        self.assertReport(
            "+   path/",
            versioned_change="added",
            modified="unchanged",
            kind=(None, "directory"),
        )
        self.assertReport(
            "+   path",
            versioned_change="added",
            modified="unchanged",
            kind=(None, None),
        )
        self.assertReport(
            "+N  path/",
            versioned_change="added",
            modified="created",
            kind=(None, "directory"),
        )
        self.assertReport(
            "+M  path/",
            versioned_change="added",
            modified="modified",
            kind=(None, "directory"),
        )

    def test_removal(self):
        self.assertReport(
            " D  path/", modified="deleted", kind=("directory", None), old_path="old"
        )
        self.assertReport(
            "-   path/",
            versioned_change="removed",
            old_path="path",
            kind=(None, "directory"),
        )
        self.assertReport(
            "-D  path",
            versioned_change="removed",
            old_path="path",
            modified="deleted",
            kind=("file", "directory"),
        )

    def test_modification(self):
        self.assertReport(" M  path", modified="modified")
        self.assertReport(" M* path", modified="modified", exe_change=True)

    def test_unversioned(self):
        # by default any unversioned file is output
        self.assertReport(
            "?   subdir/foo~",
            file_id=None,
            path="subdir/foo~",
            old_path=None,
            versioned_change="unversioned",
            renamed=False,
            modified="created",
            exe_change=False,
            kind=(None, "file"),
        )
        # but we can choose to filter these. Probably that should be done
        # close to the tree, but this is a reasonable starting point.
        self.assertReport(
            None,
            file_id=None,
            path="subdir/foo~",
            old_path=None,
            versioned_change="unversioned",
            renamed=False,
            modified="created",
            exe_change=False,
            kind=(None, "file"),
            unversioned_filter=lambda x: True,
        )

    def test_missing(self):
        self.assertReport(
            "+!  missing.c",
            file_id=None,
            path="missing.c",
            old_path=None,
            versioned_change="added",
            renamed=False,
            modified="missing",
            exe_change=False,
            kind=(None, None),
        )

    def test_view_filtering(self):
        # If a file in within the view, it should appear in the output
        expected_lines = [
            "Operating on whole tree but only reporting on 'my' view.",
            " M  path",
        ]
        self.assertReportLines(
            expected_lines, modified="modified", view_info=("my", ["path"])
        )
        # If a file in outside the view, it should not appear in the output
        expected_lines = ["Operating on whole tree but only reporting on 'my' view."]
        self.assertReportLines(
            expected_lines, modified="modified", path="foo", view_info=("my", ["path"])
        )

    def assertChangesEqual(
        self,
        file_id=b"fid",
        paths=("path", "path"),
        content_change=False,
        versioned=(True, True),
        parent_id=("pid", "pid"),
        name=("name", "name"),
        kind=("file", "file"),
        executable=(False, False),
        versioned_change="unchanged",
        renamed=False,
        copied=False,
        modified="unchanged",
        exe_change=False,
    ):
        reporter = InstrumentedReporter()
        _mod_delta.report_changes(
            [
                InventoryTreeChange(
                    file_id,
                    paths,
                    content_change,
                    versioned,
                    parent_id,
                    name,
                    kind,
                    executable,
                    copied,
                )
            ],
            reporter,
        )
        output = reporter.calls[0]
        self.assertEqual(paths, output[0])
        self.assertEqual(versioned_change, output[1])
        self.assertEqual(renamed, output[2])
        self.assertEqual(copied, output[3])
        self.assertEqual(modified, output[4])
        self.assertEqual(exe_change, output[5])
        self.assertEqual(kind, output[6])

    def test_report_changes(self):
        """Test change detection of report_changes."""
        # Ensure no changes are detected by default
        self.assertChangesEqual(
            modified="unchanged",
            renamed=False,
            versioned_change="unchanged",
            exe_change=False,
        )
        self.assertChangesEqual(modified="kind changed", kind=("file", "directory"))
        self.assertChangesEqual(modified="created", kind=(None, "directory"))
        self.assertChangesEqual(modified="deleted", kind=("directory", None))
        self.assertChangesEqual(content_change=True, modified="modified")
        self.assertChangesEqual(renamed=True, name=("old", "new"))
        self.assertChangesEqual(renamed=True, parent_id=("old-parent", "new-parent"))
        self.assertChangesEqual(versioned_change="added", versioned=(False, True))
        self.assertChangesEqual(versioned_change="removed", versioned=(True, False))
        # execute bit is only detected as "changed" if the file is and was
        # a regular file.
        self.assertChangesEqual(exe_change=True, executable=(True, False))
        self.assertChangesEqual(
            exe_change=False, executable=(True, False), kind=("directory", "directory")
        )
        self.assertChangesEqual(
            exe_change=False,
            modified="kind changed",
            executable=(False, True),
            kind=("directory", "file"),
        )
        self.assertChangesEqual(parent_id=("pid", None))

        # Now make sure they all work together
        self.assertChangesEqual(
            versioned_change="removed",
            modified="deleted",
            versioned=(True, False),
            kind=("directory", None),
        )
        self.assertChangesEqual(
            versioned_change="removed",
            modified="created",
            versioned=(True, False),
            kind=(None, "file"),
        )
        self.assertChangesEqual(
            versioned_change="removed",
            modified="modified",
            renamed=True,
            exe_change=True,
            versioned=(True, False),
            content_change=True,
            name=("old", "new"),
            executable=(False, True),
        )

    def test_report_unversioned(self):
        """Unversioned entries are reported well."""
        self.assertChangesEqual(
            file_id=None,
            paths=(None, "full/path"),
            content_change=True,
            versioned=(False, False),
            parent_id=(None, None),
            name=(None, "path"),
            kind=(None, "file"),
            executable=(None, False),
            versioned_change="unversioned",
            renamed=False,
            modified="created",
            exe_change=False,
        )


class TestChangesFrom(tests.TestCaseWithTransport):
    def show_string(self, delta, *args, **kwargs):
        to_file = StringIO()
        _mod_delta.report_delta(to_file, delta, *args, **kwargs)
        return to_file.getvalue()

    def test_kind_change(self):
        """Doing a status when a file has changed kind should work."""
        tree = self.make_branch_and_tree(".")
        self.build_tree(["filename"])
        tree.add("filename", ids=b"file-id")
        tree.commit("added filename")
        os.unlink("filename")
        self.build_tree(["filename/"])
        delta = tree.changes_from(tree.basis_tree())
        self.assertEqual(
            [("filename", "file", "directory")],
            [(c.path[1], c.kind[0], c.kind[1]) for c in delta.kind_changed],
        )
        self.assertEqual([], delta.added)
        self.assertEqual([], delta.removed)
        self.assertEqual([], delta.renamed)
        self.assertEqual([], delta.modified)
        self.assertEqual([], delta.unchanged)
        self.assertTrue(delta.has_changed())
        self.assertEqual(
            "kind changed:\n  filename (file => directory)\n", self.show_string(delta)
        )
        other_delta = _mod_delta.TreeDelta()
        self.assertNotEqual(other_delta, delta)
        other_delta.kind_changed = [
            InventoryTreeChange(
                b"file-id",
                ("filename", "filename"),
                True,
                (True, True),
                (tree.path2id(""), tree.path2id("")),
                ("filename", "filename"),
                ("file", "symlink"),
                (False, False),
            )
        ]
        self.assertNotEqual(other_delta, delta)
        other_delta.kind_changed = [
            InventoryTreeChange(
                b"file-id",
                ("filename", "filename"),
                True,
                (True, True),
                (tree.path2id(""), tree.path2id("")),
                ("filename", "filename"),
                ("file", "directory"),
                (False, False),
            )
        ]
        self.assertEqual(other_delta, delta)
        self.assertEqual(
            "K  filename (file => directory) file-id\n",
            self.show_string(delta, show_ids=True, short_status=True),
        )

        tree.rename_one("filename", "dirname")
        delta = tree.changes_from(tree.basis_tree())
        self.assertEqual([], delta.kind_changed)
        # This loses the fact that kind changed, remembering it as a
        # modification
        self.assertEqual(
            [
                InventoryTreeChange(
                    b"file-id",
                    ("filename", "dirname"),
                    True,
                    (True, True),
                    (tree.path2id(""), tree.path2id("")),
                    ("filename", "dirname"),
                    ("file", "directory"),
                    (False, False),
                )
            ],
            delta.renamed,
        )
        self.assertTrue(delta.has_changed())


class TestDeltaShow(tests.TestCaseWithTransport):
    def _get_delta(self):
        # We build the delta from a real tree to avoid depending on internal
        # implementation details.
        wt = self.make_branch_and_tree("branch")
        self.build_tree_contents(
            [
                ("branch/f1", b"1\n"),
                ("branch/f2", b"2\n"),
                ("branch/f3", b"3\n"),
                ("branch/f4", b"4\n"),
                ("branch/f5", b"5\n"),
                ("branch/dir/",),
            ]
        )
        wt.add(
            ["f1", "f2", "f3", "f4", "dir"],
            ids=[b"f1-id", b"f2-id", b"f3-id", b"f4-id", b"dir-id"],
        )
        wt.commit("commit one", rev_id=b"1")

        # TODO add rename,removed,etc. here?
        wt.add("f5")
        os.unlink("branch/f5")

        long_status = """added:
  dir/
  f1
  f2
  f3
  f4
missing:
  f5
"""
        short_status = """A  dir/
A  f1
A  f2
A  f3
A  f4
!  f5
"""

        repo = wt.branch.repository
        d = wt.changes_from(repo.revision_tree(_mod_revision.NULL_REVISION))
        return d, long_status, short_status

    def test_short_status(self):
        d, long_status, short_status = self._get_delta()
        out = StringIO()
        _mod_delta.report_delta(out, d, short_status=True)
        self.assertEqual(short_status, out.getvalue())

    def test_long_status(self):
        d, long_status, short_status = self._get_delta()
        out = StringIO()
        _mod_delta.report_delta(out, d, short_status=False)
        self.assertEqual(long_status, out.getvalue())

    def test_predicate_always(self):
        d, long_status, short_status = self._get_delta()
        out = StringIO()

        def always(path):
            return True

        _mod_delta.report_delta(out, d, short_status=True, predicate=always)
        self.assertEqual(short_status, out.getvalue())

    def test_short_status_path_predicate(self):
        d, long_status, short_status = self._get_delta()
        out = StringIO()

        def only_f2(path):
            return path == "f2"

        _mod_delta.report_delta(out, d, short_status=True, predicate=only_f2)
        self.assertEqual("A  f2\n", out.getvalue())

    def test_long_status_path_predicate(self):
        d, long_status, short_status = self._get_delta()
        out = StringIO()

        def only_f2(path):
            return path == "f2"

        _mod_delta.report_delta(out, d, short_status=False, predicate=only_f2)
        self.assertEqual("added:\n  f2\n", out.getvalue())

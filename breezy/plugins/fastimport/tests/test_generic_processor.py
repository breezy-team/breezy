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
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import time

from .... import tests
from ..helpers import kind_to_mode
from . import FastimportFeature

try:
    from fastimport import commands
except ImportError:
    commands = object()  # type: ignore


def load_tests(loader, standard_tests, pattern):
    """Parameterize tests for all versions of groupcompress."""
    scenarios = [
        ("pack-0.92", {"branch_format": "pack-0.92"}),
        ("1.9-rich-root", {"branch_format": "1.9-rich-root"}),
    ]

    scenarios.append(("2a", {"branch_format": "2a"}))
    suite = loader.suiteClass()
    result = tests.multiply_tests(standard_tests, scenarios, suite)
    return result


class TestCaseForGenericProcessor(tests.TestCaseWithTransport):
    _test_needs_features = [FastimportFeature]

    branch_format = "pack-0.92"

    def get_handler(self):
        from ..processors import generic_processor

        branch = self.make_branch(".", format=self.branch_format)
        handler = generic_processor.GenericProcessor(branch.controldir)
        return handler, branch

    # FIXME: [] as a default is bad, as it is mutable, but I want
    # to use None to mean "don't check this".
    def assertChanges(
        self,
        branch,
        revno,
        expected_added=None,
        expected_removed=None,
        expected_modified=None,
        expected_renamed=None,
        expected_kind_changed=None,
    ):
        """Check the changes introduced in a revision of a branch.

        This method checks that a revision introduces expected changes.
        The required changes are passed in as a list, where
        each entry contains the needed information about the change.

        If you do not wish to assert anything about a particular
        category then pass None instead.

        branch: The branch.
        revno: revision number of revision to check.
        expected_added: a list of (filename,) tuples that must have
            been added in the delta.
        expected_removed: a list of (filename,) tuples that must have
            been removed in the delta.
        expected_modified: a list of (filename,) tuples that must have
            been modified in the delta.
        expected_renamed: a list of (old_path, new_path) tuples that
            must have been renamed in the delta.
        expected_kind_changed: a list of (path, old_kind, new_kind) tuples
            that must have been changed in the delta.
        :return: revtree1, revtree2
        """
        if expected_kind_changed is None:
            expected_kind_changed = []
        if expected_renamed is None:
            expected_renamed = []
        if expected_modified is None:
            expected_modified = []
        if expected_removed is None:
            expected_removed = []
        if expected_added is None:
            expected_added = []
        repo = branch.repository
        revtree1 = repo.revision_tree(branch.get_rev_id(revno - 1))
        revtree2 = repo.revision_tree(branch.get_rev_id(revno))
        changes = revtree2.changes_from(revtree1)
        self._check_changes(
            changes,
            expected_added,
            expected_removed,
            expected_modified,
            expected_renamed,
            expected_kind_changed,
        )
        return revtree1, revtree2

    def _check_changes(
        self,
        changes,
        expected_added=None,
        expected_removed=None,
        expected_modified=None,
        expected_renamed=None,
        expected_kind_changed=None,
    ):
        """Check the changes in a TreeDelta.

        This method checks that the TreeDelta contains the expected
        modifications between the two trees that were used to generate
        it. The required changes are passed in as a list, where
        each entry contains the needed information about the change.

        If you do not wish to assert anything about a particular
        category then pass None instead.

        changes: The TreeDelta to check.
        expected_added: a list of (filename,) tuples that must have
            been added in the delta.
        expected_removed: a list of (filename,) tuples that must have
            been removed in the delta.
        expected_modified: a list of (filename,) tuples that must have
            been modified in the delta.
        expected_renamed: a list of (old_path, new_path) tuples that
            must have been renamed in the delta.
        expected_kind_changed: a list of (path, old_kind, new_kind) tuples
            that must have been changed in the delta.
        """
        if expected_kind_changed is None:
            expected_kind_changed = []
        if expected_renamed is None:
            expected_renamed = []
        if expected_modified is None:
            expected_modified = []
        if expected_removed is None:
            expected_removed = []
        if expected_added is None:
            expected_added = []
        renamed = changes.renamed
        added = changes.added + changes.copied
        removed = changes.removed
        modified = changes.modified
        kind_changed = changes.kind_changed
        if expected_renamed is not None:
            self.assertEqual(
                len(renamed),
                len(expected_renamed),
                "{} is renamed, expected {}".format(renamed, expected_renamed),
            )
            renamed_files = [(item.path[0], item.path[1]) for item in renamed]
            for expected_renamed_entry in expected_renamed:
                expected_renamed_entry = (
                    expected_renamed_entry[0].decode("utf-8"),
                    expected_renamed_entry[1].decode("utf-8"),
                )
                self.assertTrue(
                    expected_renamed_entry in renamed_files,
                    "{} is not renamed, {} are".format(
                        expected_renamed_entry, renamed_files
                    ),
                )
        if expected_added is not None:
            self.assertEqual(
                len(added), len(expected_added), "{} is added".format(str(added))
            )
            added_files = [(item.path[1],) for item in added]
            for expected_added_entry in expected_added:
                expected_added_entry = (expected_added_entry[0].decode("utf-8"),)
                self.assertTrue(
                    expected_added_entry in added_files,
                    "{} is not added, {} are".format(expected_added_entry, added_files),
                )
        if expected_removed is not None:
            self.assertEqual(
                len(removed),
                len(expected_removed),
                "{} is removed".format(str(removed)),
            )
            removed_files = [(item.path[0],) for item in removed]
            for expected_removed_entry in expected_removed:
                expected_removed_entry = (expected_removed_entry[0].decode("utf-8"),)
                self.assertTrue(
                    expected_removed_entry in removed_files,
                    "{} is not removed, {} are".format(
                        expected_removed_entry, removed_files
                    ),
                )
        if expected_modified is not None:
            self.assertEqual(
                len(modified),
                len(expected_modified),
                "{} is modified".format(str(modified)),
            )
            modified_files = [(item.path[1],) for item in modified]
            for expected_modified_entry in expected_modified:
                expected_modified_entry = (expected_modified_entry[0].decode("utf-8"),)
                self.assertTrue(
                    expected_modified_entry in modified_files,
                    "{} is not modified, {} are".format(
                        expected_modified_entry, modified_files
                    ),
                )
        if expected_kind_changed is not None:
            self.assertEqual(
                len(kind_changed),
                len(expected_kind_changed),
                "{} is kind-changed, expected {}".format(
                    kind_changed, expected_kind_changed
                ),
            )
            kind_changed_files = [
                (item.path[1], item.kind[0], item.kind[1]) for item in kind_changed
            ]
            for expected_kind_changed_entry in expected_kind_changed:
                expected_kind_changed_entry = (
                    expected_kind_changed_entry[0].decode("utf-8"),
                ) + expected_kind_changed_entry[1:]
                self.assertTrue(
                    expected_kind_changed_entry in kind_changed_files,
                    "{} is not kind-changed, {} are".format(
                        expected_kind_changed_entry, kind_changed_files
                    ),
                )

    def assertContent(self, branch, tree, path, content):
        with branch.lock_read():
            self.assertEqual(tree.get_file_text(path.decode("utf-8")), content)

    def assertSymlinkTarget(self, branch, tree, path, target):
        with branch.lock_read():
            self.assertEqual(tree.get_symlink_target(path.decode("utf-8")), target)

    def assertExecutable(self, branch, tree, path, executable):
        with branch.lock_read():
            self.assertEqual(tree.is_executable(path.decode("utf-8")), executable)

    def assertRevisionRoot(self, revtree, path):
        self.assertEqual(
            revtree.get_revision_id(), revtree.get_file_revision(path.decode("utf-8"))
        )


class TestImportToPackTag(TestCaseForGenericProcessor):
    def file_command_iter(
        self,
        path,
        kind="file",
        content=b"aaa",
        executable=False,
        to_kind=None,
        to_content=b"bbb",
        to_executable=None,
    ):
        # Revno 1: create a file or symlink
        # Revno 2: modify it
        if to_kind is None:
            to_kind = kind
        if to_executable is None:
            to_executable = executable

        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    path, kind_to_mode(kind, executable), None, content
                )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileModifyCommand(
                    path, kind_to_mode(to_kind, to_executable), None, to_content
                )

            # pass "head" for from_ to show that #401249 is worse than I knew
            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b"head", [], files_two
            )

            yield commands.TagCommand(b"tag1", b":1", committer, b"tag 1")

            # pass "head" for from_ to demonstrate #401249
            yield commands.TagCommand(b"tag2", b"head", committer, b"tag 2")

        return command_list

    def test_tag(self):
        handler, _branch = self.get_handler()
        path = b"a"
        raise tests.KnownFailure("non-mark committish not yet supported- bug #410249")
        handler.process(self.file_command_iter(path))


class TestImportZeroMarker(TestCaseForGenericProcessor):
    def test_tag(self):
        handler, _branch = self.get_handler()

        def command_list():
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]
            yield commands.TagCommand(b"tag1", b":0", committer, b"tag 1")

        handler.process(command_list)


class TestImportToPackModify(TestCaseForGenericProcessor):
    def file_command_iter(
        self,
        path,
        kind="file",
        content=b"aaa",
        executable=False,
        to_kind=None,
        to_content=b"bbb",
        to_executable=None,
    ):
        # Revno 1: create a file or symlink
        # Revno 2: modify it
        if to_kind is None:
            to_kind = kind
        if to_executable is None:
            to_executable = executable
        mode = kind_to_mode(kind, executable)
        to_mode = kind_to_mode(to_kind, to_executable)

        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(path, mode, None, content)

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileModifyCommand(path, to_mode, None, to_content)

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_modify_file_in_root(self):
        handler, branch = self.get_handler()
        path = b"a"
        handler.process(self.file_command_iter(path))
        _revtree0, revtree1 = self.assertChanges(branch, 1, expected_added=[(path,)])
        revtree1, revtree2 = self.assertChanges(branch, 2, expected_modified=[(path,)])
        self.assertContent(branch, revtree1, path, b"aaa")
        self.assertContent(branch, revtree2, path, b"bbb")
        self.assertRevisionRoot(revtree1, path)
        self.assertRevisionRoot(revtree2, path)

    def test_modify_file_in_subdir(self):
        handler, branch = self.get_handler()
        path = b"a/a"
        handler.process(self.file_command_iter(path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (path,)]
        )
        revtree1, revtree2 = self.assertChanges(branch, 2, expected_modified=[(path,)])
        self.assertContent(branch, revtree1, path, b"aaa")
        self.assertContent(branch, revtree2, path, b"bbb")

    def test_modify_symlink_in_root(self):
        handler, branch = self.get_handler()
        path = b"a"
        handler.process(self.file_command_iter(path, kind="symlink"))
        revtree1, revtree2 = self.assertChanges(branch, 2, expected_modified=[(path,)])
        self.assertSymlinkTarget(branch, revtree1, path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, path, "bbb")
        self.assertRevisionRoot(revtree1, path)
        self.assertRevisionRoot(revtree2, path)

    def test_modify_symlink_in_subdir(self):
        handler, branch = self.get_handler()
        path = b"a/a"
        handler.process(self.file_command_iter(path, kind="symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (path,)]
        )
        revtree1, revtree2 = self.assertChanges(branch, 2, expected_modified=[(path,)])
        self.assertSymlinkTarget(branch, revtree1, path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, path, "bbb")

    def test_modify_file_becomes_symlink(self):
        handler, branch = self.get_handler()
        path = b"a/a"
        handler.process(self.file_command_iter(path, kind="file", to_kind="symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (path,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_kind_changed=[(path, "file", "symlink")]
        )
        self.assertContent(branch, revtree1, path, b"aaa")
        self.assertSymlinkTarget(branch, revtree2, path, "bbb")

    def test_modify_symlink_becomes_file(self):
        handler, branch = self.get_handler()
        path = b"a/a"
        handler.process(self.file_command_iter(path, kind="symlink", to_kind="file"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (path,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_kind_changed=[(path, "symlink", "file")]
        )
        self.assertSymlinkTarget(branch, revtree1, path, "aaa")
        self.assertContent(branch, revtree2, path, b"bbb")

    def test_modify_file_now_executable(self):
        handler, branch = self.get_handler()
        path = b"a/a"
        handler.process(
            self.file_command_iter(
                path, executable=False, to_executable=True, to_content=b"aaa"
            )
        )
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (path,)]
        )
        revtree1, revtree2 = self.assertChanges(branch, 2, expected_modified=[(path,)])
        self.assertExecutable(branch, revtree1, path, False)
        self.assertExecutable(branch, revtree2, path, True)

    def test_modify_file_no_longer_executable(self):
        handler, branch = self.get_handler()
        path = b"a/a"
        handler.process(
            self.file_command_iter(
                path, executable=True, to_executable=False, to_content=b"aaa"
            )
        )
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (path,)]
        )
        revtree1, revtree2 = self.assertChanges(branch, 2, expected_modified=[(path,)])
        self.assertExecutable(branch, revtree1, path, True)
        self.assertExecutable(branch, revtree2, path, False)


class TestImportToPackModifyTwice(TestCaseForGenericProcessor):
    """This tests when the same file is modified twice in the one commit.

    Note: hg-fast-export produces data like this on occasions.
    """

    def file_command_iter(
        self,
        path,
        kind="file",
        content=b"aaa",
        executable=False,
        to_kind=None,
        to_content=b"bbb",
        to_executable=None,
    ):
        # Revno 1: create a file twice
        if to_kind is None:
            to_kind = kind
        if to_executable is None:
            to_executable = executable

        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    path, kind_to_mode(kind, executable), None, content
                )
                yield commands.FileModifyCommand(
                    path, kind_to_mode(to_kind, to_executable), None, to_content
                )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

        return command_list

    def test_modify_file_twice_in_root(self):
        handler, branch = self.get_handler()
        path = b"a"
        handler.process(self.file_command_iter(path))
        _revtree0, revtree1 = self.assertChanges(branch, 1, expected_added=[(path,)])
        self.assertContent(branch, revtree1, path, b"aaa")
        self.assertRevisionRoot(revtree1, path)


class TestImportToPackModifyTricky(TestCaseForGenericProcessor):
    def file_command_iter(self, path1, path2, kind="file"):
        # Revno 1: create a file or symlink in a directory
        # Revno 2: create a second file that implicitly deletes the
        # first one because either:
        # * the new file is a in directory with the old file name
        # * the new file has the same name as the directory of the first
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    path1, kind_to_mode(kind, False), None, b"aaa"
                )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileModifyCommand(
                    path2, kind_to_mode(kind, False), None, b"bbb"
                )

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_modify_file_becomes_directory(self):
        handler, branch = self.get_handler()
        path1 = b"a/b"
        path2 = b"a/b/c"
        handler.process(self.file_command_iter(path1, path2))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (path1,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_added=[(path2,)],
            expected_kind_changed=[(path1, "file", "directory")],
        )
        self.assertContent(branch, revtree1, path1, b"aaa")
        self.assertContent(branch, revtree2, path2, b"bbb")

    def test_modify_directory_becomes_file(self):
        handler, branch = self.get_handler()
        path1 = b"a/b/c"
        path2 = b"a/b"
        handler.process(self.file_command_iter(path1, path2))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (b"a/b",), (path1,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[
                (path1,),
            ],
            expected_kind_changed=[(path2, "directory", "file")],
        )
        self.assertContent(branch, revtree1, path1, b"aaa")
        self.assertContent(branch, revtree2, path2, b"bbb")

    def test_modify_symlink_becomes_directory(self):
        handler, branch = self.get_handler()
        path1 = b"a/b"
        path2 = b"a/b/c"
        handler.process(self.file_command_iter(path1, path2, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (path1,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_added=[(path2,)],
            expected_kind_changed=[(path1, "symlink", "directory")],
        )
        self.assertSymlinkTarget(branch, revtree1, path1, "aaa")
        self.assertSymlinkTarget(branch, revtree2, path2, "bbb")

    def test_modify_directory_becomes_symlink(self):
        handler, branch = self.get_handler()
        path1 = b"a/b/c"
        path2 = b"a/b"
        handler.process(self.file_command_iter(path1, path2, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (b"a/b",), (path1,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[
                (path1,),
            ],
            expected_kind_changed=[(path2, "directory", "symlink")],
        )
        self.assertSymlinkTarget(branch, revtree1, path1, "aaa")
        self.assertSymlinkTarget(branch, revtree2, path2, "bbb")


class TestImportToPackDelete(TestCaseForGenericProcessor):
    def file_command_iter(self, path, kind="file"):
        # Revno 1: create a file or symlink
        # Revno 2: delete it
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    path, kind_to_mode(kind, False), None, b"aaa"
                )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileDeleteCommand(path)

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_delete_file_in_root(self):
        handler, branch = self.get_handler()
        path = b"a"
        handler.process(self.file_command_iter(path))
        _revtree0, revtree1 = self.assertChanges(branch, 1, expected_added=[(path,)])
        revtree1, _revtree2 = self.assertChanges(branch, 2, expected_removed=[(path,)])
        self.assertContent(branch, revtree1, path, b"aaa")
        self.assertRevisionRoot(revtree1, path)

    def test_delete_file_in_subdir(self):
        handler, branch = self.get_handler()
        path = b"a/a"
        handler.process(self.file_command_iter(path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (path,)]
        )
        revtree1, _revtree2 = self.assertChanges(
            branch, 2, expected_removed=[(b"a",), (path,)]
        )
        self.assertContent(branch, revtree1, path, b"aaa")

    def test_delete_symlink_in_root(self):
        handler, branch = self.get_handler()
        path = b"a"
        handler.process(self.file_command_iter(path, kind="symlink"))
        revtree1, _revtree2 = self.assertChanges(branch, 2, expected_removed=[(path,)])
        self.assertSymlinkTarget(branch, revtree1, path, "aaa")
        self.assertRevisionRoot(revtree1, path)

    def test_delete_symlink_in_subdir(self):
        handler, branch = self.get_handler()
        path = b"a/a"
        handler.process(self.file_command_iter(path, kind="symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (path,)]
        )
        revtree1, _revtree2 = self.assertChanges(
            branch, 2, expected_removed=[(b"a",), (path,)]
        )
        self.assertSymlinkTarget(branch, revtree1, path, "aaa")

    def test_delete_file_in_deep_subdir(self):
        handler, branch = self.get_handler()
        path = b"a/b/c/d"
        handler.process(self.file_command_iter(path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (b"a/b",), (b"a/b/c",), (path,)]
        )
        revtree1, _revtree2 = self.assertChanges(
            branch, 2, expected_removed=[(b"a",), (b"a/b",), (b"a/b/c",), (path,)]
        )
        self.assertContent(branch, revtree1, path, b"aaa")


class TestImportToPackDeleteNew(TestCaseForGenericProcessor):
    """Test deletion of a newly added file."""

    def file_command_iter(self, path, kind="file"):
        # Revno 1: create a file or symlink then delete it
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    path, kind_to_mode(kind, False), None, b"aaa"
                )
                yield commands.FileDeleteCommand(path)

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

        return command_list

    def test_delete_new_file_in_root(self):
        handler, branch = self.get_handler()
        path = b"a"
        handler.process(self.file_command_iter(path))
        _revtree0, _revtree1 = self.assertChanges(
            branch,
            1,
        )

    def test_delete_new_file_in_subdir(self):
        handler, branch = self.get_handler()
        path = b"a/a"
        handler.process(self.file_command_iter(path))
        _revtree0, _revtree1 = self.assertChanges(
            branch,
            1,
        )

    def test_delete_new_symlink_in_root(self):
        handler, branch = self.get_handler()
        path = b"a"
        handler.process(self.file_command_iter(path, kind="symlink"))
        _revtree0, _revtree1 = self.assertChanges(
            branch,
            1,
        )

    def test_delete_new_symlink_in_subdir(self):
        handler, branch = self.get_handler()
        path = b"a/a"
        handler.process(self.file_command_iter(path, kind="symlink"))
        _revtree0, _revtree1 = self.assertChanges(
            branch,
            1,
        )

    def test_delete_new_file_in_deep_subdir(self):
        handler, branch = self.get_handler()
        path = b"a/b/c/d"
        handler.process(self.file_command_iter(path))
        _revtree0, _revtree1 = self.assertChanges(
            branch,
            1,
        )


class TestImportToPackDeleteMultiLevel(TestCaseForGenericProcessor):
    def file_command_iter(self, paths, paths_to_delete):
        # Revno 1: create multiple files
        # Revno 2: delete multiple files
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                for i, path in enumerate(paths):
                    yield commands.FileModifyCommand(
                        path, kind_to_mode("file", False), None, b"aaa%d" % i
                    )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                for path in paths_to_delete:
                    yield commands.FileDeleteCommand(path)

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_delete_files_in_multiple_levels(self):
        handler, branch = self.get_handler()
        paths = [b"a/b/c", b"a/b/d/e"]
        paths_to_delete = [b"a/b/c", b"a/b/d/e"]
        handler.process(self.file_command_iter(paths, paths_to_delete))
        _revtree0, revtree1 = self.assertChanges(
            branch,
            1,
            expected_added=[
                (b"a",),
                (b"a/b",),
                (b"a/b/c",),
                (b"a/b/d",),
                (b"a/b/d/e",),
            ],
        )
        _revtree1, _revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[
                (b"a",),
                (b"a/b",),
                (b"a/b/c",),
                (b"a/b/d",),
                (b"a/b/d/e",),
            ],
        )

    def test_delete_file_single_level(self):
        handler, branch = self.get_handler()
        paths = [b"a/b/c", b"a/b/d/e"]
        paths_to_delete = [b"a/b/d/e"]
        handler.process(self.file_command_iter(paths, paths_to_delete))
        _revtree0, revtree1 = self.assertChanges(
            branch,
            1,
            expected_added=[
                (b"a",),
                (b"a/b",),
                (b"a/b/c",),
                (b"a/b/d",),
                (b"a/b/d/e",),
            ],
        )
        _revtree1, _revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[
                (b"a/b/d",),
                (b"a/b/d/e",),
            ],
        )

    def test_delete_file_complex_level(self):
        handler, branch = self.get_handler()
        paths = [b"a/b/c", b"a/b/d/e", b"a/f/g", b"a/h", b"a/b/d/i/j"]
        paths_to_delete = [b"a/b/c", b"a/b/d/e", b"a/f/g", b"a/b/d/i/j"]
        handler.process(self.file_command_iter(paths, paths_to_delete))
        _revtree0, revtree1 = self.assertChanges(
            branch,
            1,
            expected_added=[
                (b"a",),
                (b"a/b",),
                (b"a/b/c",),
                (b"a/b/d",),
                (b"a/b/d/e",),
                (b"a/f",),
                (b"a/f/g",),
                (b"a/h",),
                (b"a/b/d/i",),
                (b"a/b/d/i/j",),
            ],
        )
        _revtree1, _revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[
                (b"a/b",),
                (b"a/b/c",),
                (b"a/b/d",),
                (b"a/b/d/e",),
                (b"a/f",),
                (b"a/f/g",),
                (b"a/b/d/i",),
                (b"a/b/d/i/j",),
            ],
        )


class TestImportToPackDeleteThenAdd(TestCaseForGenericProcessor):
    """Test delete followed by an add. Merges can cause this."""

    def file_command_iter(
        self,
        path,
        kind="file",
        content=b"aaa",
        executable=False,
        to_kind=None,
        to_content=b"bbb",
        to_executable=None,
    ):
        # Revno 1: create a file or symlink
        # Revno 2: delete it and add it
        if to_kind is None:
            to_kind = kind
        if to_executable is None:
            to_executable = executable

        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    path, kind_to_mode(kind, executable), None, content
                )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileDeleteCommand(path)
                yield commands.FileModifyCommand(
                    path, kind_to_mode(to_kind, to_executable), None, to_content
                )

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_delete_then_add_file_in_root(self):
        handler, branch = self.get_handler()
        path = b"a"
        handler.process(self.file_command_iter(path))
        _revtree0, revtree1 = self.assertChanges(branch, 1, expected_added=[(path,)])
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_removed=[(path,)], expected_added=[(path,)]
        )
        self.assertContent(branch, revtree1, path, b"aaa")
        self.assertContent(branch, revtree2, path, b"bbb")
        self.assertRevisionRoot(revtree1, path)
        self.assertRevisionRoot(revtree2, path)

    def test_delete_then_add_file_in_subdir(self):
        handler, branch = self.get_handler()
        path = b"a/a"
        handler.process(self.file_command_iter(path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (path,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_removed=[(path,)], expected_added=[(path,)]
        )
        self.assertContent(branch, revtree1, path, b"aaa")
        self.assertContent(branch, revtree2, path, b"bbb")

    def test_delete_then_add_symlink_in_root(self):
        handler, branch = self.get_handler()
        path = b"a"
        handler.process(self.file_command_iter(path, kind="symlink"))
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_removed=[(path,)], expected_added=[(path,)]
        )
        self.assertSymlinkTarget(branch, revtree1, path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, path, "bbb")
        self.assertRevisionRoot(revtree1, path)
        self.assertRevisionRoot(revtree2, path)

    def test_delete_then_add_symlink_in_subdir(self):
        handler, branch = self.get_handler()
        path = b"a/a"
        handler.process(self.file_command_iter(path, kind="symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (path,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_removed=[(path,)], expected_added=[(path,)]
        )
        self.assertSymlinkTarget(branch, revtree1, path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, path, "bbb")


class TestImportToPackDeleteDirectory(TestCaseForGenericProcessor):
    def file_command_iter(self, paths, dir):
        # Revno 1: create multiple files
        # Revno 2: delete a directory holding those files
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                for i, path in enumerate(paths):
                    yield commands.FileModifyCommand(
                        path, kind_to_mode("file", False), None, b"aaa%d" % i
                    )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileDeleteCommand(dir)

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_delete_dir(self):
        handler, branch = self.get_handler()
        paths = [b"a/b/c", b"a/b/d", b"a/b/e/f", b"a/g"]
        dir = b"a/b"
        handler.process(self.file_command_iter(paths, dir))
        _revtree0, revtree1 = self.assertChanges(
            branch,
            1,
            expected_added=[
                (b"a",),
                (b"a/b",),
                (b"a/b/c",),
                (b"a/b/d",),
                (b"a/b/e",),
                (b"a/b/e/f",),
                (b"a/g",),
            ],
        )
        _revtree1, _revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[
                (b"a/b",),
                (b"a/b/c",),
                (b"a/b/d",),
                (b"a/b/e",),
                (b"a/b/e/f",),
            ],
        )


class TestImportToPackDeleteDirectoryThenAddFile(TestCaseForGenericProcessor):
    """Test deleting a directory then adding a file in the same commit."""

    def file_command_iter(self, paths, dir, new_path, kind="file"):
        # Revno 1: create files in a directory
        # Revno 2: delete the directory then add a file into it
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                for i, path in enumerate(paths):
                    yield commands.FileModifyCommand(
                        path, kind_to_mode(kind, False), None, b"aaa%d" % i
                    )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileDeleteCommand(dir)
                yield commands.FileModifyCommand(
                    new_path, kind_to_mode(kind, False), None, b"bbb"
                )

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_delete_dir_then_add_file(self):
        handler, branch = self.get_handler()
        paths = [b"a/b/c", b"a/b/d"]
        dir = b"a/b"
        new_path = b"a/b/z"
        handler.process(self.file_command_iter(paths, dir, new_path))
        _revtree0, revtree1 = self.assertChanges(
            branch,
            1,
            expected_added=[
                (b"a",),
                (b"a/b",),
                (b"a/b/c",),
                (b"a/b/d",),
            ],
        )
        _revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[(b"a/b",), (b"a/b/c",), (b"a/b/d",)],
            expected_added=[(b"a/b",), (b"a/b/z",)],
        )
        self.assertContent(branch, revtree2, new_path, b"bbb")

    def test_delete_dir_then_add_symlink(self):
        handler, branch = self.get_handler()
        paths = [b"a/b/c", b"a/b/d"]
        dir = b"a/b"
        new_path = b"a/b/z"
        handler.process(self.file_command_iter(paths, dir, new_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch,
            1,
            expected_added=[
                (b"a",),
                (b"a/b",),
                (b"a/b/c",),
                (b"a/b/d",),
            ],
        )
        _revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[(b"a/b",), (b"a/b/c",), (b"a/b/d",)],
            expected_added=[(b"a/b",), (b"a/b/z",)],
        )
        self.assertSymlinkTarget(branch, revtree2, new_path, "bbb")


class TestImportToPackRename(TestCaseForGenericProcessor):
    def get_command_iter(self, old_path, new_path, kind="file"):
        # Revno 1: create a file or symlink
        # Revno 2: rename it
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    old_path, kind_to_mode(kind, False), None, b"aaa"
                )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileRenameCommand(old_path, new_path)

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_rename_file_in_root(self):
        handler, branch = self.get_handler()
        old_path = b"a"
        new_path = b"b"
        handler.process(self.get_command_iter(old_path, new_path))
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_renamed=[(old_path, new_path)]
        )
        self.assertRevisionRoot(revtree1, old_path)
        self.assertRevisionRoot(revtree2, new_path)

    def test_rename_symlink_in_root(self):
        handler, branch = self.get_handler()
        old_path = b"a"
        new_path = b"b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_renamed=[(old_path, new_path)]
        )
        self.assertRevisionRoot(revtree1, old_path)
        self.assertRevisionRoot(revtree2, new_path)

    def test_rename_file_in_subdir(self):
        handler, branch = self.get_handler()
        old_path = b"a/a"
        new_path = b"a/b"
        handler.process(self.get_command_iter(old_path, new_path))
        self.assertChanges(branch, 2, expected_renamed=[(old_path, new_path)])

    def test_rename_symlink_in_subdir(self):
        handler, branch = self.get_handler()
        old_path = b"a/a"
        new_path = b"a/b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        self.assertChanges(branch, 2, expected_renamed=[(old_path, new_path)])

    def test_rename_file_to_new_dir(self):
        handler, branch = self.get_handler()
        old_path = b"a/a"
        new_path = b"b/a"
        handler.process(self.get_command_iter(old_path, new_path))
        self.assertChanges(
            branch,
            2,
            expected_renamed=[(old_path, new_path)],
            expected_added=[(b"b",)],
            expected_removed=[(b"a",)],
        )

    def test_rename_symlink_to_new_dir(self):
        handler, branch = self.get_handler()
        old_path = b"a/a"
        new_path = b"b/a"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        self.assertChanges(
            branch,
            2,
            expected_renamed=[(old_path, new_path)],
            expected_added=[(b"b",)],
            expected_removed=[(b"a",)],
        )


class TestImportToPackRenameNew(TestCaseForGenericProcessor):
    """Test rename of a newly added file."""

    def get_command_iter(self, old_path, new_path, kind="file"):
        # Revno 1: create a file and rename it
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    old_path, kind_to_mode(kind, False), None, b"aaa"
                )
                yield commands.FileRenameCommand(old_path, new_path)

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

        return command_list

    def test_rename_new_file_in_root(self):
        handler, branch = self.get_handler()
        old_path = b"a"
        new_path = b"b"
        handler.process(self.get_command_iter(old_path, new_path))
        _revtree0, revtree1 = self.assertChanges(branch, 1, expected_added=[(new_path,)])
        self.assertRevisionRoot(revtree1, new_path)

    def test_rename_new_symlink_in_root(self):
        handler, branch = self.get_handler()
        old_path = b"a"
        new_path = b"b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(branch, 1, expected_added=[(new_path,)])
        self.assertRevisionRoot(revtree1, new_path)

    def test_rename_new_file_in_subdir(self):
        handler, branch = self.get_handler()
        old_path = b"a/a"
        new_path = b"a/b"
        handler.process(self.get_command_iter(old_path, new_path))
        _revtree0, _revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (new_path,)]
        )

    def test_rename_new_symlink_in_subdir(self):
        handler, branch = self.get_handler()
        old_path = b"a/a"
        new_path = b"a/b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        _revtree0, _revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (new_path,)]
        )


class TestImportToPackRenameToDeleted(TestCaseForGenericProcessor):
    """Test rename to a destination path deleted in this commit."""

    def get_command_iter(self, old_path, new_path, kind="file"):
        # Revno 1: create two files
        # Revno 2: delete one, rename the other one to that path
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    old_path, kind_to_mode(kind, False), None, b"aaa"
                )
                yield commands.FileModifyCommand(
                    new_path, kind_to_mode(kind, False), None, b"bbb"
                )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileDeleteCommand(new_path)
                yield commands.FileRenameCommand(old_path, new_path)

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_rename_to_deleted_file_in_root(self):
        handler, branch = self.get_handler()
        old_path = b"a"
        new_path = b"b"
        handler.process(self.get_command_iter(old_path, new_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(old_path,), (new_path,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[(new_path,)],
            expected_renamed=[(old_path, new_path)],
        )
        self.assertContent(branch, revtree1, old_path, b"aaa")
        self.assertContent(branch, revtree1, new_path, b"bbb")
        self.assertContent(branch, revtree2, new_path, b"aaa")
        self.assertRevisionRoot(revtree1, old_path)
        self.assertRevisionRoot(revtree1, new_path)

    def test_rename_to_deleted_symlink_in_root(self):
        handler, branch = self.get_handler()
        old_path = b"a"
        new_path = b"b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(old_path,), (new_path,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[(new_path,)],
            expected_renamed=[(old_path, new_path)],
        )
        self.assertSymlinkTarget(branch, revtree1, old_path, "aaa")
        self.assertSymlinkTarget(branch, revtree1, new_path, "bbb")
        self.assertSymlinkTarget(branch, revtree2, new_path, "aaa")
        self.assertRevisionRoot(revtree1, old_path)
        self.assertRevisionRoot(revtree1, new_path)

    def test_rename_to_deleted_file_in_subdir(self):
        handler, branch = self.get_handler()
        old_path = b"d/a"
        new_path = b"d/b"
        handler.process(self.get_command_iter(old_path, new_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d",), (old_path,), (new_path,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[(new_path,)],
            expected_renamed=[(old_path, new_path)],
        )
        self.assertContent(branch, revtree1, old_path, b"aaa")
        self.assertContent(branch, revtree1, new_path, b"bbb")
        self.assertContent(branch, revtree2, new_path, b"aaa")

    def test_rename_to_deleted_symlink_in_subdir(self):
        handler, branch = self.get_handler()
        old_path = b"d/a"
        new_path = b"d/b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d",), (old_path,), (new_path,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[(new_path,)],
            expected_renamed=[(old_path, new_path)],
        )
        self.assertSymlinkTarget(branch, revtree1, old_path, "aaa")
        self.assertSymlinkTarget(branch, revtree1, new_path, "bbb")
        self.assertSymlinkTarget(branch, revtree2, new_path, "aaa")

    def test_rename_to_deleted_file_in_new_dir(self):
        handler, branch = self.get_handler()
        old_path = b"d1/a"
        new_path = b"d2/b"
        handler.process(self.get_command_iter(old_path, new_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d1",), (old_path,), (b"d2",), (new_path,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[(b"d1",), (new_path,)],
            expected_renamed=[(old_path, new_path)],
        )
        self.assertContent(branch, revtree1, old_path, b"aaa")
        self.assertContent(branch, revtree1, new_path, b"bbb")
        self.assertContent(branch, revtree2, new_path, b"aaa")

    def test_rename_to_deleted_symlink_in_new_dir(self):
        handler, branch = self.get_handler()
        old_path = b"d1/a"
        new_path = b"d2/b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d1",), (old_path,), (b"d2",), (new_path,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[(b"d1",), (new_path,)],
            expected_renamed=[(old_path, new_path)],
        )
        self.assertSymlinkTarget(branch, revtree1, old_path, "aaa")
        self.assertSymlinkTarget(branch, revtree1, new_path, "bbb")
        self.assertSymlinkTarget(branch, revtree2, new_path, "aaa")


class TestImportToPackRenameModified(TestCaseForGenericProcessor):
    """Test rename of a path previously modified in this commit."""

    def get_command_iter(self, old_path, new_path, kind="file"):
        # Revno 1: create a file or symlink
        # Revno 2: modify then rename it
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    old_path, kind_to_mode(kind, False), None, b"aaa"
                )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileModifyCommand(
                    old_path, kind_to_mode(kind, False), None, b"bbb"
                )
                yield commands.FileRenameCommand(old_path, new_path)

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_rename_of_modified_file_in_root(self):
        handler, branch = self.get_handler()
        old_path = b"a"
        new_path = b"b"
        handler.process(self.get_command_iter(old_path, new_path))
        _revtree0, revtree1 = self.assertChanges(branch, 1, expected_added=[(old_path,)])
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_renamed=[(old_path, new_path)]
        )
        self.assertContent(branch, revtree1, old_path, b"aaa")
        self.assertContent(branch, revtree2, new_path, b"bbb")
        self.assertRevisionRoot(revtree1, old_path)
        self.assertRevisionRoot(revtree2, new_path)

    def test_rename_of_modified_symlink_in_root(self):
        handler, branch = self.get_handler()
        old_path = b"a"
        new_path = b"b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(branch, 1, expected_added=[(old_path,)])
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_renamed=[(old_path, new_path)]
        )
        self.assertSymlinkTarget(branch, revtree1, old_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, new_path, "bbb")
        self.assertRevisionRoot(revtree1, old_path)
        self.assertRevisionRoot(revtree2, new_path)

    def test_rename_of_modified_file_in_subdir(self):
        handler, branch = self.get_handler()
        old_path = b"d/a"
        new_path = b"d/b"
        handler.process(self.get_command_iter(old_path, new_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d",), (old_path,)]
        )
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_renamed=[(old_path, new_path)]
        )
        self.assertContent(branch, revtree1, old_path, b"aaa")
        self.assertContent(branch, revtree2, new_path, b"bbb")

    def test_rename_of_modified_symlink_in_subdir(self):
        handler, branch = self.get_handler()
        old_path = b"d/a"
        new_path = b"d/b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d",), (old_path,)]
        )
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_renamed=[(old_path, new_path)]
        )
        self.assertSymlinkTarget(branch, revtree1, old_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, new_path, "bbb")

    def test_rename_of_modified_file_to_new_dir(self):
        handler, branch = self.get_handler()
        old_path = b"d1/a"
        new_path = b"d2/b"
        handler.process(self.get_command_iter(old_path, new_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d1",), (old_path,)]
        )
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_renamed=[(old_path, new_path)],
            expected_added=[(b"d2",)],
            expected_removed=[(b"d1",)],
        )
        self.assertContent(branch, revtree1, old_path, b"aaa")
        self.assertContent(branch, revtree2, new_path, b"bbb")

    def test_rename_of_modified_symlink_to_new_dir(self):
        handler, branch = self.get_handler()
        old_path = b"d1/a"
        new_path = b"d2/b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d1",), (old_path,)]
        )
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_renamed=[(old_path, new_path)],
            expected_added=[(b"d2",)],
            expected_removed=[(b"d1",)],
        )
        self.assertSymlinkTarget(branch, revtree1, old_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, new_path, "bbb")


class TestImportToPackRenameThenModify(TestCaseForGenericProcessor):
    """Test rename of a path then modfy the new-path in the same commit."""

    def get_command_iter(self, old_path, new_path, kind="file"):
        # Revno 1: create a file or symlink
        # Revno 2: rename it then modify the newly created path
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    old_path, kind_to_mode(kind, False), None, b"aaa"
                )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileRenameCommand(old_path, new_path)
                yield commands.FileModifyCommand(
                    new_path, kind_to_mode(kind, False), None, b"bbb"
                )

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_rename_then_modify_file_in_root(self):
        handler, branch = self.get_handler()
        old_path = b"a"
        new_path = b"b"
        handler.process(self.get_command_iter(old_path, new_path))
        _revtree0, revtree1 = self.assertChanges(branch, 1, expected_added=[(old_path,)])
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_renamed=[(old_path, new_path)]
        )
        self.assertContent(branch, revtree1, old_path, b"aaa")
        self.assertContent(branch, revtree2, new_path, b"bbb")
        self.assertRevisionRoot(revtree1, old_path)
        self.assertRevisionRoot(revtree2, new_path)

    def test_rename_then_modify_file_in_subdir(self):
        handler, branch = self.get_handler()
        old_path = b"d/a"
        new_path = b"d/b"
        handler.process(self.get_command_iter(old_path, new_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d",), (old_path,)]
        )
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_renamed=[(old_path, new_path)]
        )
        self.assertContent(branch, revtree1, old_path, b"aaa")
        self.assertContent(branch, revtree2, new_path, b"bbb")

    def test_rename_then_modify_file_in_new_dir(self):
        handler, branch = self.get_handler()
        old_path = b"d1/a"
        new_path = b"d2/b"
        handler.process(self.get_command_iter(old_path, new_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d1",), (old_path,)]
        )
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_renamed=[(old_path, new_path)],
            expected_added=[(b"d2",)],
            expected_removed=[(b"d1",)],
        )
        self.assertContent(branch, revtree1, old_path, b"aaa")
        self.assertContent(branch, revtree2, new_path, b"bbb")

    def test_rename_then_modify_symlink_in_root(self):
        handler, branch = self.get_handler()
        old_path = b"a"
        new_path = b"b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(branch, 1, expected_added=[(old_path,)])
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_renamed=[(old_path, new_path)]
        )
        self.assertSymlinkTarget(branch, revtree1, old_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, new_path, "bbb")
        self.assertRevisionRoot(revtree1, old_path)
        self.assertRevisionRoot(revtree2, new_path)

    def test_rename_then_modify_symlink_in_subdir(self):
        handler, branch = self.get_handler()
        old_path = b"d/a"
        new_path = b"d/b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d",), (old_path,)]
        )
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_renamed=[(old_path, new_path)]
        )
        self.assertSymlinkTarget(branch, revtree1, old_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, new_path, "bbb")

    def test_rename_then_modify_symlink_in_new_dir(self):
        handler, branch = self.get_handler()
        old_path = b"d1/a"
        new_path = b"d2/b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d1",), (old_path,)]
        )
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_renamed=[(old_path, new_path)],
            expected_added=[(b"d2",)],
            expected_removed=[(b"d1",)],
        )
        self.assertSymlinkTarget(branch, revtree1, old_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, new_path, "bbb")


class TestImportToPackDeleteRenameThenModify(TestCaseForGenericProcessor):
    """Test rename of to a deleted path then modfy the new-path in the same commit."""

    def get_command_iter(self, old_path, new_path, kind="file"):
        # Revno 1: create two files or symlinks
        # Revno 2: delete one, rename the other to it then modify the newly created path
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    old_path, kind_to_mode(kind, False), None, b"aaa"
                )
                yield commands.FileModifyCommand(
                    new_path, kind_to_mode(kind, False), None, b"zzz"
                )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileDeleteCommand(new_path)
                yield commands.FileRenameCommand(old_path, new_path)
                yield commands.FileModifyCommand(
                    new_path, kind_to_mode(kind, False), None, b"bbb"
                )

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_delete_rename_then_modify_file_in_root(self):
        handler, branch = self.get_handler()
        old_path = b"a"
        new_path = b"b"
        handler.process(self.get_command_iter(old_path, new_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(old_path,), (new_path,)]
        )
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[(new_path,)],
            expected_renamed=[(old_path, new_path)],
        )
        self.assertContent(branch, revtree1, old_path, b"aaa")
        self.assertContent(branch, revtree1, new_path, b"zzz")
        self.assertContent(branch, revtree2, new_path, b"bbb")
        self.assertRevisionRoot(revtree1, old_path)
        self.assertRevisionRoot(revtree1, new_path)
        self.assertRevisionRoot(revtree2, new_path)

    def test_delete_rename_then_modify_file_in_subdir(self):
        handler, branch = self.get_handler()
        old_path = b"d/a"
        new_path = b"d/b"
        handler.process(self.get_command_iter(old_path, new_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d",), (old_path,), (new_path,)]
        )
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[(new_path,)],
            expected_renamed=[(old_path, new_path)],
        )
        self.assertContent(branch, revtree1, old_path, b"aaa")
        self.assertContent(branch, revtree1, new_path, b"zzz")
        self.assertContent(branch, revtree2, new_path, b"bbb")

    def test_delete_rename_then_modify_file_in_new_dir(self):
        handler, branch = self.get_handler()
        old_path = b"d1/a"
        new_path = b"d2/b"
        handler.process(self.get_command_iter(old_path, new_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d1",), (b"d2",), (old_path,), (new_path,)]
        )
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[(b"d1",), (new_path,)],
            expected_renamed=[(old_path, new_path)],
        )
        self.assertContent(branch, revtree1, old_path, b"aaa")
        self.assertContent(branch, revtree1, new_path, b"zzz")
        self.assertContent(branch, revtree2, new_path, b"bbb")

    def test_delete_rename_then_modify_symlink_in_root(self):
        handler, branch = self.get_handler()
        old_path = b"a"
        new_path = b"b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(old_path,), (new_path,)]
        )
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[(new_path,)],
            expected_renamed=[(old_path, new_path)],
        )
        self.assertSymlinkTarget(branch, revtree1, old_path, "aaa")
        self.assertSymlinkTarget(branch, revtree1, new_path, "zzz")
        self.assertSymlinkTarget(branch, revtree2, new_path, "bbb")
        self.assertRevisionRoot(revtree1, old_path)
        self.assertRevisionRoot(revtree1, new_path)
        self.assertRevisionRoot(revtree2, new_path)

    def test_delete_rename_then_modify_symlink_in_subdir(self):
        handler, branch = self.get_handler()
        old_path = b"d/a"
        new_path = b"d/b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d",), (old_path,), (new_path,)]
        )
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[(new_path,)],
            expected_renamed=[(old_path, new_path)],
        )
        self.assertSymlinkTarget(branch, revtree1, old_path, "aaa")
        self.assertSymlinkTarget(branch, revtree1, new_path, "zzz")
        self.assertSymlinkTarget(branch, revtree2, new_path, "bbb")

    def test_delete_rename_then_modify_symlink_in_new_dir(self):
        handler, branch = self.get_handler()
        old_path = b"d1/a"
        new_path = b"d2/b"
        handler.process(self.get_command_iter(old_path, new_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d1",), (b"d2",), (old_path,), (new_path,)]
        )
        # Note: the delta doesn't show the modification?
        # The actual new content is validated in the assertions following.
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_removed=[(b"d1",), (new_path,)],
            expected_renamed=[(old_path, new_path)],
        )
        self.assertSymlinkTarget(branch, revtree1, old_path, "aaa")
        self.assertSymlinkTarget(branch, revtree1, new_path, "zzz")
        self.assertSymlinkTarget(branch, revtree2, new_path, "bbb")


class TestImportToPackRenameTricky(TestCaseForGenericProcessor):
    def file_command_iter(self, path1, old_path2, new_path2, kind="file"):
        # Revno 1: create two files or symlinks in a directory
        # Revno 2: rename the second file so that it implicitly deletes the
        # first one because either:
        # * the new file is a in directory with the old file name
        # * the new file has the same name as the directory of the first
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    path1, kind_to_mode(kind, False), None, b"aaa"
                )
                yield commands.FileModifyCommand(
                    old_path2, kind_to_mode(kind, False), None, b"bbb"
                )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileRenameCommand(old_path2, new_path2)

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_rename_file_becomes_directory(self):
        handler, branch = self.get_handler()
        old_path2 = b"foo"
        path1 = b"a/b"
        new_path2 = b"a/b/c"
        handler.process(self.file_command_iter(path1, old_path2, new_path2))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (path1,), (old_path2,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_renamed=[(old_path2, new_path2)],
            expected_kind_changed=[(path1, "file", "directory")],
        )
        self.assertContent(branch, revtree1, path1, b"aaa")
        self.assertContent(branch, revtree2, new_path2, b"bbb")

    def test_rename_directory_becomes_file(self):
        handler, branch = self.get_handler()
        old_path2 = b"foo"
        path1 = b"a/b/c"
        new_path2 = b"a/b"
        handler.process(self.file_command_iter(path1, old_path2, new_path2))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (b"a/b",), (path1,), (old_path2,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_renamed=[(old_path2, new_path2)],
            expected_removed=[(path1,), (new_path2,)],
        )
        self.assertContent(branch, revtree1, path1, b"aaa")
        self.assertContent(branch, revtree2, new_path2, b"bbb")

    def test_rename_symlink_becomes_directory(self):
        handler, branch = self.get_handler()
        old_path2 = b"foo"
        path1 = b"a/b"
        new_path2 = b"a/b/c"
        handler.process(self.file_command_iter(path1, old_path2, new_path2, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (path1,), (old_path2,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_renamed=[(old_path2, new_path2)],
            expected_kind_changed=[(path1, "symlink", "directory")],
        )
        self.assertSymlinkTarget(branch, revtree1, path1, "aaa")
        self.assertSymlinkTarget(branch, revtree2, new_path2, "bbb")

    def test_rename_directory_becomes_symlink(self):
        handler, branch = self.get_handler()
        old_path2 = b"foo"
        path1 = b"a/b/c"
        new_path2 = b"a/b"
        handler.process(self.file_command_iter(path1, old_path2, new_path2, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (b"a/b",), (path1,), (old_path2,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_renamed=[(old_path2, new_path2)],
            expected_removed=[(path1,), (new_path2,)],
        )
        self.assertSymlinkTarget(branch, revtree1, path1, "aaa")
        self.assertSymlinkTarget(branch, revtree2, new_path2, "bbb")


class TestImportToPackCopy(TestCaseForGenericProcessor):
    def file_command_iter(self, src_path, dest_path, kind="file"):
        # Revno 1: create a file or symlink
        # Revno 2: copy it
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    src_path, kind_to_mode(kind, False), None, b"aaa"
                )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileCopyCommand(src_path, dest_path)

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_copy_file_in_root(self):
        handler, branch = self.get_handler()
        src_path = b"a"
        dest_path = b"b"
        handler.process(self.file_command_iter(src_path, dest_path))
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_added=[(dest_path,)]
        )
        self.assertContent(branch, revtree1, src_path, b"aaa")
        self.assertContent(branch, revtree2, src_path, b"aaa")
        self.assertContent(branch, revtree2, dest_path, b"aaa")
        self.assertRevisionRoot(revtree1, src_path)
        self.assertRevisionRoot(revtree2, dest_path)

    def test_copy_file_in_subdir(self):
        handler, branch = self.get_handler()
        src_path = b"a/a"
        dest_path = b"a/b"
        handler.process(self.file_command_iter(src_path, dest_path))
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_added=[(dest_path,)]
        )
        self.assertContent(branch, revtree1, src_path, b"aaa")
        self.assertContent(branch, revtree2, src_path, b"aaa")
        self.assertContent(branch, revtree2, dest_path, b"aaa")

    def test_copy_file_to_new_dir(self):
        handler, branch = self.get_handler()
        src_path = b"a/a"
        dest_path = b"b/a"
        handler.process(self.file_command_iter(src_path, dest_path))
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_added=[(b"b",), (dest_path,)]
        )
        self.assertContent(branch, revtree1, src_path, b"aaa")
        self.assertContent(branch, revtree2, src_path, b"aaa")
        self.assertContent(branch, revtree2, dest_path, b"aaa")

    def test_copy_symlink_in_root(self):
        handler, branch = self.get_handler()
        src_path = b"a"
        dest_path = b"b"
        handler.process(self.file_command_iter(src_path, dest_path, "symlink"))
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_added=[(dest_path,)]
        )
        self.assertSymlinkTarget(branch, revtree1, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, dest_path, "aaa")
        self.assertRevisionRoot(revtree1, src_path)
        self.assertRevisionRoot(revtree2, dest_path)

    def test_copy_symlink_in_subdir(self):
        handler, branch = self.get_handler()
        src_path = b"a/a"
        dest_path = b"a/b"
        handler.process(self.file_command_iter(src_path, dest_path, "symlink"))
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_added=[(dest_path,)]
        )
        self.assertSymlinkTarget(branch, revtree1, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, dest_path, "aaa")

    def test_copy_symlink_to_new_dir(self):
        handler, branch = self.get_handler()
        src_path = b"a/a"
        dest_path = b"b/a"
        handler.process(self.file_command_iter(src_path, dest_path, "symlink"))
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_added=[(b"b",), (dest_path,)]
        )
        self.assertSymlinkTarget(branch, revtree1, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, dest_path, "aaa")


class TestImportToPackCopyNew(TestCaseForGenericProcessor):
    """Test copy of a newly added file."""

    def file_command_iter(self, src_path, dest_path, kind="file"):
        # Revno 1: create a file or symlink and copy it
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    src_path, kind_to_mode(kind, False), None, b"aaa"
                )
                yield commands.FileCopyCommand(src_path, dest_path)

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

        return command_list

    def test_copy_new_file_in_root(self):
        handler, branch = self.get_handler()
        src_path = b"a"
        dest_path = b"b"
        handler.process(self.file_command_iter(src_path, dest_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(src_path,), (dest_path,)]
        )
        self.assertContent(branch, revtree1, src_path, b"aaa")
        self.assertContent(branch, revtree1, dest_path, b"aaa")
        self.assertRevisionRoot(revtree1, src_path)
        self.assertRevisionRoot(revtree1, dest_path)

    def test_copy_new_file_in_subdir(self):
        handler, branch = self.get_handler()
        src_path = b"a/a"
        dest_path = b"a/b"
        handler.process(self.file_command_iter(src_path, dest_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (src_path,), (dest_path,)]
        )
        self.assertContent(branch, revtree1, src_path, b"aaa")
        self.assertContent(branch, revtree1, dest_path, b"aaa")

    def test_copy_new_file_to_new_dir(self):
        handler, branch = self.get_handler()
        src_path = b"a/a"
        dest_path = b"b/a"
        handler.process(self.file_command_iter(src_path, dest_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (src_path,), (b"b",), (dest_path,)]
        )
        self.assertContent(branch, revtree1, src_path, b"aaa")
        self.assertContent(branch, revtree1, dest_path, b"aaa")

    def test_copy_new_symlink_in_root(self):
        handler, branch = self.get_handler()
        src_path = b"a"
        dest_path = b"b"
        handler.process(self.file_command_iter(src_path, dest_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(src_path,), (dest_path,)]
        )
        self.assertSymlinkTarget(branch, revtree1, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree1, dest_path, "aaa")
        self.assertRevisionRoot(revtree1, src_path)
        self.assertRevisionRoot(revtree1, dest_path)

    def test_copy_new_symlink_in_subdir(self):
        handler, branch = self.get_handler()
        src_path = b"a/a"
        dest_path = b"a/b"
        handler.process(self.file_command_iter(src_path, dest_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (src_path,), (dest_path,)]
        )
        self.assertSymlinkTarget(branch, revtree1, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree1, dest_path, "aaa")

    def test_copy_new_symlink_to_new_dir(self):
        handler, branch = self.get_handler()
        src_path = b"a/a"
        dest_path = b"b/a"
        handler.process(self.file_command_iter(src_path, dest_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"a",), (src_path,), (b"b",), (dest_path,)]
        )
        self.assertSymlinkTarget(branch, revtree1, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree1, dest_path, "aaa")


class TestImportToPackCopyToDeleted(TestCaseForGenericProcessor):
    def file_command_iter(self, src_path, dest_path, kind="file"):
        # Revno 1: create two files or symlinks
        # Revno 2: delete one and copy the other one to its path
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    src_path, kind_to_mode(kind, False), None, b"aaa"
                )
                yield commands.FileModifyCommand(
                    dest_path, kind_to_mode(kind, False), None, b"bbb"
                )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileDeleteCommand(dest_path)
                yield commands.FileCopyCommand(src_path, dest_path)

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_copy_to_deleted_file_in_root(self):
        handler, branch = self.get_handler()
        src_path = b"a"
        dest_path = b"b"
        handler.process(self.file_command_iter(src_path, dest_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(src_path,), (dest_path,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_removed=[(dest_path,)], expected_added=[(dest_path,)]
        )
        self.assertContent(branch, revtree1, src_path, b"aaa")
        self.assertContent(branch, revtree1, dest_path, b"bbb")
        self.assertContent(branch, revtree2, src_path, b"aaa")
        self.assertContent(branch, revtree2, dest_path, b"aaa")
        self.assertRevisionRoot(revtree1, src_path)
        self.assertRevisionRoot(revtree1, dest_path)

    def test_copy_to_deleted_symlink_in_root(self):
        handler, branch = self.get_handler()
        src_path = b"a"
        dest_path = b"b"
        handler.process(self.file_command_iter(src_path, dest_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(src_path,), (dest_path,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_removed=[(dest_path,)], expected_added=[(dest_path,)]
        )
        self.assertSymlinkTarget(branch, revtree1, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree1, dest_path, "bbb")
        self.assertSymlinkTarget(branch, revtree2, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, dest_path, "aaa")
        self.assertRevisionRoot(revtree1, src_path)
        self.assertRevisionRoot(revtree1, dest_path)

    def test_copy_to_deleted_file_in_subdir(self):
        handler, branch = self.get_handler()
        src_path = b"d/a"
        dest_path = b"d/b"
        handler.process(self.file_command_iter(src_path, dest_path))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d",), (src_path,), (dest_path,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_removed=[(dest_path,)], expected_added=[(dest_path,)]
        )
        self.assertContent(branch, revtree1, src_path, b"aaa")
        self.assertContent(branch, revtree1, dest_path, b"bbb")
        self.assertContent(branch, revtree2, src_path, b"aaa")
        self.assertContent(branch, revtree2, dest_path, b"aaa")

    def test_copy_to_deleted_symlink_in_subdir(self):
        handler, branch = self.get_handler()
        src_path = b"d/a"
        dest_path = b"d/b"
        handler.process(self.file_command_iter(src_path, dest_path, "symlink"))
        _revtree0, revtree1 = self.assertChanges(
            branch, 1, expected_added=[(b"d",), (src_path,), (dest_path,)]
        )
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_removed=[(dest_path,)], expected_added=[(dest_path,)]
        )
        self.assertSymlinkTarget(branch, revtree1, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree1, dest_path, "bbb")
        self.assertSymlinkTarget(branch, revtree2, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, dest_path, "aaa")


class TestImportToPackCopyModified(TestCaseForGenericProcessor):
    """Test copy of file/symlink already modified in this commit."""

    def file_command_iter(self, src_path, dest_path, kind="file"):
        # Revno 1: create a file or symlink
        # Revno 2: modify and copy it
        def command_list():
            author = [b"", b"bugs@a.com", time.time(), time.timezone]
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    src_path, kind_to_mode(kind, False), None, b"aaa"
                )

            yield commands.CommitCommand(
                b"head", b"1", author, committer, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileModifyCommand(
                    src_path, kind_to_mode(kind, False), None, b"bbb"
                )
                yield commands.FileCopyCommand(src_path, dest_path)

            yield commands.CommitCommand(
                b"head", b"2", author, committer, b"commit 2", b":1", [], files_two
            )

        return command_list

    def test_copy_of_modified_file_in_root(self):
        handler, branch = self.get_handler()
        src_path = b"a"
        dest_path = b"b"
        handler.process(self.file_command_iter(src_path, dest_path))
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_modified=[(src_path,)], expected_added=[(dest_path,)]
        )
        self.assertContent(branch, revtree1, src_path, b"aaa")
        self.assertContent(branch, revtree2, src_path, b"bbb")
        self.assertContent(branch, revtree2, dest_path, b"bbb")
        self.assertRevisionRoot(revtree1, src_path)
        self.assertRevisionRoot(revtree2, dest_path)

    def test_copy_of_modified_file_in_subdir(self):
        handler, branch = self.get_handler()
        src_path = b"d/a"
        dest_path = b"d/b"
        handler.process(self.file_command_iter(src_path, dest_path))
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_modified=[(src_path,)], expected_added=[(dest_path,)]
        )
        self.assertContent(branch, revtree1, src_path, b"aaa")
        self.assertContent(branch, revtree2, src_path, b"bbb")
        self.assertContent(branch, revtree2, dest_path, b"bbb")

    def test_copy_of_modified_file_to_new_dir(self):
        handler, branch = self.get_handler()
        src_path = b"d1/a"
        dest_path = b"d2/a"
        handler.process(self.file_command_iter(src_path, dest_path))
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_modified=[(src_path,)],
            expected_added=[(b"d2",), (dest_path,)],
        )
        self.assertContent(branch, revtree1, src_path, b"aaa")
        self.assertContent(branch, revtree2, src_path, b"bbb")
        self.assertContent(branch, revtree2, dest_path, b"bbb")

    def test_copy_of_modified_symlink_in_root(self):
        handler, branch = self.get_handler()
        src_path = b"a"
        dest_path = b"b"
        handler.process(self.file_command_iter(src_path, dest_path, "symlink"))
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_modified=[(src_path,)], expected_added=[(dest_path,)]
        )
        self.assertSymlinkTarget(branch, revtree1, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, src_path, "bbb")
        self.assertSymlinkTarget(branch, revtree2, dest_path, "bbb")
        self.assertRevisionRoot(revtree1, src_path)
        self.assertRevisionRoot(revtree2, dest_path)

    def test_copy_of_modified_symlink_in_subdir(self):
        handler, branch = self.get_handler()
        src_path = b"d/a"
        dest_path = b"d/b"
        handler.process(self.file_command_iter(src_path, dest_path, "symlink"))
        revtree1, revtree2 = self.assertChanges(
            branch, 2, expected_modified=[(src_path,)], expected_added=[(dest_path,)]
        )
        self.assertSymlinkTarget(branch, revtree1, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, src_path, "bbb")
        self.assertSymlinkTarget(branch, revtree2, dest_path, "bbb")

    def test_copy_of_modified_symlink_to_new_dir(self):
        handler, branch = self.get_handler()
        src_path = b"d1/a"
        dest_path = b"d2/a"
        handler.process(self.file_command_iter(src_path, dest_path, "symlink"))
        revtree1, revtree2 = self.assertChanges(
            branch,
            2,
            expected_modified=[(src_path,)],
            expected_added=[(b"d2",), (dest_path,)],
        )
        self.assertSymlinkTarget(branch, revtree1, src_path, "aaa")
        self.assertSymlinkTarget(branch, revtree2, src_path, "bbb")
        self.assertSymlinkTarget(branch, revtree2, dest_path, "bbb")


class TestImportToPackFileKinds(TestCaseForGenericProcessor):
    def get_command_iter(self, path, kind, content):
        def command_list():
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    path, kind_to_mode(kind, False), None, content
                )

            yield commands.CommitCommand(
                b"head", b"1", None, committer, b"commit 1", None, [], files_one
            )

        return command_list

    def test_import_plainfile(self):
        handler, _branch = self.get_handler()
        handler.process(self.get_command_iter(b"foo", "file", b"aaa"))

    def test_import_symlink(self):
        handler, _branch = self.get_handler()
        handler.process(self.get_command_iter(b"foo", "symlink", b"bar"))


class TestModifyRevertInBranch(TestCaseForGenericProcessor):
    def file_command_iter(self):
        # A     add 'foo'
        # |\
        # | B   modify 'foo'
        # | |
        # | C   revert 'foo' back to A
        # |/
        # D     merge 'foo'
        def command_list():
            committer_a = [b"", b"a@elmer.com", time.time(), time.timezone]
            committer_b = [b"", b"b@elmer.com", time.time(), time.timezone]
            committer_c = [b"", b"c@elmer.com", time.time(), time.timezone]
            committer_d = [b"", b"d@elmer.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    b"foo", kind_to_mode("file", False), None, b"content A\n"
                )

            yield commands.CommitCommand(
                b"head", b"1", None, committer_a, b"commit 1", None, [], files_one
            )

            def files_two():
                yield commands.FileModifyCommand(
                    b"foo", kind_to_mode("file", False), None, b"content B\n"
                )

            yield commands.CommitCommand(
                b"head", b"2", None, committer_b, b"commit 2", b":1", [], files_two
            )

            def files_three():
                yield commands.FileModifyCommand(
                    b"foo", kind_to_mode("file", False), None, b"content A\n"
                )

            yield commands.CommitCommand(
                b"head", b"3", None, committer_c, b"commit 3", b":2", [], files_three
            )
            yield commands.CommitCommand(
                b"head",
                b"4",
                None,
                committer_d,
                b"commit 4",
                b":1",
                [b":3"],
                lambda: [],
            )

        return command_list

    def test_modify_revert(self):
        handler, branch = self.get_handler()
        handler.process(self.file_command_iter())
        branch.lock_read()
        self.addCleanup(branch.unlock)
        rev_d = branch.last_revision()
        rev_a, rev_c = branch.repository.get_parent_map([rev_d])[rev_d]
        rev_b = branch.repository.get_parent_map([rev_c])[rev_c][0]
        rtree_a, rtree_b, rtree_c, rtree_d = branch.repository.revision_trees(
            [rev_a, rev_b, rev_c, rev_d]
        )
        self.assertEqual(rev_a, rtree_a.get_file_revision("foo"))
        self.assertEqual(rev_b, rtree_b.get_file_revision("foo"))
        self.assertEqual(rev_c, rtree_c.get_file_revision("foo"))
        self.assertEqual(rev_c, rtree_d.get_file_revision("foo"))


class TestCommitCommands(TestCaseForGenericProcessor):
    def test_non_utf8_commit_message(self):
        handler, branch = self.get_handler()

        def files_one():
            yield commands.FileModifyCommand(
                b"a", kind_to_mode("file", False), None, b"data"
            )

        def command_list():
            committer = [b"", b"elmer@a.com", time.time(), time.timezone]
            yield commands.CommitCommand(
                b"head",
                b"1",
                None,
                committer,
                b"This is a funky character: \x83",
                None,
                [],
                files_one,
            )

        handler.process(command_list)
        rev = branch.repository.get_revision(branch.last_revision())
        self.assertEqual("This is a funky character: \ufffd", rev.message)


class TestAddNonUtf8InBranch(TestCaseForGenericProcessor):
    def file_command_iter(self):
        # A     add 'foo\x83'
        def command_list():
            committer_a = [b"", b"a@elmer.com", time.time(), time.timezone]

            def files_one():
                yield commands.FileModifyCommand(
                    b"foo\x83", kind_to_mode("file", False), None, b"content A\n"
                )

            yield commands.CommitCommand(
                b"head", b"1", None, committer_a, b"commit 1", None, [], files_one
            )

        return command_list

    def test_add(self):
        handler, branch = self.get_handler()
        handler.process(self.file_command_iter())
        branch.lock_read()
        self.addCleanup(branch.unlock)
        rev_a = branch.last_revision()
        rtree_a = branch.repository.revision_tree(rev_a)
        self.assertEqual(rev_a, rtree_a.get_file_revision("foo\ufffd"))

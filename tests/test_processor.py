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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import time

from bzrlib import (
    branch,
    tests,
    )

from bzrlib.plugins.fastimport import (
    commands,
    errors,
    )

from bzrlib.plugins.fastimport.processors import (
    generic_processor,
    )


class TestRename(tests.TestCaseWithTransport):

    def get_handler(self):
        branch = self.make_branch('.')
        handler = generic_processor.GenericProcessor(branch.bzrdir)
        return (handler, branch)

    def get_command_iter(self, old_path, new_path):
        def command_list():
            author = ['', 'bugs@a.com', time.time(), time.timezone]
            committer = ['', 'elmer@a.com', time.time(), time.timezone]
            def files_one():
                yield commands.FileModifyCommand(old_path, 'file', False,
                        None, "aaa")
            yield commands.CommitCommand('head', '1', author,
                committer, "commit 1", [], files_one)
            def files_two():
                yield commands.FileRenameCommand(old_path, new_path)
            yield commands.CommitCommand('head', '2', author,
                committer, "commit 2", [":1"], files_two)
        return command_list

    # FIXME: [] as a default is bad, as it is mutable, but I want
    # to use None to mean "don't check this".
    def check_changes(self, changes, expected_added=[],
            expected_removed=[], expected_modified=[],
            expected_renamed=[]):
        """Check the changes in a TreeDelta

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
        """
        renamed = changes.renamed
        added = changes.added
        removed = changes.removed
        modified = changes.modified
        if expected_renamed is not None:
            self.assertEquals(len(renamed), len(expected_renamed),
                "%s is renamed" % str(renamed))
            renamed_files = [(item[0], item[1]) for item in renamed]
            for expected_renamed_entry in expected_renamed:
                self.assertTrue(expected_renamed_entry in renamed_files,
                    "%s is not renamed, %s are" % (str(expected_renamed_entry),
                        renamed_files))
        if expected_added is not None:
            self.assertEquals(len(added), len(expected_added),
                "%s is added" % str(added))
            added_files = [(item[0],) for item in added]
            for expected_added_entry in expected_added:
                self.assertTrue(expected_added_entry in added_files,
                    "%s is not added, %s are" % (str(expected_added_entry),
                        added_files))
        if expected_removed is not None:
            self.assertEquals(len(removed), len(expected_removed),
                "%s is removed" % str(removed))
            removed_files = [(item[0],) for item in removed]
            for expected_removed_entry in expected_removed:
                self.assertTrue(expected_removed_entry in removed_files,
                    "%s is not removed, %s are" % (str(expected_removed_entry),
                        removed_files))
        if expected_modified is not None:
            self.assertEquals(len(modified), len(expected_modified),
                "%s is modified" % str(modified))
            modified_files = [(item[0],) for item in modified]
            for expected_modified_entry in expected_modified:
                self.assertTrue(expected_modified_entry in modified_files,
                    "%s is not modified, %s are" % (str(expected_modified_entry),
                        modified_files))

    def test_rename_in_root(self):
        (handler, branch) = self.get_handler()
        old_path = 'a'
        new_path = 'b'
        command_list = self.get_command_iter(old_path, new_path)
        handler.process(command_list)
        repo = branch.repository
        revtree1 = repo.revision_tree(branch.revision_history()[0])
        revtree2 = repo.revision_tree(branch.revision_history()[1])
        changes = revtree2.changes_from(revtree1)
        self.check_changes(changes, expected_renamed=[(old_path, new_path)])

    def test_rename_in_subdir(self):
        (handler, branch) = self.get_handler()
        old_path = 'a/a'
        new_path = 'a/b'
        command_list = self.get_command_iter(old_path, new_path)
        handler.process(command_list)
        repo = branch.repository
        revtree1 = repo.revision_tree(branch.revision_history()[0])
        revtree2 = repo.revision_tree(branch.revision_history()[1])
        changes = revtree2.changes_from(revtree1)
        self.check_changes(changes, expected_renamed=[(old_path, new_path)])

    def test_move_to_new_dir(self):
        (handler, branch) = self.get_handler()
        old_path = 'a/a'
        new_path = 'b/a'
        command_list = self.get_command_iter(old_path, new_path)
        handler.process(command_list)
        repo = branch.repository
        revtree1 = repo.revision_tree(branch.revision_history()[0])
        revtree2 = repo.revision_tree(branch.revision_history()[1])
        changes = revtree2.changes_from(revtree1)
        self.check_changes(changes, expected_renamed=[(old_path, new_path)],
            expected_added=[('b',)])

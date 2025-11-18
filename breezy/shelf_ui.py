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

import contextlib
import shutil
import sys
import tempfile
from io import BytesIO

import patiencediff

from . import (
    builtins,
    delta,
    diff,
    errors,
    osutils,
    patches,
    shelf,
    textfile,
    trace,
    ui,
    workingtree,
)
from .i18n import gettext


class UseEditor(Exception):
    """Use an editor instead of selecting hunks."""


class ShelfReporter:
    vocab = {
        "add file": gettext('Shelve adding file "%(path)s"?'),
        "binary": gettext("Shelve binary changes?"),
        "change kind": gettext('Shelve changing "%s" from %(other)s to %(this)s?'),
        "delete file": gettext('Shelve removing file "%(path)s"?'),
        "final": gettext("Shelve %d change(s)?"),
        "hunk": gettext("Shelve?"),
        "modify target": gettext(
            'Shelve changing target of "%(path)s" from "%(other)s" to "%(this)s"?'
        ),
        "rename": gettext('Shelve renaming "%(other)s" => "%(this)s"?'),
    }

    invert_diff = False

    def __init__(self):
        self.delta_reporter = delta._ChangeReporter()

    def no_changes(self):
        """Report that no changes were selected to apply."""
        trace.warning("No changes to shelve.")

    def shelved_id(self, shelf_id):
        """Report the id changes were shelved to."""
        trace.note(gettext('Changes shelved with id "%d".') % shelf_id)

    def changes_destroyed(self):
        """Report that changes were made without shelving."""
        trace.note(gettext("Selected changes destroyed."))

    def selected_changes(self, transform):
        """Report the changes that were selected."""
        trace.note(gettext("Selected changes:"))
        changes = transform.iter_changes()
        delta.report_changes(changes, self.delta_reporter)

    def prompt_change(self, change):
        """Determine the prompt for a change to apply."""
        if change[0] == "rename":
            vals = {"this": change[3], "other": change[2]}
        elif change[0] == "change kind":
            vals = {"path": change[4], "other": change[2], "this": change[3]}
        elif change[0] == "modify target":
            vals = {"path": change[2], "other": change[3], "this": change[4]}
        else:
            vals = {"path": change[3]}
        prompt = self.vocab[change[0]] % vals
        return prompt


class ApplyReporter(ShelfReporter):
    vocab = {
        "add file": gettext('Delete file "%(path)s"?'),
        "binary": gettext("Apply binary changes?"),
        "change kind": gettext('Change "%(path)s" from %(this)s to %(other)s?'),
        "delete file": gettext('Add file "%(path)s"?'),
        "final": gettext("Apply %d change(s)?"),
        "hunk": gettext("Apply change?"),
        "modify target": gettext(
            'Change target of "%(path)s" from "%(this)s" to "%(other)s"?'
        ),
        "rename": gettext('Rename "%(this)s" => "%(other)s"?'),
    }

    invert_diff = True

    def changes_destroyed(self):
        pass


class Shelver:
    """Interactively shelve the changes in a working tree."""

    def __init__(
        self,
        work_tree,
        target_tree,
        diff_writer=None,
        auto=False,
        auto_apply=False,
        file_list=None,
        message=None,
        destroy=False,
        manager=None,
        reporter=None,
    ):
        """Constructor.

        :param work_tree: The working tree to shelve changes from.
        :param target_tree: The "unchanged" / old tree to compare the
            work_tree to.
        :param auto: If True, shelve each possible change.
        :param auto_apply: If True, shelve changes with no final prompt.
        :param file_list: If supplied, only files in this list may be shelved.
        :param message: The message to associate with the shelved changes.
        :param destroy: Change the working tree without storing the shelved
            changes.
        :param manager: The shelf manager to use.
        :param reporter: Object for reporting changes to user.
        """
        self.work_tree = work_tree
        self.target_tree = target_tree
        self.diff_writer = diff_writer
        if self.diff_writer is None:
            self.diff_writer = sys.stdout
        if manager is None:
            manager = work_tree.get_shelf_manager()
        self.manager = manager
        self.auto = auto
        self.auto_apply = auto_apply
        self.file_list = file_list
        self.message = message
        self.destroy = destroy
        if reporter is None:
            reporter = ShelfReporter()
        self.reporter = reporter
        config = self.work_tree.branch.get_config()
        self.change_editor = config.get_change_editor(target_tree, work_tree)
        self.work_tree.lock_tree_write()

    @classmethod
    def from_args(
        klass,
        diff_writer,
        revision=None,
        all=False,
        file_list=None,
        message=None,
        directory=None,
        destroy=False,
    ):
        """Create a shelver from commandline arguments.

        The returned shelver wil have a work_tree that is locked and should
        be unlocked.

        :param revision: RevisionSpec of the revision to compare to.
        :param all: If True, shelve all changes without prompting.
        :param file_list: If supplied, only files in this list may be  shelved.
        :param message: The message to associate with the shelved changes.
        :param directory: The directory containing the working tree.
        :param destroy: Change the working tree without storing the shelved
            changes.
        """
        if directory is None:
            directory = "."
        elif file_list:
            file_list = [osutils.pathjoin(directory, f) for f in file_list]
        tree, _path = workingtree.WorkingTree.open_containing(directory)
        # Ensure that tree is locked for the lifetime of target_tree, as
        # target tree may be reading from the same dirstate.
        with tree.lock_tree_write():
            target_tree = builtins._get_one_revision_tree(
                "shelf2", revision, tree.branch, tree
            )
            files = tree.safe_relpath_files(file_list)
            return klass(
                tree, target_tree, diff_writer, all, all, files, message, destroy
            )

    def run(self):
        """Interactively shelve the changes."""
        creator = shelf.ShelfCreator(self.work_tree, self.target_tree, self.file_list)
        self.tempdir = tempfile.mkdtemp()
        changes_shelved = 0
        try:
            for change in creator.iter_shelvable():
                if change[0] == "modify text":
                    try:
                        changes_shelved += self.handle_modify_text(creator, change[1])
                    except errors.BinaryFile:
                        if self.prompt_bool(self.reporter.vocab["binary"]):
                            changes_shelved += 1
                            creator.shelve_content_change(change[1])
                else:
                    if self.prompt_bool(self.reporter.prompt_change(change)):
                        creator.shelve_change(change)
                        changes_shelved += 1
            if changes_shelved > 0:
                self.reporter.selected_changes(creator.work_transform)
                if self.auto_apply or self.prompt_bool(
                    self.reporter.vocab["final"] % changes_shelved
                ):
                    if self.destroy:
                        creator.transform()
                        self.reporter.changes_destroyed()
                    else:
                        shelf_id = self.manager.shelve_changes(creator, self.message)
                        self.reporter.shelved_id(shelf_id)
            else:
                self.reporter.no_changes()
        finally:
            shutil.rmtree(self.tempdir)
            creator.finalize()

    def finalize(self):
        if self.change_editor is not None:
            self.change_editor.finish()
        self.work_tree.unlock()

    def get_parsed_patch(self, file_id, invert=False):
        """Return a parsed version of a file's patch.

        :param file_id: The id of the file to generate a patch for.
        :param invert: If True, provide an inverted patch (insertions displayed
            as removals, removals displayed as insertions).
        :return: A patches.Patch.
        """
        diff_file = BytesIO()
        if invert:
            old_tree = self.work_tree
            new_tree = self.target_tree
        else:
            old_tree = self.target_tree
            new_tree = self.work_tree
        old_path = old_tree.id2path(file_id)
        new_path = new_tree.id2path(file_id)
        path_encoding = osutils.get_terminal_encoding()
        text_differ = diff.DiffText(
            old_tree, new_tree, diff_file, path_encoding=path_encoding
        )
        text_differ.diff(old_path, new_path, "file", "file")
        diff_file.seek(0)
        return patches.parse_patch(diff_file)

    def prompt(self, message, choices, default):
        return ui.ui_factory.choose(message, choices, default=default)

    def prompt_bool(self, question, allow_editor=False):
        """Prompt the user with a yes/no question.

        This may be overridden by self.auto.  It may also *set* self.auto.  It
        may also raise UserAbort.
        :param question: The question to ask the user.
        :return: True or False
        """
        if self.auto:
            return True
        alternatives_chars = "yn"
        alternatives = "&yes\n&No"
        if allow_editor:
            alternatives_chars += "e"
            alternatives += "\n&edit manually"
        alternatives_chars += "fq"
        alternatives += "\n&finish\n&quit"
        choice = self.prompt(question, alternatives, 1)
        if choice is None:
            # EOF.
            char = "n"
        else:
            char = alternatives_chars[choice]
        if char == "y":
            return True
        elif char == "e" and allow_editor:
            raise UseEditor
        elif char == "f":
            self.auto = True
            return True
        if char == "q":
            raise errors.UserAbort()
        else:
            return False

    def handle_modify_text(self, creator, file_id):
        """Handle modified text, by using hunk selection or file editing.

        :param creator: A ShelfCreator.
        :param file_id: The id of the file that was modified.
        :return: The number of changes.
        """
        path = self.work_tree.id2path(file_id)
        work_tree_lines = self.work_tree.get_file_lines(path, file_id)
        try:
            lines, change_count = self._select_hunks(creator, file_id, work_tree_lines)
        except UseEditor:
            lines, change_count = self._edit_file(file_id, work_tree_lines)
        if change_count != 0:
            creator.shelve_lines(file_id, lines)
        return change_count

    def _select_hunks(self, creator, file_id, work_tree_lines):
        """Provide diff hunk selection for modified text.

        If self.reporter.invert_diff is True, the diff is inverted so that
        insertions are displayed as removals and vice versa.

        :param creator: a ShelfCreator
        :param file_id: The id of the file to shelve.
        :param work_tree_lines: Line contents of the file in the working tree.
        :return: number of shelved hunks.
        """
        if self.reporter.invert_diff:
            target_lines = work_tree_lines
        else:
            path = self.target_tree.id2path(file_id)
            target_lines = self.target_tree.get_file_lines(path)
        textfile.check_text_lines(work_tree_lines)
        textfile.check_text_lines(target_lines)
        parsed = self.get_parsed_patch(file_id, self.reporter.invert_diff)
        final_hunks = []
        if not self.auto:
            offset = 0
            self.diff_writer.write(parsed.get_header())
            for hunk in parsed.hunks:
                self.diff_writer.write(hunk.as_bytes())
                selected = self.prompt_bool(
                    self.reporter.vocab["hunk"],
                    allow_editor=(self.change_editor is not None),
                )
                if not self.reporter.invert_diff:
                    selected = not selected
                if selected:
                    hunk.mod_pos += offset
                    final_hunks.append(hunk)
                else:
                    offset -= hunk.mod_range - hunk.orig_range
        sys.stdout.flush()
        if self.reporter.invert_diff:
            change_count = len(final_hunks)
        else:
            change_count = len(parsed.hunks) - len(final_hunks)
        patched = patches.iter_patched_from_hunks(target_lines, final_hunks)
        lines = list(patched)
        return lines, change_count

    def _edit_file(self, file_id, work_tree_lines):
        """:param file_id: id of the file to edit.
        :param work_tree_lines: Line contents of the file in the working tree.
        :return: (lines, change_region_count), where lines is the new line
            content of the file, and change_region_count is the number of
            changed regions.
        """
        lines = osutils.split_lines(
            self.change_editor.edit_file(
                self.change_editor.old_tree.id2path(file_id),
                self.change_editor.new_tree.id2path(file_id),
            )
        )
        return lines, self._count_changed_regions(work_tree_lines, lines)

    @staticmethod
    def _count_changed_regions(old_lines, new_lines):
        matcher = patiencediff.PatienceSequenceMatcher(None, old_lines, new_lines)
        blocks = matcher.get_matching_blocks()
        return len(blocks) - 2


class Unshelver:
    """Unshelve changes into a working tree."""

    @classmethod
    def from_args(
        klass, shelf_id=None, action="apply", directory=".", write_diff_to=None
    ):
        """Create an unshelver from commandline arguments.

        The returned shelver will have a tree that is locked and should
        be unlocked.

        :param shelf_id: Integer id of the shelf, as a string.
        :param action: action to perform.  May be 'apply', 'dry-run',
            'delete', 'preview'.
        :param directory: The directory to unshelve changes into.
        :param write_diff_to: See Unshelver.__init__().
        """
        tree, _path = workingtree.WorkingTree.open_containing(directory)
        tree.lock_tree_write()
        try:
            manager = tree.get_shelf_manager()
            if shelf_id is not None:
                try:
                    shelf_id = int(shelf_id)
                except ValueError:
                    raise shelf.InvalidShelfId(shelf_id)
            else:
                shelf_id = manager.last_shelf()
                if shelf_id is None:
                    raise errors.CommandError(gettext("No changes are shelved."))
            apply_changes = True
            delete_shelf = True
            read_shelf = True
            show_diff = False
            if action == "dry-run":
                apply_changes = False
                delete_shelf = False
            elif action == "preview":
                apply_changes = False
                delete_shelf = False
                show_diff = True
            elif action == "delete-only":
                apply_changes = False
                read_shelf = False
            elif action == "keep":
                apply_changes = True
                delete_shelf = False
        except:
            tree.unlock()
            raise
        return klass(
            tree,
            manager,
            shelf_id,
            apply_changes,
            delete_shelf,
            read_shelf,
            show_diff,
            write_diff_to,
        )

    def __init__(
        self,
        tree,
        manager,
        shelf_id,
        apply_changes=True,
        delete_shelf=True,
        read_shelf=True,
        show_diff=False,
        write_diff_to=None,
    ):
        """Constructor.

        :param tree: The working tree to unshelve into.
        :param manager: The ShelveManager containing the shelved changes.
        :param shelf_id:
        :param apply_changes: If True, apply the shelved changes to the
            working tree.
        :param delete_shelf: If True, delete the changes from the shelf.
        :param read_shelf: If True, read the changes from the shelf.
        :param show_diff: If True, show the diff that would result from
            unshelving the changes.
        :param write_diff_to: A file-like object where the diff will be
            written to. If None, ui.ui_factory.make_output_stream() will
            be used.
        """
        self.tree = tree
        manager = tree.get_shelf_manager()
        self.manager = manager
        self.shelf_id = shelf_id
        self.apply_changes = apply_changes
        self.delete_shelf = delete_shelf
        self.read_shelf = read_shelf
        self.show_diff = show_diff
        self.write_diff_to = write_diff_to

    def run(self):
        """Perform the unshelving operation."""
        with contextlib.ExitStack() as exit_stack:
            exit_stack.enter_context(self.tree.lock_tree_write())
            if self.read_shelf:
                trace.note(gettext('Using changes with id "%d".') % self.shelf_id)
                unshelver = self.manager.get_unshelver(self.shelf_id)
                exit_stack.callback(unshelver.finalize)
                if unshelver.message is not None:
                    trace.note(gettext("Message: %s") % unshelver.message)
                change_reporter = delta._ChangeReporter()
                merger = unshelver.make_merger()
                merger.change_reporter = change_reporter
                if self.apply_changes:
                    merger.do_merge()
                elif self.show_diff:
                    self.write_diff(merger)
                else:
                    self.show_changes(merger)
            if self.delete_shelf:
                self.manager.delete_shelf(self.shelf_id)
                trace.note(gettext('Deleted changes with id "%d".') % self.shelf_id)

    def write_diff(self, merger):
        """Write this operation's diff to self.write_diff_to."""
        tree_merger = merger.make_merger()
        tt = tree_merger.make_preview_transform()
        new_tree = tt.get_preview_tree()
        if self.write_diff_to is None:
            self.write_diff_to = ui.ui_factory.make_output_stream(encoding_type="exact")
        path_encoding = osutils.get_diff_header_encoding()
        diff.show_diff_trees(
            merger.this_tree, new_tree, self.write_diff_to, path_encoding=path_encoding
        )
        tt.finalize()

    def show_changes(self, merger):
        """Show the changes that this operation specifies."""
        tree_merger = merger.make_merger()
        # This implicitly shows the changes via the reporter, so we're done...
        tt = tree_merger.make_preview_transform()
        tt.finalize()

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


from cStringIO import StringIO
import shutil
import sys
import tempfile

from bzrlib import (
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


class Shelver(object):
    """Interactively shelve the changes in a working tree."""

    def __init__(self, work_tree, target_tree, diff_writer=None, auto=False,
                 auto_apply=False, file_list=None, message=None):
        """Constructor.

        :param work_tree: The working tree to shelve changes from.
        :param target_tree: The "unchanged" / old tree to compare the
            work_tree to.
        :param auto: If True, shelve each possible change.
        :param auto_apply: If True, shelve changes with no final prompt.
        :param file_list: If supplied, only files in this list may be shelved.
        :param message: The message to associate with the shelved changes.
        """
        self.work_tree = work_tree
        self.target_tree = target_tree
        self.diff_writer = diff_writer
        if self.diff_writer is None:
            self.diff_writer = sys.stdout
        self.manager = work_tree.get_shelf_manager()
        self.auto = auto
        self.auto_apply = auto_apply
        self.file_list = file_list
        self.message = message

    @classmethod
    def from_args(klass, diff_writer, revision=None, all=False, file_list=None,
                  message=None, directory='.'):
        """Create a shelver from commandline arguments.

        :param revision: RevisionSpec of the revision to compare to.
        :param all: If True, shelve all changes without prompting.
        :param file_list: If supplied, only files in this list may be  shelved.
        :param message: The message to associate with the shelved changes.
        :param directory: The directory containing the working tree.
        """
        tree, path = workingtree.WorkingTree.open_containing(directory)
        target_tree = builtins._get_one_revision_tree('shelf2', revision,
            tree.branch, tree)
        return klass(tree, target_tree, diff_writer, all, all, file_list,
                     message)

    def run(self):
        """Interactively shelve the changes."""
        creator = shelf.ShelfCreator(self.work_tree, self.target_tree,
                                     self.file_list)
        self.tempdir = tempfile.mkdtemp()
        changes_shelved = 0
        try:
            for change in creator.iter_shelvable():
                if change[0] == 'modify text':
                    try:
                        changes_shelved += self.handle_modify_text(creator,
                                                                   change[1])
                    except errors.BinaryFile:
                        if self.prompt_bool('Shelve binary changes?'):
                            changes_shelved += 1
                            creator.shelve_content_change(change[1])
                if change[0] == 'add file':
                    if self.prompt_bool('Shelve adding file "%s"?'
                                        % change[3]):
                        creator.shelve_creation(change[1])
                        changes_shelved += 1
                if change[0] == 'delete file':
                    if self.prompt_bool('Shelve removing file "%s"?'
                                        % change[3]):
                        creator.shelve_deletion(change[1])
                        changes_shelved += 1
                if change[0] == 'change kind':
                    if self.prompt_bool('Shelve changing "%s" from %s to %s? '
                                        % (change[4], change[2], change[3])):
                        creator.shelve_content_change(change[1])
                        changes_shelved += 1
                if change[0] == 'rename':
                    if self.prompt_bool('Shelve renaming "%s" => "%s"?' %
                                   change[2:]):
                        creator.shelve_rename(change[1])
                        changes_shelved += 1
            if changes_shelved > 0:
                trace.note("Selected changes:")
                changes = creator.work_transform.iter_changes()
                reporter = delta._ChangeReporter()
                delta.report_changes(changes, reporter)
                if (self.auto_apply or self.prompt_bool(
                    'Shelve %d change(s)?' % changes_shelved)):
                    shelf_id = self.manager.shelve_changes(creator,
                                                           self.message)
                    trace.note('Changes shelved with id "%d".' % shelf_id)
            else:
                trace.warning('No changes to shelve.')
        finally:
            shutil.rmtree(self.tempdir)
            creator.finalize()

    def get_parsed_patch(self, file_id):
        """Return a parsed version of a file's patch.

        :param file_id: The id of the file to generate a patch for.
        :return: A patches.Patch.
        """
        old_path = self.target_tree.id2path(file_id)
        new_path = self.work_tree.id2path(file_id)
        diff_file = StringIO()
        text_differ = diff.DiffText(self.target_tree, self.work_tree,
                                    diff_file)
        patch = text_differ.diff(file_id, old_path, new_path, 'file', 'file')
        diff_file.seek(0)
        return patches.parse_patch(diff_file)

    def prompt(self, message):
        """Prompt the user for a character.

        :param message: The message to prompt a user with.
        :return: A character.
        """
        sys.stdout.write(message)
        char = osutils.getchar()
        sys.stdout.write("\r" + ' ' * len(message) + '\r')
        sys.stdout.flush()
        return char

    def prompt_bool(self, question):
        """Prompt the user with a yes/no question.

        This may be overridden by self.auto.  It may also *set* self.auto.  It
        may also raise UserAbort.
        :param question: The question to ask the user.
        :return: True or False
        """
        if self.auto:
            return True
        char = self.prompt(question + ' [yNfq]')
        if char == 'y':
            return True
        elif char == 'f':
            self.auto = True
            return True
        if char == 'q':
            raise errors.UserAbort()
        else:
            return False

    def handle_modify_text(self, creator, file_id):
        """Provide diff hunk selection for modified text.

        :param creator: a ShelfCreator
        :param file_id: The id of the file to shelve.
        :return: number of shelved hunks.
        """
        target_lines = self.target_tree.get_file_lines(file_id)
        textfile.check_text_lines(self.work_tree.get_file_lines(file_id))
        textfile.check_text_lines(target_lines)
        parsed = self.get_parsed_patch(file_id)
        final_hunks = []
        if not self.auto:
            offset = 0
            self.diff_writer.write(parsed.get_header())
            for hunk in parsed.hunks:
                self.diff_writer.write(str(hunk))
                if not self.prompt_bool('Shelve?'):
                    hunk.mod_pos += offset
                    final_hunks.append(hunk)
                else:
                    offset -= (hunk.mod_range - hunk.orig_range)
        sys.stdout.flush()
        if len(parsed.hunks) == len(final_hunks):
            return 0
        patched = patches.iter_patched_from_hunks(target_lines, final_hunks)
        creator.shelve_lines(file_id, list(patched))
        return len(parsed.hunks) - len(final_hunks)


class Unshelver(object):
    """Unshelve changes into a working tree."""

    @classmethod
    def from_args(klass, shelf_id=None, action='apply', directory='.'):
        """Create an unshelver from commandline arguments.

        :param shelf_id: Integer id of the shelf, as a string.
        :param action: action to perform.  May be 'apply', 'dry-run',
            'delete'.
        :param directory: The directory to unshelve changes into.
        """
        tree, path = workingtree.WorkingTree.open_containing(directory)
        manager = tree.get_shelf_manager()
        if shelf_id is not None:
            shelf_id = int(shelf_id)
        else:
            shelf_id = manager.last_shelf()
            if shelf_id is None:
                raise errors.BzrCommandError('No changes are shelved.')
            trace.note('Unshelving changes with id "%d".' % shelf_id)
        apply_changes = True
        delete_shelf = True
        read_shelf = True
        if action == 'dry-run':
            apply_changes = False
            delete_shelf = False
        if action == 'delete-only':
            apply_changes = False
            read_shelf = False
        return klass(tree, manager, shelf_id, apply_changes, delete_shelf,
                     read_shelf)

    def __init__(self, tree, manager, shelf_id, apply_changes=True,
                 delete_shelf=True, read_shelf=True):
        """Constructor.

        :param tree: The working tree to unshelve into.
        :param manager: The ShelveManager containing the shelved changes.
        :param shelf_id:
        :param apply_changes: If True, apply the shelved changes to the
            working tree.
        :param delete_shelf: If True, delete the changes from the shelf.
        :param read_shelf: If True, read the changes from the shelf.
        """
        self.tree = tree
        manager = tree.get_shelf_manager()
        self.manager = manager
        self.shelf_id = shelf_id
        self.apply_changes = apply_changes
        self.delete_shelf = delete_shelf
        self.read_shelf = read_shelf

    def run(self):
        """Perform the unshelving operation."""
        self.tree.lock_write()
        cleanups = [self.tree.unlock]
        try:
            if self.read_shelf:
                unshelver = self.manager.get_unshelver(self.shelf_id)
                cleanups.append(unshelver.finalize)
                if unshelver.message is not None:
                    trace.note('Message: %s' % unshelver.message)
                change_reporter = delta._ChangeReporter()
                merger = unshelver.make_merger()
                merger.change_reporter = change_reporter
                if self.apply_changes:
                    pb = ui.ui_factory.nested_progress_bar()
                    try:
                        merger.do_merge()
                    finally:
                        pb.finished()
                else:
                    self.show_changes(merger)
            if self.delete_shelf:
                self.manager.delete_shelf(self.shelf_id)
        finally:
            for cleanup in reversed(cleanups):
                cleanup()

    def show_changes(self, merger):
        """Show the changes that this operation specifies."""
        tree_merger = merger.make_merger()
        # This implicitly shows the changes via the reporter, so we're done...
        tt = tree_merger.make_preview_transform()
        tt.finalize()

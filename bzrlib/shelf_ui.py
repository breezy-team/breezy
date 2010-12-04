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


class ShelfReporter(object):

    vocab = {'add file': 'Shelve adding file "%(path)s"?',
             'binary': 'Shelve binary changes?',
             'change kind': 'Shelve changing "%s" from %(other)s'
             ' to %(this)s?',
             'delete file': 'Shelve removing file "%(path)s"?',
             'final': 'Shelve %d change(s)?',
             'hunk': 'Shelve?',
             'modify target': 'Shelve changing target of'
             ' "%(path)s" from "%(other)s" to "%(this)s"?',
             'rename': 'Shelve renaming "%(other)s" =>'
                        ' "%(this)s"?'
             }

    invert_diff = False

    def __init__(self):
        self.delta_reporter = delta._ChangeReporter()

    def no_changes(self):
        """Report that no changes were selected to apply."""
        trace.warning('No changes to shelve.')

    def shelved_id(self, shelf_id):
        """Report the id changes were shelved to."""
        trace.note('Changes shelved with id "%d".' % shelf_id)

    def changes_destroyed(self):
        """Report that changes were made without shelving."""
        trace.note('Selected changes destroyed.')

    def selected_changes(self, transform):
        """Report the changes that were selected."""
        trace.note("Selected changes:")
        changes = transform.iter_changes()
        delta.report_changes(changes, self.delta_reporter)

    def prompt_change(self, change):
        """Determine the prompt for a change to apply."""
        if change[0] == 'rename':
            vals = {'this': change[3], 'other': change[2]}
        elif change[0] == 'change kind':
            vals = {'path': change[4], 'other': change[2], 'this': change[3]}
        elif change[0] == 'modify target':
            vals = {'path': change[2], 'other': change[3], 'this': change[4]}
        else:
            vals = {'path': change[3]}
        prompt = self.vocab[change[0]] % vals
        return prompt


class ApplyReporter(ShelfReporter):

    vocab = {'add file': 'Delete file "%(path)s"?',
             'binary': 'Apply binary changes?',
             'change kind': 'Change "%(path)s" from %(this)s'
             ' to %(other)s?',
             'delete file': 'Add file "%(path)s"?',
             'final': 'Apply %d change(s)?',
             'hunk': 'Apply change?',
             'modify target': 'Change target of'
             ' "%(path)s" from "%(this)s" to "%(other)s"?',
             'rename': 'Rename "%(this)s" => "%(other)s"?',
             }

    invert_diff = True

    def changes_destroyed(self):
        pass


class Shelver(object):
    """Interactively shelve the changes in a working tree."""

    def __init__(self, work_tree, target_tree, diff_writer=None, auto=False,
                 auto_apply=False, file_list=None, message=None,
                 destroy=False, manager=None, reporter=None):
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

    @classmethod
    def from_args(klass, diff_writer, revision=None, all=False, file_list=None,
                  message=None, directory='.', destroy=False):
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
        tree, path = workingtree.WorkingTree.open_containing(directory)
        # Ensure that tree is locked for the lifetime of target_tree, as
        # target tree may be reading from the same dirstate.
        tree.lock_tree_write()
        try:
            target_tree = builtins._get_one_revision_tree('shelf2', revision,
                tree.branch, tree)
            files = builtins.safe_relpath_files(tree, file_list)
        except:
            tree.unlock()
            raise
        return klass(tree, target_tree, diff_writer, all, all, files, message,
                     destroy)

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
                        if self.prompt_bool(self.reporter.vocab['binary']):
                            changes_shelved += 1
                            creator.shelve_content_change(change[1])
                else:
                    if self.prompt_bool(self.reporter.prompt_change(change)):
                        creator.shelve_change(change)
                        changes_shelved += 1
            if changes_shelved > 0:
                self.reporter.selected_changes(creator.work_transform)
                if (self.auto_apply or self.prompt_bool(
                    self.reporter.vocab['final'] % changes_shelved)):
                    if self.destroy:
                        creator.transform()
                        self.reporter.changes_destroyed()
                    else:
                        shelf_id = self.manager.shelve_changes(creator,
                                                               self.message)
                        self.reporter.shelved_id(shelf_id)
            else:
                self.reporter.no_changes()
        finally:
            shutil.rmtree(self.tempdir)
            creator.finalize()

    def get_parsed_patch(self, file_id, invert=False):
        """Return a parsed version of a file's patch.

        :param file_id: The id of the file to generate a patch for.
        :param invert: If True, provide an inverted patch (insertions displayed
            as removals, removals displayed as insertions).
        :return: A patches.Patch.
        """
        diff_file = StringIO()
        if invert:
            old_tree = self.work_tree
            new_tree = self.target_tree
        else:
            old_tree = self.target_tree
            new_tree = self.work_tree
        old_path = old_tree.id2path(file_id)
        new_path = new_tree.id2path(file_id)
        text_differ = diff.DiffText(old_tree, new_tree, diff_file)
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

    def prompt_bool(self, question, long=False):
        """Prompt the user with a yes/no question.

        This may be overridden by self.auto.  It may also *set* self.auto.  It
        may also raise UserAbort.
        :param question: The question to ask the user.
        :return: True or False
        """
        if self.auto:
            return True
        if long:
            prompt = ' [(y)es, (N)o, (f)inish, or (q)uit]'
        else:
            prompt = ' [yNfq?]'
        char = self.prompt(question + prompt)
        if char == 'y':
            return True
        elif char == 'f':
            self.auto = True
            return True
        elif char == '?':
            return self.prompt_bool(question, long=True)
        if char == 'q':
            raise errors.UserAbort()
        else:
            return False

    def handle_modify_text(self, creator, file_id):
        """Provide diff hunk selection for modified text.

        If self.reporter.invert_diff is True, the diff is inverted so that
        insertions are displayed as removals and vice versa.

        :param creator: a ShelfCreator
        :param file_id: The id of the file to shelve.
        :return: number of shelved hunks.
        """
        if self.reporter.invert_diff:
            target_lines = self.work_tree.get_file_lines(file_id)
        else:
            target_lines = self.target_tree.get_file_lines(file_id)
        textfile.check_text_lines(self.work_tree.get_file_lines(file_id))
        textfile.check_text_lines(target_lines)
        parsed = self.get_parsed_patch(file_id, self.reporter.invert_diff)
        final_hunks = []
        if not self.auto:
            offset = 0
            self.diff_writer.write(parsed.get_header())
            for hunk in parsed.hunks:
                self.diff_writer.write(str(hunk))
                selected = self.prompt_bool(self.reporter.vocab['hunk'])
                if not self.reporter.invert_diff:
                    selected = (not selected)
                if selected:
                    hunk.mod_pos += offset
                    final_hunks.append(hunk)
                else:
                    offset -= (hunk.mod_range - hunk.orig_range)
        sys.stdout.flush()
        if not self.reporter.invert_diff and (
            len(parsed.hunks) == len(final_hunks)):
            return 0
        if self.reporter.invert_diff and len(final_hunks) == 0:
            return 0
        patched = patches.iter_patched_from_hunks(target_lines, final_hunks)
        creator.shelve_lines(file_id, list(patched))
        if self.reporter.invert_diff:
            return len(final_hunks)
        return len(parsed.hunks) - len(final_hunks)


class Unshelver(object):
    """Unshelve changes into a working tree."""

    @classmethod
    def from_args(klass, shelf_id=None, action='apply', directory='.'):
        """Create an unshelver from commandline arguments.

        The returned shelver wil have a tree that is locked and should
        be unlocked.

        :param shelf_id: Integer id of the shelf, as a string.
        :param action: action to perform.  May be 'apply', 'dry-run',
            'delete'.
        :param directory: The directory to unshelve changes into.
        """
        tree, path = workingtree.WorkingTree.open_containing(directory)
        tree.lock_tree_write()
        try:
            manager = tree.get_shelf_manager()
            if shelf_id is not None:
                try:
                    shelf_id = int(shelf_id)
                except ValueError:
                    raise errors.InvalidShelfId(shelf_id)
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
        except:
            tree.unlock()
            raise
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
        self.tree.lock_tree_write()
        cleanups = [self.tree.unlock]
        try:
            if self.read_shelf:
                unshelver = self.manager.get_unshelver(self.shelf_id)
                cleanups.append(unshelver.finalize)
                if unshelver.message is not None:
                    trace.note('Message: %s' % unshelver.message)
                change_reporter = delta._ChangeReporter()
                task = ui.ui_factory.nested_progress_bar()
                try:
                    merger = unshelver.make_merger(task)
                    merger.change_reporter = change_reporter
                    if self.apply_changes:
                        merger.do_merge()
                    else:
                        self.show_changes(merger)
                finally:
                    task.finished()
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

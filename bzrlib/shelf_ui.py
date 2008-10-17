# Copyright (C) 2008 Aaron Bentley <aaron@aaronbentley.com>
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


from cStringIO import StringIO
import shutil
import sys
import tempfile

from bzrlib import (
    builtins,
    delta,
    diff,
    errors,
    patches,
    shelf,
    textfile,
    trace,
    ui,
    workingtree)
from bzrlib.plugins.bzrtools import colordiff
from bzrlib.plugins.bzrtools.userinteractor import getchar


class Shelver(object):

    def __init__(self, work_tree, target_tree, path, auto=False,
                 auto_apply=False, file_list=None, message=None):
        self.work_tree = work_tree
        self.target_tree = target_tree
        self.path = path
        self.diff_file = StringIO()
        self.text_differ = diff.DiffText(self.target_tree, self.work_tree,
                                         self.diff_file)
        self.diff_writer = colordiff.DiffWriter(sys.stdout, False)
        self.manager = work_tree.get_shelf_manager()
        self.auto = auto
        self.auto_apply = auto_apply
        self.file_list = file_list
        self.message = message

    @classmethod
    def from_args(klass, revision=None, all=False, file_list=None,
                  message=None):
        tree, path = workingtree.WorkingTree.open_containing('.')
        target_tree = builtins._get_one_revision_tree('shelf2', revision,
            tree.branch, tree)
        return klass(tree, target_tree, path, all, all, file_list, message)

    def run(self):
        creator = shelf.ShelfCreator(self.work_tree, self.target_tree,
                                     self.file_list)
        self.tempdir = tempfile.mkdtemp()
        changes_shelved = 0
        try:
            for change in creator:
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
                    if self.prompt_bool('Shelve removing file "%s"? '
                                        % change[3]):
                        creator.shelve_deletion(change[1])
                        changes_shelved += 1
                if change[0] == 'change kind':
                    if self.prompt_bool('Shelve changing "%s" from %s to %s? '
                                        % (change[4], change[2], change[3])):
                        creator.shelve_content_change(change[1])
                        changes_shelved += 1
                if change[0] == 'rename':
                    if self.prompt_bool('Shelve renaming %s => %s?' %
                                   change[2:]):
                        creator.shelve_rename(change[1])
                        changes_shelved += 1
            if changes_shelved > 0:
                trace.note("Selected changes:")
                changes = creator.work_transform.iter_changes()
                reporter = delta._ChangeReporter()
                delta.report_changes(changes, reporter)
                if (self.prompt_bool('Shelve %d change(s)?' %
                    changes_shelved, auto=self.auto_apply)):
                    shelf_id = self.manager.shelve_changes(creator,
                                                           self.message)
                    trace.note('Changes shelved with id "%d".' % shelf_id)
            else:
                trace.warning('No changes to shelve.')
        finally:
            shutil.rmtree(self.tempdir)
            creator.finalize()

    def get_parsed_patch(self, file_id):
        old_path = self.work_tree.id2path(file_id)
        new_path = self.target_tree.id2path(file_id)
        try:
            patch = self.text_differ.diff(file_id, old_path, new_path, 'file',
                                          'file')
            self.diff_file.seek(0)
            return patches.parse_patch(self.diff_file)
        finally:
            self.diff_file.truncate(0)

    def prompt_bool(self, question, auto=None):
        if auto is None:
            auto = self.auto
        if auto:
            return True
        message = question + ' [yNfq]'
        sys.stdout.write(message)
        char = getchar()
        sys.stdout.write("\r" + ' ' * len(message) + '\r')
        sys.stdout.flush()
        if char == 'y':
            return True
        elif char == 'f':
            self.auto = True
            return True
        if char == 'q':
            sys.exit(0)
        else:
            return False

    def handle_modify_text(self, creator, file_id):
        target_lines = self.target_tree.get_file_lines(file_id)
        work_file = self.work_tree.get_file(file_id)
        try:
            textfile.text_file(work_file)
        finally:
            work_file.close()
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

    @classmethod
    def from_args(klass, shelf_id=None, action='apply'):
        tree, path = workingtree.WorkingTree.open_containing('.')
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

    def __init__(self, tree, manager, shelf_id, apply_changes, delete_shelf,
                 read_shelf):
        self.tree = tree
        self.manager = manager
        self.shelf_id = shelf_id
        self.apply_changes = apply_changes
        self.delete_shelf = delete_shelf
        self.read_shelf = read_shelf

    def run(self):
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
        tree_merger = merger.make_merger()
        # This implicitly shows the changes via the reporter, so we're done...
        tt = tree_merger.make_preview_transform()
        tt.finalize()

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


import copy
from cStringIO import StringIO
import os.path
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
    trace,
    workingtree)
from bzrlib.plugins.bzrtools import colordiff, hunk_selector
from bzrlib.plugins.bzrtools.patch import run_patch
from bzrlib.plugins.bzrtools.userinteractor import getchar
from bzrlib.plugins.shelf2 import shelf


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
                    changes_shelved += self.handle_modify_text(creator,
                                                               change[1])
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
                if change[0] == 'rename':
                    if self.prompt_bool('Shelve renaming %s => %s?' %
                                   change[2:]):
                        creator.shelve_rename(change[1])
                        changes_shelved += 1
            if changes_shelved > 0:
                print "Selected changes:"
                changes = creator.work_transform.iter_changes()
                reporter = delta._ChangeReporter(output_file=sys.stdout)
                delta.report_changes(changes, reporter)
                if (self.prompt_bool('Shelve %d change(s)?' %
                    changes_shelved, auto=self.auto_apply)):
                    shelf_id = self.manager.shelve_changes(creator,
                                                           self.message)
                    trace.note('Changes shelved with id "%d".' % shelf_id)
            else:
                print 'No changes to shelve.'
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
        print message,
        char = getchar()
        print "\r" + ' ' * len(message) + '\r',
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
        parsed = self.get_parsed_patch(file_id)
        final_hunks = []
        if not self.auto:
            offset = 0
            for hunk in parsed.hunks:
                self.diff_writer.write(str(hunk))
                if not self.prompt_bool('Shelve?'):
                    hunk.mod_pos += offset
                    final_hunks.append(hunk)
                else:
                    offset -= (hunk.mod_range - hunk.orig_range)
        target_lines = self.target_tree.get_file_lines(file_id)
        patched = patches.iter_patched_from_hunks(target_lines, final_hunks)
        creator.shelve_lines(file_id, list(patched))
        return len(parsed.hunks) - len(final_hunks)


class Unshelver(object):

    @classmethod
    def from_args(klass, shelf_id):
        tree, path = workingtree.WorkingTree.open_containing('.')
        manager = tree.get_shelf_manager()
        if shelf_id is not None:
            shelf_id = int(shelf_id)
        else:
            shelf_id = manager.last_shelf()
            if shelf_id is None:
                raise errors.BzrCommandError('No changes are shelved.')
            trace.note('Unshelving changes with id "%d".' % shelf_id)
        return klass(tree, manager, shelf_id)

    def __init__(self, tree, manager, shelf_id):
        self.tree = tree
        self.manager = manager
        self.shelf_id = shelf_id

    def run(self):
        self.tree.lock_write()
        cleanups = [self.tree.unlock]
        try:
            unshelver = self.manager.get_unshelver(self.shelf_id)
            cleanups.append(unshelver.finalize)
            if unshelver.message is not None:
                trace.note('Message: %s' % unshelver.message)
            unshelver.unshelve(delta._ChangeReporter())
            self.manager.delete_shelf(self.shelf_id)
        finally:
            for cleanup in reversed(cleanups):
                cleanup()

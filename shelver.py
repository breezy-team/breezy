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

from bzrlib import (builtins, diff, errors, osutils, patches, workingtree)
from bzrlib.plugins.bzrtools import colordiff, hunk_selector
from bzrlib.plugins.bzrtools.patch import run_patch
from bzrlib.plugins.bzrtools.userinteractor import getchar
from bzrlib.plugins.shelf2 import prepare_shelf


class Shelver(object):

    def __init__(self, work_tree, target_tree, path, auto=False):
        self.work_tree = work_tree
        self.target_tree = target_tree
        self.path = path
        self.diff_file = StringIO()
        self.text_differ = diff.DiffText(self.target_tree, self.work_tree,
                                         self.diff_file)
        self.diff_writer = colordiff.DiffWriter(sys.stdout, False)
        self.manager = prepare_shelf.ShelfManager.for_tree(work_tree)
        self.auto = auto

    @classmethod
    def from_args(klass, revision=None, all=False):
        tree, path = workingtree.WorkingTree.open_containing('.')
        target_tree = builtins._get_one_revision_tree('shelf2', revision,
            tree.branch, tree)
        return klass(tree, target_tree, path, all)

    def run(self):
        creator = prepare_shelf.ShelfCreator(self.work_tree, self.target_tree)
        self.tempdir = tempfile.mkdtemp()
        try:
            for change in creator:
                if change[0] == 'modify text':
                    self.handle_modify_text(creator, change[1])
                if change[0] == 'add file':
                    if self.prompt('Shelve adding file?') == 'y':
                        creator.shelve_creation(change[1])
                if change[0] == 'delete file':
                    if self.prompt('Shelve deleting file?') == 'y':
                        creator.shelve_deletion(change[1])
                if change[0] == 'rename':
                    if self.prompt('Shelve renaming %s => %s?' %
                                   change[2:]) == 'y':
                        creator.shelve_rename(change[1])
            choice = self.prompt('Shelve changes? [y/n]')
            if choice == 'y':
                shelf_id, shelf_file = self.manager.new_shelf()
                try:
                    creator.write_shelf(shelf_file)
                finally:
                    shelf_file.close()
                creator.transform()
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

    def prompt(self, question):
        if self.auto:
            return 'y'
        print question,
        char = getchar()
        print ""
        return char

    def get_patched_text(self, file_id, patch):
        target_file = self.target_tree.get_file(file_id)
        try:
            if len(patch.hunks) == 0:
                return target_file.read()
            filename = os.path.join(self.tempdir, 'patch-target')
            outfile = open(filename, 'w+b')
            try:
                osutils.pumpfile(target_file, outfile)
            finally:
                outfile.close()
        finally:
            target_file.close()
        run_patch('.', [str(patch)], target_file=filename)
        outfile = open(filename, 'rb')
        try:
            return outfile.read()
        finally:
            outfile.close()

    def handle_modify_text(self, creator, file_id):
        parsed = self.get_parsed_patch(file_id)
        selected_hunks = []
        final_patch = copy.copy(parsed)
        final_patch.hunks = []
        if not self.auto:
            for hunk in parsed.hunks:
                self.diff_writer.write(str(hunk))
                char = self.prompt('Shelve? [y/n]')
                if char == 'n':
                    final_patch.hunks.append(hunk)
        patched_text = self.get_patched_text(file_id, final_patch)
        creator.shelve_text(file_id, patched_text)


class Unshelver(object):

    @classmethod
    def from_args(klass):
        tree, path = workingtree.WorkingTree.open_containing('.')
        manager = prepare_shelf.ShelfManager.for_tree(tree)
        shelf_id = manager.last_shelf()
        if shelf_id is None:
            raise errors.BzrCommandError('No changes are shelved.')
        return klass(tree, manager, shelf_id)

    def __init__(self, tree, manager, shelf_id):
        self.tree = tree
        self.manager = manager
        self.shelf_id = shelf_id

    def run(self):
        self.tree.lock_write()
        try:
            shelf_file = self.manager.read_shelf(self.shelf_id)
            try:
                unshelver = prepare_shelf.Unshelver.from_tree_and_shelf(
                    self.tree, shelf_file)
                unshelver.unshelve()
                self.manager.delete_shelf(self.shelf_id)
            finally:
                unshelver.finalize()
                shelf_file.close()
        finally:
            self.tree.unlock()

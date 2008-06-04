#    tree_patcher.py -- Patch a working tree.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#    Copyright (C) 2008 Canonical Limited.
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

import cStringIO
import os
import select
from subprocess import Popen, PIPE

from bzrlib import osutils
from bzrlib.errors import (
        BzrError,
        )


files_to_ignore = set(['.cvsignore', '.arch-inventory', '.bzrignore',
    '.gitignore', 'CVS', 'RCS', '.deps', '{arch}', '.arch-ids', '.svn',
    '.hg', '_darcs', '.git', '.shelf', '.bzr', '.bzr.backup', '.bzrtags',
    '.bzr-builddeb'])

exclude_as_files = ['*/' + x for x in files_to_ignore]
exclude_as_dirs = ['*/' + x + '/*' for x in files_to_ignore]
exclude = exclude_as_files + exclude_as_dirs
underscore_x = ['-x'] * len(exclude)
ignore_arguments = []
map(ignore_arguments.extend, zip(underscore_x, exclude))
ignore_arguments = ignore_arguments + ['-x', '*,v']


class TreePatcher(object):
    """Patch a WorkingTree, including recording additions and removals."""

    def __init__(self, tree):
        """Create a TreePatcher to patch tree.

        :param tree: the WorkingTree to act upon.
        """
        self.tree = tree
        self.patch = None

    def set_patch(self, patch):
        """Set the patch to use from a String.

        :param patch: the patch in the form of a string.
        """
        self.patch = cStringIO.StringIO(patch)

    def set_patch_from_fileobj(self, fileobj):
        """Set the patch from a file-like object.

        :param fileobj: the file-like object to retrieve the patch from.
        """
        self.patch = fileobj

    def _make_filter_proc(self):
        """Create a filterdiff subprocess."""
        filter_cmd = ['filterdiff'] + ignore_arguments
        filter_proc = Popen(filter_cmd, stdin=PIPE, stdout=PIPE)
        return filter_proc

    def _patch_tree(self, patch, basedir):
        """Patch a tree located at basedir."""
        filter_proc = self._make_filter_proc()
        patch_cmd = ['patch', '-g', '0', '--strip', '1', '--quiet', '-f',
                     '--directory', basedir]
        patch_proc = Popen(patch_cmd, stdin=filter_proc.stdout,
                close_fds=True)
        for line in patch:
            filter_proc.stdin.write(line)
            filter_proc.stdin.flush()
        filter_proc.stdin.close()
        r = patch_proc.wait()
        if r != 0:
            raise BzrError('patch failed')

    def _get_touched_paths(self, patch):
        """Return the list of paths that are touched by the patch."""
        filter_proc = self._make_filter_proc()
        cmd = ['lsdiff', '--strip', '1']
        child_proc = Popen(cmd, stdin=filter_proc.stdout, stdout=PIPE,
                           close_fds=True)
        output = ''
        for line in patch:
            filter_proc.stdin.write(line)
            filter_proc.stdin.flush()
            while select.select([child_proc.stdout], [], [], 0)[0]:
                output += child_proc.stdout.read(1)
        filter_proc.stdin.close()
        output += child_proc.stdout.read()
        touched_paths = []
        for filename in output.split('\n'):
            if filename.endswith('\n'):
                filename = filename[:-1]
            if filename != "":
                touched_paths.append(filename)
        r = child_proc.wait()
        if r != 0:
            raise BzrError('lsdiff failed')
        return touched_paths

    def _update_path(self, path, parent_trees):
        """You probably want _update_path_info instead."""
        tree = self.tree
        # If tree doesn't have it then it was removed.
        if not tree.has_filename(path):
            tree.remove([path], verbose=False)
            return
        # Now look through the parents in order
        # Give it the id of the first parent in which
        # it is found.
        added = False
        for parent_tree in parent_trees:
            file_id = parent_tree.path2id(path)
            if file_id is not None:
                tree.add([path], [file_id])
                break
        if not added:
            # New file that didn't exist in any parent, just add it
            tree.add([path])

    def _update_path_info(self, touched_paths, parents):
        """Update the working tree to reflect the changes in certain paths.

        Given a list of paths this method will update the working tree
        to reflect any adds/removes that occured in those paths when
        compared to their parents.

        :param tree: the WorkingTree in which to make the changes.
        :param touched_paths: a list of paths for which to perform
            any needed modifications.
        :param parents: a list of revision ids that should be used
            for working out whether a path needs modification.
        """
        tree = self.tree
        def get_tree(parent):
            return tree.branch.repository.revision_tree(parent)
        parent_trees = [get_tree(p) for p in parents]
        checked_paths = set()
        for path in touched_paths:
            base_path = None
            for part in osutils.splitpath(path):
                if base_path is None:
                    base_path = part
                else:
                    base_path = os.path.join(base_path, part)
                if base_path in checked_paths:
                    continue
                self._update_path(base_path, parent_trees)
                checked_paths.add(base_path)

    def patch_tree(self, parents):
        """Patch the tree with the supplied patch file.

        :param parents: a list of parent ids to take the file ids from
            for any added files.
        """
        assert self.patch is not None, "You must set the patch first"
        self._patch_tree(self.patch, self.tree.basedir)
        self.patch.seek(0)
        touched_paths = self._get_touched_paths(self.patch)
        self._update_path_info(touched_paths, parents)



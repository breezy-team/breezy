# Copyright (C) 2005 Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import sys
from os.path import dirname

import bzrlib.errors as errors
from bzrlib.inventory import InventoryEntry
from bzrlib.trace import mutter, note, warning
from bzrlib.errors import NotBranchError
from bzrlib.branch import is_control_file
import bzrlib.osutils
from bzrlib.workingtree import WorkingTree

def glob_expand_for_win32(file_list):
    if not file_list:
        return
    import glob
    expanded_file_list = []
    for possible_glob in file_list:
        glob_files = glob.glob(possible_glob)
       
        if glob_files == []:
            # special case to let the normal code path handle
            # files that do not exists
            expanded_file_list.append(possible_glob)
        else:
            expanded_file_list += glob_files
    return expanded_file_list


def _prepare_file_list(file_list):
    """Prepare a file list for use by smart_add_*."""
    if sys.platform == 'win32':
        file_list = glob_expand_for_win32(file_list)
    if not file_list:
        file_list = [u'.']
    file_list = list(file_list)
    return file_list


class AddAction(object):
    """A class which defines what action to take when adding a file."""

    should_add = False
    should_print = False

    def __init__(self, to_file=None, should_add=None, should_print=None):
        self._to_file = to_file
        if to_file is None:
            self._to_file = sys.stdout
        if should_add is not None:
            self.should_add = should_add
        if should_print is not None:
            self.should_print = should_print

    def __call__(self, inv, path, kind):
        """Add path to inventory.

        The default action does nothing.

        :param inv: The inventory we are working with.
        :param path: The path being added
        :param kind: The kind of the object being added.
        """
        if self.should_add:
            self._add_to_inv(inv, path, kind)
        if self.should_print:
            self._print(inv, path, kind)

    def _print(self, inv, path, kind):
        self._to_file.write('added ')
        self._to_file.write(bzrlib.osutils.quotefn(path))
        self._to_file.write('\n')

    def _add_to_inv(self, inv, path, kind):
        entry = inv.add_path(path, kind=kind)
        mutter("added %r kind %r file_id={%s}", path, kind, entry.file_id)


# TODO: jam 20050105 These could be used for compatibility
#       however, they bind against the current stdout, not the
#       one which exists at the time they are called, so they
#       don't work for the test suite.
# deprecated
add_action_null = AddAction()
add_action_add = AddAction(should_add=True)
add_action_print = AddAction(should_print=True)
add_action_add_and_print = AddAction(should_add=True, should_print=True)


def smart_add(file_list, recurse=True, action=None):
    """Add files to version, optionally recursing into directories.

    This is designed more towards DWIM for humans than API simplicity.
    For the specific behaviour see the help for cmd_add().

    Returns the number of files added.

    """
    file_list = _prepare_file_list(file_list)
    tree = WorkingTree.open_containing(file_list[0])[0]
    return smart_add_tree(tree, file_list, recurse, action=action)


def smart_add_tree(tree, file_list, recurse=True, action=None):
    """Add files to version, optionally recursing into directories.

    This is designed more towards DWIM for humans than API simplicity.
    For the specific behaviour see the help for cmd_add().

    This calls reporter with each (path, kind, file_id) of added files.

    Returns the number of files added.
    """
    import os, errno
    from bzrlib.errors import BadFileKindError, ForbiddenFileError
    assert isinstance(recurse, bool)
    if action is None:
        action = AddAction(should_add=True)

    file_list = _prepare_file_list(file_list)
    user_list = file_list[:]
    inv = tree.read_working_inventory()
    added = []
    ignored = {}

    for f in file_list:
        rf = tree.relpath(f)
        af = tree.abspath(rf)

        try:
            kind = bzrlib.osutils.file_kind(af)
        except OSError, e:
            if hasattr(e, 'errno') and e.errno == errno.ENOENT:
                raise errors.NoSuchFile(rf)
            raise

        if not InventoryEntry.versionable_kind(kind):
            if f in user_list:
                raise BadFileKindError("cannot add %s of type %s" % (f, kind))
            else:
                warning("skipping %s (can't add file of kind '%s')", f, kind)
                continue

        mutter("smart add of %r, abs=%r", f, af)
        
        if is_control_file(af):
            raise ForbiddenFileError('cannot add control file %s' % f)
            
        versioned = (inv.path2id(rf) != None)

        if kind == 'directory':
            try:
                sub_branch = WorkingTree(af)
                sub_tree = True
            except NotBranchError:
                sub_tree = False
            except errors.UnsupportedFormatError:
                sub_tree = True
        else:
            sub_tree = False

        if rf == '':
            mutter("tree root doesn't need to be added")
            sub_tree = False
        elif versioned:
            mutter("%r is already versioned", f)
        elif sub_tree:
            mutter("%r is a bzr tree", f)
        else:
            added.extend(__add_one(tree, inv, rf, kind, action))

        if kind == 'directory' and recurse and not sub_tree:
            for subf in os.listdir(af):
                subp = bzrlib.osutils.pathjoin(rf, subf)
                if subf == bzrlib.BZRDIR:
                    mutter("skip control directory %r", subp)
                else:
                    ignore_glob = tree.is_ignored(subp)
                    if ignore_glob is not None:
                        mutter("skip ignored sub-file %r", subp)
                        if ignore_glob not in ignored:
                            ignored[ignore_glob] = []
                        ignored[ignore_glob].append(subp)
                    else:
                        mutter("queue to add sub-file %r", subp)
                        file_list.append(tree.abspath(subp))


    mutter('added %d entries', len(added))
    
    if len(added) > 0:
        tree._write_inventory(inv)

    return added, ignored


def __add_one(tree, inv, path, kind, action):
    """Add a file or directory, automatically add unversioned parents."""

    # Nothing to do if path is already versioned.
    # This is safe from infinite recursion because the tree root is
    # always versioned.
    if inv.path2id(path) != None:
        return []

    # add parent
    added = __add_one(tree, inv, dirname(path), 'directory', action)
    action(inv, path, kind)

    return added + [path]

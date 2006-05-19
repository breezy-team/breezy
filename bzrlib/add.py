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

from os.path import dirname

import bzrlib.errors as errors
from bzrlib.inventory import InventoryEntry
from bzrlib.trace import mutter, note, warning
from bzrlib.errors import NotBranchError
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
    import sys
    if sys.platform == 'win32':
        file_list = glob_expand_for_win32(file_list)
    if not file_list:
        file_list = [u'.']
    file_list = list(file_list)
    return file_list


def add_action_null(inv, parent_ie, path, kind):
    """Absorb add actions and do nothing."""
    pass


def add_action_print(inv, parent_ie, path, kind):
    """Print a line to stdout for each file that would be added."""
    print "added", bzrlib.osutils.quotefn(path)


def add_action_add(inv, parent_ie, path, kind):
    """Add each file to the given inventory. Produce no output."""
    if parent_ie is not None:
        entry = bzrlib.inventory.make_entry(
            kind, bzrlib.osutils.basename(path),  parent_ie.file_id)
        inv.add(entry)
    else:
        entry = inv.add_path(path, kind=kind)
    # mutter("added %r kind %r file_id={%s}" % (path, kind, entry.file_id))


def add_action_add_and_print(inv, parent_ie, path, kind):
    """Add each file to the given inventory, and print a line to stdout."""
    add_action_add(inv, parent_ie, path, kind)
    add_action_print(inv, parent_ie, path, kind)


def smart_add(file_list, recurse=True, action=add_action_add):
    """Add files to version, optionally recursing into directories.

    This is designed more towards DWIM for humans than API simplicity.
    For the specific behaviour see the help for cmd_add().

    Returns the number of files added.
    """
    file_list = _prepare_file_list(file_list)
    tree = WorkingTree.open_containing(file_list[0])[0]
    return smart_add_tree(tree, file_list, recurse, action)


def smart_add_tree(tree, file_list, recurse=True, action=add_action_add):
    """Add files to version, optionally recursing into directories.

    This is designed more towards DWIM for humans than API simplicity.
    For the specific behaviour see the help for cmd_add().

    This calls reporter with each (path, kind, file_id) of added files.

    Returns the number of files added.
    """
    import os, errno
    from bzrlib.errors import BadFileKindError, ForbiddenFileError
    assert isinstance(recurse, bool)
    
    orig_list = file_list
    file_list = _prepare_file_list(file_list)
    mutter("smart add of %r, originally %r", file_list, orig_list)
    inv = tree.read_working_inventory()
    added = []
    ignored = {}
    user_files = list(file_list)
    file_list = []

    # validate user file paths and convert all paths to tree 
    # relative : its cheaper to make a tree relative path an abspath
    # than to convert an abspath to tree relative.
    for filepath in user_files:
        rf = tree.relpath(filepath)
        file_list.append((rf, None))
        # validate user parameters. Our recursive code avoids adding new files
        # that need such validation 
        if tree.is_control_filename(rf):
            raise ForbiddenFileError('cannot add control file %s' % filepath)

    user_files = set([path for path, parent_ie in file_list])
        
    for filepath, parent_ie in file_list:
        # filepath is tree-relative
        abspath = tree.abspath(filepath)

        # find the kind of the path being added. This is not
        # currently determined when we list directories 
        # recursively, but in theory we can determine while 
        # doing the directory listing on *some* platformans.
        # TODO: a safe, portable, clean interface which will 
        # be faster than os.listdir() + stat. Specifically,
        # readdir - dirent.d_type supplies the file type when
        # it is defined. (Apparently Mac OSX has the field but
        # does not fill it in ?!) Robert C, Martin P.
        try:
            kind = bzrlib.osutils.file_kind(abspath)
        except OSError, e:
            if hasattr(e, 'errno') and e.errno == errno.ENOENT:
                raise errors.NoSuchFile(abspath)
            raise

        # we need to call this to determine the inventory kind to create.
        if not InventoryEntry.versionable_kind(kind):
            if filepath in user_files:
                raise BadFileKindError("cannot add %s of type %s" % (abspath, kind))
            else:
                warning("skipping %s (can't add file of kind '%s')", abspath, kind)
                continue

        if parent_ie is not None:
            versioned = bzrlib.osutils.basename(filepath) in parent_ie.children
        else:
            # without the parent ie, use the relatively slower inventory 
            # probing method
            versioned = inv.has_filename(filepath)

        if kind == 'directory':
            try:
                sub_branch = bzrlib.bzrdir.BzrDir.open(abspath)
                sub_tree = True
            except NotBranchError:
                sub_tree = False
            except errors.UnsupportedFormatError:
                sub_tree = True
        else:
            sub_tree = False

        if filepath == '':
            # mutter("tree root doesn't need to be added")
            sub_tree = False
        elif versioned:
            pass
            # mutter("%r is already versioned", abspath)
        elif sub_tree:
            mutter("%r is a nested bzr tree", abspath)
        else:
            added.extend(__add_one(tree, inv, parent_ie, filepath, kind, action))

        if kind == 'directory' and recurse and not sub_tree:
            try:
                if parent_ie is not None:
                    # must be present:
                    this_ie = parent_ie.children[bzrlib.osutils.basename(filepath)]
                else:
                    # without the parent ie, use the relatively slower inventory 
                    # probing method
                    this_id = inv.path2id(filepath)
                    if this_id is None:
                        this_ie = None
                    else:
                        this_ie = inv[this_id]
            except KeyError:
                this_ie = None

            for subf in os.listdir(abspath):
                # here we could use TreeDirectory rather than 
                # string concatenation.
                subp = bzrlib.osutils.pathjoin(filepath, subf)
                # TODO: is_control_filename is very slow. Make it faster. 
                # TreeDirectory.is_control_filename could also make this 
                # faster - its impossible for a non root dir to have a 
                # control file.
                if tree.is_control_filename(subp):
                    mutter("skip control directory %r", subp)
                else:
                    # ignore while selecting files - if we globbed in the
                    # outer loop we would ignore user files.
                    ignore_glob = tree.is_ignored(subp)
                    if ignore_glob is not None:
                        # mutter("skip ignored sub-file %r", subp)
                        if ignore_glob not in ignored:
                            ignored[ignore_glob] = []
                        ignored[ignore_glob].append(subp)
                    else:
                        #mutter("queue to add sub-file %r", subp)
                        file_list.append((subp, this_ie))

    if len(added) > 0:
        tree._write_inventory(inv)
    return added, ignored


def __add_one(tree, inv, parent_ie, path, kind, action):
    """Add a file or directory, automatically add unversioned parents."""

    # Nothing to do if path is already versioned.
    # This is safe from infinite recursion because the tree root is
    # always versioned.
    if parent_ie is not None:
        # we have a parent ie already
        added = []
    else:
        # slower but does not need parent_ie
        if inv.has_filename(path):
            return []
        # add parent
        added = __add_one(tree, inv, None, dirname(path), 'directory', action)
        parent_id = inv.path2id(dirname(path))
        if parent_id is not None:
            parent_ie = inv[inv.path2id(dirname(path))]
        else:
            parent_ie = None
    action(inv, parent_ie, path, kind)

    return added + [path]

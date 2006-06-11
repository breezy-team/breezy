# Copyright (C) 2005 Canonical Ltd
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

import sys
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
    if sys.platform == 'win32':
        file_list = glob_expand_for_win32(file_list)
    if not file_list:
        file_list = [u'.']
    file_list = list(file_list)
    return file_list


class AddAction(object):
    """A class which defines what action to take when adding a file."""

    def __init__(self, to_file=None, should_print=None):
        self._to_file = to_file
        if to_file is None:
            self._to_file = sys.stdout
        self.should_print = False
        if should_print is not None:
            self.should_print = should_print

    def __call__(self, inv, parent_ie, path, kind, _quote=bzrlib.osutils.quotefn):
        """Add path to inventory.

        The default action does nothing.

        :param inv: The inventory we are working with.
        :param path: The FastPath being added
        :param kind: The kind of the object being added.
        """
        if not self.should_print:
            return
        self._to_file.write('added %s\n' % _quote(path.raw_path))


# TODO: jam 20050105 These could be used for compatibility
#       however, they bind against the current stdout, not the
#       one which exists at the time they are called, so they
#       don't work for the test suite.
# deprecated
add_action_add = AddAction()
add_action_null = add_action_add
add_action_add_and_print = AddAction(should_print=True)
add_action_print = add_action_add_and_print


def smart_add(file_list, recurse=True, action=None, save=True):
    """Add files to version, optionally recursing into directories.

    This is designed more towards DWIM for humans than API simplicity.
    For the specific behaviour see the help for cmd_add().

    Returns the number of files added.
    Please see smart_add_tree for more detail.
    """
    file_list = _prepare_file_list(file_list)
    tree = WorkingTree.open_containing(file_list[0])[0]
    return smart_add_tree(tree, file_list, recurse, action=action)


class FastPath(object):
    """A path object with fast accessors for things like basename."""

    __slots__ = ['raw_path', 'base_path']

    def __init__(self, path, base_path=None):
        """Construct a FastPath from path."""
        if base_path is None:
            self.base_path = bzrlib.osutils.basename(path)
        else:
            self.base_path = base_path
        self.raw_path = path


def smart_add_tree(tree, file_list, recurse=True, action=None, save=True):
    """Add files to version, optionally recursing into directories.

    This is designed more towards DWIM for humans than API simplicity.
    For the specific behaviour see the help for cmd_add().

    This calls reporter with each (path, kind, file_id) of added files.

    Returns the number of files added.
    
    :param save: Save the inventory after completing the adds. If False this
    provides dry-run functionality by doing the add and not saving the
    inventory.  Note that the modified inventory is left in place, allowing 
    further dry-run tasks to take place. To restore the original inventory
    call tree.read_working_inventory().
    """
    import os, errno
    from bzrlib.errors import BadFileKindError, ForbiddenFileError
    assert isinstance(recurse, bool)
    if action is None:
        action = AddAction()
    
    prepared_list = _prepare_file_list(file_list)
    mutter("smart add of %r, originally %r", prepared_list, file_list)
    inv = tree.read_working_inventory()
    added = []
    ignored = {}
    dirs_to_add = []
    user_dirs = set()

    # validate user file paths and convert all paths to tree 
    # relative : its cheaper to make a tree relative path an abspath
    # than to convert an abspath to tree relative.
    for filepath in prepared_list:
        rf = FastPath(tree.relpath(filepath))
        # validate user parameters. Our recursive code avoids adding new files
        # that need such validation 
        if tree.is_control_filename(rf.raw_path):
            raise ForbiddenFileError('cannot add control file %s' % filepath)
        
        abspath = tree.abspath(rf.raw_path)
        kind = bzrlib.osutils.file_kind(abspath)
        if kind == 'directory':
            # schedule the dir for scanning
            user_dirs.add(rf.raw_path)
        else:
            if not InventoryEntry.versionable_kind(kind):
                raise BadFileKindError("cannot add %s of type %s" % (abspath, kind))
        # ensure the named path is added, so that ignore rules in the later directory
        # walk dont skip it.
        # we dont have a parent ie known yet.: use the relatively slower inventory 
        # probing method
        versioned = inv.has_filename(rf.raw_path)
        if versioned:
            continue
        added.extend(__add_one_and_parent(tree, inv, None, rf, kind, action))

    if not recurse:
        # no need to walk any directories at all.
        if len(added) > 0 and save:
            tree._write_inventory(inv)
        return added, ignored

    # only walk the minimal parents needed: we have user_dirs to override
    # ignores.
    prev_dir = None
    for path in sorted(user_dirs):
        if (prev_dir is None or not
            bzrlib.osutils.is_inside_or_parent_of_any([prev_dir], path)):
            dirs_to_add.append((rf, None))
        prev_dir = path

    # this will eventually be *just* directories, right now it starts off with 
    # just directories.
    for directory, parent_ie in dirs_to_add:
        # directory is tree-relative
        abspath = tree.abspath(directory.raw_path)

        # get the contents of this directory.

        # find the kind of the path being added.
        kind = bzrlib.osutils.file_kind(abspath)

        if not InventoryEntry.versionable_kind(kind):
            warning("skipping %s (can't add file of kind '%s')", abspath, kind)
            continue

        if parent_ie is not None:
            versioned = directory.base_path in parent_ie.children
        else:
            # without the parent ie, use the relatively slower inventory 
            # probing method
            versioned = inv.has_filename(directory.raw_path)

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

        if directory.raw_path == '':
            # mutter("tree root doesn't need to be added")
            sub_tree = False
        elif versioned:
            pass
            # mutter("%r is already versioned", abspath)
        elif sub_tree:
            mutter("%r is a nested bzr tree", abspath)
        else:
            __add_one(tree, inv, parent_ie, directory, kind, action)
            added.append(directory.raw_path)

        if kind == 'directory' and not sub_tree:
            if parent_ie is not None:
                # must be present:
                this_ie = parent_ie.children[directory.base_path]
            else:
                # without the parent ie, use the relatively slower inventory 
                # probing method
                this_id = inv.path2id(directory.raw_path)
                if this_id is None:
                    this_ie = None
                else:
                    this_ie = inv[this_id]

            for subf in os.listdir(abspath):
                # here we could use TreeDirectory rather than 
                # string concatenation.
                subp = bzrlib.osutils.pathjoin(directory.raw_path, subf)
                # TODO: is_control_filename is very slow. Make it faster. 
                # TreeDirectory.is_control_filename could also make this 
                # faster - its impossible for a non root dir to have a 
                # control file.
                if tree.is_control_filename(subp):
                    mutter("skip control directory %r", subp)
                elif subf in this_ie.children:
                    # recurse into this already versioned subdir.
                    dirs_to_add.append((FastPath(subp, subf), this_ie))
                else:
                    # user selection overrides ignoes
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
                        dirs_to_add.append((FastPath(subp, subf), this_ie))

    if len(added) > 0 and save:
        tree._write_inventory(inv)
    return added, ignored


def __add_one_and_parent(tree, inv, parent_ie, path, kind, action):
    """Add a new entry to the inventory and automatically add unversioned parents.

    :param inv: Inventory which will receive the new entry.
    :param parent_ie: Parent inventory entry if known, or None.  If
    None, the parent is looked up by name and used if present, otherwise
    it is recursively added.
    :param kind: Kind of new entry (file, directory, etc)
    :param action: callback(inv, parent_ie, path, kind); return ignored.
    :returns: A list of paths which have been added.
    """
    # Nothing to do if path is already versioned.
    # This is safe from infinite recursion because the tree root is
    # always versioned.
    if parent_ie is not None:
        # we have a parent ie already
        added = []
    else:
        # slower but does not need parent_ie
        if inv.has_filename(path.raw_path):
            return []
        # its really not there : add the parent
        # note that the dirname use leads to some extra str copying etc but as
        # there are a limited number of dirs we can be nested under, it should
        # generally find it very fast and not recurse after that.
        added = __add_one_and_parent(tree, inv, None, FastPath(dirname(path.raw_path)), 'directory', action)
        parent_id = inv.path2id(dirname(path.raw_path))
        if parent_id is None:
            parent_ie = inv[inv.path2id(dirname(path.raw_path))]
        else:
            parent_ie = inv[parent_id]
    __add_one(tree, inv, parent_ie, path, kind, action)
    return added + [path.raw_path]


def __add_one(tree, inv, parent_ie, path, kind, action):
    """Add a new entry to the inventory.

    :param inv: Inventory which will receive the new entry.
    :param parent_ie: Parent inventory entry.
    :param kind: Kind of new entry (file, directory, etc)
    :param action: callback(inv, parent_ie, path, kind); return ignored.
    :returns: None
    """
    action(inv, parent_ie, path, kind)
    entry = bzrlib.inventory.make_entry(kind, path.base_path, parent_ie.file_id)
    inv.add(entry)

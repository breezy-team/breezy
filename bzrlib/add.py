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
from bzrlib.branch import Branch
from bzrlib.osutils import quotefn

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


def add_reporter_null(path, kind, entry):
    """Absorb add reports and do nothing."""
    pass

def add_reporter_print(path, kind, entry):
    """Print a line to stdout for each file that's added."""
    print "added", quotefn(path)
    
def _prepare_file_list(file_list):
    """Prepare a file list for use by smart_add_*."""
    import sys
    if sys.platform == 'win32':
        file_list = glob_expand_for_win32(file_list)
    if not file_list:
        file_list = ['.']
    file_list = list(file_list)
    return file_list


def smart_add(file_list, recurse=True, reporter=add_reporter_null):
    """Add files to version, optionally recursing into directories.

    This is designed more towards DWIM for humans than API simplicity.
    For the specific behaviour see the help for cmd_add().

    Returns the number of files added.
    """
    file_list = _prepare_file_list(file_list)
    b = Branch.open_containing(file_list[0])[0]
    return smart_add_branch(b, file_list, recurse, reporter)

        
def smart_add_branch(branch, file_list, recurse=True, reporter=add_reporter_null):
    """Add files to version, optionally recursing into directories.

    This is designed more towards DWIM for humans than API simplicity.
    For the specific behaviour see the help for cmd_add().

    This yields a sequence of (path, kind, file_id) for added files.

    Returns the number of files added.
    """
    import os
    from bzrlib.errors import BadFileKindError, ForbiddenFileError
    import bzrlib.branch

    assert isinstance(recurse, bool)

    file_list = _prepare_file_list(file_list)
    user_list = file_list[:]
    inv = branch.read_working_inventory()
    tree = branch.working_tree()
    count = 0

    for f in file_list:
        rf = tree.relpath(f)
        af = branch.abspath(rf)

        kind = bzrlib.osutils.file_kind(af)

        if not InventoryEntry.versionable_kind(kind):
            if f in user_list:
                raise BadFileKindError("cannot add %s of type %s" % (f, kind))
            else:
                warning("skipping %s (can't add file of kind '%s')", f, kind)
                continue

        mutter("smart add of %r, abs=%r" % (f, af))
        
        if bzrlib.branch.is_control_file(af):
            raise ForbiddenFileError('cannot add control file %s' % f)
            
        versioned = (inv.path2id(rf) != None)

        if kind == 'directory':
            try:
                sub_branch = Branch.open(af)
                sub_tree = True
            except NotBranchError:
                sub_tree = False
            except errors.UnsupportedFormatError:
                sub_tree = True
        else:
            sub_tree = False

        if rf == '':
            mutter("branch root doesn't need to be added")
            sub_tree = False
        elif versioned:
            mutter("%r is already versioned" % f)
        elif sub_tree:
            mutter("%r is a bzr tree" %f)
        else:
            count += __add_one(branch, inv, rf, kind, reporter)

        if kind == 'directory' and recurse and not sub_tree:
            for subf in os.listdir(af):
                subp = os.path.join(rf, subf)
                if subf == bzrlib.BZRDIR:
                    mutter("skip control directory %r" % subp)
                elif tree.is_ignored(subp):
                    mutter("skip ignored sub-file %r" % subp)
                else:
                    mutter("queue to add sub-file %r" % subp)
                    file_list.append(branch.abspath(subp))


    mutter('added %d entries', count)
    
    if count > 0:
        branch._write_inventory(inv)

    return count

def __add_one(branch, inv, path, kind, reporter):
    """Add a file or directory, automatically add unversioned parents."""

    # Nothing to do if path is already versioned.
    # This is safe from infinite recursion because the branch root is
    # always versioned.
    if inv.path2id(path) != None:
        return 0

    # add parent
    count = __add_one(branch, inv, dirname(path), 'directory', reporter)

    entry = inv.add_path(path, kind=kind)
    mutter("added %r kind %r file_id={%s}" % (path, kind, entry.file_id))
    reporter(path, kind, entry)

    return count + 1

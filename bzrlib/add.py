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

from trace import mutter, note
from bzrlib.errors import NotBranchError
from bzrlib.branch import Branch

def glob_expand_for_win32(file_list):
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

def smart_add(file_list, verbose=True, recurse=True):
    """Add files to version, optionally recursing into directories.

    This is designed more towards DWIM for humans than API simplicity.
    For the specific behaviour see the help for cmd_add().
    """
    import os
    import sys
    from bzrlib.osutils import quotefn
    from bzrlib.errors import BadFileKindError, ForbiddenFileError
    import bzrlib.branch
    import bzrlib.osutils

    if sys.platform == 'win32':
        file_list = glob_expand_for_win32(file_list)
        
    if not file_list:
        file_list = ['.']
    
    user_list = file_list[:]
    file_list = list(file_list)
    assert not isinstance(file_list, basestring)
    b = Branch(file_list[0], find_root=True)
    inv = b.read_working_inventory()
    tree = b.working_tree()
    count = 0

    for f in file_list:
        rf = b.relpath(f)
        af = b.abspath(rf)

        kind = bzrlib.osutils.file_kind(af)

        if kind != 'file' and kind != 'directory':
            if f in user_list:
                raise BadFileKindError("cannot add %s of type %s" % (f, kind))
            else:
                print "skipping %s (can't add file of kind '%s')" % (f, kind)
                continue

        mutter("smart add of %r, abs=%r" % (f, af))
        
        if bzrlib.branch.is_control_file(af):
            raise ForbiddenFileError('cannot add control file %s' % f)
            
        versioned = (inv.path2id(rf) != None)

        if kind == 'directory':
            try:
                sub_branch = Branch(af, find_root=False)
                sub_tree = True
            except NotBranchError:
                sub_tree = False
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
            file_id = bzrlib.branch.gen_file_id(rf)
            inv.add_path(rf, kind=kind, file_id=file_id)
            mutter("added %r kind %r file_id={%s}" % (rf, kind, file_id))
            count += 1 

            print 'added', quotefn(f)

        if kind == 'directory' and recurse and not sub_tree:
            for subf in os.listdir(af):
                subp = os.path.join(rf, subf)
                if subf == bzrlib.BZRDIR:
                    mutter("skip control directory %r" % subp)
                elif tree.is_ignored(subp):
                    mutter("skip ignored sub-file %r" % subp)
                else:
                    mutter("queue to add sub-file %r" % subp)
                    file_list.append(b.abspath(subp))

    if count > 0:
        if verbose:
            note('added %d' % count)
        b._write_inventory(inv)
    else:
        print "nothing new to add"
        # should this return 1 to the shell?

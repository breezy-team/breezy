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

import types, os, sys, stat
import bzrlib

from osutils import quotefn, appendpath
from errors import bailout
from trace import mutter, note

def smart_add(file_list, verbose=False, recurse=True):
    """Add files to version, optionall recursing into directories.

    This is designed more towards DWIM for humans than API simplicity.
    For the specific behaviour see the help for cmd_add().
    """
    assert file_list
    assert not isinstance(file_list, basestring)
    b = bzrlib.branch.Branch(file_list[0], find_root=True)
    inv = b.read_working_inventory()
    tree = b.working_tree()
    count = 0

    for f in file_list:
        rf = b.relpath(f)
        af = b.abspath(rf)

        ## TODO: It's OK to add root but only in recursive mode

        bzrlib.mutter("smart add of %r" % f)
        
        if bzrlib.branch.is_control_file(af):
            bailout("cannot add control file %r" % af)

        kind = bzrlib.osutils.file_kind(f)

        if kind != 'file' and kind != 'directory':
            bailout("can't add file of kind %r" % kind)
            
        versioned = (inv.path2id(rf) != None)

        if rf == '':
            mutter("branch root doesn't need to be added")
        elif versioned:
            mutter("%r is already versioned" % f)
        else:
            file_id = bzrlib.branch.gen_file_id(rf)
            inv.add_path(rf, kind=kind, file_id=file_id)
            bzrlib.mutter("added %r kind %r file_id={%s}" % (rf, kind, file_id))
            count += 1 
            if verbose:
                bzrlib.textui.show_status('A', kind, quotefn(f))

        if kind == 'directory' and recurse:
            for subf in os.listdir(af):
                subp = appendpath(rf, subf)
                if tree.is_ignored(subp):
                    mutter("skip ignored sub-file %r" % subp)
                else:
                    mutter("queue to add sub-file %r" % (subp))
                    file_list.append(subp)

    if count > 0:
        if verbose:
            note('added %d' % count)
        b._write_inventory(inv)

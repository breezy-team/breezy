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

from osutils import quotefn
from errors import bailout

def smart_add(file_list, verbose=False, recurse=False):
    """Add files to version, optionall recursing into directories.

    This is designed more towards DWIM for humans than API simplicity.
    For the specific behaviour see the help for cmd_add().
    """
    assert file_list
    assert not isinstance(file_list, types.StringTypes)
    b = bzrlib.branch.Branch(file_list[0], find_root=True)
    inv = b.read_working_inventory()
    dirty = False

    for f in file_list:
        rf = b.relpath(f)
        af = b.abspath(rf)

        bzrlib.mutter("smart add of %r" % f)
        
        if bzrlib.branch.is_control_file(af):
            bailout("cannot add control file %r" % af)

        kind = bzrlib.osutils.file_kind(f)
        if kind == 'file':
            if inv.path2id(rf):
                bzrlib.warning("%r is already versioned" % f)
                continue
        elif kind == 'directory':
            if inv.path2id(rf):
                if not recurse:
                    bzrlib.warning("%r is already versioned" % f)
                    continue
                else:
                    # TODO: don't add, but recurse down
                    continue
        else:
            bailout("can't smart_add file kind %r" % kind)

        file_id = bzrlib.branch.gen_file_id(rf)
        inv.add_path(rf, kind=kind, file_id=file_id)
        bzrlib.mutter("added %r kind %r file_id={%s}" % (rf, kind, file_id))
        dirty = True
        if verbose:
            bzrlib.textui.show_status('A', kind, quotefn(f))

    if dirty:
        b._write_inventory(inv)

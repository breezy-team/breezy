# Copyright (C) 2004, 2005 by Martin Pool
# Copyright (C) 2005 by Canonical Ltd

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



######################################################################
# consistency checks


from sets import Set

import bzrlib
from trace import mutter
from errors import bailout


def check(branch):
    mutter('checking tree %r' % branch.base)

    mutter('checking revision history')
    last_ptr = None
    checked_revs = Set()
    for rid in branch.revision_history():
        mutter('    revision {%s}' % rid)
        rev = branch.get_revision(rid)
        if rev.revision_id != rid:
            bailout('wrong internal revision id in revision {%s}' % rid)
        if rev.precursor != last_ptr:
            bailout('mismatched precursor in revision {%s}' % rid)
        last_ptr = rid
        if rid in checked_revs:
            bailout('repeated revision {%s}' % rid)
        checked_revs.add(rid)

    #check_inventory()

    mutter('branch %s is OK' % branch.base)

    ## TODO: Check that previous-inventory and previous-manifest
    ## are the same as those stored in the previous changeset.

    ## TODO: Check all patches present in patch directory are
    ## mentioned in patch history; having an orphaned patch only gives
    ## a warning.

    ## TODO: Check cached data is consistent with data reconstructed
    ## from scratch.

    ## TODO: Check no control files are versioned.

    ## TODO: Check that the before-hash of each file in a later
    ## revision matches the after-hash in the previous revision to
    ## touch it.


def check_inventory():
    mutter("checking inventory file and ids...")
    seen_ids = Set()
    seen_names = Set()
    
    for l in controlfile('inventory').readlines():
        parts = l.split()
        if len(parts) != 2:
            bailout("malformed inventory line: " + `l`)
        file_id, name = parts
        
        if file_id in seen_ids:
            bailout("duplicated file id " + file_id)
        seen_ids.add(file_id)

        if name in seen_names:
            bailout("duplicated file name in inventory: " + quotefn(name))
        seen_names.add(name)
        
        if is_control_file(name):
            raise BzrError("control file %s present in inventory" % quotefn(name))

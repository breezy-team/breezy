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

        ## TODO: Check all the required fields are present on the revision.

        inv = branch.get_inventory(rev.inventory_id)
        check_inventory(branch, inv)

    mutter('branch %s is OK' % branch.base)



def check_inventory(branch, inv):
    seen_ids = Set()
    seen_names = Set()

    for path, ie in inv.iter_entries():
        if path in seen_names:
            bailout('duplicated path %r in inventory' % path)
        seen_names.add(path)
        if ie.kind == 'file':
            if not ie.text_id in branch.text_store:
                bailout('text {%s} not in text_store' % ie.text_id)
        

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

import sys

from trace import mutter
from errors import bailout
import osutils

def check(branch, progress=True):
    from bzrlib import set

    out = sys.stdout

    # TODO: factor out
    if not (hasattr(out, 'isatty') and out.isatty()):
        progress=False

    if progress:
        def p(m):
            mutter('checking ' + m)
            out.write('\rchecking: %-50.50s' % m)
            out.flush()
    else:
        def p(m):
            mutter('checking ' + m)

    p('history of %r' % branch.base)
    last_ptr = None
    checked_revs = set()
    
    history = branch.revision_history()
    revno = 0
    revcount = len(history)

    checked_texts = {}
    
    for rid in history:
        revno += 1
        p('revision %d/%d' % (revno, revcount))
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
        seen_ids = set()
        seen_names = set()

        p('revision %d/%d file ids' % (revno, revcount))
        for file_id in inv:
            if file_id in seen_ids:
                bailout('duplicated file_id {%s} in inventory for revision {%s}'
                        % (file_id, rid))
            seen_ids.add(file_id)

        i = 0
        len_inv = len(inv)
        for file_id in inv:
            i += 1
            if (i % 100) == 0:
                p('revision %d/%d file text %d/%d' % (revno, revcount, i, len_inv))

            ie = inv[file_id]

            if ie.parent_id != None:
                if ie.parent_id not in seen_ids:
                    bailout('missing parent {%s} in inventory for revision {%s}'
                            % (ie.parent_id, rid))

            if ie.kind == 'file':
                if ie.text_id in checked_texts:
                    fp = checked_texts[ie.text_id]
                else:
                    if not ie.text_id in branch.text_store:
                        bailout('text {%s} not in text_store' % ie.text_id)

                    tf = branch.text_store[ie.text_id]
                    fp = osutils.fingerprint_file(tf)
                    checked_texts[ie.text_id] = fp

                if ie.text_size != fp['size']:
                    bailout('text {%s} wrong size' % ie.text_id)
                if ie.text_sha1 != fp['sha1']:
                    bailout('text {%s} wrong sha1' % ie.text_id)
            elif ie.kind == 'directory':
                if ie.text_sha1 != None or ie.text_size != None or ie.text_id != None:
                    bailout('directory {%s} has text in revision {%s}'
                            % (file_id, rid))

        p('revision %d/%d file paths' % (revno, revcount))
        for path, ie in inv.iter_entries():
            if path in seen_names:
                bailout('duplicated path %r in inventory for revision {%s}' % (path, revid))
            seen_names.add(path)


    p('done')
    if progress:
        print 
    print 'checked %d revisions, %d file texts' % (revcount, len(checked_texts))


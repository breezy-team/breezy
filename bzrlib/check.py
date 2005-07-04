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




def check(branch):
    """Run consistency checks on a branch.

    TODO: Also check non-mainline revisions mentioned as parents.

    TODO: Check for extra files in the control directory.
    """
    from bzrlib.trace import mutter
    from bzrlib.errors import BzrCheckError
    from bzrlib.osutils import fingerprint_file
    from bzrlib.progress import ProgressBar

    branch.lock_read()

    try:
        pb = ProgressBar(show_spinner=True)
        last_rev_id = None

        missing_inventory_sha_cnt = 0
        missing_revision_sha_cnt = 0

        history = branch.revision_history()
        revno = 0
        revcount = len(history)
        mismatch_inv_id = []

        # for all texts checked, text_id -> sha1
        checked_texts = {}

        for rev_id in history:
            revno += 1
            pb.update('checking revision', revno, revcount)
            mutter('    revision {%s}' % rev_id)
            rev = branch.get_revision(rev_id)
            if rev.revision_id != rev_id:
                raise BzrCheckError('wrong internal revision id in revision {%s}'
                                    % rev_id)

            # check the previous history entry is a parent of this entry
            if rev.parents:
                if last_rev_id is None:
                    raise BzrCheckError("revision {%s} has %d parents, but is the "
                                        "start of the branch"
                                        % (rev_id, len(rev.parents)))
                for prr in rev.parents:
                    if prr.revision_id == last_rev_id:
                        break
                else:
                    raise BzrCheckError("previous revision {%s} not listed among "
                                        "parents of {%s}"
                                        % (last_rev_id, rev_id))

                for prr in rev.parents:
                    if prr.revision_sha1 is None:
                        missing_revision_sha_cnt += 1
                        continue
                    prid = prr.revision_id
                    actual_sha = branch.get_revision_sha1(prid)
                    if prr.revision_sha1 != actual_sha:
                        raise BzrCheckError("mismatched revision sha1 for "
                                            "parent {%s} of {%s}: %s vs %s"
                                            % (prid, rev_id,
                                               prr.revision_sha1, actual_sha))
            elif last_rev_id:
                raise BzrCheckError("revision {%s} has no parents listed but preceded "
                                    "by {%s}"
                                    % (rev_id, last_rev_id))

            if rev.inventory_id != rev_id:
                mismatch_inv_id.append(rev_id)

            ## TODO: Check all the required fields are present on the revision.

            if rev.inventory_sha1:
                inv_sha1 = branch.get_inventory_sha1(rev.inventory_id)
                if inv_sha1 != rev.inventory_sha1:
                    raise BzrCheckError('Inventory sha1 hash doesn\'t match'
                        ' value in revision {%s}' % rev_id)
            else:
                missing_inventory_sha_cnt += 1
                mutter("no inventory_sha1 on revision {%s}" % rev_id)

            inv = branch.get_inventory(rev.inventory_id)
            seen_ids = {}
            seen_names = {}

            ## p('revision %d/%d file ids' % (revno, revcount))
            for file_id in inv:
                if file_id in seen_ids:
                    raise BzrCheckError('duplicated file_id {%s} '
                                        'in inventory for revision {%s}'
                                        % (file_id, rev_id))
                seen_ids[file_id] = True

            i = 0
            for file_id in inv:
                i += 1
                if i & 31 == 0:
                    pb.tick()

                ie = inv[file_id]

                if ie.parent_id != None:
                    if ie.parent_id not in seen_ids:
                        raise BzrCheckError('missing parent {%s} in inventory for revision {%s}'
                                % (ie.parent_id, rev_id))

                if ie.kind == 'file':
                    if ie.text_id in checked_texts:
                        fp = checked_texts[ie.text_id]
                    else:
                        if not ie.text_id in branch.text_store:
                            raise BzrCheckError('text {%s} not in text_store' % ie.text_id)

                        tf = branch.text_store[ie.text_id]
                        fp = fingerprint_file(tf)
                        checked_texts[ie.text_id] = fp

                    if ie.text_size != fp['size']:
                        raise BzrCheckError('text {%s} wrong size' % ie.text_id)
                    if ie.text_sha1 != fp['sha1']:
                        raise BzrCheckError('text {%s} wrong sha1' % ie.text_id)
                elif ie.kind == 'directory':
                    if ie.text_sha1 != None or ie.text_size != None or ie.text_id != None:
                        raise BzrCheckError('directory {%s} has text in revision {%s}'
                                % (file_id, rev_id))

            pb.tick()
            for path, ie in inv.iter_entries():
                if path in seen_names:
                    raise BzrCheckError('duplicated path %s '
                                        'in inventory for revision {%s}'
                                        % (path, rev_id))
            seen_names[path] = True
            last_rev_id = rev_id

    finally:
        branch.unlock()

    pb.clear()

    print 'checked %d revisions, %d file texts' % (revcount, len(checked_texts))
    
    if missing_inventory_sha_cnt:
        print '%d revisions are missing inventory_sha1' % missing_inventory_sha_cnt

    if missing_revision_sha_cnt:
        print '%d parent links are missing revision_sha1' % missing_revision_sha_cnt

    if (missing_inventory_sha_cnt
        or missing_revision_sha_cnt):
        print '  (use "bzr upgrade" to fix them)'

    if mismatch_inv_id:
        print '%d revisions have mismatched inventory ids:' % len(mismatch_inv_id)
        for rev_id in mismatch_inv_id:
            print '  ', rev_id

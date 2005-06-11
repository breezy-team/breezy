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




def check(branch, update=False):
    """Run consistency checks on a branch.

    If update is True, for revisions missing certain information
    (right now this is inventory_sha1 and revision_sha1),
    update them to include the appropriate values.
    """
    import sys

    from bzrlib.trace import mutter
    from bzrlib.errors import BzrCheckError
    from bzrlib.osutils import fingerprint_file
    from bzrlib.progress import ProgressBar
    
    out = sys.stdout

    pb = ProgressBar(show_spinner=True)
    last_ptr = None
    checked_revs = {}

    missing_inventory_sha_cnt = 0
    
    history = branch.revision_history()
    revno = 0
    revcount = len(history)

    checked_texts = {}

    updated_revisions = []

    # Set to True in the case that the previous revision entry
    # was updated, since this will affect future revision entries
    updated_previous_revision = False
    
    for rid in history:
        revno += 1
        pb.update('checking revision', revno, revcount)
        mutter('    revision {%s}' % rid)
        rev = branch.get_revision(rid)
        if rev.revision_id != rid:
            raise BzrCheckError('wrong internal revision id in revision {%s}' % rid)
        if rev.precursor != last_ptr:
            raise BzrCheckError('mismatched precursor in revision {%s}' % rid)
        last_ptr = rid
        if rid in checked_revs:
            raise BzrCheckError('repeated revision {%s}' % rid)
        checked_revs[rid] = True

        ## TODO: Check all the required fields are present on the revision.

        updated = False
        if rev.inventory_sha1:
            #mutter('    checking inventory hash {%s}' % rev.inventory_sha1)
            inv_sha1 = branch.get_inventory_sha1(rev.inventory_id)
            if inv_sha1 != rev.inventory_sha1:
                raise BzrCheckError('Inventory sha1 hash doesn\'t match'
                    ' value in revision {%s}' % rid)
        elif update:
            inv_sha1 = branch.get_inventory_sha1(rev.inventory_id)
            rev.inventory_sha1 = inv_sha1
            updated = True
        else:
            missing_inventory_sha_cnt += 1
            mutter("no inventory_sha1 on revision {%s}" % rid)

        if rev.precursor:
            if rev.precursor_sha1:
                precursor_sha1 = branch.get_revision_sha1(rev.precursor)
                if updated_previous_revision: 
                    # we don't expect the hashes to match, because
                    # we had to modify the previous revision_history entry.
                    rev.precursor_sha1 = precursor_sha1
                    updated = True
                else:
                    #mutter('    checking precursor hash {%s}' % rev.precursor_sha1)
                    if rev.precursor_sha1 != precursor_sha1:
                        raise BzrCheckError('Precursor sha1 hash doesn\'t match'
                            ' value in revision {%s}' % rid)
            elif update:
                precursor_sha1 = branch.get_revision_sha1(rev.precursor)
                rev.precursor_sha1 = precursor_sha1
                updated = True

        if updated:
            updated_previous_revision = True
            # We had to update this revision entries hashes
            # Now we need to write out a new value
            # This is a little bit invasive, since we are *rewriting* a
            # revision entry. I'm not supremely happy about it, but
            # there should be *some* way of making old entries have
            # the full meta information.
            import tempfile, os, errno
            rev_tmp = tempfile.TemporaryFile()
            rev.write_xml(rev_tmp)
            rev_tmp.seek(0)

            tmpfd, tmp_path = tempfile.mkstemp(prefix=rid, suffix='.gz',
                dir=branch.controlfilename('revision-store'))
            os.close(tmpfd)
            def special_rename(p1, p2):
                if sys.platform == 'win32':
                    try:
                        os.remove(p2)
                    except OSError, e:
                        if e.errno != e.ENOENT:
                            raise
                os.rename(p1, p2)

            try:
                # TODO: We may need to handle the case where the old revision
                # entry was not compressed (and thus did not end with .gz)

                # Remove the old revision entry out of the way
                rev_path = branch.controlfilename(['revision-store', rid+'.gz'])
                special_rename(rev_path, tmp_path)
                branch.revision_store.add(rev_tmp, rid) # Add the new one
                os.remove(tmp_path) # Remove the old name
                mutter('    Updated revision entry {%s}' % rid)
            except:
                # On any exception, restore the old entry
                special_rename(tmp_path, rev_path)
                raise
            rev_tmp.close()
            updated_revisions.append(rid)
        else:
            updated_previous_revision = False
            
        inv = branch.get_inventory(rev.inventory_id)
        seen_ids = {}
        seen_names = {}

        ## p('revision %d/%d file ids' % (revno, revcount))
        for file_id in inv:
            if file_id in seen_ids:
                raise BzrCheckError('duplicated file_id {%s} '
                                    'in inventory for revision {%s}'
                                    % (file_id, rid))
            seen_ids[file_id] = True

        i = 0
        len_inv = len(inv)
        for file_id in inv:
            i += 1
            if i & 31 == 0:
                pb.tick()

            ie = inv[file_id]

            if ie.parent_id != None:
                if ie.parent_id not in seen_ids:
                    raise BzrCheckError('missing parent {%s} in inventory for revision {%s}'
                            % (ie.parent_id, rid))

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
                            % (file_id, rid))

        pb.tick()
        for path, ie in inv.iter_entries():
            if path in seen_names:
                raise BzrCheckError('duplicated path %r '
                                    'in inventory for revision {%s}'
                                    % (path, revid))
            seen_names[path] = True


    pb.clear()

    print 'checked %d revisions, %d file texts' % (revcount, len(checked_texts))
    if updated_revisions:
        print '%d revisions updated to current format' % len(updated_revisions)
    if missing_inventory_sha_cnt:
        print '%d revisions are missing inventory_sha1' % missing_inventory_sha_cnt
        print '  (use bzr check --update to fix them)'

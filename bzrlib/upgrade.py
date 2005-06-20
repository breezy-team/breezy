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




def upgrade(branch):
    """
    Upgrade branch to current format.

    This causes objects to be rewritten into the current format.

    If they change, their SHA-1 will of course change, which might
    break any later signatures, or backreferences that check the
    SHA-1.
    """
    import sys

    from bzrlib.trace import mutter
    from bzrlib.errors import BzrCheckError
    from bzrlib.progress import ProgressBar

    branch.lock_write()

    try:
        pb = ProgressBar(show_spinner=True)
        last_ptr = None
        checked_revs = {}

        history = branch.revision_history()
        revno = 0
        revcount = len(history)

        updated_revisions = []

        # Set to True in the case that the previous revision entry
        # was updated, since this will affect future revision entries
        updated_previous_revision = False

        for rid in history:
            revno += 1
            pb.update('upgrading revision', revno, revcount)
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
            else:
                inv_sha1 = branch.get_inventory_sha1(rev.inventory_id)
                rev.inventory_sha1 = inv_sha1
                updated = True

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
                else:
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
                            if e.errno != errno.ENOENT:
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

    finally:
        branch.unlock()

    pb.clear()

    if updated_revisions:
        print '%d revisions updated to current format' % len(updated_revisions)

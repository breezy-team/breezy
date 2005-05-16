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



def commit(branch, message, timestamp=None, timezone=None,
           committer=None,
           verbose=True,
           specific_files=None,
           rev_id=None):
    """Commit working copy as a new revision.

    The basic approach is to add all the file texts into the
    store, then the inventory, then make a new revision pointing
    to that inventory and store that.

    This is not quite safe if the working copy changes during the
    commit; for the moment that is simply not allowed.  A better
    approach is to make a temporary copy of the files before
    computing their hashes, and then add those hashes in turn to
    the inventory.  This should mean at least that there are no
    broken hash pointers.  There is no way we can get a snapshot
    of the whole directory at an instant.  This would also have to
    be robust against files disappearing, moving, etc.  So the
    whole thing is a bit hard.

    timestamp -- if not None, seconds-since-epoch for a
         postdated/predated commit.

    specific_files
        If true, commit only those files.
    """

    import os, time, tempfile

    from inventory import Inventory
    from osutils import isdir, isfile, sha_string, quotefn, \
         local_time_offset, username, kind_marker, is_inside_any
    
    from branch import gen_file_id
    from errors import BzrError
    from revision import Revision
    from trace import mutter, note

    branch._need_writelock()

    ## TODO: Show branch names

    # TODO: Don't commit if there are no changes, unless forced?

    # First walk over the working inventory; and both update that
    # and also build a new revision inventory.  The revision
    # inventory needs to hold the text-id, sha1 and size of the
    # actual file versions committed in the revision.  (These are
    # not present in the working inventory.)  We also need to
    # detect missing/deleted files, and remove them from the
    # working inventory.

    work_tree = branch.working_tree()
    work_inv = work_tree.inventory
    inv = Inventory()
    basis = branch.basis_tree()
    basis_inv = basis.inventory
    missing_ids = []

    print 'looking for changes...'
    for path, entry in work_inv.iter_entries():
        ## TODO: Cope with files that have gone missing.

        ## TODO: Check that the file kind has not changed from the previous
        ## revision of this file (if any).

        entry = entry.copy()

        p = branch.abspath(path)
        file_id = entry.file_id
        mutter('commit prep file %s, id %r ' % (p, file_id))

        if specific_files and not is_inside_any(specific_files, path):
            if basis_inv.has_id(file_id):
                # carry over with previous state
                inv.add(basis_inv[file_id].copy())
            else:
                # omit this from committed inventory
                pass
            continue

        if not work_tree.has_id(file_id):
            note('deleted %s%s' % (path, kind_marker(entry.kind)))
            mutter("    file is missing, removing from inventory")
            missing_ids.append(file_id)
            continue

        inv.add(entry)

        if basis_inv.has_id(file_id):
            old_kind = basis_inv[file_id].kind
            if old_kind != entry.kind:
                raise BzrError("entry %r changed kind from %r to %r"
                        % (file_id, old_kind, entry.kind))

        if entry.kind == 'directory':
            if not isdir(p):
                raise BzrError("%s is entered as directory but not a directory"
                               % quotefn(p))
        elif entry.kind == 'file':
            if not isfile(p):
                raise BzrError("%s is entered as file but is not a file" % quotefn(p))

            new_sha1 = work_tree.get_file_sha1(file_id)

            old_ie = basis_inv.has_id(file_id) and basis_inv[file_id]
            if (old_ie
                and old_ie.text_sha1 == new_sha1):
                ## assert content == basis.get_file(file_id).read()
                entry.text_id = old_ie.text_id
                entry.text_sha1 = new_sha1
                entry.text_size = old_ie.text_size
                mutter('    unchanged from previous text_id {%s}' %
                       entry.text_id)
            else:
                content = file(p, 'rb').read()

                entry.text_sha1 = sha_string(content)
                entry.text_size = len(content)

                entry.text_id = gen_file_id(entry.name)
                branch.text_store.add(content, entry.text_id)
                mutter('    stored with text_id {%s}' % entry.text_id)
                if not old_ie:
                    note('added %s' % path)
                elif (old_ie.name == entry.name
                      and old_ie.parent_id == entry.parent_id):
                    note('modified %s' % path)
                else:
                    note('renamed %s' % path)


    for file_id in missing_ids:
        # Any files that have been deleted are now removed from the
        # working inventory.  Files that were not selected for commit
        # are left as they were in the working inventory and ommitted
        # from the revision inventory.
        
        # have to do this later so we don't mess up the iterator.
        # since parents may be removed before their children we
        # have to test.

        # FIXME: There's probably a better way to do this; perhaps
        # the workingtree should know how to filter itbranch.
        if work_inv.has_id(file_id):
            del work_inv[file_id]


    if rev_id is None:
        rev_id = _gen_revision_id(time.time())
    inv_id = rev_id

    inv_tmp = tempfile.TemporaryFile()
    inv.write_xml(inv_tmp)
    inv_tmp.seek(0)
    branch.inventory_store.add(inv_tmp, inv_id)
    mutter('new inventory_id is {%s}' % inv_id)

    branch._write_inventory(work_inv)

    if timestamp == None:
        timestamp = time.time()

    if committer == None:
        committer = username()

    if timezone == None:
        timezone = local_time_offset()

    mutter("building commit log message")
    rev = Revision(timestamp=timestamp,
                   timezone=timezone,
                   committer=committer,
                   precursor = branch.last_patch(),
                   message = message,
                   inventory_id=inv_id,
                   revision_id=rev_id)

    rev_tmp = tempfile.TemporaryFile()
    rev.write_xml(rev_tmp)
    rev_tmp.seek(0)
    branch.revision_store.add(rev_tmp, rev_id)
    mutter("new revision_id is {%s}" % rev_id)

    ## XXX: Everything up to here can simply be orphaned if we abort
    ## the commit; it will leave junk files behind but that doesn't
    ## matter.

    ## TODO: Read back the just-generated changeset, and make sure it
    ## applies and recreates the right state.

    ## TODO: Also calculate and store the inventory SHA1
    mutter("committing patch r%d" % (branch.revno() + 1))


    branch.append_revision(rev_id)

    note("commited r%d" % branch.revno())



def _gen_revision_id(when):
    """Return new revision-id."""
    from binascii import hexlify
    from osutils import rand_bytes, compact_date, user_email

    s = '%s-%s-' % (user_email(), compact_date(when))
    s += hexlify(rand_bytes(8))
    return s



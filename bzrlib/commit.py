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



# FIXME: "bzr commit doc/format" commits doc/format.txt!

def commit(branch, message,
           timestamp=None,
           timezone=None,
           committer=None,
           verbose=True,
           specific_files=None,
           rev_id=None,
           allow_pointless=True):
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

    This raises PointlessCommit if there are no changes, no new merges,
    and allow_pointless  is false.

    timestamp -- if not None, seconds-since-epoch for a
         postdated/predated commit.

    specific_files
        If true, commit only those files.

    rev_id
        If set, use this as the new revision id.
        Useful for test or import commands that need to tightly
        control what revisions are assigned.  If you duplicate
        a revision id that exists elsewhere it is your own fault.
        If null (default), a time/random revision id is generated.
    """

    import time, tempfile

    from bzrlib.osutils import local_time_offset, username
    from bzrlib.branch import gen_file_id
    from bzrlib.errors import BzrError, PointlessCommit
    from bzrlib.revision import Revision, RevisionReference
    from bzrlib.trace import mutter, note
    from bzrlib.xml import pack_xml

    branch.lock_write()

    try:
        # First walk over the working inventory; and both update that
        # and also build a new revision inventory.  The revision
        # inventory needs to hold the text-id, sha1 and size of the
        # actual file versions committed in the revision.  (These are
        # not present in the working inventory.)  We also need to
        # detect missing/deleted files, and remove them from the
        # working inventory.

        work_tree = branch.working_tree()
        work_inv = work_tree.inventory
        basis = branch.basis_tree()
        basis_inv = basis.inventory

        if verbose:
            note('looking for changes...')

        pending_merges = branch.pending_merges()

        missing_ids, new_inv, any_changes = \
                     _gather_commit(branch,
                                    work_tree,
                                    work_inv,
                                    basis_inv,
                                    specific_files,
                                    verbose)

        if not (any_changes or allow_pointless or pending_merges):
            raise PointlessCommit()

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
        pack_xml(new_inv, inv_tmp)
        inv_tmp.seek(0)
        branch.inventory_store.add(inv_tmp, inv_id)
        mutter('new inventory_id is {%s}' % inv_id)

        # We could also just sha hash the inv_tmp file
        # however, in the case that branch.inventory_store.add()
        # ever actually does anything special
        inv_sha1 = branch.get_inventory_sha1(inv_id)

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
                       message = message,
                       inventory_id=inv_id,
                       inventory_sha1=inv_sha1,
                       revision_id=rev_id)

        rev.parents = []
        precursor_id = branch.last_patch()
        if precursor_id:
            precursor_sha1 = branch.get_revision_sha1(precursor_id)
            rev.parents.append(RevisionReference(precursor_id, precursor_sha1))
        for merge_rev in pending_merges:
            rev.parents.append(RevisionReference(merge_rev))            

        rev_tmp = tempfile.TemporaryFile()
        pack_xml(rev, rev_tmp)
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

        branch.set_pending_merges([])

        if verbose:
            note("commited r%d" % branch.revno())
    finally:
        branch.unlock()



def _gen_revision_id(when):
    """Return new revision-id."""
    from binascii import hexlify
    from osutils import rand_bytes, compact_date, user_email

    s = '%s-%s-' % (user_email(), compact_date(when))
    s += hexlify(rand_bytes(8))
    return s


def _gather_commit(branch, work_tree, work_inv, basis_inv, specific_files,
                   verbose):
    """Build inventory preparatory to commit.

    Returns missing_ids, new_inv, any_changes.

    This adds any changed files into the text store, and sets their
    test-id, sha and size in the returned inventory appropriately.

    missing_ids
        Modified to hold a list of files that have been deleted from
        the working directory; these should be removed from the
        working inventory.
    """
    from bzrlib.inventory import Inventory
    from osutils import isdir, isfile, sha_string, quotefn, \
         local_time_offset, username, kind_marker, is_inside_any
    
    from branch import gen_file_id
    from errors import BzrError
    from revision import Revision
    from bzrlib.trace import mutter, note

    any_changes = False
    inv = Inventory()
    missing_ids = []
    
    for path, entry in work_inv.iter_entries():
        ## TODO: Check that the file kind has not changed from the previous
        ## revision of this file (if any).

        p = branch.abspath(path)
        file_id = entry.file_id
        mutter('commit prep file %s, id %r ' % (p, file_id))

        if specific_files and not is_inside_any(specific_files, path):
            mutter('  skipping file excluded from commit')
            if basis_inv.has_id(file_id):
                # carry over with previous state
                inv.add(basis_inv[file_id].copy())
            else:
                # omit this from committed inventory
                pass
            continue

        if not work_tree.has_id(file_id):
            if verbose:
                print('deleted %s%s' % (path, kind_marker(entry.kind)))
                any_changes = True
            mutter("    file is missing, removing from inventory")
            missing_ids.append(file_id)
            continue

        # this is present in the new inventory; may be new, modified or
        # unchanged.
        old_ie = basis_inv.has_id(file_id) and basis_inv[file_id]
        
        entry = entry.copy()
        inv.add(entry)

        if old_ie:
            old_kind = old_ie.kind
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

                # calculate the sha again, just in case the file contents
                # changed since we updated the cache
                entry.text_sha1 = sha_string(content)
                entry.text_size = len(content)

                entry.text_id = gen_file_id(entry.name)
                branch.text_store.add(content, entry.text_id)
                mutter('    stored with text_id {%s}' % entry.text_id)

        if verbose:
            marked = path + kind_marker(entry.kind)
            if not old_ie:
                print 'added', marked
                any_changes = True
            elif old_ie == entry:
                pass                    # unchanged
            elif (old_ie.name == entry.name
                  and old_ie.parent_id == entry.parent_id):
                print 'modified', marked
                any_changes = True
            else:
                print 'renamed', marked
                any_changes = True
                        
    return missing_ids, inv, any_changes



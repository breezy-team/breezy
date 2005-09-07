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


## XXX: Everything up to here can simply be orphaned if we abort
## the commit; it will leave junk files behind but that doesn't
## matter.

## TODO: Read back the just-generated changeset, and make sure it
## applies and recreates the right state.


import os
import sys
import time
import tempfile
from binascii import hexlify

from bzrlib.osutils import (local_time_offset, username,
                            rand_bytes, compact_date, user_email,
                            kind_marker, is_inside_any, quotefn,
                            sha_string, sha_file, isdir, isfile)
from bzrlib.branch import gen_file_id
from bzrlib.errors import BzrError, PointlessCommit
from bzrlib.revision import Revision, RevisionReference
from bzrlib.trace import mutter, note
from bzrlib.xml5 import serializer_v5
from bzrlib.inventory import Inventory
from bzrlib.delta import compare_trees
from bzrlib.weave import Weave
from bzrlib.weavefile import read_weave, write_weave_v5
from bzrlib.atomicfile import AtomicFile


class NullCommitReporter(object):
    """I report on progress of a commit."""
    def added(self, path):
        pass

    def removed(self, path):
        pass

    def renamed(self, old_path, new_path):
        pass


class ReportCommitToLog(NullCommitReporter):
    def added(self, path):
        note('added %s', path)

    def removed(self, path):
        note('removed %s', path)

    def renamed(self, old_path, new_path):
        note('renamed %s => %s', old_path, new_path)


class Commit(object):
    """Task of committing a new revision.

    This is a MethodObject: it accumulates state as the commit is
    prepared, and then it is discarded.  It doesn't represent
    historical revisions, just the act of recording a new one.

            missing_ids
            Modified to hold a list of files that have been deleted from
            the working directory; these should be removed from the
            working inventory.
    """
    def __init__(self,
                 reporter=None):
        if reporter is not None:
            self.reporter = reporter
        else:
            self.reporter = NullCommitReporter()

        
    def commit(self,
               branch, message,
               timestamp=None,
               timezone=None,
               committer=None,
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

        self.branch = branch
        self.branch.lock_write()
        self.rev_id = rev_id
        self.specific_files = specific_files

        if timestamp is None:
            self.timestamp = time.time()
        else:
            self.timestamp = long(timestamp)
            
        if committer is None:
            self.committer = username(self.branch)
        else:
            assert isinstance(committer, basestring), type(committer)
            self.committer = committer

        if timezone is None:
            self.timezone = local_time_offset()
        else:
            self.timezone = int(timezone)

        assert isinstance(message, basestring), type(message)
        self.message = message

        try:
            # First walk over the working inventory; and both update that
            # and also build a new revision inventory.  The revision
            # inventory needs to hold the text-id, sha1 and size of the
            # actual file versions committed in the revision.  (These are
            # not present in the working inventory.)  We also need to
            # detect missing/deleted files, and remove them from the
            # working inventory.

            self.work_tree = self.branch.working_tree()
            self.work_inv = self.work_tree.inventory
            self.basis_tree = self.branch.basis_tree()
            self.basis_inv = self.basis_tree.inventory

            self.pending_merges = self.branch.pending_merges()

            if self.rev_id is None:
                self.rev_id = _gen_revision_id(self.branch, time.time())

            self.delta = compare_trees(self.basis_tree, self.work_tree,
                                       specific_files=self.specific_files)

            if not (self.delta.has_changed()
                    or self.allow_pointless
                    or self.pending_merges):
                raise PointlessCommit()

            self.new_inv = self.basis_inv.copy()

            self.delta.show(sys.stdout)

            self._remove_deleted()
            self._store_texts()

            self.branch._write_inventory(self.work_inv)
            self._record_inventory()

            self._make_revision()
            note('committted r%d', (self.branch.revno() + 1))
            self.branch.append_revision(rev_id)
            self.branch.set_pending_merges([])
        finally:
            self.branch.unlock()


    def _record_inventory(self):
        inv_tmp = tempfile.TemporaryFile()
        serializer_v5.write_inventory(self.new_inv, inv_tmp)
        inv_tmp.seek(0)
        self.inv_sha1 = sha_file(inv_tmp)
        inv_tmp.seek(0)
        self.branch.inventory_store.add(inv_tmp, self.rev_id)


    def _make_revision(self):
        """Record a new revision object for this commit."""
        self.rev = Revision(timestamp=self.timestamp,
                            timezone=self.timezone,
                            committer=self.committer,
                            message=self.message,
                            inventory_sha1=self.inv_sha1,
                            revision_id=self.rev_id)

        self.rev.parents = []
        precursor_id = self.branch.last_patch()
        if precursor_id:
            self.rev.parents.append(RevisionReference(precursor_id))
        for merge_rev in self.pending_merges:
            rev.parents.append(RevisionReference(merge_rev))

        rev_tmp = tempfile.TemporaryFile()
        serializer_v5.write_revision(self.rev, rev_tmp)
        rev_tmp.seek(0)
        self.branch.revision_store.add(rev_tmp, self.rev_id)
        mutter('new revision_id is {%s}', self.rev_id)


    def _remove_deleted(self):
        """Remove deleted files from the working and stored inventories."""
        for path, id, kind in self.delta.removed:
            if self.work_inv.has_id(id):
                del self.work_inv[id]
            if self.new_inv.has_id(id):
                del self.new_inv[id]


    def _store_texts(self):
        """Store new texts of modified/added files."""
        for path, id, kind in self.delta.modified:
            if kind != 'file':
                continue
            self._store_file_text(path, id)

        for path, id, kind in self.delta.added:
            if kind != 'file':
                continue
            self._store_file_text(path, id)

        for old_path, new_path, id, kind, text_modified in self.delta.renamed:
            if kind != 'file':
                continue
            if not text_modified:
                continue
            self._store_file_text(path, id)


    def _store_file_text(self, path, id):
        """Store updated text for one modified or added file."""
        # TODO: Add or update the inventory entry for this file;
        # put in the new text version
        note('store new text for {%s} in revision {%s}', id, self.rev_id)
        new_lines = self.work_tree.get_file(id).readlines()
        weave_fn = self.branch.controlfilename(['weaves', id+'.weave'])
        if os.path.exists(weave_fn):
            w = read_weave(file(weave_fn, 'rb'))
        else:
            w = Weave()
        w.add(self.rev_id, [], new_lines)
        af = AtomicFile(weave_fn)
        try:
            write_weave_v5(w, af)
            af.commit()
        finally:
            af.close()


    def _gather(self):
        """Build inventory preparatory to commit.

        This adds any changed files into the text store, and sets their
        test-id, sha and size in the returned inventory appropriately.

        """
        self.any_changes = False
        self.new_inv = Inventory(self.work_inv.root.file_id)
        self.missing_ids = []

        for path, entry in self.work_inv.iter_entries():
            ## TODO: Check that the file kind has not changed from the previous
            ## revision of this file (if any).

            p = self.branch.abspath(path)
            file_id = entry.file_id
            mutter('commit prep file %s, id %r ' % (p, file_id))

            if (self.specific_files
            and not is_inside_any(self.specific_files, path)):
                mutter('  skipping file excluded from commit')
                if self.basis_inv.has_id(file_id):
                    # carry over with previous state
                    self.new_inv.add(self.basis_inv[file_id].copy())
                else:
                    # omit this from committed inventory
                    pass
                continue

            if not self.work_tree.has_id(file_id):
                mutter("    file is missing, removing from inventory")
                self.missing_ids.append(file_id)
                continue

            # this is present in the new inventory; may be new, modified or
            # unchanged.
            old_ie = self.basis_inv.has_id(file_id) and self.basis_inv[file_id]

            entry = entry.copy()
            self.new_inv.add(entry)

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

                new_sha1 = self.work_tree.get_file_sha1(file_id)

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
                    self.branch.text_store.add(content, entry.text_id)
                    mutter('    stored with text_id {%s}' % entry.text_id)

            marked = path + kind_marker(entry.kind)
            if not old_ie:
                self.reporter.added(marked)
                self.any_changes = True
            elif old_ie == entry:
                pass                    # unchanged
            elif (old_ie.name == entry.name
                  and old_ie.parent_id == entry.parent_id):
                self.reporter.modified(marked)
                self.any_changes = True
            else:
                old_path = old_inv.id2path(file_id) + kind_marker(entry.kind)
                self.reporter.renamed(old_path, marked)
                self.any_changes = True



def _gen_revision_id(branch, when):
    """Return new revision-id."""
    s = '%s-%s-' % (user_email(branch), compact_date(when))
    s += hexlify(rand_bytes(8))
    return s



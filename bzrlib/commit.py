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


## XXX: Can we do any better about making interrupted commits change
## nothing?

## XXX: If we merged two versions of a file then we still need to
## create a new version representing that merge, even if it didn't
## change from the parent.

## TODO: Read back the just-generated changeset, and make sure it
## applies and recreates the right state.


## This is not quite safe if the working copy changes during the
## commit; for the moment that is simply not allowed.  A better
## approach is to make a temporary copy of the files before
## computing their hashes, and then add those hashes in turn to
## the inventory.  This should mean at least that there are no
## broken hash pointers.  There is no way we can get a snapshot
## of the whole directory at an instant.  This would also have to
## be robust against files disappearing, moving, etc.  So the
## whole thing is a bit hard.

## The newly committed revision is going to have a shape corresponding
## to that of the working inventory.  Files that are not in the
## working tree and that were in the predecessor are reported as
## removed -- this can include files that were either removed from the
## inventory or deleted in the working tree.  If they were only
## deleted from disk, they are removed from the working inventory.

## We then consider the remaining entries, which will be in the new
## version.  Directory entries are simply copied across.  File entries
## must be checked to see if a new version of the file should be
## recorded.  For each parent revision inventory, we check to see what
## version of the file was present.  If the file was present in at
## least one tree, and if it was the same version in all the trees,
## then we can just refer to that version.  Otherwise, a new version
## representing the merger of the file versions must be added.





import os
import sys
import time
import tempfile
import sha

from binascii import hexlify
from cStringIO import StringIO

from bzrlib.osutils import (local_time_offset, username,
                            rand_bytes, compact_date, user_email,
                            kind_marker, is_inside_any, quotefn,
                            sha_string, sha_strings, sha_file, isdir, isfile)
from bzrlib.branch import gen_file_id, INVENTORY_FILEID, ANCESTRY_FILEID
from bzrlib.errors import BzrError, PointlessCommit
from bzrlib.revision import Revision, RevisionReference
from bzrlib.trace import mutter, note
from bzrlib.xml5 import serializer_v5
from bzrlib.inventory import Inventory
from bzrlib.delta import compare_trees
from bzrlib.weave import Weave
from bzrlib.weavefile import read_weave, write_weave_v5
from bzrlib.atomicfile import AtomicFile


def commit(*args, **kwargs):
    """Commit a new revision to a branch.

    Function-style interface for convenience of old callers.

    New code should use the Commit class instead.
    """
    Commit().commit(*args, **kwargs)


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
        self.rev_id = rev_id
        self.specific_files = specific_files
        self.allow_pointless = allow_pointless

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

        self.branch.lock_write()
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

            self._gather_parents()

            if self.rev_id is None:
                self.rev_id = _gen_revision_id(self.branch, time.time())

            self._remove_deletions()

            # TODO: update hashcache
            self.delta = compare_trees(self.basis_tree, self.work_tree,
                                       specific_files=self.specific_files)

            if not (self.delta.has_changed()
                    or self.allow_pointless
                    or len(self.parents) != 1):
                raise PointlessCommit()

            self.new_inv = self.basis_inv.copy()

            ## FIXME: Don't write to stdout!
            self.delta.show(sys.stdout)

            self._remove_deleted()
            self._store_files()

            self.branch._write_inventory(self.work_inv)
            self._record_inventory()
            self._record_ancestry()

            self._make_revision()
            note('committted r%d {%s}', (self.branch.revno() + 1),
                 self.rev_id)
            self.branch.append_revision(self.rev_id)
            self.branch.set_pending_merges([])
        finally:
            self.branch.unlock()



    def _remove_deletions(self):
        """Remove deleted files from the working inventory."""
        pass



    def _record_inventory(self):
        """Store the inventory for the new revision."""
        inv_tmp = StringIO()
        serializer_v5.write_inventory(self.new_inv, inv_tmp)
        inv_tmp.seek(0)
        self.inv_sha1 = sha_string(inv_tmp.getvalue())
        inv_lines = inv_tmp.readlines()
        self.branch.weave_store.add_text(INVENTORY_FILEID, self.rev_id,
                                         inv_lines, self.parents)


    def _record_ancestry(self):
        """Append merged revision ancestry to the ancestry file."""
        if len(self.parents) > 1:
            raise NotImplementedError("sorry, can't commit merges yet")
        w = self.branch.weave_store.get_weave_or_empty(ANCESTRY_FILEID)
        if self.parents:
            lines = w.get(w.lookup(self.parents[0]))
        else:
            lines = []
        lines.append(self.rev_id + '\n')
        parent_idxs = map(w.lookup, self.parents)
        w.add(self.rev_id, parent_idxs, lines)
        self.branch.weave_store.put_weave(ANCESTRY_FILEID, w)


    def _gather_parents(self):
        pending_merges = self.branch.pending_merges()
        if pending_merges:
            raise NotImplementedError("sorry, can't commit merges to the weave format yet")
        self.parents = []
        precursor_id = self.branch.last_revision()
        if precursor_id:
            self.parents.append(precursor_id)
        self.parents += pending_merges


    def _make_revision(self):
        """Record a new revision object for this commit."""
        self.rev = Revision(timestamp=self.timestamp,
                            timezone=self.timezone,
                            committer=self.committer,
                            message=self.message,
                            inventory_sha1=self.inv_sha1,
                            revision_id=self.rev_id)
        self.rev.parents = map(RevisionReference, self.parents)
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



    def _store_files(self):
        """Store new texts of modified/added files."""
        # We must make sure that directories are added before anything
        # inside them is added.  the files within the delta report are
        # sorted by path so we know the directory will come before its
        # contents. 
        for path, file_id, kind in self.delta.added:
            if kind != 'file':
                ie = self.work_inv[file_id].copy()
                self.new_inv.add(ie)
            else:
                self._store_file_text(file_id)

        for path, file_id, kind in self.delta.modified:
            if kind != 'file':
                continue
            self._store_file_text(file_id)

        for old_path, new_path, file_id, kind, text_modified in self.delta.renamed:
            if kind != 'file':
                continue
            if not text_modified:
                continue
            self._store_file_text(file_id)


    def _store_file_text(self, file_id):
        """Store updated text for one modified or added file."""
        note('store new text for {%s} in revision {%s}',
             file_id, self.rev_id)
        new_lines = self.work_tree.get_file(file_id).readlines()
        if file_id in self.new_inv:     # was in basis inventory
            ie = self.new_inv[file_id]
            assert ie.file_id == file_id
            assert file_id in self.basis_inv
            assert self.basis_inv[file_id].kind == 'file'
            old_version = self.basis_inv[file_id].text_version
            file_parents = [old_version]
        else:                           # new in this revision
            ie = self.work_inv[file_id].copy()
            self.new_inv.add(ie)
            assert file_id not in self.basis_inv
            file_parents = []
        assert ie.kind == 'file'
        self._add_text_to_weave(file_id, new_lines, file_parents)
        # make a new inventory entry for this file, using whatever
        # it had in the working copy, plus details on the new text
        ie.text_sha1 = sha_strings(new_lines)
        ie.text_size = sum(map(len, new_lines))
        ie.text_version = self.rev_id
        ie.entry_version = self.rev_id


    def _add_text_to_weave(self, file_id, new_lines, parents):
        if file_id.startswith('__'):
            raise ValueError('illegal file-id %r for text file' % file_id)
        self.branch.weave_store.add_text(file_id, self.rev_id, new_lines, parents)


def _gen_revision_id(branch, when):
    """Return new revision-id."""
    s = '%s-%s-' % (user_email(branch), compact_date(when))
    s += hexlify(rand_bytes(8))
    return s


# Copyright (C) 2005 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


# XXX: Can we do any better about making interrupted commits change
# nothing?  Perhaps the best approach is to integrate commit of
# AtomicFiles with releasing the lock on the Branch.

# TODO: Separate 'prepare' phase where we find a list of potentially
# committed files.  We then can then pause the commit to prompt for a
# commit message, knowing the summary will be the same as what's
# actually used for the commit.  (But perhaps simpler to simply get
# the tree status, then use that for a selective commit?)

# The newly committed revision is going to have a shape corresponding
# to that of the working inventory.  Files that are not in the
# working tree and that were in the predecessor are reported as
# removed --- this can include files that were either removed from the
# inventory or deleted in the working tree.  If they were only
# deleted from disk, they are removed from the working inventory.

# We then consider the remaining entries, which will be in the new
# version.  Directory entries are simply copied across.  File entries
# must be checked to see if a new version of the file should be
# recorded.  For each parent revision inventory, we check to see what
# version of the file was present.  If the file was present in at
# least one tree, and if it was the same version in all the trees,
# then we can just refer to that version.  Otherwise, a new version
# representing the merger of the file versions must be added.

# TODO: Update hashcache before and after - or does the WorkingTree
# look after that?

# TODO: Rather than mashing together the ancestry and storing it back,
# perhaps the weave should have single method which does it all in one
# go, avoiding a lot of redundant work.

# TODO: Perhaps give a warning if one of the revisions marked as
# merged is already in the ancestry, and then don't record it as a
# distinct parent.

# TODO: If the file is newly merged but unchanged from the version it
# merges from, then it should still be reported as newly added
# relative to the basis revision.

# TODO: Do checks that the tree can be committed *before* running the 
# editor; this should include checks for a pointless commit and for 
# unknown or missing files.

# TODO: If commit fails, leave the message in a file somewhere.


import os
import re
import sys
import time
import pdb

from binascii import hexlify
from cStringIO import StringIO

from bzrlib.atomicfile import AtomicFile
from bzrlib.osutils import (local_time_offset,
                            rand_bytes, compact_date,
                            kind_marker, is_inside_any, quotefn,
                            sha_string, sha_strings, sha_file, isdir, isfile,
                            split_lines)
import bzrlib.config
from bzrlib.errors import (BzrError, PointlessCommit,
                           HistoryMissing,
                           ConflictsInTree,
                           StrictCommitFailed
                           )
import bzrlib.gpg as gpg
from bzrlib.revision import Revision
from bzrlib.testament import Testament
from bzrlib.trace import mutter, note, warning
from bzrlib.xml5 import serializer_v5
from bzrlib.inventory import Inventory, ROOT_ID
from bzrlib.weave import Weave
from bzrlib.weavefile import read_weave, write_weave_v5
from bzrlib.workingtree import WorkingTree


def commit(*args, **kwargs):
    """Commit a new revision to a branch.

    Function-style interface for convenience of old callers.

    New code should use the Commit class instead.
    """
    ## XXX: Remove this in favor of Branch.commit?
    Commit().commit(*args, **kwargs)


class NullCommitReporter(object):
    """I report on progress of a commit."""

    def snapshot_change(self, change, path):
        pass

    def completed(self, revno, rev_id):
        pass

    def deleted(self, file_id):
        pass

    def escaped(self, escape_count, message):
        pass

    def missing(self, path):
        pass


class ReportCommitToLog(NullCommitReporter):

    def snapshot_change(self, change, path):
        note("%s %s", change, path)

    def completed(self, revno, rev_id):
        note('committed r%d {%s}', revno, rev_id)
    
    def deleted(self, file_id):
        note('deleted %s', file_id)

    def escaped(self, escape_count, message):
        note("replaced %d control characters in message", escape_count)

    def missing(self, path):
        note('missing %s', path)


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
                 reporter=None,
                 config=None):
        if reporter is not None:
            self.reporter = reporter
        else:
            self.reporter = NullCommitReporter()
        if config is not None:
            self.config = config
        else:
            self.config = None
        
    def commit(self,
               branch, message,
               timestamp=None,
               timezone=None,
               committer=None,
               specific_files=None,
               rev_id=None,
               allow_pointless=True,
               strict=False,
               verbose=False,
               revprops=None):
        """Commit working copy as a new revision.

        timestamp -- if not None, seconds-since-epoch for a
             postdated/predated commit.

        specific_files -- If true, commit only those files.

        rev_id -- If set, use this as the new revision id.
            Useful for test or import commands that need to tightly
            control what revisions are assigned.  If you duplicate
            a revision id that exists elsewhere it is your own fault.
            If null (default), a time/random revision id is generated.

        allow_pointless -- If true (default), commit even if nothing
            has changed and no merges are recorded.

        strict -- If true, don't allow a commit if the working tree
            contains unknown files.

        revprops -- Properties for new revision
        """
        mutter('preparing to commit')

        self.branch = branch
        self.weave_store = branch.weave_store
        self.rev_id = rev_id
        self.specific_files = specific_files
        self.allow_pointless = allow_pointless
        self.revprops = revprops
        self.work_tree = WorkingTree(branch.base, branch)

        if strict:
            # raise an exception as soon as we find a single unknown.
            for unknown in self.work_tree.unknowns():
                raise StrictCommitFailed()

        if timestamp is None:
            self.timestamp = time.time()
        else:
            self.timestamp = long(timestamp)
            
        if self.config is None:
            self.config = bzrlib.config.BranchConfig(self.branch)

        if rev_id is None:
            self.rev_id = _gen_revision_id(self.config, self.timestamp)
        else:
            self.rev_id = rev_id

        if committer is None:
            self.committer = self.config.username()
        else:
            assert isinstance(committer, basestring), type(committer)
            self.committer = committer

        if timezone is None:
            self.timezone = local_time_offset()
        else:
            self.timezone = int(timezone)

        assert isinstance(message, basestring), type(message)
        self.message = message
        self._escape_commit_message()

        self.branch.lock_write()
        try:
            self.work_inv = self.work_tree.inventory
            self.basis_tree = self.branch.basis_tree()
            self.basis_inv = self.basis_tree.inventory

            self._gather_parents()
            if len(self.parents) > 1 and self.specific_files:
                raise NotImplementedError('selected-file commit of merges is not supported yet')
            self._check_parents_present()
            
            self._remove_deleted()
            self._populate_new_inv()
            self._store_snapshot()
            self._report_deletes()

            if not (self.allow_pointless
                    or len(self.parents) > 1
                    or self.new_inv != self.basis_inv):
                raise PointlessCommit()

            if len(list(self.work_tree.iter_conflicts()))>0:
                raise ConflictsInTree

            self._record_inventory()
            self._make_revision()
            self.branch.append_revision(self.rev_id)
            self.work_tree.set_pending_merges([])
            self.reporter.completed(self.branch.revno()+1, self.rev_id)
            if self.config.post_commit() is not None:
                hooks = self.config.post_commit().split(' ')
                # this would be nicer with twisted.python.reflect.namedAny
                for hook in hooks:
                    result = eval(hook + '(branch, rev_id)',
                                  {'branch':self.branch,
                                   'bzrlib':bzrlib,
                                   'rev_id':self.rev_id})
        finally:
            self.branch.unlock()

    def _record_inventory(self):
        """Store the inventory for the new revision."""
        inv_text = serializer_v5.write_inventory_to_string(self.new_inv)
        self.inv_sha1 = sha_string(inv_text)
        s = self.branch.control_weaves
        s.add_text('inventory', self.rev_id,
                   split_lines(inv_text), self.present_parents,
                   self.branch.get_transaction())

    def _escape_commit_message(self):
        """Replace xml-incompatible control characters."""
        # Python strings can include characters that can't be
        # represented in well-formed XML; escape characters that
        # aren't listed in the XML specification
        # (http://www.w3.org/TR/REC-xml/#NT-Char).
        if isinstance(self.message, unicode):
            char_pattern = u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]'
        else:
            # Use a regular 'str' as pattern to avoid having re.subn
            # return 'unicode' results.
            char_pattern = '[^x09\x0A\x0D\x20-\xFF]'
        self.message, escape_count = re.subn(
            char_pattern,
            lambda match: match.group(0).encode('unicode_escape'),
            self.message)
        if escape_count:
            self.reporter.escaped(escape_count, self.message)

    def _gather_parents(self):
        """Record the parents of a merge for merge detection."""
        pending_merges = self.work_tree.pending_merges()
        self.parents = []
        self.parent_invs = []
        self.present_parents = []
        precursor_id = self.branch.last_revision()
        if precursor_id:
            self.parents.append(precursor_id)
        self.parents += pending_merges
        for revision in self.parents:
            if self.branch.has_revision(revision):
                self.parent_invs.append(self.branch.get_inventory(revision))
                self.present_parents.append(revision)

    def _check_parents_present(self):
        for parent_id in self.parents:
            mutter('commit parent revision {%s}', parent_id)
            if not self.branch.has_revision(parent_id):
                if parent_id == self.branch.last_revision():
                    warning("parent is missing %r", parent_id)
                    raise HistoryMissing(self.branch, 'revision', parent_id)
                else:
                    mutter("commit will ghost revision %r", parent_id)
            
    def _make_revision(self):
        """Record a new revision object for this commit."""
        self.rev = Revision(timestamp=self.timestamp,
                            timezone=self.timezone,
                            committer=self.committer,
                            message=self.message,
                            inventory_sha1=self.inv_sha1,
                            revision_id=self.rev_id,
                            properties=self.revprops)
        self.rev.parent_ids = self.parents
        rev_tmp = StringIO()
        serializer_v5.write_revision(self.rev, rev_tmp)
        rev_tmp.seek(0)
        if self.config.signature_needed():
            plaintext = Testament(self.rev, self.new_inv).as_short_text()
            self.branch.store_revision_signature(gpg.GPGStrategy(self.config),
                                                 plaintext, self.rev_id)
        self.branch.revision_store.add(rev_tmp, self.rev_id)
        mutter('new revision_id is {%s}', self.rev_id)

    def _remove_deleted(self):
        """Remove deleted files from the working inventories.

        This is done prior to taking the working inventory as the
        basis for the new committed inventory.

        This returns true if any files
        *that existed in the basis inventory* were deleted.
        Files that were added and deleted
        in the working copy don't matter.
        """
        specific = self.specific_files
        deleted_ids = []
        for path, ie in self.work_inv.iter_entries():
            if specific and not is_inside_any(specific, path):
                continue
            if not self.work_tree.has_filename(path):
                self.reporter.missing(path)
                deleted_ids.append((path, ie.file_id))
        if deleted_ids:
            deleted_ids.sort(reverse=True)
            for path, file_id in deleted_ids:
                del self.work_inv[file_id]
            self.work_tree._write_inventory(self.work_inv)

    def _store_snapshot(self):
        """Pass over inventory and record a snapshot.

        Entries get a new revision when they are modified in 
        any way, which includes a merge with a new set of
        parents that have the same entry. 
        """
        # XXX: Need to think more here about when the user has
        # made a specific decision on a particular value -- c.f.
        # mark-merge.  
        for path, ie in self.new_inv.iter_entries():
            previous_entries = ie.find_previous_heads(
                self.parent_invs, 
                self.weave_store.get_weave_or_empty(ie.file_id,
                    self.branch.get_transaction()))
            if ie.revision is None:
                change = ie.snapshot(self.rev_id, path, previous_entries,
                                     self.work_tree, self.weave_store,
                                     self.branch.get_transaction())
            else:
                change = "unchanged"
            self.reporter.snapshot_change(change, path)

    def _populate_new_inv(self):
        """Build revision inventory.

        This creates a new empty inventory. Depending on
        which files are selected for commit, and what is present in the
        current tree, the new inventory is populated. inventory entries 
        which are candidates for modification have their revision set to
        None; inventory entries that are carried over untouched have their
        revision set to their prior value.
        """
        mutter("Selecting files for commit with filter %s", self.specific_files)
        self.new_inv = Inventory()
        for path, new_ie in self.work_inv.iter_entries():
            file_id = new_ie.file_id
            mutter('check %s {%s}', path, new_ie.file_id)
            if self.specific_files:
                if not is_inside_any(self.specific_files, path):
                    mutter('%s not selected for commit', path)
                    self._carry_entry(file_id)
                    continue
                else:
                    # this is selected, ensure its parents are too.
                    parent_id = new_ie.parent_id
                    while parent_id != ROOT_ID:
                        if not self.new_inv.has_id(parent_id):
                            ie = self._select_entry(self.work_inv[parent_id])
                            mutter('%s selected for commit because of %s',
                                   self.new_inv.id2path(parent_id), path)

                        ie = self.new_inv[parent_id]
                        if ie.revision is not None:
                            ie.revision = None
                            mutter('%s selected for commit because of %s',
                                   self.new_inv.id2path(parent_id), path)
                        parent_id = ie.parent_id
            mutter('%s selected for commit', path)
            self._select_entry(new_ie)

    def _select_entry(self, new_ie):
        """Make new_ie be considered for committing."""
        ie = new_ie.copy()
        ie.revision = None
        self.new_inv.add(ie)
        return ie

    def _carry_entry(self, file_id):
        """Carry the file unchanged from the basis revision."""
        if self.basis_inv.has_id(file_id):
            self.new_inv.add(self.basis_inv[file_id].copy())

    def _report_deletes(self):
        for file_id in self.basis_inv:
            if file_id not in self.new_inv:
                self.reporter.deleted(self.basis_inv.id2path(file_id))

def _gen_revision_id(config, when):
    """Return new revision-id."""
    s = '%s-%s-' % (config.user_email(), compact_date(when))
    s += hexlify(rand_bytes(8))
    return s

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
                            sha_file, isdir, isfile,
                            split_lines)
import bzrlib.config
import bzrlib.errors as errors
from bzrlib.errors import (BzrError, PointlessCommit,
                           HistoryMissing,
                           ConflictsInTree,
                           StrictCommitFailed
                           )
from bzrlib.revision import Revision
from bzrlib.testament import Testament
from bzrlib.trace import mutter, note, warning
from bzrlib.xml5 import serializer_v5
from bzrlib.inventory import Inventory, ROOT_ID
from bzrlib.symbol_versioning import *
from bzrlib.workingtree import WorkingTree


@deprecated_function(zero_seven)
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
        if change == 'unchanged':
            return
        note("%s %s", change, path)

    def completed(self, revno, rev_id):
        note('Committed revision %d.', revno)
    
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
               branch=DEPRECATED_PARAMETER, message=None,
               timestamp=None,
               timezone=None,
               committer=None,
               specific_files=None,
               rev_id=None,
               allow_pointless=True,
               strict=False,
               verbose=False,
               revprops=None,
               working_tree=None,
               local=False,
               reporter=None,
               config=None):
        """Commit working copy as a new revision.

        branch -- the deprecated branch to commit to. New callers should pass in 
                  working_tree instead

        message -- the commit message, a mandatory parameter

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
        :param local: Perform a local only commit.
        """
        mutter('preparing to commit')

        if deprecated_passed(branch):
            warn("Commit.commit (branch, ...): The branch parameter is "
                 "deprecated as of bzr 0.8. Please use working_tree= instead.",
                 DeprecationWarning, stacklevel=2)
            self.branch = branch
            self.work_tree = self.branch.bzrdir.open_workingtree()
        elif working_tree is None:
            raise BzrError("One of branch and working_tree must be passed into commit().")
        else:
            self.work_tree = working_tree
            self.branch = self.work_tree.branch
        if message is None:
            raise BzrError("The message keyword parameter is required for commit().")

        self.weave_store = self.branch.repository.weave_store
        self.bound_branch = None
        self.local = local
        self.master_branch = None
        self.master_locked = False
        self.rev_id = rev_id
        self.specific_files = specific_files
        self.allow_pointless = allow_pointless
        self.revprops = {}
        if revprops is not None:
            self.revprops.update(revprops)

        if reporter is None and self.reporter is None:
            self.reporter = NullCommitReporter()
        elif reporter is not None:
            self.reporter = reporter

        self.work_tree.lock_write()
        self.pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            # Cannot commit with conflicts present.
            if len(self.work_tree.conflicts())>0:
                raise ConflictsInTree

            # setup the bound branch variables as needed.
            self._check_bound_branch()

            # check for out of date working trees
            # if we are bound, then self.branch is the master branch and this
            # test is thus all we need.
            if self.work_tree.last_revision() != self.master_branch.last_revision():
                raise errors.OutOfDateTree(self.work_tree)
    
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
    
            if isinstance(message, str):
                message = message.decode(bzrlib.user_encoding)
            assert isinstance(message, unicode), type(message)
            self.message = message
            self._escape_commit_message()

            self.work_inv = self.work_tree.inventory
            self.basis_tree = self.work_tree.basis_tree()
            self.basis_inv = self.basis_tree.inventory
            # one to finish, one for rev and inventory, and one for each
            # inventory entry, and the same for the new inventory.
            # note that this estimate is too long when we do a partial tree
            # commit which excludes some new files from being considered.
            # The estimate is corrected when we populate the new inv.
            self.pb_total = len(self.basis_inv) + len(self.work_inv) + 3 - 1
            self.pb_count = 0

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

            self._update()
            self.inv_sha1 = self.branch.repository.add_inventory(
                self.rev_id,
                self.new_inv,
                self.present_parents
                )
            self._update()
            self._make_revision()
            # revision data is in the local branch now.
            
            # upload revision data to the master.
            # this will propogate merged revisions too if needed.
            if self.bound_branch:
                self.master_branch.repository.fetch(self.branch.repository,
                                                    revision_id=self.rev_id)
                # now the master has the revision data
                # 'commit' to the master first so a timeout here causes the local
                # branch to be out of date
                self.master_branch.append_revision(self.rev_id)

            # and now do the commit locally.
            self.branch.append_revision(self.rev_id)

            self.work_tree.set_pending_merges([])
            self.work_tree.set_last_revision(self.rev_id)
            # now the work tree is up to date with the branch
            
            self.reporter.completed(self.branch.revno(), self.rev_id)
            if self.config.post_commit() is not None:
                hooks = self.config.post_commit().split(' ')
                # this would be nicer with twisted.python.reflect.namedAny
                for hook in hooks:
                    result = eval(hook + '(branch, rev_id)',
                                  {'branch':self.branch,
                                   'bzrlib':bzrlib,
                                   'rev_id':self.rev_id})
            self._update()
        finally:
            self._cleanup()

    def _check_bound_branch(self):
        """Check to see if the local branch is bound.

        If it is bound, then most of the commit will actually be
        done using the remote branch as the target branch.
        Only at the end will the local branch be updated.
        """
        if self.local and not self.branch.get_bound_location():
            raise errors.LocalRequiresBoundBranch()

        if not self.local:
            self.master_branch = self.branch.get_master_branch()

        if not self.master_branch:
            # make this branch the reference branch for out of date checks.
            self.master_branch = self.branch
            return

        # If the master branch is bound, we must fail
        master_bound_location = self.master_branch.get_bound_location()
        if master_bound_location:
            raise errors.CommitToDoubleBoundBranch(self.branch,
                    self.master_branch, master_bound_location)

        # TODO: jam 20051230 We could automatically push local
        #       commits to the remote branch if they would fit.
        #       But for now, just require remote to be identical
        #       to local.
        
        # Make sure the local branch is identical to the master
        master_rh = self.master_branch.revision_history()
        local_rh = self.branch.revision_history()
        if local_rh != master_rh:
            raise errors.BoundBranchOutOfDate(self.branch,
                    self.master_branch)

        # Now things are ready to change the master branch
        # so grab the lock
        self.bound_branch = self.branch
        self.master_branch.lock_write()
        self.master_locked = True
####        
####        # Check to see if we have any pending merges. If we do
####        # those need to be pushed into the master branch
####        pending_merges = self.work_tree.pending_merges()
####        if pending_merges:
####            for revision_id in pending_merges:
####                self.master_branch.repository.fetch(self.bound_branch.repository,
####                                                    revision_id=revision_id)

    def _cleanup(self):
        """Cleanup any open locks, progress bars etc."""
        cleanups = [self._cleanup_bound_branch,
                    self.work_tree.unlock,
                    self.pb.finished]
        found_exception = None
        for cleanup in cleanups:
            try:
                cleanup()
            # we want every cleanup to run no matter what.
            # so we have a catchall here, but we will raise the
            # last encountered exception up the stack: and
            # typically this will be useful enough.
            except Exception, e:
                found_exception = e
        if found_exception is not None: 
            # dont do a plan raise, because the last exception may have been
            # trashed, e is our sure-to-work exception even though it loses the
            # full traceback. XXX: RBC 20060421 perhaps we could check the
            # exc_info and if its the same one do a plain raise otherwise 
            # 'raise e' as we do now.
            raise e

    def _cleanup_bound_branch(self):
        """Executed at the end of a try/finally to cleanup a bound branch.

        If the branch wasn't bound, this is a no-op.
        If it was, it resents self.branch to the local branch, instead
        of being the master.
        """
        if not self.bound_branch:
            return
        if self.master_locked:
            self.master_branch.unlock()

    def _escape_commit_message(self):
        """Replace xml-incompatible control characters."""
        # FIXME: RBC 20060419 this should be done by the revision
        # serialiser not by commit. Then we can also add an unescaper
        # in the deserializer and start roundtripping revision messages
        # precisely. See repository_implementations/test_repository.py
        
        # Python strings can include characters that can't be
        # represented in well-formed XML; escape characters that
        # aren't listed in the XML specification
        # (http://www.w3.org/TR/REC-xml/#NT-Char).
        self.message, escape_count = re.subn(
            u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
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
            if self.branch.repository.has_revision(revision):
                inventory = self.branch.repository.get_inventory(revision)
                self.parent_invs.append(inventory)
                self.present_parents.append(revision)

    def _check_parents_present(self):
        for parent_id in self.parents:
            mutter('commit parent revision {%s}', parent_id)
            if not self.branch.repository.has_revision(parent_id):
                if parent_id == self.branch.last_revision():
                    warning("parent is missing %r", parent_id)
                    raise HistoryMissing(self.branch, 'revision', parent_id)
                else:
                    mutter("commit will ghost revision %r", parent_id)
            
    def _make_revision(self):
        """Record a new revision object for this commit."""
        rev = Revision(timestamp=self.timestamp,
                       timezone=self.timezone,
                       committer=self.committer,
                       message=self.message,
                       inventory_sha1=self.inv_sha1,
                       revision_id=self.rev_id,
                       properties=self.revprops)
        rev.parent_ids = self.parents
        self.branch.repository.add_revision(self.rev_id, rev, self.new_inv, self.config)

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

        # iter_entries does not visit the ROOT_ID node so we need to call
        # self._update once by hand.
        self._update()
        for path, ie in self.new_inv.iter_entries():
            self._update()
            previous_entries = ie.find_previous_heads(
                self.parent_invs,
                self.weave_store,
                self.branch.repository.get_transaction())
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
        self.new_inv = Inventory(revision_id=self.rev_id)
        # iter_entries does not visit the ROOT_ID node so we need to call
        # self._update once by hand.
        self._update()
        for path, new_ie in self.work_inv.iter_entries():
            self._update()
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

    def _update(self):
        """Emit an update to the progress bar."""
        self.pb.update("Committing", self.pb_count, self.pb_total)
        self.pb_count += 1

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
        else:
            # this entry is new and not being committed
            self.pb_total -= 1

    def _report_deletes(self):
        for file_id in self.basis_inv:
            if file_id not in self.new_inv:
                self.reporter.deleted(self.basis_inv.id2path(file_id))

def _gen_revision_id(config, when):
    """Return new revision-id."""
    s = '%s-%s-' % (config.user_email(), compact_date(when))
    s += hexlify(rand_bytes(8))
    return s

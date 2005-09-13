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

import sys
import os

import bzrlib.errors
from bzrlib.trace import mutter, note
from bzrlib.branch import Branch
from bzrlib.progress import ProgressBar


def greedy_fetch(to_branch, from_branch, revision, pb):
    f = Fetcher(to_branch, from_branch, revision, pb)
    return f.count_copied, f.failed_revisions


class Fetcher(object):
    """Pull history from one branch to another."""
    def __init__(self, to_branch, from_branch, revision_limit=None, pb=None):
        self.to_branch = to_branch
        self.from_branch = from_branch
        self.revision_limit = revision_limit
        if pb is None:
            self.pb = bzrlib.ui.ui_factory.progress_bar()
        else:
            self.pb = pb
        self._scan_histories()
        self.failed_revisions = []
        self.count_copied = 0
        self._copy()


    def _scan_histories(self):
        self.from_history = from_branch.revision_history()
        self.required_revisions = set(from_history)
        self.to_history = to_branch.revision_history()
        if self.revision_limit:
            raise NotImplementedError('sorry, revision_limit not handled yet')
        self.need_revisions = []
        for rev_id in self.from_history:
            if not has_revision(self.to_branch):
                self.need_revisions.append(rev_id)
                mutter('need to get revision {%s}', rev_id)


    def _copy(self):
        while self.need_revisions:
            rev_id = self.need_revisions.pop()
            mutter('try to get revision {%s}', rev_id)

    
        
    

def has_revision(branch, revision_id):
    try:
        branch.get_revision_xml(revision_id)
        return True
    except bzrlib.errors.NoSuchRevision:
        return False


def old_greedy_fetch(to_branch, from_branch, revision=None, pb=None):
    """Copy all history from one branch to another.

    revision
        If set, copy only up to this point in the source branch.

    @returns: number copied, missing ids       
    """
    from_history = from_branch.revision_history()
    required_revisions = set(from_history)
    all_failed = set()
    if revision is not None:
        required_revisions.add(revision)
        try:
            rev_index = from_history.index(revision)
        except ValueError:
            rev_index = None
        if rev_index is not None:
            from_history = from_history[:rev_index + 1]
        else:
            from_history = [revision]
    to_history = to_branch.revision_history()
    missing = []
    for rev_id in from_history:
        if not has_revision(to_branch, rev_id):
            missing.append(rev_id)

    # recurse down through the revision graph, looking for things that
    # can't be found.
    count = 0
    while len(missing) > 0:
        installed, failed = to_branch.install_revisions(from_branch, 
                                                        revision_ids=missing,
                                                        pb=pb)
        count += installed
        required_failed = failed.intersection(required_revisions)
        if len(required_failed) > 0:
            raise bzrlib.errors.InstallFailed(required_failed)
        for rev_id in failed:
            note("Failed to install %s" % rev_id)
        all_failed.update(failed)
        new_missing = set() 
        for rev_id in missing:
            try:
                revision = from_branch.get_revision(rev_id)
            except bzrlib.errors.NoSuchRevision:
                if revision in from_history:
                    raise
                else:
                    continue
            for parent in [p.revision_id for p in revision.parents]:
                if not has_revision(to_branch, parent):
                    new_missing.add(parent)
        missing = new_missing
    return count, all_failed


def old_install_revisions(branch, other, revision_ids, pb):
    """Copy revisions from other branch into branch.

    This is a lower-level function used by a pull or a merge.  It
    incorporates some history from one branch into another, but
    does not update the revision history or operate on the working
    copy.

    revision_ids
        Sequence of revisions to copy.

    pb
        Progress bar for copying.
    """
    if False:
        if hasattr(other.revision_store, "prefetch"):
            other.revision_store.prefetch(revision_ids)
        if hasattr(other.inventory_store, "prefetch"):
            other.inventory_store.prefetch(revision_ids)

    if pb is None:
        pb = bzrlib.ui.ui_factory.progress_bar()

    revisions = []
    needed_texts = set()
    i = 0

    failures = set()
    for i, rev_id in enumerate(revision_ids):
        pb.update('fetching revision', i+1, len(revision_ids))
        try:
            rev = other.get_revision(rev_id)
        except bzrlib.errors.NoSuchRevision:
            failures.add(rev_id)
            continue

        revisions.append(rev)
        inv = other.get_inventory(rev_id)
        for key, entry in inv.iter_entries():
            if entry.text_id is None:
                continue
            if entry.text_id not in branch.text_store:
                needed_texts.add(entry.text_id)

    pb.clear()

    count, cp_fail = branch.text_store.copy_multi(other.text_store, 
                                                needed_texts)
    count, cp_fail = branch.inventory_store.copy_multi(other.inventory_store, 
                                                     revision_ids)
    count, cp_fail = branch.revision_store.copy_multi(other.revision_store, 
                                                    revision_ids,
                                                    permit_failure=True)
    assert len(cp_fail) == 0 
    return count, failures



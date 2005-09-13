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
from cStringIO import StringIO

import bzrlib.errors
from bzrlib.trace import mutter, note, warning
from bzrlib.branch import Branch, INVENTORY_FILEID, ANCESTRY_FILEID
from bzrlib.progress import ProgressBar
from bzrlib.xml5 import serializer_v5
from bzrlib.osutils import sha_string, split_lines

"""Copying of history from one branch to another.

The basic plan is that every branch knows the history of everything
that has merged into it.  As the first step of a merge, pull, or
branch operation we copy history from the source into the destination
branch.

The copying is done in a slightly complicated order.  We don't want to
add a revision to the store until everything it refers to is also
stored, so that if a revision is present we can totally recreate it.
However, we can't know what files are included in a revision until we
read its inventory.  Therefore, we first pull the XML and hold it in
memory until we've updated all of the files referenced.
"""

# TODO: Avoid repeatedly opening weaves so many times.


def greedy_fetch(to_branch, from_branch, revision, pb):
    f = Fetcher(to_branch, from_branch, revision, pb)
    return f.count_copied, f.failed_revisions


class Fetcher(object):
    """Pull history from one branch to another.

    revision_limit
        If set, pull only up to this revision_id.
        """
    def __init__(self, to_branch, from_branch, revision_limit=None, pb=None):
        self.to_branch = to_branch
        self.from_branch = from_branch
        self.revision_limit = revision_limit
        self.failed_revisions = []
        self.count_copied = 0
        if pb is None:
            self.pb = bzrlib.ui.ui_factory.progress_bar()
        else:
            self.pb = pb
        self._load_histories()
        revs_to_fetch = self._compare_ancestries()
        self._copy_revisions(revs_to_fetch)
        # - get a list of revisions that need to be pulled in
        # - for each one, pull in that revision file
        #   and get the inventory, and store the inventory with right
        #   parents.
        # - and get the ancestry, and store that with right parents too
        # - and keep a note of all file ids and version seen
        # - then go through all files; for each one get the weave,
        #   and add in all file versions


    def _load_histories(self):
        """Load histories of both branches, up to the limit."""
        self.from_history = self.from_branch.revision_history()
        self.to_history = self.to_branch.revision_history()
        if self.revision_limit:
            assert isinstance(revision_limit, basestring)
            try:
                rev_index = self.from_history.index(revision_limit)
            except ValueError:
                rev_index = None
            if rev_index is not None:
                self.from_history = self.from_history[:rev_index + 1]
            else:
                self.from_history = [revision]
            

    def _compare_ancestries(self):
        """Get a list of revisions that must be copied.

        That is, every revision that's in the ancestry of the source
        branch and not in the destination branch."""
        if self.from_history:
            self.from_ancestry = self.from_branch.get_ancestry(self.from_history[-1])
        else:
            self.from_ancestry = []
        if self.to_history:
            self.to_history = self.to_branch.get_ancestry(self.to_history[-1])
        else:
            self.to_history = []
        ss = set(self.to_history)
        to_fetch = []
        for rev_id in self.from_ancestry:
            if rev_id not in ss:
                to_fetch.append(rev_id)
                mutter('need to get revision {%s}', rev_id)
        mutter('need to get %d revisions in total', len(to_fetch))
        return to_fetch
                


    def _copy_revisions(self, revs_to_fetch):
        for rev_id in revs_to_fetch:
            self._copy_one_revision(rev_id)


    def _copy_one_revision(self, rev_id):
        """Copy revision and everything referenced by it."""
        mutter('copying revision {%s}', rev_id)
        rev_xml = self.from_branch.get_revision_xml(rev_id)
        inv_xml = self.from_branch.get_inventory_xml(rev_id)
        rev = serializer_v5.read_revision_from_string(rev_xml)
        inv = serializer_v5.read_inventory_from_string(inv_xml)
        assert rev.revision_id == rev_id
        assert rev.inventory_sha1 == sha_string(inv_xml)
        mutter('  commiter %s, %d parents',
               rev.committer,
               len(rev.parents))
        self._copy_new_texts(rev_id, inv)
        self.to_branch.weave_store.add_text(INVENTORY_FILEID, rev_id,
                                            split_lines(inv_xml), rev.parents)
        self.to_branch.revision_store.add(StringIO(rev_xml), rev_id)

        
    def _copy_new_texts(self, rev_id, inv):
        """Copy any new texts occuring in this revision."""
        # TODO: Rather than writing out weaves every time, hold them
        # in memory until everything's done?  But this way is nicer
        # if it's interrupted.
        for path, ie in inv.iter_entries():
            if ie.kind != 'file':
                continue
            if ie.text_version != rev_id:
                continue
            mutter('%s {%s} is changed in this revision',
                   path, ie.file_id)
            self._copy_one_text(rev_id, ie.file_id)


    def _copy_one_text(self, rev_id, file_id):
        """Copy one file text."""
        from_weave = self.from_branch.weave_store.get_weave(file_id)
        from_idx = from_weave.lookup(rev_id)
        from_parents = map(from_weave.idx_to_name, from_weave.parents(from_idx))
        text_lines = from_weave.get(from_idx)
        to_weave = self.to_branch.weave_store.get_weave_or_empty(file_id)
        if rev_id in to_weave._name_map:
            warning('version {%s} already present in weave of file {%s}',
                    rev_id, file_id)
            return
        to_parents = map(to_weave.lookup, from_parents)
        to_weave.add(rev_id, to_parents, text_lines)
        self.to_branch.weave_store.put_weave(file_id, to_weave)
    

def has_revision(branch, revision_id):
    try:
        branch.get_revision_xml_file(revision_id)
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



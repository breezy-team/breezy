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

from copy import copy
import os
from cStringIO import StringIO

import bzrlib
import bzrlib.errors as errors
from bzrlib.errors import (InstallFailed, NoSuchRevision, WeaveError,
                           MissingText)
from bzrlib.trace import mutter, note, warning
from bzrlib.branch import Branch
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

# XXX: This doesn't handle ghost (not present in branch) revisions at
# all yet.  I'm not sure they really should be supported.

# NOTE: This doesn't copy revisions which may be present but not
# merged into the last revision.  I'm not sure we want to do that.

# - get a list of revisions that need to be pulled in
# - for each one, pull in that revision file
#   and get the inventory, and store the inventory with right
#   parents.
# - and get the ancestry, and store that with right parents too
# - and keep a note of all file ids and version seen
# - then go through all files; for each one get the weave,
#   and add in all file versions



def greedy_fetch(to_branch, from_branch, revision=None, pb=None):
    f = Fetcher(to_branch, from_branch, revision, pb)
    return f.count_copied, f.failed_revisions



class Fetcher(object):
    """Pull revisions and texts from one branch to another.

    This doesn't update the destination's history; that can be done
    separately if desired.  

    revision_limit
        If set, pull only up to this revision_id.

    After running:

    last_revision -- if last_revision
        is given it will be that, otherwise the last revision of
        from_branch

    count_copied -- number of revisions copied

    count_weaves -- number of file weaves copied
    """
    def __init__(self, to_branch, from_branch, last_revision=None, pb=None):
        if to_branch == from_branch:
            raise Exception("can't fetch from a branch to itself")
        self.to_branch = to_branch
        self.to_storage = to_branch.storage
        self.to_weaves = self.to_storage.weave_store
        self.to_control = self.to_storage.control_weaves
        self.from_branch = from_branch
        self.from_storage = from_branch.storage
        self.from_weaves = self.from_storage.weave_store
        self.from_control = self.from_storage.control_weaves
        self.failed_revisions = []
        self.count_copied = 0
        self.count_total = 0
        self.count_weaves = 0
        self.copied_file_ids = set()
        self.file_ids_names = {}
        if pb is None:
            self.pb = bzrlib.ui.ui_factory.progress_bar()
        else:
            self.pb = pb
        self.from_branch.lock_read()
        try:
            self._fetch_revisions(last_revision)
        finally:
            self.from_branch.unlock()
            self.pb.clear()

    def _fetch_revisions(self, last_revision):
        self.last_revision = self._find_last_revision(last_revision)
        mutter('fetch up to rev {%s}', self.last_revision)
        if (self.last_revision is not None and 
            self.to_storage.has_revision(self.last_revision)):
            return
        try:
            revs_to_fetch = self._compare_ancestries()
        except WeaveError:
            raise InstallFailed([self.last_revision])
        self._copy_revisions(revs_to_fetch)
        self.new_ancestry = revs_to_fetch

    def _find_last_revision(self, last_revision):
        """Find the limiting source revision.

        Every ancestor of that revision will be merged across.

        Returns the revision_id, or returns None if there's no history
        in the source branch."""
        if last_revision:
            return last_revision
        self.pb.update('get source history')
        from_history = self.from_branch.revision_history()
        self.pb.update('get destination history')
        if from_history:
            return from_history[-1]
        else:
            return None                 # no history in the source branch
            

    def _compare_ancestries(self):
        """Get a list of revisions that must be copied.

        That is, every revision that's in the ancestry of the source
        branch and not in the destination branch."""
        self.pb.update('get source ancestry')
        from_storage = self.from_branch.storage
        self.from_ancestry = from_storage.get_ancestry(self.last_revision)

        dest_last_rev = self.to_branch.last_revision()
        self.pb.update('get destination ancestry')
        if dest_last_rev:
            to_storage = self.to_branch.storage
            dest_ancestry = to_storage.get_ancestry(dest_last_rev)
        else:
            dest_ancestry = []
        ss = set(dest_ancestry)
        to_fetch = []
        for rev_id in self.from_ancestry:
            if rev_id not in ss:
                to_fetch.append(rev_id)
                mutter('need to get revision {%s}', rev_id)
        mutter('need to get %d revisions in total', len(to_fetch))
        self.count_total = len(to_fetch)
        return to_fetch

    def _copy_revisions(self, revs_to_fetch):
        i = 0
        for rev_id in revs_to_fetch:
            i += 1
            if rev_id is None:
                continue
            if self.to_storage.has_revision(rev_id):
                continue
            self.pb.update('copy revision', i, self.count_total)
            self._copy_one_revision(rev_id)
            self.count_copied += 1


    def _copy_one_revision(self, rev_id):
        """Copy revision and everything referenced by it."""
        mutter('copying revision {%s}', rev_id)
        rev_xml = self.from_storage.get_revision_xml(rev_id)
        inv_xml = self.from_storage.get_inventory_xml(rev_id)
        rev = serializer_v5.read_revision_from_string(rev_xml)
        inv = serializer_v5.read_inventory_from_string(inv_xml)
        assert rev.revision_id == rev_id
        assert rev.inventory_sha1 == sha_string(inv_xml)
        mutter('  commiter %s, %d parents',
               rev.committer,
               len(rev.parent_ids))
        self._copy_new_texts(rev_id, inv)
        parents = rev.parent_ids
        new_parents = copy(parents)
        for parent in parents:
            if not self.to_storage.has_revision(parent):
                new_parents.pop(new_parents.index(parent))
        self._copy_inventory(rev_id, inv_xml, new_parents)
        self.to_storage.revision_store.add(StringIO(rev_xml), rev_id)
        mutter('copied revision %s', rev_id)

    def _copy_inventory(self, rev_id, inv_xml, parent_ids):
        self.to_control.add_text('inventory', rev_id,
                                split_lines(inv_xml), parent_ids,
                                self.to_storage.get_transaction())

    def _copy_new_texts(self, rev_id, inv):
        """Copy any new texts occuring in this revision."""
        # TODO: Rather than writing out weaves every time, hold them
        # in memory until everything's done?  But this way is nicer
        # if it's interrupted.
        for path, ie in inv.iter_entries():
            self._copy_one_weave(rev_id, ie.file_id, ie.revision)

    def _copy_one_weave(self, rev_id, file_id, text_revision):
        """Copy one file weave, esuring the result contains text_revision."""
        # check if the revision is already there
        if file_id in self.file_ids_names.keys( ) and \
            text_revision in self.file_ids_names[file_id]:
                return        
        to_weave = self.to_weaves.get_weave_or_empty(file_id,
            self.to_storage.get_transaction())
        if not file_id in self.file_ids_names.keys( ):
            self.file_ids_names[file_id] = to_weave.names( )
        if text_revision in to_weave:
            return
        from_weave = self.from_weaves.get_weave(file_id,
            self.from_branch.storage.get_transaction())
        if text_revision not in from_weave:
            raise MissingText(self.from_branch, text_revision, file_id)
        mutter('copy file {%s} modified in {%s}', file_id, rev_id)

        if to_weave.numversions() > 0:
            # destination has contents, must merge
            try:
                to_weave.join(from_weave)
            except errors.WeaveParentMismatch:
                to_weave.reweave(from_weave)
        else:
            # destination is empty, just replace it
            to_weave = from_weave.copy( )
        self.to_weaves.put_weave(file_id, to_weave,
            self.to_storage.get_transaction())
        self.count_weaves += 1
        self.copied_file_ids.add(file_id)
        self.file_ids_names[file_id] = to_weave.names()
        mutter('copied file {%s}', file_id)


fetch = Fetcher

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
from bzrlib.revision import NULL_REVISION
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


class RepoFetcher(object):
    """Pull revisions and texts from one repository to another.

    last_revision
        if set, try to limit to the data this revision references.

    after running:
    count_copied -- number of revisions copied
    count_weaves -- number of file weaves copied
    """
    def __init__(self, to_repository, from_repository, last_revision=None, pb=None):
        if to_repository.bzrdir.transport.base == from_repository.bzrdir.transport.base:
            # check that last_revision is in 'from' and then return a no-operation.
            if last_revision not in (None, NULL_REVISION):
                from_repository.get_revision(last_revision)
            return
        self.to_repository = to_repository
        self.from_repository = from_repository
        # must not mutate self._last_revision as its potentially a shared instance
        self._last_revision = last_revision
        if pb is None:
            self.pb = bzrlib.ui.ui_factory.progress_bar()
        else:
            self.pb = pb
        self.from_repository.lock_read()
        try:
            self.to_repository.lock_write()
            try:
                self.__fetch()
            finally:
                self.to_repository.unlock()
        finally:
            self.from_repository.unlock()

    def __fetch(self):
        """Primary worker function.

        This initialises all the needed variables, and then fetches the 
        requested revisions, finally clearing the progress bar.
        """
        self.to_weaves = self.to_repository.weave_store
        self.to_control = self.to_repository.control_weaves
        self.from_weaves = self.from_repository.weave_store
        self.from_control = self.from_repository.control_weaves
        self.failed_revisions = []
        self.count_copied = 0
        self.count_total = 0
        self.count_weaves = 0
        self.copied_file_ids = set()
        self.file_ids_names = {}
        try:
            revs = self._revids_to_fetch()
            # nothing to do
            if revs: 
                self._fetch_weave_texts(revs)
                self._fetch_inventory_weave(revs)
                self._fetch_revision_texts(revs)
                self.count_copied += len(revs)
        finally:
            self.pb.clear()

    def _revids_to_fetch(self):
        mutter('fetch up to rev {%s}', self._last_revision)
        if self._last_revision is NULL_REVISION:
            # explicit limit of no revisions needed
            return None
        if (self._last_revision != None and
            self.to_repository.has_revision(self._last_revision)):
            return None
            
        try:
            return self.to_repository.missing_revision_ids(self.from_repository,
                                                           self._last_revision)
        except errors.NoSuchRevision:
            raise InstallFailed([self._last_revision])

    def _fetch_revision_texts(self, revs):
        self.to_repository.revision_store.copy_multi(
            self.from_repository.revision_store,
            revs,
            pb=self.pb)

    def _fetch_weave_texts(self, revs):
        file_ids = self.from_repository.fileid_involved_by_set(revs)
        count = 0
        num_file_ids = len(file_ids)
        for file_id in file_ids:
            self.pb.update("merge weaves", count, num_file_ids)
            count +=1
            to_weave = self.to_weaves.get_weave_or_empty(file_id,
                self.to_repository.get_transaction())
            from_weave = self.from_weaves.get_weave(file_id,
                self.from_repository.get_transaction())

            if to_weave.numversions() > 0:
                # destination has contents, must merge
                try:
                    to_weave.join(from_weave)
                except errors.WeaveParentMismatch:
                    to_weave.reweave(from_weave)
            else:
                # destination is empty, just replace it
                to_weave = from_weave.copy()

            self.to_weaves.put_weave(file_id, to_weave,
                self.to_repository.get_transaction())
        self.pb.clear()

    def _fetch_inventory_weave(self, revs):
        self.pb.update("inventory fetch", 0, 2)
        from_weave = self.from_repository.get_inventory_weave()
        to_weave = self.to_repository.get_inventory_weave()
        self.pb.update("inventory fetch", 1, 2)
        to_weave = self.to_control.get_weave('inventory',
                self.to_repository.get_transaction())
        self.pb.update("inventory fetch", 2, 2)

        if to_weave.numversions() > 0:
            # destination has contents, must merge
            try:
                to_weave.join(from_weave, pb=self.pb, msg='merge inventory')
            except errors.WeaveParentMismatch:
                to_weave.reweave(from_weave, pb=self.pb, msg='reweave inventory')
        else:
            # destination is empty, just replace it
            to_weave = from_weave.copy()

        self.to_control.put_weave('inventory', to_weave,
            self.to_repository.get_transaction())

        self.pb.clear()


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
        if to_branch.base == from_branch.base:
            raise Exception("can't fetch from a branch to itself %s, %s" % 
                            (from_branch.base, to_branch.base))
        
        self.to_branch = to_branch
        self.from_branch = from_branch
        self._last_revision = last_revision
        if pb is None:
            self.pb = bzrlib.ui.ui_factory.progress_bar()
        else:
            self.pb = pb
        self.from_branch.lock_read()
        try:
            self.to_branch.lock_write()
            try:
                self.__fetch()
            finally:
                self.to_branch.unlock()
        finally:
            self.from_branch.unlock()

    def __fetch(self):
        self._find_last_revision()
        repo_fetcher = RepoFetcher(to_repository=self.to_branch.repository,
                                   from_repository=self.from_branch.repository,
                                   pb=self.pb,
                                   last_revision=self._last_revision)
        self.failed_revisions = repo_fetcher.failed_revisions
        self.count_copied = repo_fetcher.count_copied
        self.count_total = repo_fetcher.count_total
        self.count_weaves = repo_fetcher.count_weaves
        self.copied_file_ids = repo_fetcher.copied_file_ids

    def _find_last_revision(self):
        """Find the limiting source revision.

        Every ancestor of that revision will be merged across.

        Returns the revision_id, or returns None if there's no history
        in the source branch."""
        if self._last_revision:
            return
        self.pb.update('get source history')
        from_history = self.from_branch.revision_history()
        self.pb.update('get destination history')
        if from_history:
            self._last_revision = from_history[-1]
        else:
            # no history in the source branch
            self._last_revision = NULL_REVISION

fetch = Fetcher

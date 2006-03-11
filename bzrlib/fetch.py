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


"""Copying of history from one branch to another.

The basic plan is that every branch knows the history of everything
that has merged into it.  As the first step of a merge, pull, or
branch operation we copy history from the source into the destination
branch.

The copying is done in a slightly complicated order.  We don't want to
add a revision to the store until everything it refers to is also
stored, so that if a revision is present we can totally recreate it.
However, we can't know what files are included in a revision until we
read its inventory.  So we query the inventory store of the source for
the ids we need, and then pull those ids and finally actually join
the inventories.
"""

import bzrlib
import bzrlib.errors as errors
from bzrlib.errors import (InstallFailed, NoSuchRevision,
                           MissingText)
from bzrlib.trace import mutter
from bzrlib.reconcile import RepoReconciler
from bzrlib.revision import NULL_REVISION
from bzrlib.symbol_versioning import *


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


@deprecated_function(zero_eight)
def greedy_fetch(to_branch, from_branch, revision=None, pb=None):
    """Legacy API, please see branch.fetch(from_branch, last_revision, pb)."""
    f = Fetcher(to_branch, from_branch, revision, pb)
    return f.count_copied, f.failed_revisions

fetch = greedy_fetch


class RepoFetcher(object):
    """Pull revisions and texts from one repository to another.

    last_revision
        if set, try to limit to the data this revision references.

    after running:
    count_copied -- number of revisions copied

    This should not be used directory, its essential a object to encapsulate
    the logic in InterRepository.fetch().
    """
    def __init__(self, to_repository, from_repository, last_revision=None, pb=None):
        # result variables.
        self.failed_revisions = []
        self.count_copied = 0
        if to_repository.control_files._transport.base == from_repository.control_files._transport.base:
            # check that last_revision is in 'from' and then return a no-operation.
            if last_revision not in (None, NULL_REVISION):
                from_repository.get_revision(last_revision)
            return
        self.to_repository = to_repository
        self.from_repository = from_repository
        # must not mutate self._last_revision as its potentially a shared instance
        self._last_revision = last_revision
        if pb is None:
            self.pb = bzrlib.ui.ui_factory.nested_progress_bar()
            self.nested_pb = self.pb
        else:
            self.pb = pb
            self.nested_pb = None
        self.from_repository.lock_read()
        try:
            self.to_repository.lock_write()
            try:
                self.__fetch()
            finally:
                if self.nested_pb is not None:
                    self.nested_pb.finished()
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
        self.count_total = 0
        self.file_ids_names = {}
        self.total_steps = 4
        try:
            revs = self._revids_to_fetch()
            # something to do ?
            if revs: 
                self.pb.update('Fetching text', 1, self.total_steps)
                self._fetch_weave_texts(revs)
                self.pb.update('Fetching inventories', 2, self.total_steps)
                self._fetch_inventory_weave(revs)
                self.pb.update('Fetching revisions', 3, self.total_steps)
                self._fetch_revision_texts(revs)
                self.pb.update('Fetching revisions', 4, self.total_steps)
                self.count_copied += len(revs)
        finally:
            self.pb.clear()

    def _revids_to_fetch(self):
        self.pb.update('Calculating needed data', 0, self.total_steps)
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

    def _fetch_weave_texts(self, revs):
        texts_pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            file_ids = self.from_repository.fileid_involved_by_set(revs)
            count = 0
            num_file_ids = len(file_ids)
            for file_id in file_ids:
                texts_pb.update("fetch texts", count, num_file_ids)
                count +=1
                to_weave = self.to_weaves.get_weave_or_empty(file_id,
                    self.to_repository.get_transaction())
    
                if to_weave.num_versions() > 0:
                    # destination has contents, must merge
                    from_weave = self.from_weaves.get_weave(file_id,
                        self.from_repository.get_transaction())
                    # we fetch all the texts, because texts do
                    # not reference anything, and its cheap enough
                    to_weave.join(from_weave)
                else:
                    # destination is empty, just copy it.
                    # this copies all the texts, which is useful and 
                    # on per-file basis quite cheap.
                    self.to_weaves.copy_multi(
                        self.from_weaves,
                        [file_id],
                        None,
                        self.from_repository.get_transaction(),
                        self.to_repository.get_transaction())
        finally:
            texts_pb.finished()

    def _fetch_inventory_weave(self, revs):
        inv_pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            inv_pb.update("fetch inventory", 0, 2)
            to_weave = self.to_control.get_weave('inventory',
                    self.to_repository.get_transaction())
    
            # just merge, this is optimisable and its means we dont
            # copy unreferenced data such as not-needed inventories.
            self.pb.update("fetch inventory", 1, 2)
            from_weave = self.from_repository.get_inventory_weave()
            self.pb.update("fetch inventory", 2, 2)
            # we fetch only the referenced inventories because we do not
            # know for unselected inventories whether all their required
            # texts are present in the other repository - it could be
            # corrupt.
            to_weave.join(from_weave, msg='fetch inventory', version_ids=revs)
        finally:
            inv_pb.finished()


class GenericRepoFetcher(RepoFetcher):
    """This is a generic repo to repo fetcher.

    This makes minimal assumptions about repo layout and contents.
    It triggers a reconciliation after fetching to ensure integrity.
    """

    def _fetch_revision_texts(self, revs):
        rev_pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            self.to_transaction = self.to_repository.get_transaction()
            count = 0
            total = len(revs)
            for rev in revs:
                rev_pb.update('fetch revisions', count, total)
                try:
                    sig_text = self.from_repository.get_signature_text(rev)
                    self.to_repository._revision_store.add_revision_signature_text(
                        rev, sig_text, self.to_transaction)
                except errors.NoSuchRevision:
                    # not signed.
                    pass
                self.to_repository._revision_store.add_revision(
                    self.from_repository.get_revision(rev),
                    self.to_transaction)
                count += 1
            rev_pb.update('copying revisions', count, total)
            # fixup inventory if needed: 
            # this is expensive because we have no inverse index to current ghosts.
            # but on local disk its a few seconds and sftp push is already insane.
            # so we just-do-it.
            # FIXME: repository should inform if this is needed.
            self.to_repository.reconcile()
        finally:
            rev_pb.finished()
    

class KnitRepoFetcher(RepoFetcher):
    """This is a knit format repository specific fetcher.

    This differs from the GenericRepoFetcher by not doing a 
    reconciliation after copying, and using knit joining to
    copy revision texts.
    """

    def _fetch_revision_texts(self, revs):
        # may need to be a InterRevisionStore call here.
        from_transaction = self.from_repository.get_transaction()
        to_transaction = self.to_repository.get_transaction()
        to_sf = self.to_repository._revision_store.get_signature_file(
            to_transaction)
        from_sf = self.from_repository._revision_store.get_signature_file(
            from_transaction)
        to_sf.join(from_sf, version_ids=revs, ignore_missing=True)
        to_rf = self.to_repository._revision_store.get_revision_file(
            to_transaction)
        from_rf = self.from_repository._revision_store.get_revision_file(
            from_transaction)
        to_rf.join(from_rf, version_ids=revs)


class Fetcher(object):
    """Backwards compatability glue for branch.fetch()."""

    @deprecated_method(zero_eight)
    def __init__(self, to_branch, from_branch, last_revision=None, pb=None):
        """Please see branch.fetch()."""
        to_branch.fetch(from_branch, last_revision, pb)

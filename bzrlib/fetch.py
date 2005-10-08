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

import os
from cStringIO import StringIO

import bzrlib.errors
from bzrlib.trace import mutter, note, warning
from bzrlib.branch import Branch
from bzrlib.progress import ProgressBar
from bzrlib.xml5 import serializer_v5
from bzrlib.osutils import sha_string, split_lines
from bzrlib.errors import InstallFailed, NoSuchRevision, WeaveError

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

    count_texts -- number of file texts copied
    """
    def __init__(self, to_branch, from_branch, last_revision=None, pb=None):
        if to_branch == from_branch:
            raise Exception("can't fetch from a branch to itself")
        self.to_branch = to_branch
        self.to_weaves = to_branch.weave_store
        self.to_control = to_branch.control_weaves
        self.from_branch = from_branch
        self.from_weaves = from_branch.weave_store
        self.from_control = from_branch.control_weaves
        self.failed_revisions = []
        self.count_copied = 0
        self.count_total = 0
        self.count_texts = 0
        if pb is None:
            self.pb = bzrlib.ui.ui_factory.progress_bar()
        else:
            self.pb = pb
        try:
            try:
                self.last_revision = self._find_last_revision(last_revision)
            except NoSuchRevision, e:
                mutter('failed getting last revision: %s', e)
                raise InstallFailed([last_revision])
            mutter('fetch up to rev {%s}', self.last_revision)
            try:
                revs_to_fetch = self._compare_ancestries()
            except WeaveError:
                raise InstallFailed([self.last_revision])
            self._copy_revisions(revs_to_fetch)
            self.new_ancestry = revs_to_fetch
        finally:
            self.pb.clear()


    def _find_last_revision(self, last_revision):
        """Find the limiting source revision.

        Every ancestor of that revision will be merged across.

        Returns the revision_id, or returns None if there's no history
        in the source branch."""
        self.pb.update('get source history')
        from_history = self.from_branch.revision_history()
        self.pb.update('get destination history')
        if last_revision:
            self.from_branch.get_revision(last_revision)
            return last_revision
        elif from_history:
            return from_history[-1]
        else:
            return None                 # no history in the source branch
            

    def _compare_ancestries(self):
        """Get a list of revisions that must be copied.

        That is, every revision that's in the ancestry of the source
        branch and not in the destination branch."""
        self.pb.update('get source ancestry')
        self.from_ancestry = self.from_branch.get_ancestry(self.last_revision)

        dest_last_rev = self.to_branch.last_revision()
        self.pb.update('get destination ancestry')
        if dest_last_rev:
            dest_ancestry = self.to_branch.get_ancestry(dest_last_rev)
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
            if self.to_branch.has_revision(rev_id):
                continue
            self.pb.update('fetch revision', i, self.count_total)
            self._copy_one_revision(rev_id)
            self.count_copied += 1


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
               len(rev.parent_ids))
        self._copy_new_texts(rev_id, inv)
        parents = rev.parent_ids
        for parent in parents:
            if not self.to_branch.has_revision(parent):
                parents.pop(parents.index(parent))
        self._copy_inventory(rev_id, inv_xml, parents)
        self._copy_ancestry(rev_id, parents)
        self.to_branch.revision_store.add(StringIO(rev_xml), rev_id)


    def _copy_inventory(self, rev_id, inv_xml, parent_ids):
        self.to_control.add_text('inventory', rev_id,
                                split_lines(inv_xml), parent_ids)


    def _copy_ancestry(self, rev_id, parent_ids):
        ancestry_lines = self.from_control.get_lines('ancestry', rev_id)
        self.to_control.add_text('ancestry', rev_id, ancestry_lines,
                                 parent_ids)

        
    def _copy_new_texts(self, rev_id, inv):
        """Copy any new texts occuring in this revision."""
        # TODO: Rather than writing out weaves every time, hold them
        # in memory until everything's done?  But this way is nicer
        # if it's interrupted.
        for path, ie in inv.iter_entries():
            if not ie.has_text():
                continue
            if ie.revision != rev_id:
                continue
            mutter('%s {%s} is changed in this revision',
                   path, ie.file_id)
            self._copy_one_text(rev_id, ie.file_id)


    def _copy_one_text(self, rev_id, file_id):
        """Copy one file text."""
        mutter('copy text version {%s} of file {%s}',
               rev_id, file_id)
        from_weave = self.from_weaves.get_weave(file_id)
        from_idx = from_weave.lookup(rev_id)
        from_parents = map(from_weave.idx_to_name, from_weave.parents(from_idx))
        text_lines = from_weave.get(from_idx)
        to_weave = self.to_weaves.get_weave_or_empty(file_id)
        to_parents = map(to_weave.lookup, from_parents)
        # it's ok to add even if the text is already there
        to_weave.add(rev_id, to_parents, text_lines)
        self.to_weaves.put_weave(file_id, to_weave)
        self.count_texts += 1


fetch = Fetcher

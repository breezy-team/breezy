# Copyright (C) 2008 Canonical Ltd
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

"""Parameterised loading of revisions into a repository."""


from bzrlib import errors


class RevisionLoader(object):
    # NOTE: This is effectively bzrlib.repository._install_revision
    # refactored to be a class. When importing, we want more flexibility
    # in how previous revisions are cached, data is feed in, etc.

    def __init__(self, repo, inventories_provider=None):
        """An object responsible for loading revisions into a repository.

        NOTE: Repository locking is not managed by this class. Clients
        should take a write lock, call load() multiple times, then release
        the lock.

        :param repository: the target repository
        :param inventories_provider: a callable expecting a repository and
            a list of revision-ids, that returns:
              * the list of revision-ids present in the repository
              * the list of inventories for the revision-id's,
                including an empty inventory for the missing revisions
            If None, a default implementation is provided.
        """
        self.repo = repo
        if inventories_provider is not None:
            self.inventories_provider = inventories_provider
        else:
            self.inventories_provider = self._default_inventories_provider

    def load(self, rev, inv, signature, text_provider):
        """Load a revision into a repository.

        :param rev: the Revision
        :param inv: the inventory
        :param signature: signing information
        :param text_provider: a callable expecting a file_id parameter
            that returns the text for that file-id
        """
        present_parents, parent_invs = self.inventories_provider(
            rev.parent_ids)
        self._load_texts(rev.revision_id, inv.iter_entries(), parent_invs,
            text_provider)
        try:
            rev.inventory_sha1 = self.repo.add_inventory(rev.revision_id,
                inv, present_parents)
        except errors.RevisionAlreadyPresent:
            pass
        if signature is not None:
            self.repo.add_signature_text(rev.revision_id, signature)
        self.repo.add_revision(rev.revision_id, rev, inv)

    def _load_texts(self, revision_id, entries, parent_invs, text_provider):
        """Load texts to a repository for inventory entries.
        
        This method is provided for subclasses to use or override.

        :param revision_id: the revision identifier
        :param entries: iterator over the inventory entries
        :param parent_inv: the parent inventories
        :param text_provider: a callable expecting a file_id parameter
            that returns the text for that file-id
        """

        # Backwards compatibility hack: skip the root id.
        if not self.repo.supports_rich_root():
            path, root = entries.next()
            if root.revision != revision_id:
                raise errors.IncompatibleRevision(repr(self.repo))
        # Add the texts that are not already present
        tx = self.repo.get_transaction()
        for path, ie in entries:
            # This test is *really* slow: over 50% of import time
            #w = self.repo.weave_store.get_weave_or_empty(ie.file_id, tx)
            #if ie.revision in w:
            #    continue
            # Try another way ...
            if ie.revision != revision_id:
                continue
            text_parents = []
            for parent_inv in parent_invs:
                if ie.file_id not in parent_inv:
                    continue
                parent_id = parent_inv[ie.file_id].revision
                if parent_id in text_parents:
                    continue
                text_parents.append(parent_id)
            vfile = self.repo.weave_store.get_weave_or_empty(ie.file_id,  tx)
            lines = text_provider(ie.file_id)
            vfile.add_lines(revision_id, text_parents, lines)

    def _default_inventories_provider(self, revision_ids):
        """An inventories provider that queries the repository."""
        present = []
        inventories = []
        for revision_id in revision_ids:
            if self.repo.has_revision(revision_id):
                present.append(revision_id)
                rev_tree = self.repo.revision_tree(revision_id)
            else:
                rev_tree = self.repo.revision_tree(None)
            inventories.append(rev_tree.inventory)
        return present, inventories

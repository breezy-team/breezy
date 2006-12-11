# Copyright (C) 2006 Canonical Ltd
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

"""VersionedFile based revision store.

This stores revisions as individual entries in a knit, and signatures in a 
parallel knit.
"""


import bzrlib
from bzrlib import errors, osutils
from bzrlib.knit import KnitVersionedFile, KnitPlainFactory
from bzrlib.store.revision import RevisionStore
from bzrlib.store.versioned import VersionedFileStore
from bzrlib.transport import get_transport


class KnitRevisionStoreFactory(object):
    """Factory to create a KnitRevisionStore for testing."""

    def create(self, url):
        """Create a revision store at url."""
        t = get_transport(url)
        t.mkdir('revision-store')
        versioned_file_store = VersionedFileStore(
            t.clone('revision-store'),
            precious=True,
            versionedfile_class=KnitVersionedFile,
            versionedfile_kwargs={'delta':False, 'factory':KnitPlainFactory()})
        return KnitRevisionStore(versioned_file_store)

    def __str__(self):
        return "KnitRevisionStore"


class KnitRevisionStore(RevisionStore):
    """A RevisionStore layering on a VersionedFileStore."""

    def __init__(self, versioned_file_store):
        """Create a KnitRevisionStore object.

        :param versioned_file_store: the text store to use for storing 
                                     revisions and signatures.
        """
        super(KnitRevisionStore, self).__init__()
        self.versioned_file_store = versioned_file_store

    def _add_revision(self, revision, revision_as_file, transaction):
        """Template method helper to store revision in this store."""
        # FIXME: make this ghost aware at the knit level
        rf = self.get_revision_file(transaction)
        self.get_revision_file(transaction).add_lines_with_ghosts(
            revision.revision_id,
            revision.parent_ids,
            osutils.split_lines(revision_as_file.read()))

    def add_revision_signature_text(self, revision_id, signature_text, transaction):
        """See RevisionStore.add_revision_signature_text()."""
        self.get_signature_file(transaction).add_lines(
            revision_id, [], osutils.split_lines(signature_text))

    def all_revision_ids(self, transaction):
        """See RevisionStore.all_revision_ids()."""
        rev_file = self.get_revision_file(transaction)
        return rev_file.get_ancestry(rev_file.versions())

    def get_revisions(self, revision_ids, transaction):
        """See RevisionStore.get_revisions()."""
        texts = self._get_serialized_revisions(revision_ids, transaction)
        revisions = []
        try:
            for text, revision_id in zip(texts, revision_ids):
                r = self._serializer.read_revision_from_string(text)
                assert r.revision_id == revision_id
                revisions.append(r)
        except SyntaxError, e:
            raise errors.BzrError('failed to unpack revision_xml',
                                   [revision_id,
                                   str(e)])
        return revisions 

    def _get_serialized_revisions(self, revision_ids, transaction):
        texts = []
        vf = self.get_revision_file(transaction)
        try:
            return vf.get_texts(revision_ids)
        except (errors.RevisionNotPresent), e:
            raise errors.NoSuchRevision(self, e.revision_id)

    def _get_revision_xml(self, revision_id, transaction):
        try:
            return self.get_revision_file(transaction).get_text(revision_id)
        except (errors.RevisionNotPresent):
            raise errors.NoSuchRevision(self, revision_id)

    def get_revision_file(self, transaction):
        """Get the revision versioned file object."""
        return self.versioned_file_store.get_weave_or_empty('revisions', transaction)

    def get_signature_file(self, transaction):
        """Get the signature text versioned file object."""
        return self.versioned_file_store.get_weave_or_empty('signatures', transaction)

    def _get_signature_text(self, revision_id, transaction):
        """See RevisionStore._get_signature_text()."""
        try:
            return self.get_signature_file(transaction).get_text(revision_id)
        except errors.RevisionNotPresent:
            raise errors.NoSuchRevision(self, revision_id)

    def has_revision_id(self, revision_id, transaction):
        """True if the store contains revision_id."""
        return (revision_id is None
                or self.get_revision_file(transaction).has_version(revision_id))
        
    def _has_signature(self, revision_id, transaction):
        """See RevisionStore._has_signature()."""
        return self.get_signature_file(transaction).has_version(revision_id)

    def total_size(self, transaction):
        """ See RevisionStore.total_size()."""
        return (len(self.all_revision_ids(transaction)),
            self.versioned_file_store.total_size()[1])

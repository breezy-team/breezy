# Copyright (C) 2006 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published by
# the Free Software Foundation.
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
import bzrlib.errors as errors
from bzrlib.knit import KnitVersionedFile
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
            versionedfile_class=KnitVersionedFile)
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
        parents = []
        for parent_id in revision.parent_ids:
            if rf.has_version(parent_id):
                parents.append(parent_id)
        self.get_revision_file(transaction).add_lines(
            revision.revision_id,
            parents,
            revision_as_file.readlines())

    def add_revision_signature_text(self, revision_id, signature_text, transaction):
        """See RevisionStore.add_revision_signature_text()."""
        self._get_signature_file(transaction).add_lines(
            revision_id, [], bzrlib.osutils.split_lines(signature_text))

    def all_revision_ids(self, transaction):
        """See RevisionStore.all_revision_ids()."""
        rev_file = self.get_revision_file(transaction)
        return rev_file.get_ancestry(rev_file.versions())

    def get_revision(self, revision_id, transaction):
        """See RevisionStore.get_revision()."""
        xml = self._get_revision_xml(revision_id, transaction)
        try:
            r = self._serializer.read_revision_from_string(xml)
        except SyntaxError, e:
            raise errors.BzrError('failed to unpack revision_xml',
                                   [revision_id,
                                   str(e)])
        assert r.revision_id == revision_id
        return r

    def _get_revision_xml(self, revision_id, transaction):
        try:
            return self.get_revision_file(transaction).get_text(revision_id)
        except (errors.RevisionNotPresent):
            raise errors.NoSuchRevision(self, revision_id)

    def get_revision_file(self, transaction):
        """Get the revision versioned file object."""
        return self.versioned_file_store.get_weave_or_empty('revisions', transaction)

    def _get_signature_file(self, transaction):
        """Get the signature text versioned file object."""
        return self.versioned_file_store.get_weave_or_empty('signatures', transaction)

    def _get_signature_text(self, revision_id, transaction):
        """See RevisionStore._get_signature_text()."""
        try:
            return self._get_signature_file(transaction).get_text(revision_id)
        except errors.RevisionNotPresent:
            raise errors.NoSuchRevision(self, revision_id)

    def has_revision_id(self, revision_id, transaction):
        """True if the store contains revision_id."""
        return (revision_id is None
                or self.get_revision_file(transaction).has_version(revision_id))
        
    def _has_signature(self, revision_id, transaction):
        """See RevisionStore._has_signature()."""
        return self._get_signature_file(transaction).has_version(revision_id)

    def total_size(self, transaction):
        """ See RevisionStore.total_size()."""
        return self.versioned_file_store.total_size()

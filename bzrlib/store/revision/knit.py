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


from bzrlib.store.revision import RevisionStore
from bzrlib.store.versioned import VersionedFileStore
from bzrlib.transport import get_transport


class KnitRevisionStoreFactory(object):
    """Factory to create a KnitRevisionStore for testing."""

    def create(self, url):
        """Create a revision store at url."""
        t = get_transport(url)
        t.mkdir('revstore')
        versioned_file_store = VersionedFileStore(t.clone('revstore'))
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
        self.versioned_file_store = versioned_file_store

    def get_revision_file(self, transaction):
        """Get the revision versioned file object."""
        return self.versioned_file_store.get_weave('revisions', transaction)

    def has_revision_id(self, revision_id, transaction):
        """True if the store contains revision_id."""
        return (revision_id is None
                or self.get_revision_file(transaction).has_version(revision_id))

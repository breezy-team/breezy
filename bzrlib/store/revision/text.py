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

"""TextStore based revision store.

This stores revisions as individual text entries in a TextStore and 
requires access to a inventory weave to produce object graphs.
"""


from cStringIO import StringIO


import bzrlib
import bzrlib.errors as errors
from bzrlib.store.revision import RevisionStore
from bzrlib.store.text import TextStore
from bzrlib.store.versioned import VersionedFileStore
from bzrlib.transport import get_transport


class TextRevisionStoreTestFactory(object):
    """Factory to create a TextRevisionStore for testing.

    This creates a inventory weave and hooks it into the revision store
    """

    def create(self, url):
        """Create a revision store at url."""
        t = get_transport(url)
        t.mkdir('revstore')
        text_store = TextStore(t.clone('revstore'))
        return TextRevisionStore(text_store)

    def __str__(self):
        return "TextRevisionStore"


class TextRevisionStore(RevisionStore):
    """A RevisionStore layering on a TextStore and Inventory weave store."""

    def __init__(self, text_store, serializer=None):
        """Create a TextRevisionStore object.

        :param text_store: the text store to put serialised revisions into.
        """
        super(TextRevisionStore, self).__init__(serializer)
        self.text_store = text_store
        self.text_store.register_suffix('sig')

    def _add_revision(self, revision, revision_as_file, transaction):
        """Template method helper to store revision in this store."""
        self.text_store.add(revision_as_file, revision.revision_id)

    def _add_revision_signature_text(self, revision_id, signature_text, transaction):
        """See RevisionStore._add_revision_signature_text()."""
        self.text_store.add(StringIO(signature_text), revision_id, "sig")

    def get_revision(self, revision_id, transaction):
        """See RevisionStore.get_revision()."""
        xml_file = self._get_revision_xml_file(revision_id)
        try:
            r = self._serializer.read_revision(xml_file)
        except SyntaxError, e:
            raise errors.BzrError('failed to unpack revision_xml',
                                   [revision_id,
                                   str(e)])
            
        assert r.revision_id == revision_id
        return r

    def _get_revision_xml_file(self, revision_id):
        try:
            return self.text_store.get(revision_id)
        except (IndexError, KeyError):
            raise bzrlib.errors.NoSuchRevision(self, revision_id)

    def has_revision_id(self, revision_id, transaction):
        """True if the store contains revision_id."""
        return (revision_id is None
                or self.text_store.has_id(revision_id))
        
    def total_size(self, transaction):
        """ See RevisionStore.total_size()."""
        return self.text_store.total_size()

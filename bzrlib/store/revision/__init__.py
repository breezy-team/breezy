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

"""Revision stores.

Revision stores are responsible for storing a group of revisions
and returning some interesting data about them such as ancestors
and ghosts information.
"""


from copy import deepcopy
from cStringIO import StringIO
from unittest import TestSuite


import bzrlib
import bzrlib.errors as errors
from bzrlib.trace import mutter


class RevisionStoreTestProviderAdapter(object):
    """A tool to generate a suite testing multiple repository stores.

    This is done by copying the test once for each repository store
    and injecting the transport_server, transport_readonly_server,
    and revision-store-factory into each copy.
    Each copy is also given a new id() to make it easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, factories):
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self._factories = factories
    
    def adapt(self, test):
        result = TestSuite()
        for factory in self._factories:
            new_test = deepcopy(test)
            new_test.transport_server = self._transport_server
            new_test.transport_readonly_server = self._transport_readonly_server
            new_test.store_factory = factory
            def make_new_test_id():
                new_id = "%s(%s)" % (new_test.id(), factory)
                return lambda: new_id
            new_test.id = make_new_test_id()
            result.addTest(new_test)
        return result

    @staticmethod
    def default_test_list():
        """Generate the default list of revision store permutations to test."""
        from bzrlib.store.revision.text import TextRevisionStoreTestFactory
        from bzrlib.store.revision.knit import KnitRevisionStoreFactory
        result = []
        # test the fallback InterVersionedFile from weave to annotated knits
        result.append(TextRevisionStoreTestFactory())
        result.append(KnitRevisionStoreFactory())
        return result


class RevisionStore(object):
    """A revision store stores revisions."""

    def __init__(self, serializer=None):
        if serializer is None:
            serializer = bzrlib.xml5.serializer_v5
        self._serializer = serializer

    def add_revision(self, revision, transaction):
        """Add revision to the revision store.

        :param rev: The revision object.
        """
        # serialisation : common to all at the moment.
        rev_tmp = StringIO()
        self._serializer.write_revision(revision, rev_tmp)
        rev_tmp.seek(0)
        self._add_revision(revision, rev_tmp, transaction)
        mutter('added revision_id {%s}', revision.revision_id)

    def _add_revision(self, revision, revision_as_file, transaction):
        """Template method helper to store revision in this store."""
        raise NotImplementedError(self._add_revision)

    def add_revision_signature_text(self, revision_id, signature_text, transaction):
        """Add signature_text as a signature for revision_id."""
        raise NotImplementedError(self.add_revision_signature_text)

    def all_revision_ids(self, transaction):
        """Returns a list of all the revision ids in the revision store. 

        :return: list of revision_ids in topological order.
        """
        raise NotImplementedError(self.all_revision_ids)

    def get_revision(self, revision_id, transaction):
        """Return the Revision object for a named revision."""
        raise NotImplementedError(self.get_revision)

    def get_signature_text(self, revision_id, transaction):
        """Get the signature text for the digital signature of revision_id.
        
        :return: a signature text.
        """
        self._guard_revision(revision_id, transaction)
        return self._get_signature_text(revision_id, transaction)

    def _get_signature_text(self, revision_id, transaction):
        """Helper method for get_signature_text to return the text itself."""
        raise NotImplementedError(self.get_signature_text)

    def _guard_revision(self, revision_id, transaction):
        """Guard method for testing the presence of a revision."""
        if not self.has_revision_id(revision_id, transaction):
            raise errors.NoSuchRevision(self, revision_id)

    def has_revision_id(self, revision_id, transaction):
        """True if the store contains revision_id."""
        raise NotImplementedError(self.has_revision_id)

    def has_signature(self, revision_id, transaction):
        """True if the store has a signature for revision_id."""
        self._guard_revision(revision_id, transaction)
        return self._has_signature(revision_id, transaction)

    def _has_signature(self, revision_id, transaction):
        """Return the presence of a signature for revision_id.

        A worker memrthod for has_signature, this can assume the
        revision is present.
        """
        return NotImplementedError(self._has_signature)
        
    def total_size(self, transaction):
        """How big is the store?

        :return: (count, bytes) tuple.
        """
        raise NotImplementedError(self.total_size)

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
from unittest import TestSuite


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
    """A revision store stores revisions and signatures."""

    def has_revision_id(self, revision_id, transaction):
        """True if the store contains revision_id."""
        raise NotImplementedError(self.has_revision_id)

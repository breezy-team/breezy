# Copyright (C) 2006 by Canonical Ltd
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

"""Revision store tests."""


import bzrlib.errors as errors
from bzrlib.revision import Revision
from bzrlib.store.revision import RevisionStore
from bzrlib.tests import TestCaseWithTransport
from bzrlib.transactions import PassThroughTransaction
from bzrlib.tree import EmptyTree


class TestFactory(TestCaseWithTransport):

    def test_factory_keeps_smoke_in(self):
        s = self.store_factory.create(self.get_url('.'))
        self.assertTrue(isinstance(s, RevisionStore))


class TestAll(TestCaseWithTransport):

    def setUp(self):
        super(TestAll, self).setUp()
        self.store = self.store_factory.create(self.get_url('.'))
        self.transaction = PassThroughTransaction()

    def test_add_has_get(self):
        rev = Revision(timestamp=0,
                       timezone=None,
                       committer="Foo Bar <foo@example.com>",
                       message="Message",
                       inventory_sha1='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                       revision_id='A')
        self.store.add_revision(rev, self.transaction)
        self.assertTrue(self.store.has_revision_id('A', self.transaction))
        rev2 = self.store.get_revision('A', self.transaction)
        self.assertEqual(rev, rev2)

    def test_has_missing(self):
        # has of a non present id -> False
        self.assertFalse(self.store.has_revision_id('missing', self.transaction))

    def test_has_None(self):
        # has of None -> True
        self.assertTrue(self.store.has_revision_id(None, self.transaction))

    def test_get_revision_none(self):
        # get_revision(None) -> raises NoSuchRevision
        self.assertRaises(errors.NoSuchRevision,
                          self.store.get_revision,
                          'B',
                          self.transaction)

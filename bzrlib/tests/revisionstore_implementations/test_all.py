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
        rev = self.add_sample_rev()
        self.assertTrue(self.store.has_revision_id('A', self.transaction))
        rev2 = self.store.get_revision('A', self.transaction)
        self.assertEqual(rev, rev2)

    def add_sample_rev(self):
        rev = Revision(timestamp=0,
                       timezone=None,
                       committer="Foo Bar <foo@example.com>",
                       message="Message",
                       inventory_sha1='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                       revision_id='A')
        self.store.add_revision(rev, self.transaction)
        return rev

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

    def test_add_signature_text_missing(self):
        # add of a text signature for a missing revision must work, to allow
        # revisions to be added after the signature.
        self.store.add_revision_signature_text('A', 'foo\nbar', self.transaction)
        # but must not be visible
        self.assertRaises(errors.NoSuchRevision,
                          self.store.has_signature,
                          'A',
                          self.transaction)
        # at all
        self.assertRaises(errors.NoSuchRevision,
                          self.store.get_signature_text,
                          'A',
                          self.transaction)
        # until the revision is added
        self.add_sample_rev()
        self.assertTrue(self.store.has_signature('A', self.transaction))
        self.assertEqual('foo\nbar',
                         self.store.get_signature_text('A', self.transaction))
    
    def test_add_signature_text(self):
        # add a signature to a existing revision works.
        self.add_sample_rev()
        self.assertFalse(self.store.has_signature('A', self.transaction))
        self.assertRaises(errors.NoSuchRevision,
                          self.store.get_signature_text,
                          'A',
                          self.transaction)
        self.store.add_revision_signature_text('A', 'foo\nbar', self.transaction)
        self.assertTrue(self.store.has_signature('A', self.transaction))
        self.assertEqual('foo\nbar',
                         self.store.get_signature_text('A', self.transaction))

    def test_total_size(self):
        # we get a revision count and a numeric size figure from total_size().
        count, bytes = self.store.total_size(self.transaction)
        self.assertEqual(0, count)
        self.assertEqual(0, bytes)
        self.add_sample_rev()
        count, bytes = self.store.total_size(self.transaction)
        self.assertEqual(1, count)
        self.assertNotEqual(0, bytes)
        
    def test_all_revision_ids(self):
        self.assertEqual([], self.store.all_revision_ids(self.transaction))
        self.add_sample_rev()
        self.assertEqual(['A'], self.store.all_revision_ids(self.transaction))

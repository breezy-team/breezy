# Copyright (C) 2007 Canonical Ltd
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

"""Tests for the FileCollection class."""

from bzrlib import errors
from bzrlib.file_collection import FileCollection
from bzrlib.tests import TestCaseWithMemoryTransport
from bzrlib.transport import get_transport


class TestFileCollection(TestCaseWithMemoryTransport):

    def test_initialise(self):
        t = self.get_transport()
        for name in ('index', '00index'):
            collection = FileCollection(t, name)
            collection.initialise()
            self.assertFalse(t.has(name))
            collection.save()
            self.assertEqual('', t.get_bytes(name))
        
    def test_allocate_trivial(self):
        t = self.get_transport()
        collection = FileCollection(t, 'index')
        collection.initialise()
        name = collection.allocate()
        self.assertEqual('0', name)
        self.assertFalse(t.has('index'))
        name = collection.allocate()
        self.assertEqual('1', name)
        self.assertFalse(t.has('index'))

    def test_allocate_overrun(self):
        t = self.get_transport()
        collection = FileCollection(t, 'index')
        collection.initialise()
        collection._cap = 5
        for number in xrange(5):
            name = collection.allocate()
        self.assertRaises(errors.BzrError, collection.allocate)

    def test_load(self):
        t = self.get_transport()
        collection = FileCollection(t, 'index')
        collection.initialise()
        collection.allocate()
        collection.allocate()
        collection.save()
        collection = FileCollection(t, 'index')
        collection.load()
        self.assertEqual(set(['0', '1']), collection.names())

    def test_names(self):
        t = self.get_transport()
        collection = FileCollection(t, 'index')
        collection.initialise()
        collection.allocate()
        collection.allocate()
        self.assertEqual(set(['0', '1']), collection.names())

    def test_names_on_unlistable_works(self):
        t = self.get_transport()
        collection = FileCollection(t, 'index')
        collection.initialise()
        collection.allocate()
        collection.allocate()
        collection.save()
        collection = FileCollection(
            get_transport('unlistable+' + self.get_url()), 'index')
        collection.load()
        self.assertEqual(set(['0', '1']), collection.names())

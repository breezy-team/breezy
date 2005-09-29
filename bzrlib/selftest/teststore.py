# Copyright (C) 2005 by Canonical Development Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test Store implementation
"""

from StringIO import StringIO
import os

from bzrlib.store import copy_all, ImmutableStore, RemoteStore
from bzrlib.selftest import TestCase, TestCaseInTempDir
from bzrlib.errors import BzrError, UnlistableStore
import bzrlib.store


class TestStore(TestCaseInTempDir):

    def test_multiple_add(self):
        """Multiple add with same ID should raise a BzrError"""
        store = ImmutableStore('.')
        store.add(StringIO('goodbye'), '123123')
        self.assertRaises(BzrError, store.add, StringIO('goodbye'), '123123')

    def test_total_size(self):
        store = ImmutableStore('.')
        store.add(StringIO('goodbye'), '123123')
        store.add(StringIO('goodbye2'), '123123.dsc')
        # these get gzipped - content should be stable
        self.assertEqual(store.total_size(), (2, 55))
        
    def test_copy_all(self):
        """Test copying"""
        os.mkdir('a')
        store_a = ImmutableStore('a')
        store_a.add('foo', '1')
        os.mkdir('b')
        store_b = ImmutableStore('b')
        copy_all(store_a, store_b)
        self.assertEqual(store_a['1'].read(), 'foo')
        self.assertEqual(store_b['1'].read(), 'foo')
        store_c = RemoteStore('http://example.com/')
        self.assertRaises(UnlistableStore, copy_all, store_c, store_b)


class TestMemoryStore(TestCase):
    
    def get_store(self):
        return bzrlib.store.ImmutableMemoryStore()
    
    def test_imports(self):
        from bzrlib.store import ImmutableMemoryStore

    def test_add_and_retrieve(self):
        store = self.get_store()
        store.add(StringIO('hello'), 'aa')
        self.assertNotEqual(store['aa'], None)
        self.assertEqual(store['aa'].read(), 'hello')
        store.add(StringIO('hello world'), 'bb')
        self.assertNotEqual(store['bb'], None)
        self.assertEqual(store['bb'].read(), 'hello world')

    def test_missing_is_absent(self):
        store = self.get_store()
        self.failIf('aa' in store)

    def test_adding_fails_when_present(self):
        store = self.get_store()
        store.add(StringIO('hello'), 'aa')
        self.assertRaises(bzrlib.store.StoreError,
                          store.add, StringIO('hello'), 'aa')

    def test_total_size(self):
        store = self.get_store()
        store.add(StringIO('goodbye'), '123123')
        store.add(StringIO('goodbye2'), '123123.dsc')
        self.assertEqual(store.total_size(), (2, 15))

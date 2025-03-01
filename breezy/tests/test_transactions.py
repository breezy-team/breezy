# Copyright (C) 2005, 2006, 2009, 2011 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for the behaviour of the Transaction concept in bzr."""

# import breezy specific imports here
import breezy.errors as errors
import breezy.transactions as transactions
from breezy.tests import TestCase


class DummyWeave:
    """A class that can be instantiated and compared."""

    def __init__(self, message):
        self._message = message
        self.finished = False

    def __eq__(self, other):
        if other is None:
            return False
        return self._message == other._message

    def __hash__(self):
        return hash((type(self), self._message))

    def transaction_finished(self):
        self.finished = True


class TestSymbols(TestCase):
    def test_public_symbols(self):
        from breezy.transactions import (
            PassThroughTransaction,  # noqa: F401
            ReadOnlyTransaction,  # noqa: F401
        )


class TestReadOnlyTransaction(TestCase):
    def setUp(self):
        self.transaction = transactions.ReadOnlyTransaction()
        super().setUp()

    def test_register_clean(self):
        self.transaction.register_clean("anobject")

    def test_register_dirty_raises(self):
        self.assertRaises(
            errors.ReadOnlyError, self.transaction.register_dirty, "anobject"
        )

    def test_map(self):
        self.assertNotEqual(None, getattr(self.transaction, "map", None))

    def test_add_and_get(self):
        weave = "a weave"
        self.transaction.map.add_weave("id", weave)
        self.assertEqual(weave, self.transaction.map.find_weave("id"))

    def test_finish_returns(self):
        self.transaction.finish()

    def test_finish_does_not_tell_versioned_file_finished(self):
        # read only transactions never write, so theres no
        # need to inform versioned files about finishing
        weave = DummyWeave("a weave")
        self.transaction.finish()
        self.assertFalse(weave.finished)

    def test_zero_size_cache(self):
        self.transaction.set_cache_size(0)
        weave = DummyWeave("a weave")
        self.transaction.map.add_weave("id", weave)
        self.assertEqual(weave, self.transaction.map.find_weave("id"))
        weave = None
        # add an object, should fall right out if there are no references
        self.transaction.register_clean(self.transaction.map.find_weave("id"))
        self.assertEqual(None, self.transaction.map.find_weave("id"))
        # but if we have a reference it should stick around
        weave = DummyWeave("another weave")
        self.transaction.map.add_weave("id", weave)
        self.transaction.register_clean(self.transaction.map.find_weave("id"))
        self.assertEqual(weave, self.transaction.map.find_weave("id"))
        del weave
        # its not a weakref system
        self.assertEqual(
            DummyWeave("another weave"), self.transaction.map.find_weave("id")
        )

    def test_small_cache(self):
        self.transaction.set_cache_size(1)
        # add an object, should not fall right out if there are no references
        # sys.getrefcounts(foo)
        self.transaction.map.add_weave("id", DummyWeave("a weave"))
        self.transaction.register_clean(self.transaction.map.find_weave("id"))
        self.assertEqual(DummyWeave("a weave"), self.transaction.map.find_weave("id"))
        self.transaction.map.add_weave("id2", DummyWeave("a weave also"))
        self.transaction.register_clean(self.transaction.map.find_weave("id2"))
        # currently a fifo
        self.assertEqual(None, self.transaction.map.find_weave("id"))
        self.assertEqual(
            DummyWeave("a weave also"), self.transaction.map.find_weave("id2")
        )

    def test_small_cache_with_references(self):
        # if we have a reference it should stick around
        weave = "a weave"
        weave2 = "another weave"
        self.transaction.map.add_weave("id", weave)
        self.transaction.map.add_weave("id2", weave2)
        self.assertEqual(weave, self.transaction.map.find_weave("id"))
        self.assertEqual(weave2, self.transaction.map.find_weave("id2"))
        weave = None
        # its not a weakref system
        self.assertEqual("a weave", self.transaction.map.find_weave("id"))

    def test_precious_with_zero_size_cache(self):
        self.transaction.set_cache_size(0)
        weave = DummyWeave("a weave")
        self.transaction.map.add_weave("id", weave)
        self.assertEqual(weave, self.transaction.map.find_weave("id"))
        weave = None
        # add an object, should not fall out even with no references.
        self.transaction.register_clean(
            self.transaction.map.find_weave("id"), precious=True
        )
        self.assertEqual(DummyWeave("a weave"), self.transaction.map.find_weave("id"))

    def test_writable(self):
        self.assertFalse(self.transaction.writeable())


class TestPassThroughTransaction(TestCase):
    def test_construct(self):
        transactions.PassThroughTransaction()

    def test_register_clean(self):
        transaction = transactions.PassThroughTransaction()
        transaction.register_clean("anobject")

    def test_register_dirty(self):
        transaction = transactions.PassThroughTransaction()
        transaction.register_dirty("anobject")

    def test_map(self):
        transaction = transactions.PassThroughTransaction()
        self.assertNotEqual(None, getattr(transaction, "map", None))

    def test_add_and_get(self):
        transaction = transactions.PassThroughTransaction()
        weave = "a weave"
        transaction.map.add_weave("id", weave)
        self.assertEqual(None, transaction.map.find_weave("id"))

    def test_finish_returns(self):
        transaction = transactions.PassThroughTransaction()
        transaction.finish()

    def test_finish_tells_versioned_file_finished(self):
        # pass through transactions allow writes so they
        # need to inform versioned files about finishing
        weave = DummyWeave("a weave")
        transaction = transactions.PassThroughTransaction()
        transaction.register_dirty(weave)
        transaction.finish()
        self.assertTrue(weave.finished)

    def test_cache_is_ignored(self):
        transaction = transactions.PassThroughTransaction()
        transaction.set_cache_size(100)
        weave = "a weave"
        transaction.map.add_weave("id", weave)
        self.assertEqual(None, transaction.map.find_weave("id"))

    def test_writable(self):
        transaction = transactions.PassThroughTransaction()
        self.assertTrue(transaction.writeable())


class TestWriteTransaction(TestCase):
    def setUp(self):
        self.transaction = transactions.WriteTransaction()
        super().setUp()

    def test_register_clean(self):
        self.transaction.register_clean("anobject")

    def test_register_dirty(self):
        self.transaction.register_dirty("anobject")

    def test_map(self):
        self.assertNotEqual(None, getattr(self.transaction, "map", None))

    def test_add_and_get(self):
        weave = "a weave"
        self.transaction.map.add_weave("id", weave)
        self.assertEqual(weave, self.transaction.map.find_weave("id"))

    def test_finish_returns(self):
        self.transaction.finish()

    def test_finish_tells_versioned_file_finished(self):
        # write transactions allow writes so they
        # need to inform versioned files about finishing
        weave = DummyWeave("a weave")
        self.transaction.register_dirty(weave)
        self.transaction.finish()
        self.assertTrue(weave.finished)

    def test_zero_size_cache(self):
        self.transaction.set_cache_size(0)
        # add an object, should fall right out if there are no references
        weave = DummyWeave("a weave")
        self.transaction.map.add_weave("id", weave)
        self.assertEqual(weave, self.transaction.map.find_weave("id"))
        weave = None
        self.transaction.register_clean(self.transaction.map.find_weave("id"))
        self.assertEqual(None, self.transaction.map.find_weave("id"))
        # but if we have a reference to a clean object it should stick around
        weave = DummyWeave("another weave")
        self.transaction.map.add_weave("id", weave)
        self.transaction.register_clean(self.transaction.map.find_weave("id"))
        self.assertEqual(weave, self.transaction.map.find_weave("id"))
        del weave
        # its not a weakref system
        self.assertEqual(
            DummyWeave("another weave"), self.transaction.map.find_weave("id")
        )

    def test_zero_size_cache_dirty_objects(self):
        self.transaction.set_cache_size(0)
        # add a dirty object, which should not fall right out.
        weave = DummyWeave("a weave")
        self.transaction.map.add_weave("id", weave)
        self.assertEqual(weave, self.transaction.map.find_weave("id"))
        weave = None
        self.transaction.register_dirty(self.transaction.map.find_weave("id"))
        self.assertNotEqual(None, self.transaction.map.find_weave("id"))

    def test_clean_to_dirty(self):
        # a clean object may become dirty.
        weave = DummyWeave("A weave")
        self.transaction.map.add_weave("id", weave)
        self.transaction.register_clean(weave)
        self.transaction.register_dirty(weave)
        self.assertTrue(self.transaction.is_dirty(weave))
        self.assertFalse(self.transaction.is_clean(weave))

    def test_small_cache(self):
        self.transaction.set_cache_size(1)
        # add an object, should not fall right out if there are no references
        # sys.getrefcounts(foo)
        self.transaction.map.add_weave("id", DummyWeave("a weave"))
        self.transaction.register_clean(self.transaction.map.find_weave("id"))
        self.assertEqual(DummyWeave("a weave"), self.transaction.map.find_weave("id"))
        self.transaction.map.add_weave("id2", DummyWeave("a weave also"))
        self.transaction.register_clean(self.transaction.map.find_weave("id2"))
        # currently a fifo
        self.assertEqual(None, self.transaction.map.find_weave("id"))
        self.assertEqual(
            DummyWeave("a weave also"), self.transaction.map.find_weave("id2")
        )

    def test_small_cache_with_references(self):
        # if we have a reference it should stick around
        weave = "a weave"
        weave2 = "another weave"
        self.transaction.map.add_weave("id", weave)
        self.transaction.map.add_weave("id2", weave2)
        self.assertEqual(weave, self.transaction.map.find_weave("id"))
        self.assertEqual(weave2, self.transaction.map.find_weave("id2"))
        weave = None
        # its not a weakref system
        self.assertEqual("a weave", self.transaction.map.find_weave("id"))

    def test_precious_with_zero_size_cache(self):
        self.transaction.set_cache_size(0)
        weave = DummyWeave("a weave")
        self.transaction.map.add_weave("id", weave)
        self.assertEqual(weave, self.transaction.map.find_weave("id"))
        weave = None
        # add an object, should not fall out even with no references.
        self.transaction.register_clean(
            self.transaction.map.find_weave("id"), precious=True
        )
        self.assertEqual(DummyWeave("a weave"), self.transaction.map.find_weave("id"))

    def test_writable(self):
        self.assertTrue(self.transaction.writeable())

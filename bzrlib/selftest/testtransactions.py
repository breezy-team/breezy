# Copyright (C) 2005 by Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for the behaviour of the Transaction concept in bzr."""

# import system imports here
import os
import sys

#import bzrlib specific imports here
import bzrlib.errors as errors
from bzrlib.selftest import TestCase, TestCaseInTempDir
import bzrlib.transactions as transactions


class TestReadOnlyTransaction(TestCase):

    def test_symbols(self):
        from bzrlib.transactions import ReadOnlyTransaction

    def test_construct(self):
        transactions.ReadOnlyTransaction()

    def test_register_clean(self):
        transaction = transactions.ReadOnlyTransaction()
        transaction.register_clean("anobject")
    
    def test_commit_raises(self):
        transaction = transactions.ReadOnlyTransaction()
        self.assertRaises(errors.CommitNotPossible, transaction.commit)

    def test_map(self):
        transaction = transactions.ReadOnlyTransaction()
        self.assertNotEqual(None, getattr(transaction, "map", None))
    
    def test_add_and_get(self):
        transaction = transactions.ReadOnlyTransaction()
        weave = "a weave"
        transaction.map.add_weave("id", weave)
        self.assertEqual(weave, transaction.map.find_weave("id"))

    def test_rollback_returns(self):
        transaction = transactions.ReadOnlyTransaction()
        transaction.rollback()

    def test_finish_returns(self):
        transaction = transactions.ReadOnlyTransaction()
        transaction.finish()

        
class TestPassThroughTransaction(TestCase):

    def test_symbols(self):
        from bzrlib.transactions import PassThroughTransaction

    def test_construct(self):
        transactions.PassThroughTransaction()

    def test_register_clean(self):
        transaction = transactions.PassThroughTransaction()
        transaction.register_clean("anobject")
    
    def test_commit_nothing_returns(self):
        transaction = transactions.PassThroughTransaction()
        transaction.commit()

    def test_map(self):
        transaction = transactions.PassThroughTransaction()
        self.assertNotEqual(None, getattr(transaction, "map", None))
    
    def test_add_and_get(self):
        transaction = transactions.PassThroughTransaction()
        weave = "a weave"
        transaction.map.add_weave("id", weave)
        self.assertEqual(None, transaction.map.find_weave("id"))
        
    def test_rollback_asserts(self):
        transaction = transactions.PassThroughTransaction()
        self.assertRaises(errors.AlreadyCommitted, transaction.rollback)

    def test_finish_returns(self):
        transaction = transactions.PassThroughTransaction()
        transaction.finish()

# Copyright (C) 2010 Canonical Ltd
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

"""Tests of bzrlib test matchers."""

from testtools.matchers import *

from bzrlib.tests import TestCase
from bzrlib.tests.matchers import *


class StubTree(object):
    """Stubg for testing."""

    def __init__(self, lock_status):
        self._is_locked = lock_status

    def __str__(self):
        return u'I am da tree'

    def is_locked(self):
        return self._is_locked


class FakeUnlockable(object):
    """Something that can be unlocked."""

    def unlock(self):
        pass


class TestReturnsUnlockable(TestCase):

    def test___str__(self):
        matcher = ReturnsUnlockable(StubTree(True))
        self.assertEqual(
            'ReturnsUnlockable(lockable_thing=I am da tree)',
            str(matcher))

    def test_match(self):
        stub_tree = StubTree(False)
        matcher = ReturnsUnlockable(stub_tree)
        self.assertThat(matcher.match(lambda:FakeUnlockable()), Equals(None))

    def test_mismatch(self):
        stub_tree = StubTree(True)
        matcher = ReturnsUnlockable(stub_tree)
        mismatch = matcher.match(lambda:FakeUnlockable())
        self.assertNotEqual(None, mismatch)
        self.assertThat(mismatch.describe(), Equals("I am da tree is locked"))


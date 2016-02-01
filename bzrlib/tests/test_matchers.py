# Copyright (C) 2010, 2011, 2012, 2016 Canonical Ltd
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

from bzrlib.smart.client import CallHookParams

from bzrlib.tests import (
    CapturedCall,
    TestCase,
    TestCaseWithTransport,
    )
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


class TestMatchesAncestry(TestCaseWithTransport):

    def test__str__(self):
        matcher = MatchesAncestry("A repository", "arevid")
        self.assertEqual(
            "MatchesAncestry(repository='A repository', "
            "revision_id='arevid')",
            str(matcher))

    def test_match(self):
        b = self.make_branch_builder('.')
        b.start_series()
        revid1 = b.build_commit()
        revid2 = b.build_commit()
        b.finish_series()
        branch = b.get_branch()
        m = MatchesAncestry(branch.repository, revid2)
        self.assertThat([revid2, revid1], m)
        self.assertThat([revid1, revid2], m)
        m = MatchesAncestry(branch.repository, revid1)
        self.assertThat([revid1], m)
        m = MatchesAncestry(branch.repository, "unknown")
        self.assertThat(["unknown"], m)

    def test_mismatch(self):
        b = self.make_branch_builder('.')
        b.start_series()
        revid1 = b.build_commit()
        revid2 = b.build_commit()
        b.finish_series()
        branch = b.get_branch()
        m = MatchesAncestry(branch.repository, revid1)
        mismatch = m.match([])
        self.assertIsNot(None, mismatch)
        self.assertEqual(
            "mismatched ancestry for revision '%s' was ['%s'], expected []" % (
                revid1, revid1),
            mismatch.describe())


class TestHasLayout(TestCaseWithTransport):

    def test__str__(self):
        matcher = HasLayout([("a", "a-id")])
        self.assertEqual("HasLayout([('a', 'a-id')])", str(matcher))

    def test_match(self):
        t = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        t.add(['a', 'b', 'b/c'], ['a-id', 'b-id', 'c-id'])
        self.assertThat(t, HasLayout(['', 'a', 'b/', 'b/c']))
        self.assertThat(t, HasLayout(
            [('', t.get_root_id()),
             ('a', 'a-id'),
             ('b/', 'b-id'),
             ('b/c', 'c-id')]))

    def test_mismatch(self):
        t = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        t.add(['a', 'b', 'b/c'], ['a-id', 'b-id', 'c-id'])
        mismatch = HasLayout(['a']).match(t)
        self.assertIsNot(None, mismatch)
        self.assertEqual(
            "['a'] != [u'', u'a', u'b/', u'b/c']",
            mismatch.describe())

    def test_no_dirs(self):
        # Some tree/repository formats do not support versioned directories
        t = self.make_branch_and_tree('.')
        t.has_versioned_directories = lambda: False
        self.build_tree(['a', 'b/', 'b/c'])
        t.add(['a', 'b', 'b/c'], ['a-id', 'b-id', 'c-id'])
        self.assertIs(None, HasLayout(['', 'a', 'b/', 'b/c']).match(t))
        self.assertIs(None, HasLayout(['', 'a', 'b/', 'b/c', 'd/']).match(t))
        mismatch = HasLayout([u'', u'a', u'd/']).match(t)
        self.assertIsNot(None, mismatch)
        self.assertEqual(
            "[u'', u'a'] != [u'', u'a', u'b/', u'b/c']",
            mismatch.describe())


class TestContainsNoVfsCalls(TestCase):

    def _make_call(self, method, args):
        return CapturedCall(CallHookParams(method, args, None, None, None), 0)

    def test__str__(self):
        self.assertEqual("ContainsNoVfsCalls()", str(ContainsNoVfsCalls()))

    def test_empty(self):
        self.assertIs(None, ContainsNoVfsCalls().match([]))

    def test_no_vfs_calls(self):
        calls = [self._make_call("Branch.get_config_file", [])]
        self.assertIs(None, ContainsNoVfsCalls().match(calls))

    def test_ignores_unknown(self):
        calls = [self._make_call("unknown", [])]
        self.assertIs(None, ContainsNoVfsCalls().match(calls))

    def test_match(self):
        calls = [self._make_call("append", ["file"]),
                 self._make_call("Branch.get_config_file", [])]
        mismatch = ContainsNoVfsCalls().match(calls)
        self.assertIsNot(None, mismatch)
        self.assertEqual([calls[0].call], mismatch.vfs_calls)
        self.assertEqual("no VFS calls expected, got: append('file')""",
                mismatch.describe())


class TestRevisionHistoryMatches(TestCaseWithTransport):

    def test_empty(self):
        tree = self.make_branch_and_tree('.')
        matcher = RevisionHistoryMatches([])
        self.assertIs(None, matcher.match(tree.branch))

    def test_matches(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('msg1', rev_id='a')
        tree.commit('msg2', rev_id='b')
        matcher = RevisionHistoryMatches(['a', 'b'])
        self.assertIs(None, matcher.match(tree.branch))

    def test_mismatch(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('msg1', rev_id='a')
        tree.commit('msg2', rev_id='b')
        matcher = RevisionHistoryMatches(['a', 'b', 'c'])
        self.assertEqual(
            "['a', 'b', 'c'] != ['a', 'b']",
            matcher.match(tree.branch).describe())

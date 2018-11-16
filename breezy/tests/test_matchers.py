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

"""Tests of breezy test matchers."""

from testtools.matchers import *

from ..bzr.smart.client import CallHookParams
from ..sixish import PY3

from . import (
    CapturedCall,
    TestCase,
    TestCaseWithTransport,
    )
from .matchers import *


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
        self.assertThat(matcher.match(lambda: FakeUnlockable()), Equals(None))

    def test_mismatch(self):
        stub_tree = StubTree(True)
        matcher = ReturnsUnlockable(stub_tree)
        mismatch = matcher.match(lambda: FakeUnlockable())
        self.assertNotEqual(None, mismatch)
        self.assertThat(mismatch.describe(), Equals("I am da tree is locked"))


class TestMatchesAncestry(TestCaseWithTransport):

    def test__str__(self):
        matcher = MatchesAncestry("A repository", b"arevid")
        self.assertEqual(
            "MatchesAncestry(repository='A repository', "
            "revision_id=%r)" % (b'arevid', ),
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
        m = MatchesAncestry(branch.repository, b"unknown")
        self.assertThat([b"unknown"], m)

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
            "mismatched ancestry for revision %r was [%r], expected []" % (
                revid1, revid1),
            mismatch.describe())


class TestHasLayout(TestCaseWithTransport):

    def test__str__(self):
        matcher = HasLayout([(b"a", b"a-id")])
        self.assertEqual("HasLayout(%r)" % ([(b'a', b'a-id')], ), str(matcher))

    def test_match(self):
        t = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        t.add(['a', 'b', 'b/c'], [b'a-id', b'b-id', b'c-id'])
        self.assertThat(t, HasLayout(['', 'a', 'b/', 'b/c']))
        self.assertThat(t, HasLayout(
            [('', t.get_root_id()),
             ('a', b'a-id'),
             ('b/', b'b-id'),
             ('b/c', b'c-id')]))

    def test_mismatch(self):
        t = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        t.add(['a', 'b', 'b/c'], [b'a-id', b'b-id', b'c-id'])
        mismatch = HasLayout(['a']).match(t)
        self.assertIsNot(None, mismatch)
        if PY3:
            self.assertEqual(
                set(("['', 'a', 'b/', 'b/c']", "['a']")),
                set(mismatch.describe().split(" != ")))
        else:
            self.assertEqual(
                set(("[u'', u'a', u'b/', u'b/c']", "['a']")),
                set(mismatch.describe().split(" != ")))

    def test_no_dirs(self):
        # Some tree/repository formats do not support versioned directories
        t = self.make_branch_and_tree('.')
        t.has_versioned_directories = lambda: False
        self.build_tree(['a', 'b/', 'b/c'])
        t.add(['a', 'b', 'b/c'], [b'a-id', b'b-id', b'c-id'])
        self.assertIs(None, HasLayout(['', 'a', 'b/', 'b/c']).match(t))
        self.assertIs(None, HasLayout(['', 'a', 'b/', 'b/c', 'd/']).match(t))
        mismatch = HasLayout([u'', u'a', u'd/']).match(t)
        self.assertIsNot(None, mismatch)
        if PY3:
            self.assertEqual(
                set(("['', 'a', 'b/', 'b/c']", "['', 'a']")),
                set(mismatch.describe().split(" != ")))
        else:
            self.assertEqual(
                set(("[u'', u'a', u'b/', u'b/c']", "[u'', u'a']")),
                set(mismatch.describe().split(" != ")))


class TestHasPathRelations(TestCaseWithTransport):

    def test__str__(self):
        t = self.make_branch_and_tree('.')
        matcher = HasPathRelations(t, [("a", "b")])
        self.assertEqual("HasPathRelations(%r, %r)" %
                         (t, [('a', 'b')]), str(matcher))

    def test_match(self):
        t = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        t.add(['a', 'b', 'b/c'])
        self.assertThat(t, HasPathRelations(t,
                                            [('', ''),
                                             ('a', 'a'),
                                                ('b/', 'b/'),
                                                ('b/c', 'b/c')]))

    def test_mismatch(self):
        t = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])
        t.add(['a', 'b', 'b/c'])
        mismatch = HasPathRelations(t, [('a', 'a')]).match(t)
        self.assertIsNot(None, mismatch)


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
        calls = [self._make_call(b"append", [b"file"]),
                 self._make_call(b"Branch.get_config_file", [])]
        mismatch = ContainsNoVfsCalls().match(calls)
        self.assertIsNot(None, mismatch)
        self.assertEqual([calls[0].call], mismatch.vfs_calls)
        self.assertIn(mismatch.describe(), [
            "no VFS calls expected, got: b'append'(b'file')",
            "no VFS calls expected, got: append('file')"])


class TestRevisionHistoryMatches(TestCaseWithTransport):

    def test_empty(self):
        tree = self.make_branch_and_tree('.')
        matcher = RevisionHistoryMatches([])
        self.assertIs(None, matcher.match(tree.branch))

    def test_matches(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('msg1', rev_id=b'a')
        tree.commit('msg2', rev_id=b'b')
        matcher = RevisionHistoryMatches([b'a', b'b'])
        self.assertIs(None, matcher.match(tree.branch))

    def test_mismatch(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('msg1', rev_id=b'a')
        tree.commit('msg2', rev_id=b'b')
        matcher = RevisionHistoryMatches([b'a', b'b', b'c'])
        if PY3:
            self.assertEqual(
                set(("[b'a', b'b']", "[b'a', b'b', b'c']")),
                set(matcher.match(tree.branch).describe().split(" != ")))
        else:
            self.assertEqual(
                set(("['a', 'b']", "['a', 'b', 'c']")),
                set(matcher.match(tree.branch).describe().split(" != ")))

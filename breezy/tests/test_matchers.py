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

from . import TestCase, TestCaseWithTransport
from .matchers import *


class StubTree:
    """Stubg for testing."""

    def __init__(self, lock_status):
        self._is_locked = lock_status

    def __str__(self):
        return "I am da tree"

    def is_locked(self):
        return self._is_locked


class FakeUnlockable:
    """Something that can be unlocked."""

    def unlock(self):
        pass


class TestReturnsUnlockable(TestCase):
    def test___str__(self):
        matcher = ReturnsUnlockable(StubTree(True))
        self.assertEqual("ReturnsUnlockable(lockable_thing=I am da tree)", str(matcher))

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
            "MatchesAncestry(repository='A repository', revision_id={!r})".format(
                b"arevid"
            ),
            str(matcher),
        )

    def test_match(self):
        b = self.make_branch_builder(".")
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
        b = self.make_branch_builder(".")
        b.start_series()
        revid1 = b.build_commit()
        b.build_commit()
        b.finish_series()
        branch = b.get_branch()
        m = MatchesAncestry(branch.repository, revid1)
        mismatch = m.match([])
        self.assertIsNot(None, mismatch)
        self.assertEqual(
            "mismatched ancestry for revision {!r} was [{!r}], expected []".format(
                revid1, revid1
            ),
            mismatch.describe(),
        )


class TestHasLayout(TestCaseWithTransport):
    def test__str__(self):
        matcher = HasLayout([(b"a", b"a-id")])
        self.assertEqual("HasLayout({!r})".format([(b"a", b"a-id")]), str(matcher))

    def test_match(self):
        t = self.make_branch_and_tree(".")
        self.build_tree(["a", "b/", "b/c"])
        t.add(["a", "b", "b/c"], ids=[b"a-id", b"b-id", b"c-id"])
        self.assertThat(t, HasLayout(["", "a", "b/", "b/c"]))
        self.assertThat(
            t,
            HasLayout(
                [("", t.path2id("")), ("a", b"a-id"), ("b/", b"b-id"), ("b/c", b"c-id")]
            ),
        )

    def test_mismatch(self):
        t = self.make_branch_and_tree(".")
        self.build_tree(["a", "b/", "b/c"])
        t.add(["a", "b", "b/c"], ids=[b"a-id", b"b-id", b"c-id"])
        mismatch = HasLayout(["a"]).match(t)
        self.assertIsNot(None, mismatch)
        self.assertEqual(
            {"['', 'a', 'b/', 'b/c']", "['a']"}, set(mismatch.describe().split(" != "))
        )

    def test_no_dirs(self):
        # Some tree/repository formats do not support versioned directories
        t = self.make_branch_and_tree(".")
        t.has_versioned_directories = lambda: False
        self.build_tree(["a", "b/", "b/c"])
        t.add(["a", "b", "b/c"], ids=[b"a-id", b"b-id", b"c-id"])
        self.assertIs(None, HasLayout(["", "a", "b/", "b/c"]).match(t))
        self.assertIs(None, HasLayout(["", "a", "b/", "b/c", "d/"]).match(t))
        mismatch = HasLayout(["", "a", "d/"]).match(t)
        self.assertIsNot(None, mismatch)
        self.assertEqual(
            {"['', 'a', 'b/', 'b/c']", "['', 'a']"},
            set(mismatch.describe().split(" != ")),
        )


class TestHasPathRelations(TestCaseWithTransport):
    def test__str__(self):
        t = self.make_branch_and_tree(".")
        matcher = HasPathRelations(t, [("a", "b")])
        self.assertEqual(
            "HasPathRelations({!r}, {!r})".format(t, [("a", "b")]), str(matcher)
        )

    def test_match(self):
        t = self.make_branch_and_tree(".")
        self.build_tree(["a", "b/", "b/c"])
        t.add(["a", "b", "b/c"])
        self.assertThat(
            t, HasPathRelations(t, [("", ""), ("a", "a"), ("b/", "b/"), ("b/c", "b/c")])
        )

    def test_mismatch(self):
        t = self.make_branch_and_tree(".")
        self.build_tree(["a", "b/", "b/c"])
        t.add(["a", "b", "b/c"])
        mismatch = HasPathRelations(t, [("a", "a")]).match(t)
        self.assertIsNot(None, mismatch)


class TestRevisionHistoryMatches(TestCaseWithTransport):
    def test_empty(self):
        tree = self.make_branch_and_tree(".")
        matcher = RevisionHistoryMatches([])
        self.assertIs(None, matcher.match(tree.branch))

    def test_matches(self):
        tree = self.make_branch_and_tree(".")
        tree.commit("msg1", rev_id=b"a")
        tree.commit("msg2", rev_id=b"b")
        matcher = RevisionHistoryMatches([b"a", b"b"])
        self.assertIs(None, matcher.match(tree.branch))

    def test_mismatch(self):
        tree = self.make_branch_and_tree(".")
        tree.commit("msg1", rev_id=b"a")
        tree.commit("msg2", rev_id=b"b")
        matcher = RevisionHistoryMatches([b"a", b"b", b"c"])
        self.assertEqual(
            {"[b'a', b'b']", "[b'a', b'b', b'c']"},
            set(matcher.match(tree.branch).describe().split(" != ")),
        )

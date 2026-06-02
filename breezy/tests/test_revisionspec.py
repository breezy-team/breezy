# Copyright (C) 2005-2012, 2016 Canonical Ltd
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

import datetime
import time

from vcsgraph.errors import NoCommonAncestor

from breezy import errors
from breezy import revision as _mod_revision
from breezy.tests import TestCaseWithTransport

from ..revisionspec import (
    InvalidRevisionSpec,
    RevisionInfo,
    RevisionSpec,
    RevisionSpec_dwim,
    RevisionSpec_tag,
)


def spec_in_history(spec, branch):
    """A simple helper to change a revision spec into a branch search."""
    return RevisionSpec.from_string(spec).in_history(branch)


# Basic class, which just creates a really basic set of revisions
class TestRevisionSpec(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        # this sets up a revision graph:
        # r1: []             1
        # alt_r2: [r1]       1.1.1
        # r2: [r1, alt_r2]   2

        self.tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/a"])
        self.tree.lock_write()
        self.addCleanup(self.tree.unlock)
        self.tree.add(["a"])
        self.tree.commit("a", rev_id=b"r1")

        self.tree2 = self.tree.controldir.sprout("tree2").open_workingtree()
        self.tree2.commit("alt", rev_id=b"alt_r2")

        self.tree.merge_from_branch(self.tree2.branch)
        self.tree.commit("second", rev_id=b"r2")

    def get_in_history(self, revision_spec):
        return spec_in_history(revision_spec, self.tree.branch)

    def assertInHistoryIs(self, exp_revno, exp_revision_id, revision_spec):
        rev_info = self.get_in_history(revision_spec)
        self.assertEqual(
            exp_revno,
            rev_info.revno,
            f"Revision spec: {revision_spec!r} returned wrong revno: {exp_revno!r} != {rev_info.revno!r}",
        )
        self.assertEqual(
            exp_revision_id,
            rev_info.rev_id,
            f"Revision spec: {revision_spec!r} returned wrong revision id:"
            f" {exp_revision_id!r} != {rev_info.rev_id!r}",
        )

    def assertInvalid(self, revision_spec, extra="", invalid_as_revision_id=True):
        try:
            self.get_in_history(revision_spec)
        except InvalidRevisionSpec as e:
            self.assertEqual(revision_spec, e.spec)
            self.assertEqual(extra, e.extra)
        else:
            self.fail(
                "Expected InvalidRevisionSpec to be raised for"
                f" {revision_spec!r}.in_history"
            )
        if invalid_as_revision_id:
            try:
                spec = RevisionSpec.from_string(revision_spec)
                spec.as_revision_id(self.tree.branch)
            except InvalidRevisionSpec as e:
                self.assertEqual(revision_spec, e.spec)
                self.assertEqual(extra, e.extra)
            else:
                self.fail(
                    "Expected InvalidRevisionSpec to be raised for"
                    f" {revision_spec!r}.as_revision_id"
                )

    def assertAsRevisionId(self, revision_id, revision_spec):
        """Calling as_revision_id() should return the specified id."""
        spec = RevisionSpec.from_string(revision_spec)
        self.assertEqual(revision_id, spec.as_revision_id(self.tree.branch))

    def get_as_tree(self, revision_spec, tree=None):
        if tree is None:
            tree = self.tree
        spec = RevisionSpec.from_string(revision_spec)
        return spec.as_tree(tree.branch)


class RevisionSpecMatchOnTrap(RevisionSpec):
    def _match_on(self, branch, revs):
        self.last_call = (branch, revs)
        return super()._match_on(branch, revs)


class TestRevisionSpecBase(TestRevisionSpec):
    def test_wants_no_revision_history(self):
        # If wants_revision_history = False, then _match_on should get None for
        # the branch revision history
        spec = RevisionSpecMatchOnTrap("foo", _internal=True)
        spec.in_history(self.tree.branch)

        self.assertEqual((self.tree.branch, None), spec.last_call)


class TestOddRevisionSpec(TestRevisionSpec):
    """Test things that aren't normally thought of as revision specs."""

    def test_none(self):
        self.assertInHistoryIs(None, None, None)

    def test_object(self):
        self.assertRaises(TypeError, RevisionSpec.from_string, object())


class RevisionSpec_bork(RevisionSpec):
    prefix = "irrelevant:"

    def _match_on(self, branch, revs):
        if self.spec == "bork":
            return RevisionInfo.from_revision_id(branch, b"r1")
        else:
            raise InvalidRevisionSpec(self.spec, branch)


class TestRevisionSpec_dwim(TestRevisionSpec):
    # Don't need to test revno's explicitly since TRS_revno already
    # covers that well for us
    def test_dwim_spec_revno(self):
        self.assertInHistoryIs(2, b"r2", "2")
        self.assertAsRevisionId(b"alt_r2", "1.1.1")

    def test_dwim_spec_revid(self):
        self.assertInHistoryIs(2, b"r2", "r2")

    def test_dwim_spec_tag(self):
        self.tree.branch.tags.set_tag("footag", b"r1")
        self.assertAsRevisionId(b"r1", "footag")
        self.tree.branch.tags.delete_tag("footag")
        self.assertRaises(InvalidRevisionSpec, self.get_in_history, "footag")

    def test_dwim_spec_tag_that_looks_like_revno(self):
        # Test that we slip past revno with things that look like revnos,
        # but aren't.  Tags are convenient for testing this since we can
        # make them look however we want.
        self.tree.branch.tags.set_tag("3", b"r2")
        self.assertAsRevisionId(b"r2", "3")
        self.build_tree(["tree/b"])
        self.tree.add(["b"])
        self.tree.commit("b", rev_id=b"r3")
        self.assertAsRevisionId(b"r3", "3")

    def test_dwim_spec_date(self):
        self.assertAsRevisionId(b"r1", "today")

    def test_dwim_spec_branch(self):
        self.assertInHistoryIs(None, b"alt_r2", "tree2")

    def test_dwim_spec_nonexistent(self):
        self.assertInvalid("somethingrandom", invalid_as_revision_id=False)
        self.assertInvalid("-1.1", invalid_as_revision_id=False)
        self.assertInvalid(".1", invalid_as_revision_id=False)
        self.assertInvalid("1..1", invalid_as_revision_id=False)
        self.assertInvalid("1.2..1", invalid_as_revision_id=False)
        self.assertInvalid("1.", invalid_as_revision_id=False)

    def test_append_dwim_revspec(self):
        original_dwim_revspecs = list(RevisionSpec_dwim._possible_revspecs)

        def reset_dwim_revspecs():
            RevisionSpec_dwim._possible_revspecs = original_dwim_revspecs

        self.addCleanup(reset_dwim_revspecs)
        RevisionSpec_dwim.append_possible_revspec(RevisionSpec_bork)
        self.assertAsRevisionId(b"r1", "bork")

    def test_append_lazy_dwim_revspec(self):
        original_dwim_revspecs = list(RevisionSpec_dwim._possible_revspecs)

        def reset_dwim_revspecs():
            RevisionSpec_dwim._possible_revspecs = original_dwim_revspecs

        self.addCleanup(reset_dwim_revspecs)
        RevisionSpec_dwim.append_possible_lazy_revspec(
            "breezy.tests.test_revisionspec", "RevisionSpec_bork"
        )
        self.assertAsRevisionId(b"r1", "bork")


class TestRevisionSpec_revno(TestRevisionSpec):
    def test_positive_int(self):
        self.assertInHistoryIs(0, b"null:", "0")
        self.assertInHistoryIs(1, b"r1", "1")
        self.assertInHistoryIs(2, b"r2", "2")
        self.assertInvalid("3")

    def test_dotted_decimal(self):
        self.assertInHistoryIs(None, b"alt_r2", "1.1.1")
        self.assertInvalid("1.1.123")

    def test_negative_int(self):
        self.assertInHistoryIs(2, b"r2", "-1")
        self.assertInHistoryIs(1, b"r1", "-2")

        self.assertInHistoryIs(1, b"r1", "-3")
        self.assertInHistoryIs(1, b"r1", "-4")
        self.assertInHistoryIs(1, b"r1", "-100")

    def test_positive(self):
        self.assertInHistoryIs(0, b"null:", "revno:0")
        self.assertInHistoryIs(1, b"r1", "revno:1")
        self.assertInHistoryIs(2, b"r2", "revno:2")

        self.assertInvalid("revno:3")

    def test_negative(self):
        self.assertInHistoryIs(2, b"r2", "revno:-1")
        self.assertInHistoryIs(1, b"r1", "revno:-2")

        self.assertInHistoryIs(1, b"r1", "revno:-3")
        self.assertInHistoryIs(1, b"r1", "revno:-4")

    def test_invalid_number(self):
        # Get the right exception text
        try:
            int("X")
        except ValueError as e:
            self.assertInvalid("revno:X", extra="\n" + str(e))
        else:
            self.fail()

    def test_missing_number_and_branch(self):
        self.assertInvalid(
            "revno::", extra="\ncannot have an empty revno and no branch"
        )

    def test_invalid_number_with_branch(self):
        try:
            int("X")
        except ValueError as e:
            self.assertInvalid("revno:X:tree2", extra="\n" + str(e))
        else:
            self.fail()

    def test_non_exact_branch(self):
        # It seems better to require an exact path to the branch
        # Branch.open() rather than using Branch.open_containing()
        spec = RevisionSpec.from_string("revno:2:tree2/a")
        self.assertRaises(errors.NotBranchError, spec.in_history, self.tree.branch)

    def test_with_branch(self):
        # Passing a URL overrides the supplied branch path
        revinfo = self.get_in_history("revno:2:tree2")
        self.assertNotEqual(self.tree.branch.base, revinfo.branch.base)
        self.assertEqual(self.tree2.branch.base, revinfo.branch.base)
        self.assertEqual(2, revinfo.revno)
        self.assertEqual(b"alt_r2", revinfo.rev_id)

    def test_int_with_branch(self):
        revinfo = self.get_in_history("2:tree2")
        self.assertNotEqual(self.tree.branch.base, revinfo.branch.base)
        self.assertEqual(self.tree2.branch.base, revinfo.branch.base)
        self.assertEqual(2, revinfo.revno)
        self.assertEqual(b"alt_r2", revinfo.rev_id)

    def test_with_url(self):
        url = self.get_url() + "/tree2"
        revinfo = self.get_in_history(f"revno:2:{url}")
        self.assertNotEqual(self.tree.branch.base, revinfo.branch.base)
        self.assertEqual(self.tree2.branch.base, revinfo.branch.base)
        self.assertEqual(2, revinfo.revno)
        self.assertEqual(b"alt_r2", revinfo.rev_id)

    def test_negative_with_url(self):
        url = self.get_url() + "/tree2"
        revinfo = self.get_in_history(f"revno:-1:{url}")
        self.assertNotEqual(self.tree.branch.base, revinfo.branch.base)
        self.assertEqual(self.tree2.branch.base, revinfo.branch.base)
        self.assertEqual(2, revinfo.revno)
        self.assertEqual(b"alt_r2", revinfo.rev_id)

    def test_different_history_lengths(self):
        # Make sure we use the revisions and offsets in the supplied branch
        # not the ones in the original branch.
        self.tree2.commit("three", rev_id=b"r3")
        self.assertInHistoryIs(3, b"r3", "revno:3:tree2")
        self.assertInHistoryIs(3, b"r3", "revno:-1:tree2")

    def test_invalid_branch(self):
        self.assertRaises(errors.NotBranchError, self.get_in_history, "revno:-1:tree3")

    def test_invalid_revno_in_branch(self):
        self.tree.commit("three", rev_id=b"r3")
        self.assertInvalid("revno:3:tree2")

    def test_revno_n_path(self):
        """Old revno:N:path tests."""
        wta = self.make_branch_and_tree("a")
        ba = wta.branch

        wta.commit("Commit one", rev_id=b"a@r-0-1")
        wta.commit("Commit two", rev_id=b"a@r-0-2")
        wta.commit("Commit three", rev_id=b"a@r-0-3")

        wtb = self.make_branch_and_tree("b")
        bb = wtb.branch

        wtb.commit("Commit one", rev_id=b"b@r-0-1")
        wtb.commit("Commit two", rev_id=b"b@r-0-2")
        wtb.commit("Commit three", rev_id=b"b@r-0-3")

        self.assertEqual((1, b"a@r-0-1"), spec_in_history("revno:1:a/", ba))
        # The argument of in_history should be ignored since it is
        # redundant with the path in the spec.
        self.assertEqual((1, b"a@r-0-1"), spec_in_history("revno:1:a/", None))
        self.assertEqual((1, b"a@r-0-1"), spec_in_history("revno:1:a/", bb))
        self.assertEqual((2, b"b@r-0-2"), spec_in_history("revno:2:b/", None))

    def test_as_revision_id(self):
        self.assertAsRevisionId(b"null:", "0")
        self.assertAsRevisionId(b"r1", "1")
        self.assertAsRevisionId(b"r2", "2")
        self.assertAsRevisionId(b"r1", "-2")
        self.assertAsRevisionId(b"r2", "-1")
        self.assertAsRevisionId(b"alt_r2", "1.1.1")

    def test_as_tree(self):
        tree = self.get_as_tree("0")
        self.assertEqual(_mod_revision.NULL_REVISION, tree.get_revision_id())
        tree = self.get_as_tree("1")
        self.assertEqual(b"r1", tree.get_revision_id())
        tree = self.get_as_tree("2")
        self.assertEqual(b"r2", tree.get_revision_id())
        tree = self.get_as_tree("-2")
        self.assertEqual(b"r1", tree.get_revision_id())
        tree = self.get_as_tree("-1")
        self.assertEqual(b"r2", tree.get_revision_id())
        tree = self.get_as_tree("1.1.1")
        self.assertEqual(b"alt_r2", tree.get_revision_id())


class TestRevisionSpec_revid(TestRevisionSpec):
    def test_in_history(self):
        # We should be able to access revisions that are directly
        # in the history.
        self.assertInHistoryIs(1, b"r1", "revid:r1")
        self.assertInHistoryIs(2, b"r2", "revid:r2")

    def test_missing(self):
        self.assertInvalid("revid:r3", invalid_as_revision_id=False)

    def test_merged(self):
        """We can reach revisions in the ancestry."""
        self.assertInHistoryIs(None, b"alt_r2", "revid:alt_r2")

    def test_not_here(self):
        self.tree2.commit("alt third", rev_id=b"alt_r3")
        # It exists in tree2, but not in tree
        self.assertInvalid("revid:alt_r3", invalid_as_revision_id=False)

    def test_in_repository(self):
        """We can get any revision id in the repository."""
        # XXX: This may change in the future, but for now, it is true
        self.tree2.commit("alt third", rev_id=b"alt_r3")
        self.tree.branch.fetch(self.tree2.branch, b"alt_r3")
        self.assertInHistoryIs(None, b"alt_r3", "revid:alt_r3")

    def test_unicode(self):
        """We correctly convert a unicode ui string to an encoded revid."""
        revision_id = "\N{SNOWMAN}".encode()
        self.tree.commit("unicode", rev_id=revision_id)
        self.assertInHistoryIs(3, revision_id, "revid:\N{SNOWMAN}")
        self.assertInHistoryIs(3, revision_id, "revid:" + revision_id.decode("utf-8"))

    def test_as_revision_id(self):
        self.assertAsRevisionId(b"r1", "revid:r1")
        self.assertAsRevisionId(b"r2", "revid:r2")
        self.assertAsRevisionId(b"alt_r2", "revid:alt_r2")


class TestRevisionSpec_last(TestRevisionSpec):
    def test_positive(self):
        self.assertInHistoryIs(2, b"r2", "last:1")
        self.assertInHistoryIs(1, b"r1", "last:2")
        self.assertInHistoryIs(0, b"null:", "last:3")

    def test_empty(self):
        self.assertInHistoryIs(2, b"r2", "last:")

    def test_negative(self):
        self.assertInvalid("last:-1", extra="\nyou must supply a positive value")

    def test_missing(self):
        self.assertInvalid("last:4")

    def test_no_history(self):
        tree = self.make_branch_and_tree("tree3")

        self.assertRaises(errors.NoCommits, spec_in_history, "last:", tree.branch)

    def test_not_a_number(self):
        last_e = None
        try:
            int("Y")
        except ValueError as e:
            last_e = e
        self.assertInvalid("last:Y", extra="\n" + str(last_e))

    def test_as_revision_id(self):
        self.assertAsRevisionId(b"r2", "last:1")
        self.assertAsRevisionId(b"r1", "last:2")


class TestRevisionSpec_before(TestRevisionSpec):
    def test_int(self):
        self.assertInHistoryIs(1, b"r1", "before:2")
        self.assertInHistoryIs(1, b"r1", "before:-1")

    def test_before_one(self):
        self.assertInHistoryIs(0, b"null:", "before:1")

    def test_before_none(self):
        self.assertInvalid("before:0", extra="\ncannot go before the null: revision")

    def test_revid(self):
        self.assertInHistoryIs(1, b"r1", "before:revid:r2")

    def test_last(self):
        self.assertInHistoryIs(1, b"r1", "before:last:1")

    def test_alt_revid(self):
        # This will grab the left-most ancestor for alternate histories
        self.assertInHistoryIs(1, b"r1", "before:revid:alt_r2")

    def test_alt_no_parents(self):
        new_tree = self.make_branch_and_tree("new_tree")
        new_tree.commit("first", rev_id=b"new_r1")
        self.tree.branch.fetch(new_tree.branch, b"new_r1")
        self.assertInHistoryIs(0, b"null:", "before:revid:new_r1")

    def test_as_revision_id(self):
        self.assertAsRevisionId(b"r1", "before:revid:r2")
        self.assertAsRevisionId(b"r1", "before:2")
        self.assertAsRevisionId(b"r1", "before:1.1.1")
        self.assertAsRevisionId(b"r1", "before:revid:alt_r2")


class TestRevisionSpec_tag(TestRevisionSpec):
    def make_branch_and_tree(self, relpath):
        # override format as the default one may not support tags
        return TestRevisionSpec.make_branch_and_tree(
            self, relpath, format="dirstate-tags"
        )

    def test_from_string_tag(self):
        spec = RevisionSpec.from_string("tag:bzr-0.14")
        self.assertIsInstance(spec, RevisionSpec_tag)
        self.assertEqual(spec.spec, "bzr-0.14")

    def test_lookup_tag(self):
        self.tree.branch.tags.set_tag("bzr-0.14", b"r1")
        self.assertInHistoryIs(1, b"r1", "tag:bzr-0.14")
        self.tree.branch.tags.set_tag("null_rev", b"null:")
        self.assertInHistoryIs(0, b"null:", "tag:null_rev")

    def test_failed_lookup(self):
        # tags that don't exist give a specific message: arguably we should
        # just give InvalidRevisionSpec but I think this is more helpful
        self.assertRaises(errors.NoSuchTag, self.get_in_history, "tag:some-random-tag")

    def test_as_revision_id(self):
        self.tree.branch.tags.set_tag("my-tag", b"r2")
        self.tree.branch.tags.set_tag("null_rev", b"null:")
        self.assertAsRevisionId(b"r2", "tag:my-tag")
        self.assertAsRevisionId(b"null:", "tag:null_rev")
        self.assertAsRevisionId(b"r1", "before:tag:my-tag")


class TestRevisionSpec_date(TestRevisionSpec):
    def setUp(self):
        super(TestRevisionSpec, self).setUp()

        new_tree = self.make_branch_and_tree("new_tree")
        self.revid1 = new_tree.commit(
            "Commit one", timestamp=time.time() - 60 * 60 * 24
        )
        self.revid2 = new_tree.commit("Commit two")
        self.revid3 = new_tree.commit("Commit three")

        self.tree = new_tree

    def test_tomorrow(self):
        self.assertInvalid("date:tomorrow")

    def test_today(self):
        self.assertInHistoryIs(2, self.revid2, "date:today")
        self.assertInHistoryIs(1, self.revid1, "before:date:today")

    def test_yesterday(self):
        self.assertInHistoryIs(1, self.revid1, "date:yesterday")

    def test_invalid(self):
        self.assertInvalid("date:foobar", extra="\ninvalid date")
        # You must have '-' between year/month/day
        self.assertInvalid("date:20040404", extra="\ninvalid date")
        # Need 2 digits for each date piece
        self.assertInvalid("date:2004-4-4", extra="\ninvalid date")

    def test_day(self):
        now = datetime.datetime.now()
        self.assertInHistoryIs(
            2, self.revid2, "date:%04d-%02d-%02d" % (now.year, now.month, now.day)
        )

    def test_as_revision_id(self):
        self.assertAsRevisionId(self.revid2, "date:today")


class TestRevisionSpec_date_no_revno(TestRevisionSpec_date):
    # some formats don't implement .revno(), so it triggers a different codepath

    def get_in_history(self, revision_spec):
        old_revno = self.overrideAttr(self.tree.branch, "revno", lambda: None)
        try:
            return spec_in_history(revision_spec, self.tree.branch)
        finally:
            self.tree.branch.revno = old_revno

    def test_today(self):
        self.assertInHistoryIs(2, self.revid2, "date:today")
        # Drop before: since it messes with our monkeypatching of Branch.revno.


class TestRevisionSpec_ancestor(TestRevisionSpec):
    def test_non_exact_branch(self):
        # It seems better to require an exact path to the branch
        # Branch.open() rather than using Branch.open_containing()
        self.assertRaises(
            errors.NotBranchError, self.get_in_history, "ancestor:tree2/a"
        )

    def test_simple(self):
        # Common ancestor of trees is 'alt_r2'
        self.assertInHistoryIs(None, b"alt_r2", "ancestor:tree2")

        # Going the other way, we get a valid revno
        tmp = self.tree
        self.tree = self.tree2
        self.tree2 = tmp
        self.assertInHistoryIs(2, b"alt_r2", "ancestor:tree")

    def test_self(self):
        self.assertInHistoryIs(2, b"r2", "ancestor:tree")

    def test_unrelated(self):
        new_tree = self.make_branch_and_tree("new_tree")

        new_tree.commit("Commit one", rev_id=b"new_r1")
        new_tree.commit("Commit two", rev_id=b"new_r2")
        new_tree.commit("Commit three", rev_id=b"new_r3")

        # With no common ancestor, we should raise another user error
        self.assertRaises(NoCommonAncestor, self.get_in_history, "ancestor:new_tree")

    def test_no_commits(self):
        new_tree = self.make_branch_and_tree("new_tree")
        self.assertRaises(
            errors.NoCommits, spec_in_history, "ancestor:new_tree", self.tree.branch
        )

        self.assertRaises(
            errors.NoCommits, spec_in_history, "ancestor:tree", new_tree.branch
        )

    def test_as_revision_id(self):
        self.assertAsRevisionId(b"alt_r2", "ancestor:tree2")

    def test_default(self):
        # We don't have a parent to default to
        self.assertRaises(errors.NotBranchError, self.get_in_history, "ancestor:")

        # Create a branch with a parent to default to
        tree3 = self.tree.controldir.sprout("tree3").open_workingtree()
        tree3.commit("foo", rev_id=b"r3")
        self.tree = tree3
        self.assertInHistoryIs(2, b"r2", "ancestor:")


class TestRevisionSpec_branch(TestRevisionSpec):
    def test_non_exact_branch(self):
        # It seems better to require an exact path to the branch
        # Branch.open() rather than using Branch.open_containing()
        self.assertRaises(errors.NotBranchError, self.get_in_history, "branch:tree2/a")

    def test_simple(self):
        self.assertInHistoryIs(None, b"alt_r2", "branch:tree2")

    def test_self(self):
        self.assertInHistoryIs(2, b"r2", "branch:tree")

    def test_unrelated(self):
        new_tree = self.make_branch_and_tree("new_tree")

        new_tree.commit("Commit one", rev_id=b"new_r1")
        new_tree.commit("Commit two", rev_id=b"new_r2")
        new_tree.commit("Commit three", rev_id=b"new_r3")

        self.assertInHistoryIs(None, b"new_r3", "branch:new_tree")

        # XXX: Right now, we use fetch() to make sure the remote revisions
        # have been pulled into the local branch. We may change that
        # behavior in the future.
        self.assertTrue(self.tree.branch.repository.has_revision(b"new_r3"))

    def test_no_commits(self):
        self.make_branch_and_tree("new_tree")
        self.assertRaises(errors.NoCommits, self.get_in_history, "branch:new_tree")
        self.assertRaises(errors.NoCommits, self.get_as_tree, "branch:new_tree")

    def test_as_revision_id(self):
        self.assertAsRevisionId(b"alt_r2", "branch:tree2")

    def test_as_tree(self):
        tree = self.get_as_tree("branch:tree", self.tree2)
        self.assertEqual(b"r2", tree.get_revision_id())
        self.assertFalse(self.tree2.branch.repository.has_revision(b"r2"))


class TestRevisionSpec_submit(TestRevisionSpec):
    def test_submit_branch(self):
        # Common ancestor of trees is 'alt_r2'
        self.assertRaises(errors.NoSubmitBranch, self.get_in_history, "submit:")
        self.tree.branch.set_parent("../tree2")
        self.assertInHistoryIs(None, b"alt_r2", "submit:")
        self.tree.branch.set_parent("bogus")
        self.assertRaises(errors.NotBranchError, self.get_in_history, "submit:")
        # submit branch overrides parent branch
        self.tree.branch.set_submit_branch("tree2")
        self.assertInHistoryIs(None, b"alt_r2", "submit:")

    def test_as_revision_id(self):
        self.tree.branch.set_submit_branch("tree2")
        self.assertAsRevisionId(b"alt_r2", "branch:tree2")


class TestRevisionSpec_mainline(TestRevisionSpec):
    def test_as_revision_id(self):
        self.assertAsRevisionId(b"r1", "mainline:1")
        self.assertAsRevisionId(b"r2", "mainline:1.1.1")
        self.assertAsRevisionId(b"r2", "mainline:revid:alt_r2")
        spec = RevisionSpec.from_string("mainline:revid:alt_r22")
        e = self.assertRaises(
            InvalidRevisionSpec, spec.as_revision_id, self.tree.branch
        )
        self.assertContainsRe(
            str(e),
            "Requested revision: 'mainline:revid:alt_r22' does not exist in branch: ",
        )

    def test_in_history(self):
        self.assertInHistoryIs(2, b"r2", "mainline:revid:alt_r2")


class TestRevisionSpec_annotate(TestRevisionSpec):
    def setUp(self):
        super().setUp()
        self.tree = self.make_branch_and_tree("annotate-tree")
        self.build_tree_contents([("annotate-tree/file1", b"1\n")])
        self.tree.add("file1")
        self.tree.commit("r1", rev_id=b"r1")
        self.build_tree_contents([("annotate-tree/file1", b"2\n1\n")])
        self.tree.commit("r2", rev_id=b"r2")
        self.build_tree_contents([("annotate-tree/file1", b"2\n1\n3\n")])

    def test_as_revision_id_r1(self):
        self.assertAsRevisionId(b"r1", "annotate:annotate-tree/file1:2")

    def test_as_revision_id_r2(self):
        self.assertAsRevisionId(b"r2", "annotate:annotate-tree/file1:1")

    def test_as_revision_id_uncommitted(self):
        spec = RevisionSpec.from_string("annotate:annotate-tree/file1:3")
        e = self.assertRaises(
            InvalidRevisionSpec, spec.as_revision_id, self.tree.branch
        )
        self.assertContainsRe(
            str(e),
            r"Requested revision: \'annotate:annotate-tree/file1:3\' does not"
            " exist in branch: .*\nLine 3 has not been committed.",
        )

    def test_non_existent_line(self):
        spec = RevisionSpec.from_string("annotate:annotate-tree/file1:4")
        e = self.assertRaises(
            InvalidRevisionSpec, spec.as_revision_id, self.tree.branch
        )
        self.assertContainsRe(
            str(e),
            r"Requested revision: \'annotate:annotate-tree/file1:4\' does not"
            " exist in branch: .*\nNo such line: 4",
        )

    def test_invalid_line(self):
        spec = RevisionSpec.from_string("annotate:annotate-tree/file1:q")
        e = self.assertRaises(
            InvalidRevisionSpec, spec.as_revision_id, self.tree.branch
        )
        self.assertContainsRe(
            str(e),
            r"Requested revision: \'annotate:annotate-tree/file1:q\' does not"
            " exist in branch: .*\nNo such line: q",
        )

    def test_no_such_file(self):
        spec = RevisionSpec.from_string("annotate:annotate-tree/file2:1")
        e = self.assertRaises(
            InvalidRevisionSpec, spec.as_revision_id, self.tree.branch
        )
        self.assertContainsRe(
            str(e),
            r"Requested revision: \'annotate:annotate-tree/file2:1\' does not"
            " exist in branch: .*\nFile 'file2' is not versioned",
        )

    def test_no_such_file_with_colon(self):
        spec = RevisionSpec.from_string("annotate:annotate-tree/fi:le2:1")
        e = self.assertRaises(
            InvalidRevisionSpec, spec.as_revision_id, self.tree.branch
        )
        self.assertContainsRe(
            str(e),
            r"Requested revision: \'annotate:annotate-tree/fi:le2:1\' does not"
            " exist in branch: .*\nFile 'fi:le2' is not versioned",
        )

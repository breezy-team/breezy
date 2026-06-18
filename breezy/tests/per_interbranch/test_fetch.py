# Copyright (C) 2011, 2016 Canonical Ltd
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

"""Tests for InterBranch.fetch."""

from breezy.tests import TestNotApplicable
from breezy.tests.per_interbranch import TestCaseWithInterBranch

from ...errors import FetchLimitUnsupported, NoRoundtrippingSupport
from ...revision import NULL_REVISION


class TestInterBranchFetch(TestCaseWithInterBranch):
    def test_fetch_revisions(self):
        """Test fetch-revision operation."""
        wt = self.make_from_branch_and_tree("b1")
        b1 = wt.branch
        self.build_tree_contents([("b1/foo", b"hello")])
        wt.add(["foo"])
        rev1 = wt.commit("lala!", allow_pointless=False)

        b2 = self.make_to_branch("b2")
        try:
            b2.fetch(b1)
        except NoRoundtrippingSupport as e:
            raise TestNotApplicable(
                f"lossless cross-vcs fetch {b1!r} to {b2!r} not supported"
            ) from e

        # fetch does not update the last revision
        self.assertEqual(NULL_REVISION, b2.last_revision())

        b2.repository.get_revision(rev1)
        tree = b2.repository.revision_tree(rev1)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(tree.get_file_text("foo"), b"hello")

    def test_fetch_revisions_limit(self):
        """Test fetch-revision operation."""
        builder = self.make_branch_builder(
            "b1", format=self.branch_format_from._matchingcontroldir
        )
        builder.start_series()
        rev1 = builder.build_commit()
        rev2 = builder.build_commit()
        rev3 = builder.build_commit()
        builder.finish_series()
        b1 = builder.get_branch()
        b2 = self.make_to_branch("b2")
        try:
            b2.fetch(b1, limit=1)
        except FetchLimitUnsupported as e:
            raise TestNotApplicable("interbranch does not support fetch limits") from e
        except NoRoundtrippingSupport as e:
            raise TestNotApplicable(
                f"lossless cross-vcs fetch {b1!r} to {b2!r} not supported"
            ) from e

        # fetch does not update the last revision
        self.assertEqual(NULL_REVISION, b2.last_revision())

        self.assertEqual({rev1}, b2.repository.has_revisions([rev1, rev2, rev3]))

    def test_fetch_revisions_limit_incremental(self):
        """Test incremental fetch-revision operation with limit."""
        wt = self.make_from_branch_and_tree("b1")
        b1 = wt.branch
        self.build_tree_contents([("b1/foo", b"hello")])
        wt.add(["foo"])
        rev1 = wt.commit("lala!", allow_pointless=False)

        b2 = self.make_to_branch("b2")
        try:
            b2.fetch(b1, limit=1)
        except FetchLimitUnsupported as e:
            raise TestNotApplicable("interbranch does not support fetch limits") from e
        except NoRoundtrippingSupport as e:
            raise TestNotApplicable(
                f"lossless cross-vcs fetch {b1!r} to {b2!r} not supported"
            ) from e

        self.assertEqual(
            {rev1}, b2.repository.has_revisions([rev1, b"revision-2", b"revision-3"])
        )

        rev2 = wt.commit("hmm")
        rev3 = wt.commit("hmmm")

        b2.fetch(b1, limit=1)

        # fetch does not update the last revision
        self.assertEqual(NULL_REVISION, b2.last_revision())

        self.assertEqual({rev1, rev2}, b2.repository.has_revisions([rev1, rev2, rev3]))

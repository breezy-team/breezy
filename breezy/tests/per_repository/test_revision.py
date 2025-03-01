# Copyright (C) 2005, 2006, 2008, 2009, 2011, 2016 Canonical Ltd
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

"""Tests for revision properties."""

from breezy.tests import TestNotApplicable
from breezy.tests.per_repository import TestCaseWithRepository


class TestRevProps(TestCaseWithRepository):
    def test_simple_revprops(self):
        """Simple revision properties."""
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        b.nick = "Nicholas"
        if b.repository._format.supports_custom_revision_properties:
            props = {
                "flavor": "choc-mint",
                "condiment": "orange\n  mint\n\tcandy",
                "empty": "",
                "non_ascii": "\xb5",
            }
        else:
            props = {}
        rev1 = wt.commit(
            message="initial null commit", revprops=props, allow_pointless=True
        )
        rev = b.repository.get_revision(rev1)
        if b.repository._format.supports_custom_revision_properties:
            self.assertTrue("flavor" in rev.properties)
            self.assertEqual(rev.properties["flavor"], "choc-mint")
            expected_revprops = {
                "condiment": "orange\n  mint\n\tcandy",
                "empty": "",
                "flavor": "choc-mint",
                "non_ascii": "\xb5",
            }
        else:
            expected_revprops = {}
        if b.repository._format.supports_storing_branch_nick:
            expected_revprops["branch-nick"] = "Nicholas"
        for name, value in expected_revprops.items():
            self.assertEqual(rev.properties[name], value)

    def test_invalid_revprops(self):
        """Invalid revision properties."""
        wt = self.make_branch_and_tree(".")
        b = wt.branch
        if not b.repository._format.supports_custom_revision_properties:
            raise TestNotApplicable(
                "format does not support custom revision properties"
            )
        self.assertRaises(
            ValueError,
            wt.commit,
            message="invalid",
            revprops={"what a silly property": "fine"},
        )
        self.assertRaises(
            ValueError, wt.commit, message="invalid", revprops={"number": 13}
        )


class TestRevisionAttributes(TestCaseWithRepository):
    """Test that revision attributes are correct."""

    def test_revision_accessors(self):
        """Make sure the values that come out of a revision are the
        same as the ones that go in.
        """
        tree1 = self.make_branch_and_tree("br1")
        if tree1.branch.repository._format.supports_custom_revision_properties:
            revprops = {
                "empty": "",
                "value": "one",
                "unicode": "\xb5",
                "multiline": "foo\nbar\n\n",
            }
        else:
            revprops = {}
        # create a revision
        rev1 = tree1.commit(
            message="quux", allow_pointless=True, committer="jaq", revprops=revprops
        )
        self.assertEqual(tree1.branch.last_revision(), rev1)
        rev_a = tree1.branch.repository.get_revision(tree1.branch.last_revision())

        tree2 = self.make_branch_and_tree("br2")
        tree2.commit(
            message=rev_a.message,
            timestamp=rev_a.timestamp,
            timezone=rev_a.timezone,
            committer=rev_a.committer,
            rev_id=(
                rev_a.revision_id
                if tree2.branch.repository._format.supports_setting_revision_ids
                else None
            ),
            revprops=rev_a.properties,
            allow_pointless=True,  # there's nothing in this commit
            strict=True,
            verbose=True,
        )
        rev_b = tree2.branch.repository.get_revision(tree2.branch.last_revision())

        self.assertEqual(rev_a.message, rev_b.message)
        self.assertEqual(rev_a.timestamp, rev_b.timestamp)
        self.assertEqual(rev_a.timezone, rev_b.timezone)
        self.assertEqual(rev_a.committer, rev_b.committer)
        self.assertEqual(rev_a.revision_id, rev_b.revision_id)
        self.assertEqual(rev_a.properties, rev_b.properties)

    def test_zero_timezone(self):
        tree1 = self.make_branch_and_tree("br1")

        # create a revision
        r1 = tree1.commit(message="quux", timezone=0)
        rev_a = tree1.branch.repository.get_revision(r1)
        self.assertEqual(0, rev_a.timezone)

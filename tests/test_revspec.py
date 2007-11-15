# Copyright (C) 2005-2007 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
Tests for revision specificiers.
"""

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import BzrError, InvalidRevisionSpec
from bzrlib.revisionspec import RevisionSpec, RevisionInfo
from bzrlib.tests import TestCase

from tests import TestCaseWithSubversionRepository


class TestRevSpec(TestCase):
    def test_present(self):
        self.assertIsNot(None, RevisionSpec.from_string("svn:foo"))

    def test_needs_branch(self):
        self.assertTrue(RevisionSpec.from_string("svn:foo").needs_branch())

    def test_get_branch(self):
        self.assertIs(None, RevisionSpec.from_string("svn:foo").get_branch())


class TestRevSpecsBySubversion(TestCaseWithSubversionRepository):
    def test_by_single_revno(self):
        revspec = RevisionSpec.from_string("svn:2")
        repos_url = self.make_client("a", "dc")
        self.build_tree({"dc/foo": "foo"})
        self.client_add("dc/foo")
        self.client_commit("dc", "msg")

        self.build_tree({"dc/bar": "bar"})
        self.client_add("dc/bar")
        self.client_commit("dc", "msg2")

        branch = Branch.open(repos_url)
        revinfo = revspec._match_on(branch, None)

        self.assertEquals(RevisionInfo.from_revision_id(branch, branch.last_revision(), branch.revision_history()), revinfo)

    def test_invalid_revnum(self):
        revspec = RevisionSpec.from_string("svn:foo")
        repos_url = self.make_client("a", "dc")
        self.build_tree({"dc/bar": "bar"})
        self.client_add("dc/bar")
        self.client_commit("dc", "msg2")

        branch = Branch.open(repos_url)

        self.assertRaises(InvalidRevisionSpec, revspec._match_on, branch, None)

    def test_oor_revnum(self):
        """Out-of-range revnum."""
        revspec = RevisionSpec.from_string("svn:24")
        repos_url = self.make_client("a", "dc")
        self.build_tree({"dc/bar": "bar"})
        self.client_add("dc/bar")
        self.client_commit("dc", "msg2")

        branch = Branch.open(repos_url)

        self.assertRaises(InvalidRevisionSpec, revspec._match_on, branch, None)

    def test_non_svn_branch(self):
        revspec = RevisionSpec.from_string("svn:0")
        branch = BzrDir.create_standalone_workingtree("a").branch
        self.assertRaises(BzrError, revspec._match_on, branch, None)

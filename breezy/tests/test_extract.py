# Copyright (C) 2006, 2007, 2009, 2011 Canonical Ltd
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

from .. import branch, errors
from . import TestCaseWithTransport


class TestExtract(TestCaseWithTransport):
    def test_extract(self):
        self.build_tree(["a/", "a/b/", "a/b/c", "a/d"])
        wt = self.make_branch_and_tree("a", format="rich-root-pack")
        wt.add(["b", "b/c", "d"], ids=[b"b-id", b"c-id", b"d-id"])
        wt.commit("added files")
        b_wt = wt.extract("b")
        self.assertTrue(b_wt.is_versioned(""))
        if b_wt.supports_setting_file_ids():
            self.assertEqual(b"b-id", b_wt.path2id(""))
            self.assertEqual(b"c-id", b_wt.path2id("c"))
            self.assertEqual("c", b_wt.id2path(b"c-id"))
            self.assertRaises(errors.BzrError, wt.id2path, b"b-id")
        self.assertEqual(b_wt.basedir, wt.abspath("b"))
        self.assertEqual(wt.get_parent_ids(), b_wt.get_parent_ids())
        self.assertEqual(wt.branch.last_revision(), b_wt.branch.last_revision())

    def extract_in_checkout(self, a_branch):
        self.build_tree(["a/", "a/b/", "a/b/c/", "a/b/c/d"])
        wt = a_branch.create_checkout("a", lightweight=True)
        wt.add(["b", "b/c", "b/c/d"], ids=[b"b-id", b"c-id", b"d-id"])
        wt.commit("added files")
        return wt.extract("b")

    def test_extract_in_checkout(self):
        a_branch = self.make_branch("branch", format="rich-root-pack")
        self.extract_in_checkout(a_branch)
        b_branch = branch.Branch.open("branch/b")
        b_branch_ref = branch.Branch.open("a/b")
        self.assertEqual(b_branch.base, b_branch_ref.base)

    def test_extract_in_deep_checkout(self):
        a_branch = self.make_branch("branch", format="rich-root-pack")
        self.build_tree(["a/", "a/b/", "a/b/c/", "a/b/c/d/", "a/b/c/d/e"])
        wt = a_branch.create_checkout("a", lightweight=True)
        wt.add(
            ["b", "b/c", "b/c/d", "b/c/d/e/"], ids=[b"b-id", b"c-id", b"d-id", b"e-id"]
        )
        wt.commit("added files")
        wt.extract("b/c/d")
        b_branch = branch.Branch.open("branch/b/c/d")
        b_branch_ref = branch.Branch.open("a/b/c/d")
        self.assertEqual(b_branch.base, b_branch_ref.base)

    def test_bad_repo_format(self):
        repo = self.make_repository("branch", shared=True, format="knit")
        a_branch = repo.controldir.create_branch()
        self.assertRaises(errors.RootNotRich, self.extract_in_checkout, a_branch)

    def test_good_repo_format(self):
        repo = self.make_repository(
            "branch", shared=True, format="dirstate-with-subtree"
        )
        a_branch = repo.controldir.create_branch()
        wt_b = self.extract_in_checkout(a_branch)
        self.assertEqual(
            wt_b.branch.repository.controldir.transport.base,
            repo.controldir.transport.base,
        )

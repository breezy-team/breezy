# Copyright (C) 2007-2010 Canonical Ltd
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


from breezy.tests import TestCaseWithTransport


class TestCatRevision(TestCaseWithTransport):
    def test_cat_unicode_revision(self):
        tree = self.make_branch_and_tree(".")
        tree.commit("This revision", rev_id=b"abcd")
        output, errors = self.run_bzr(["cat-revision", "abcd"])
        self.assertContainsRe(output, "This revision")
        self.assertEqual("", errors)

    def test_cat_revision(self):
        """Test brz cat-revision."""
        wt = self.make_branch_and_tree(".")
        r = wt.branch.repository

        wt.commit("Commit one", rev_id=b"a@r-0-1")
        wt.commit("Commit two", rev_id=b"a@r-0-2")
        wt.commit("Commit three", rev_id=b"a@r-0-3")

        with r.lock_read():
            revs = {}
            for i in (1, 2, 3):
                revid = b"a@r-0-%d" % i
                stream = r.revisions.get_record_stream([(revid,)], "unordered", False)
                revs[i] = next(stream).get_bytes_as("fulltext")

        for i in [1, 2, 3]:
            self.assertEqual(
                revs[i],
                self.run_bzr("cat-revision -r revid:a@r-0-%d" % i)[0].encode("utf-8"),
            )
            self.assertEqual(
                revs[i], self.run_bzr("cat-revision a@r-0-%d" % i)[0].encode("utf-8")
            )
            self.assertEqual(
                revs[i], self.run_bzr("cat-revision -r %d" % i)[0].encode("utf-8")
            )

    def test_cat_no_such_revid(self):
        self.make_branch_and_tree(".")
        err = self.run_bzr("cat-revision abcd", retcode=3)[1]
        self.assertContainsRe(err, "The repository .* contains no revision abcd.")

    def test_cat_revision_directory(self):
        """Test --directory option."""
        tree = self.make_branch_and_tree("a")
        tree.commit("This revision", rev_id=b"abcd")
        output, errors = self.run_bzr(["cat-revision", "-d", "a", "abcd"])
        self.assertContainsRe(output, "This revision")
        self.assertEqual("", errors)

    def test_cat_tree_less_branch(self):
        tree = self.make_branch_and_tree(".")
        tree.commit("This revision", rev_id=b"abcd")
        tree.controldir.destroy_workingtree()
        output, errors = self.run_bzr(["cat-revision", "-d", "a", "abcd"])
        self.assertContainsRe(output, "This revision")
        self.assertEqual("", errors)

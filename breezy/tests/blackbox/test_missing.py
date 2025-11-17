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

"""Black-box tests for brz missing."""

from breezy import osutils, tests


class TestMissing(tests.TestCaseWithTransport):
    def assertMessages(self, out, must_have=(), must_not_have=()):
        """Check if commit messages are in or not in the output."""
        for m in must_have:
            self.assertContainsRe(out, r"\nmessage:\n  {}\n".format(m))
        for m in must_not_have:
            self.assertNotContainsRe(out, r"\nmessage:\n  {}\n".format(m))

    def test_missing_quiet(self):
        # <https://bugs.launchpad.net/bzr/+bug/284748>
        # create a source branch
        #
        # XXX: This still needs a test that missing is quiet when there are
        # missing revisions.
        a_tree = self.make_branch_and_tree(".")
        self.build_tree_contents([("a", b"initial\n")])
        a_tree.add("a")
        a_tree.commit(message="initial")

        out, err = self.run_bzr("missing -q .")
        self.assertEqual("", out)
        self.assertEqual("", err)

    def test_missing(self):
        missing_one = "You are missing 1 revision:"
        extra_one = "You have 1 extra revision:"

        # create a source branch
        a_tree = self.make_branch_and_tree("a")
        self.build_tree_contents([("a/a", b"initial\n")])
        a_tree.add("a")
        a_tree.commit(message="initial")

        # clone and add a differing revision
        b_tree = a_tree.controldir.sprout("b").open_workingtree()
        self.build_tree_contents([("b/a", b"initial\nmore\n")])
        b_tree.commit(message="more")

        def run_missing(args, retcode=1, working_dir=None):
            out, err = self.run_bzr(
                ["missing"] + args, retcode=retcode, working_dir=working_dir
            )
            # we do not expect any error output.
            self.assertEqual("", err)
            return out.splitlines()

        def run_missing_a(args, retcode=1):
            return run_missing(["../a"] + args, retcode=retcode, working_dir="b")

        def run_missing_b(args, retcode=1):
            return run_missing(["../b"] + args, retcode=retcode, working_dir="a")

        # run missing in a against b
        # this should not require missing to take out a write lock on a
        # or b. So we take a write lock on both to test that at the same
        # time. This may let the test pass while the default branch is an
        # os-locking branch, but it will trigger failures with lockdir based
        # branches.
        a_branch = a_tree.branch
        a_branch.lock_write()
        b_branch = b_tree.branch
        b_branch.lock_write()

        lines = run_missing_b([])
        # we're missing the extra revision here
        self.assertEqual(missing_one, lines[0])
        # and we expect 8 lines of output which we trust at the moment to be
        # good.
        self.assertEqual(8, len(lines))
        # unlock the branches for the rest of the test
        a_branch.unlock()
        b_branch.unlock()

        # get extra revision from b
        a_tree.merge_from_branch(b_branch)
        a_tree.commit(message="merge")

        # compare again, but now we have the 'merge' commit extra
        lines = run_missing_b([])
        self.assertEqual(extra_one, lines[0])
        self.assertLength(8, lines)

        lines2 = run_missing_b(["--mine-only"])
        self.assertEqual(lines, lines2)

        lines3 = run_missing_b(["--theirs-only"], retcode=0)
        self.assertEqualDiff("Other branch has no new revisions.", lines3[0])

        # relative to a, missing the 'merge' commit
        lines = run_missing_a([])
        self.assertEqual(missing_one, lines[0])
        self.assertLength(8, lines)

        lines2 = run_missing_a(["--theirs-only"])
        self.assertEqual(lines, lines2)

        lines3 = run_missing_a(["--mine-only"], retcode=0)
        self.assertEqualDiff("This branch has no new revisions.", lines3[0])

        lines4 = run_missing_a(["--short"])
        self.assertLength(4, lines4)

        lines4a = run_missing_a(["-S"])
        self.assertEqual(lines4, lines4a)

        lines5 = run_missing_a(["--line"])
        self.assertLength(2, lines5)

        lines6 = run_missing_a(["--reverse"])
        self.assertEqual(lines6, lines)

        lines7 = run_missing_a(["--show-ids"])
        self.assertLength(11, lines7)

        lines8 = run_missing_a(["--verbose"])
        self.assertEqual("modified:", lines8[-2])
        self.assertEqual("  a", lines8[-1])

        self.assertEqualDiff(
            "Other branch has no new revisions.",
            run_missing_b(["--theirs-only"], retcode=0)[0],
        )

        # after a pull we're back on track
        b_tree.pull(a_branch)
        self.assertEqualDiff(
            "Branches are up to date.", run_missing_b([], retcode=0)[0]
        )
        self.assertEqualDiff(
            "Branches are up to date.", run_missing_a([], retcode=0)[0]
        )
        # If you supply mine or theirs you only know one side is up to date
        self.assertEqualDiff(
            "This branch has no new revisions.",
            run_missing_a(["--mine-only"], retcode=0)[0],
        )
        self.assertEqualDiff(
            "Other branch has no new revisions.",
            run_missing_a(["--theirs-only"], retcode=0)[0],
        )

    def test_missing_filtered(self):
        # create a source branch
        a_tree = self.make_branch_and_tree("a")
        self.build_tree_contents([("a/a", b"initial\n")])
        a_tree.add("a")
        a_tree.commit(message="r1")
        # clone and add differing revisions
        b_tree = a_tree.controldir.sprout("b").open_workingtree()

        for i in range(2, 6):
            a_tree.commit(message="a%d" % i)
            b_tree.commit(message="b%d" % i)

        # local
        out, err = self.run_bzr(
            "missing ../b --my-revision 3", retcode=1, working_dir="a"
        )
        self.assertMessages(out, ("a3", "b2", "b3", "b4", "b5"), ("a2", "a4"))

        out, err = self.run_bzr(
            "missing ../b --my-revision 3..4", retcode=1, working_dir="a"
        )
        self.assertMessages(out, ("a3", "a4"), ("a2", "a5"))

        # remote
        out, err = self.run_bzr("missing ../b -r 3", retcode=1, working_dir="a")
        self.assertMessages(out, ("a2", "a3", "a4", "a5", "b3"), ("b2", "b4"))

        out, err = self.run_bzr("missing ../b -r 3..4", retcode=1, working_dir="a")
        self.assertMessages(out, ("b3", "b4"), ("b2", "b5"))

        # both
        out, _err = self.run_bzr(
            "missing ../b --my-revision 3..4 -r 3..4", retcode=1, working_dir="a"
        )
        self.assertMessages(out, ("a3", "a4", "b3", "b4"), ("a2", "a5", "b2", "b5"))

    def test_missing_check_last_location(self):
        # check that last location shown as filepath not file URL

        # create a source branch
        wt = self.make_branch_and_tree("a")
        b = wt.branch
        self.build_tree(["a/foo"])
        wt.add("foo")
        wt.commit("initial")

        location = osutils.getcwd() + "/a/"

        # clone
        b.controldir.sprout("b")

        # check last location
        lines, err = self.run_bzr("missing", working_dir="b")
        self.assertEqual(
            "Using saved parent location: {}\nBranches are up to date.\n".format(
                location
            ),
            lines,
        )
        self.assertEqual("", err)

    def test_missing_directory(self):
        """Test --directory option."""
        # create a source branch
        a_tree = self.make_branch_and_tree("a")
        self.build_tree_contents([("a/a", b"initial\n")])
        a_tree.add("a")
        a_tree.commit(message="initial")

        # clone and add a differing revision
        b_tree = a_tree.controldir.sprout("b").open_workingtree()
        self.build_tree_contents([("b/a", b"initial\nmore\n")])
        b_tree.commit(message="more")

        out2, err2 = self.run_bzr("missing --directory a b", retcode=1)
        out1, err1 = self.run_bzr("missing ../b", retcode=1, working_dir="a")
        self.assertEqualDiff(out1, out2)
        self.assertEqualDiff(err1, err2)

    def test_missing_tags(self):
        """Test showing tags."""
        # create a source branch
        a_tree = self.make_branch_and_tree("a")
        self.build_tree_contents([("a/a", b"initial\n")])
        a_tree.add("a")
        a_tree.commit(message="initial")

        # clone and add a differing revision
        b_tree = a_tree.controldir.sprout("b").open_workingtree()
        self.build_tree_contents([("b/a", b"initial\nmore\n")])
        b_tree.commit(message="more")
        b_tree.branch.tags.set_tag("a-tag", b_tree.last_revision())

        for log_format in ["long", "short", "line"]:
            out, err = self.run_bzr(
                f"missing --log-format={log_format} ../a", working_dir="b", retcode=1
            )
            self.assertContainsString(out, "a-tag")

            out, _err = self.run_bzr(
                f"missing --log-format={log_format} ../b", working_dir="a", retcode=1
            )
            self.assertContainsString(out, "a-tag")

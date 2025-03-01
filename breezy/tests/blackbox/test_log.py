# Copyright (C) 2006-2012, 2016 Canonical Ltd
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


"""Black-box tests for brz log."""

import os

from breezy import branchbuilder, errors, log, osutils, tests
from breezy.tests import features, test_log


class TestLog(tests.TestCaseWithTransport, test_log.TestLogMixin):
    def make_minimal_branch(self, path=".", format=None):
        tree = self.make_branch_and_tree(path, format=format)
        self.build_tree([path + "/hello.txt"])
        tree.add("hello.txt")
        tree.commit(message="message1")
        return tree

    def make_linear_branch(self, path=".", format=None):
        tree = self.make_branch_and_tree(path, format=format)
        self.build_tree(
            [path + "/hello.txt", path + "/goodbye.txt", path + "/meep.txt"]
        )
        tree.add("hello.txt")
        tree.commit(message="message1")
        tree.add("goodbye.txt")
        tree.commit(message="message2")
        tree.add("meep.txt")
        tree.commit(message="message3")
        return tree

    def make_merged_branch(self, path=".", format=None):
        tree = self.make_linear_branch(path, format)
        tree2 = tree.controldir.sprout(
            "tree2", revision_id=tree.branch.get_rev_id(1)
        ).open_workingtree()
        tree2.commit(message="tree2 message2")
        tree2.commit(message="tree2 message3")
        tree.merge_from_branch(tree2.branch)
        tree.commit(message="merge")
        return tree


class TestLogWithLogCatcher(TestLog):
    def setUp(self):
        super().setUp()
        # Capture log formatter creations

        class MyLogFormatter(test_log.LogCatcher):
            def __new__(klass, *args, **kwargs):
                self.log_catcher = test_log.LogCatcher(*args, **kwargs)
                # Always return our own log formatter
                return self.log_catcher

        # Break cycle with closure over self on cleanup by removing method
        self.addCleanup(setattr, MyLogFormatter, "__new__", None)

        def getme(branch):
            # Always return our own log formatter class hijacking the
            # default behavior (which requires setting up a config
            # variable)
            return MyLogFormatter

        self.overrideAttr(log.log_formatter_registry, "get_default", getme)

    def get_captured_revisions(self):
        return self.log_catcher.revisions

    def assertLogRevnos(self, args, expected_revnos, working_dir=".", out="", err=""):
        actual_out, actual_err = self.run_bzr(["log"] + args, working_dir=working_dir)
        self.assertEqual(out, actual_out)
        self.assertEqual(err, actual_err)
        self.assertEqual(
            expected_revnos, [r.revno for r in self.get_captured_revisions()]
        )

    def assertLogRevnosAndDepths(
        self, args, expected_revnos_and_depths, working_dir="."
    ):
        self.run_bzr(["log"] + args, working_dir=working_dir)
        self.assertEqual(
            expected_revnos_and_depths,
            [(r.revno, r.merge_depth) for r in self.get_captured_revisions()],
        )


class TestLogRevSpecs(TestLogWithLogCatcher):
    def test_log_no_revspec(self):
        self.make_linear_branch()
        self.assertLogRevnos([], ["3", "2", "1"])

    def test_log_null_end_revspec(self):
        self.make_linear_branch()
        self.assertLogRevnos(["-r1.."], ["3", "2", "1"])

    def test_log_null_begin_revspec(self):
        self.make_linear_branch()
        self.assertLogRevnos(["-r..3"], ["3", "2", "1"])

    def test_log_null_both_revspecs(self):
        self.make_linear_branch()
        self.assertLogRevnos(["-r.."], ["3", "2", "1"])

    def test_log_negative_begin_revspec_full_log(self):
        self.make_linear_branch()
        self.assertLogRevnos(["-r-3.."], ["3", "2", "1"])

    def test_log_negative_both_revspec_full_log(self):
        self.make_linear_branch()
        self.assertLogRevnos(["-r-3..-1"], ["3", "2", "1"])

    def test_log_negative_both_revspec_partial(self):
        self.make_linear_branch()
        self.assertLogRevnos(["-r-3..-2"], ["2", "1"])

    def test_log_negative_begin_revspec(self):
        self.make_linear_branch()
        self.assertLogRevnos(["-r-2.."], ["3", "2"])

    def test_log_positive_revspecs(self):
        self.make_linear_branch()
        self.assertLogRevnos(["-r1..3"], ["3", "2", "1"])

    def test_log_dotted_revspecs(self):
        self.make_merged_branch()
        self.assertLogRevnos(["-n0", "-r1..1.1.1"], ["1.1.1", "1"])

    def test_log_limit(self):
        tree = self.make_branch_and_tree(".")
        # We want more commits than our batch size starts at
        for pos in range(10):
            tree.commit("{}".format(pos))
        self.assertLogRevnos(["--limit", "2"], ["10", "9"])

    def test_log_limit_short(self):
        self.make_linear_branch()
        self.assertLogRevnos(["-l", "2"], ["3", "2"])

    def test_log_change_revno(self):
        self.make_linear_branch()
        self.assertLogRevnos(["-c1"], ["1"])

    def test_branch_revspec(self):
        foo = self.make_branch_and_tree("foo")
        bar = self.make_branch_and_tree("bar")
        self.build_tree(["foo/foo.txt", "bar/bar.txt"])
        foo.add("foo.txt")
        bar.add("bar.txt")
        foo.commit(message="foo")
        bar.commit(message="bar")
        self.run_bzr("log -r branch:../bar", working_dir="foo")
        self.assertEqual(
            [bar.branch.get_rev_id(1)],
            [r.rev.revision_id for r in self.get_captured_revisions()],
        )


class TestLogExcludeCommonAncestry(TestLogWithLogCatcher):
    def test_exclude_common_ancestry_simple_revnos(self):
        self.make_linear_branch()
        self.assertLogRevnos(["-r1..3", "--exclude-common-ancestry"], ["3", "2"])


class TestLogMergedLinearAncestry(TestLogWithLogCatcher):
    def setUp(self):
        super().setUp()
        # FIXME: Using a MemoryTree would be even better here (but until we
        # stop calling run_bzr, there is no point) --vila 100118.
        builder = branchbuilder.BranchBuilder(self.get_transport())
        builder.start_series()
        # 1
        # | \
        # 2  1.1.1
        # | / |
        # 3  1.1.2
        # |   |
        # |  1.1.3
        # | / |
        # 4  1.1.4
        # | /
        # 5
        # | \
        # | 5.1.1
        # | /
        # 6

        # mainline
        builder.build_snapshot(
            None, [("add", ("", b"root-id", "directory", ""))], revision_id=b"1"
        )
        builder.build_snapshot([b"1"], [], revision_id=b"2")
        # branch
        builder.build_snapshot([b"1"], [], revision_id=b"1.1.1")
        # merge branch into mainline
        builder.build_snapshot([b"2", b"1.1.1"], [], revision_id=b"3")
        # new commits in branch
        builder.build_snapshot([b"1.1.1"], [], revision_id=b"1.1.2")
        builder.build_snapshot([b"1.1.2"], [], revision_id=b"1.1.3")
        # merge branch into mainline
        builder.build_snapshot([b"3", b"1.1.3"], [], revision_id=b"4")
        # merge mainline into branch
        builder.build_snapshot([b"1.1.3", b"4"], [], revision_id=b"1.1.4")
        # merge branch into mainline
        builder.build_snapshot([b"4", b"1.1.4"], [], revision_id=b"5")
        builder.build_snapshot([b"5"], [], revision_id=b"5.1.1")
        builder.build_snapshot([b"5", b"5.1.1"], [], revision_id=b"6")
        builder.finish_series()

    def test_n0(self):
        self.assertLogRevnos(
            ["-n0", "-r1.1.1..1.1.4"], ["1.1.4", "4", "1.1.3", "1.1.2", "3", "1.1.1"]
        )

    def test_n0_forward(self):
        self.assertLogRevnos(
            ["-n0", "-r1.1.1..1.1.4", "--forward"],
            ["3", "1.1.1", "4", "1.1.2", "1.1.3", "1.1.4"],
        )

    def test_n1(self):
        # starting from 1.1.4 we follow the left-hand ancestry
        self.assertLogRevnos(
            ["-n1", "-r1.1.1..1.1.4"], ["1.1.4", "1.1.3", "1.1.2", "1.1.1"]
        )

    def test_n1_forward(self):
        self.assertLogRevnos(
            ["-n1", "-r1.1.1..1.1.4", "--forward"], ["1.1.1", "1.1.2", "1.1.3", "1.1.4"]
        )

    def test_fallback_when_end_rev_is_not_on_mainline(self):
        self.assertLogRevnos(
            ["-n1", "-r1.1.1..5.1.1"],
            # We don't get 1.1.1 because we say -n1
            ["5.1.1", "5", "4", "3"],
        )


class Test_GenerateAllRevisions(TestLogWithLogCatcher):
    def setUp(self):
        super().setUp()
        builder = self.make_branch_with_many_merges()
        b = builder.get_branch()
        b.lock_read()
        self.addCleanup(b.unlock)
        self.branch = b

    def make_branch_with_many_merges(self, path=".", format=None):
        builder = branchbuilder.BranchBuilder(self.get_transport())
        builder.start_series()
        # The graph below may look a bit complicated (and it may be but I've
        # banged my head enough on it) but the bug requires at least dotted
        # revnos *and* merged revisions below that.
        # 1
        # | \
        # 2  1.1.1
        # | X
        # 3  2.1.1
        # |   |    \
        # |  2.1.2  2.2.1
        # |   |    X
        # |  2.1.3  \
        # | /       /
        # 4        /
        # |       /
        # 5 -----/
        builder.build_snapshot(
            None, [("add", ("", b"root-id", "directory", ""))], revision_id=b"1"
        )
        builder.build_snapshot([b"1"], [], revision_id=b"2")
        builder.build_snapshot([b"1"], [], revision_id=b"1.1.1")
        builder.build_snapshot([b"2"], [], revision_id=b"2.1.1")
        builder.build_snapshot([b"2", b"1.1.1"], [], revision_id=b"3")
        builder.build_snapshot([b"2.1.1"], [], revision_id=b"2.1.2")
        builder.build_snapshot([b"2.1.1"], [], revision_id=b"2.2.1")
        builder.build_snapshot([b"2.1.2", b"2.2.1"], [], revision_id=b"2.1.3")
        builder.build_snapshot([b"3", b"2.1.3"], [], revision_id=b"4")
        builder.build_snapshot([b"4", b"2.1.2"], [], revision_id=b"5")
        builder.finish_series()
        return builder

    def test_not_an_ancestor(self):
        self.assertRaises(
            errors.CommandError,
            log._generate_all_revisions,
            self.branch,
            "1.1.1",
            "2.1.3",
            "reverse",
            delayed_graph_generation=True,
        )

    def test_wrong_order(self):
        self.assertRaises(
            errors.CommandError,
            log._generate_all_revisions,
            self.branch,
            "5",
            "2.1.3",
            "reverse",
            delayed_graph_generation=True,
        )

    def test_no_start_rev_id_with_end_rev_id_being_a_merge(self):
        log._generate_all_revisions(
            self.branch, None, "2.1.3", "reverse", delayed_graph_generation=True
        )


class TestLogRevSpecsWithPaths(TestLogWithLogCatcher):
    def test_log_revno_n_path_wrong_namespace(self):
        self.make_linear_branch("branch1")
        self.make_linear_branch("branch2")
        # There is no guarantee that a path exist between two arbitrary
        # revisions.
        self.run_bzr("log -r revno:2:branch1..revno:3:branch2", retcode=3)

    def test_log_revno_n_path_correct_order(self):
        self.make_linear_branch("branch2")
        self.assertLogRevnos(["-rrevno:1:branch2..revno:3:branch2"], ["3", "2", "1"])

    def test_log_revno_n_path(self):
        self.make_linear_branch("branch2")
        self.assertLogRevnos(["-rrevno:1:branch2"], ["1"])
        rev_props = self.log_catcher.revisions[0].rev.properties
        self.assertEqual("branch2", rev_props["branch-nick"])


class TestLogErrors(TestLog):
    def test_log_zero_revspec(self):
        self.make_minimal_branch()
        self.run_bzr_error(
            ["brz: ERROR: Logging revision 0 is invalid."], ["log", "-r0"]
        )

    def test_log_zero_begin_revspec(self):
        self.make_linear_branch()
        self.run_bzr_error(
            ["brz: ERROR: Logging revision 0 is invalid."], ["log", "-r0..2"]
        )

    def test_log_zero_end_revspec(self):
        self.make_linear_branch()
        self.run_bzr_error(
            ["brz: ERROR: Logging revision 0 is invalid."], ["log", "-r-2..0"]
        )

    def test_log_nonexistent_revno(self):
        self.make_minimal_branch()
        self.run_bzr_error(
            ["brz: ERROR: Requested revision: '1234' does not exist in branch:"],
            ["log", "-r1234"],
        )

    def test_log_nonexistent_dotted_revno(self):
        self.make_minimal_branch()
        self.run_bzr_error(
            ["brz: ERROR: Requested revision: '123.123' does not exist in branch:"],
            ["log", "-r123.123"],
        )

    def test_log_change_nonexistent_revno(self):
        self.make_minimal_branch()
        self.run_bzr_error(
            ["brz: ERROR: Requested revision: '1234' does not exist in branch:"],
            ["log", "-c1234"],
        )

    def test_log_change_nonexistent_dotted_revno(self):
        self.make_minimal_branch()
        self.run_bzr_error(
            ["brz: ERROR: Requested revision: '123.123' does not exist in branch:"],
            ["log", "-c123.123"],
        )

    def test_log_change_single_revno_only(self):
        self.make_minimal_branch()
        self.run_bzr_error(
            ["brz: ERROR: Option --change does not accept revision ranges"],
            ["log", "--change", "2..3"],
        )

    def test_log_change_incompatible_with_revision(self):
        self.run_bzr_error(
            ["brz: ERROR: --revision and --change are mutually exclusive"],
            ["log", "--change", "2", "--revision", "3"],
        )

    def test_log_nonexistent_file(self):
        self.make_minimal_branch()
        # files that don't exist in either the basis tree or working tree
        # should give an error
        out, err = self.run_bzr("log does-not-exist", retcode=3)
        self.assertContainsRe(
            err, "Path unknown at end or start of revision range: does-not-exist"
        )

    def test_log_reversed_revspecs(self):
        self.make_linear_branch()
        self.run_bzr_error(
            ("brz: ERROR: Start revision must be older than the end revision.\n",),
            ["log", "-r3..1"],
        )

    def test_log_reversed_dotted_revspecs(self):
        self.make_merged_branch()
        self.run_bzr_error(
            ("brz: ERROR: Start revision not found in history of end revision.\n",),
            "log -r 1.1.1..1",
        )

    def test_log_bad_message_re(self):
        """Bad --message argument gives a sensible message.

        See https://bugs.launchpad.net/bzr/+bug/251352
        """
        self.make_minimal_branch()
        out, err = self.run_bzr(["log", "-m", "*"], retcode=3)
        self.assertContainsRe(err, "ERROR.*Invalid pattern.*nothing to repeat")
        self.assertNotContainsRe(err, "Unprintable exception")
        self.assertEqual(out, "")

    def test_log_unsupported_timezone(self):
        self.make_linear_branch()
        self.run_bzr_error(
            [
                'brz: ERROR: Unsupported timezone format "foo", '
                'options are "utc", "original", "local".'
            ],
            ["log", "--timezone", "foo"],
        )

    def test_log_exclude_ancestry_no_range(self):
        self.make_linear_branch()
        self.run_bzr_error(
            ["brz: ERROR: --exclude-common-ancestry requires -r with two revisions"],
            ["log", "--exclude-common-ancestry"],
        )

    def test_log_exclude_ancestry_single_revision(self):
        self.make_merged_branch()
        self.run_bzr_error(
            ["brz: ERROR: --exclude-common-ancestry requires two different revisions"],
            ["log", "--exclude-common-ancestry", "-r1.1.1..1.1.1"],
        )


class TestLogTags(TestLog):
    def test_log_with_tags(self):
        tree = self.make_linear_branch(format="dirstate-tags")
        branch = tree.branch
        branch.tags.set_tag("tag1", branch.get_rev_id(1))
        branch.tags.set_tag("tag1.1", branch.get_rev_id(1))
        branch.tags.set_tag("tag3", branch.last_revision())

        log = self.run_bzr("log -r-1")[0]
        self.assertTrue("tags: tag3" in log)

        log = self.run_bzr("log -r1")[0]
        # I guess that we can't know the order of tags in the output
        # since dicts are unordered, need to check both possibilities
        self.assertContainsRe(log, r"tags: (tag1, tag1\.1|tag1\.1, tag1)")

    def test_merged_log_with_tags(self):
        branch1_tree = self.make_linear_branch("branch1", format="dirstate-tags")
        branch1 = branch1_tree.branch
        branch2_tree = branch1_tree.controldir.sprout("branch2").open_workingtree()
        branch1_tree.commit(message="foobar", allow_pointless=True)
        branch1.tags.set_tag("tag1", branch1.last_revision())
        # tags don't propagate if we don't merge
        self.run_bzr("merge ../branch1", working_dir="branch2")
        branch2_tree.commit(message="merge branch 1")
        log = self.run_bzr("log -n0 -r-1", working_dir="branch2")[0]
        self.assertContainsRe(log, r"    tags: tag1")
        log = self.run_bzr("log -n0 -r3.1.1", working_dir="branch2")[0]
        self.assertContainsRe(log, r"tags: tag1")


class TestLogSignatures(TestLog):
    def test_log_with_signatures(self):
        self.requireFeature(features.gpg)

        self.make_linear_branch(format="dirstate-tags")

        log = self.run_bzr("log --signatures")[0]
        self.assertTrue("signature: no signature" in log)

    def test_log_without_signatures(self):
        self.requireFeature(features.gpg)

        self.make_linear_branch(format="dirstate-tags")

        log = self.run_bzr("log")[0]
        self.assertFalse("signature: no signature" in log)


class TestLogVerbose(TestLog):
    def setUp(self):
        super().setUp()
        self.make_minimal_branch()

    def assertUseShortDeltaFormat(self, cmd):
        log = self.run_bzr(cmd)[0]
        # Check that we use the short status format
        self.assertContainsRe(log, "(?m)^\\s*A  hello.txt$")
        self.assertNotContainsRe(log, "(?m)^\\s*added:$")

    def assertUseLongDeltaFormat(self, cmd):
        log = self.run_bzr(cmd)[0]
        # Check that we use the long status format
        self.assertNotContainsRe(log, "(?m)^\\s*A  hello.txt$")
        self.assertContainsRe(log, "(?m)^\\s*added:$")

    def test_log_short_verbose(self):
        self.assertUseShortDeltaFormat(["log", "--short", "-v"])

    def test_log_s_verbose(self):
        self.assertUseShortDeltaFormat(["log", "-S", "-v"])

    def test_log_short_verbose_verbose(self):
        self.assertUseLongDeltaFormat(["log", "--short", "-vv"])

    def test_log_long_verbose(self):
        # Check that we use the long status format, ignoring the verbosity
        # level
        self.assertUseLongDeltaFormat(["log", "--long", "-v"])

    def test_log_long_verbose_verbose(self):
        # Check that we use the long status format, ignoring the verbosity
        # level
        self.assertUseLongDeltaFormat(["log", "--long", "-vv"])


class TestLogMerges(TestLogWithLogCatcher):
    def setUp(self):
        super().setUp()
        self.make_branches_with_merges()

    def make_branches_with_merges(self):
        level0 = self.make_branch_and_tree("level0")
        self.wt_commit(level0, "in branch level0")
        level1 = level0.controldir.sprout("level1").open_workingtree()
        self.wt_commit(level1, "in branch level1")
        level2 = level1.controldir.sprout("level2").open_workingtree()
        self.wt_commit(level2, "in branch level2")
        level1.merge_from_branch(level2.branch)
        self.wt_commit(level1, "merge branch level2")
        level0.merge_from_branch(level1.branch)
        self.wt_commit(level0, "merge branch level1")

    def test_merges_are_indented_by_level(self):
        self.run_bzr(["log", "-n0"], working_dir="level0")
        [
            (r.revno, r.merge_depth) for r in self.get_captured_revisions()
        ]
        self.assertEqual(
            [("2", 0), ("1.1.2", 1), ("1.2.1", 2), ("1.1.1", 1), ("1", 0)],
            [(r.revno, r.merge_depth) for r in self.get_captured_revisions()],
        )

    def test_force_merge_revisions_off(self):
        self.assertLogRevnos(["-n1"], ["2", "1"], working_dir="level0")

    def test_force_merge_revisions_on(self):
        self.assertLogRevnos(
            ["-n0"], ["2", "1.1.2", "1.2.1", "1.1.1", "1"], working_dir="level0"
        )

    def test_include_merged(self):
        # Confirm --include-merged gives the same output as -n0
        expected = ["2", "1.1.2", "1.2.1", "1.1.1", "1"]
        self.assertLogRevnos(["--include-merged"], expected, working_dir="level0")
        self.assertLogRevnos(["--include-merged"], expected, working_dir="level0")

    def test_force_merge_revisions_N(self):
        self.assertLogRevnos(
            ["-n2"], ["2", "1.1.2", "1.1.1", "1"], working_dir="level0"
        )

    def test_merges_single_merge_rev(self):
        self.assertLogRevnosAndDepths(
            ["-n0", "-r1.1.2"], [("1.1.2", 0), ("1.2.1", 1)], working_dir="level0"
        )

    def test_merges_partial_range(self):
        self.assertLogRevnosAndDepths(
            ["-n0", "-r1.1.1..1.1.2"],
            [("1.1.2", 0), ("1.2.1", 1), ("1.1.1", 0)],
            working_dir="level0",
        )

    def test_merges_partial_range_ignore_before_lower_bound(self):
        """Dont show revisions before the lower bound's merged revs."""
        self.assertLogRevnosAndDepths(
            ["-n0", "-r1.1.2..2"],
            [("2", 0), ("1.1.2", 1), ("1.2.1", 2)],
            working_dir="level0",
        )

    def test_omit_merges_with_sidelines(self):
        self.assertLogRevnos(
            ["--omit-merges", "-n0"], ["1.2.1", "1.1.1", "1"], working_dir="level0"
        )

    def test_omit_merges_without_sidelines(self):
        self.assertLogRevnos(["--omit-merges", "-n1"], ["1"], working_dir="level0")


class TestLogDiff(TestLogWithLogCatcher):
    # FIXME: We need specific tests for each LogFormatter about how the diffs
    # are displayed: --long indent them by depth, --short use a fixed
    # indent and --line does't display them. -- vila 10019

    def setUp(self):
        super().setUp()
        self.make_branch_with_diffs()

    def make_branch_with_diffs(self):
        level0 = self.make_branch_and_tree("level0")
        self.build_tree(["level0/file1", "level0/file2"])
        level0.add("file1")
        level0.add("file2")
        self.wt_commit(level0, "in branch level0")

        level1 = level0.controldir.sprout("level1").open_workingtree()
        self.build_tree_contents([("level1/file2", b"hello\n")])
        self.wt_commit(level1, "in branch level1")
        level0.merge_from_branch(level1.branch)
        self.wt_commit(level0, "merge branch level1")

    def _diff_file1_revno1(self):
        return b"""=== added file 'file1'
--- file1\t1970-01-01 00:00:00 +0000
+++ file1\t2005-11-22 00:00:00 +0000
@@ -0,0 +1,1 @@
+contents of level0/file1

"""

    def _diff_file2_revno2(self):
        return b"""=== modified file 'file2'
--- file2\t2005-11-22 00:00:00 +0000
+++ file2\t2005-11-22 00:00:01 +0000
@@ -1,1 +1,1 @@
-contents of level0/file2
+hello

"""

    def _diff_file2_revno1_1_1(self):
        return b"""=== modified file 'file2'
--- file2\t2005-11-22 00:00:00 +0000
+++ file2\t2005-11-22 00:00:01 +0000
@@ -1,1 +1,1 @@
-contents of level0/file2
+hello

"""

    def _diff_file2_revno1(self):
        return b"""=== added file 'file2'
--- file2\t1970-01-01 00:00:00 +0000
+++ file2\t2005-11-22 00:00:00 +0000
@@ -0,0 +1,1 @@
+contents of level0/file2

"""

    def assertLogRevnosAndDiff(self, args, expected, working_dir="."):
        self.run_bzr(["log", "-p"] + args, working_dir=working_dir)
        expected_revnos_and_depths = [(revno, depth) for revno, depth, diff in expected]
        # Check the revnos and depths first to make debugging easier
        self.assertEqual(
            expected_revnos_and_depths,
            [(r.revno, r.merge_depth) for r in self.get_captured_revisions()],
        )
        # Now check the diffs, adding the revno  in case of failure
        fmt = "In revno %s\n%s"
        for expected_rev, actual_rev in zip(expected, self.get_captured_revisions()):
            revno, depth, expected_diff = expected_rev
            actual_diff = actual_rev.diff
            self.assertEqualDiff(
                fmt % (revno, expected_diff), fmt % (revno, actual_diff)
            )

    def test_log_diff_with_merges(self):
        self.assertLogRevnosAndDiff(
            ["-n0"],
            [
                ("2", 0, self._diff_file2_revno2()),
                ("1.1.1", 1, self._diff_file2_revno1_1_1()),
                ("1", 0, self._diff_file1_revno1() + self._diff_file2_revno1()),
            ],
            working_dir="level0",
        )

    def test_log_diff_file1(self):
        self.assertLogRevnosAndDiff(
            ["-n0", "file1"],
            [("1", 0, self._diff_file1_revno1())],
            working_dir="level0",
        )

    def test_log_diff_file2(self):
        self.assertLogRevnosAndDiff(
            ["-n1", "file2"],
            [("2", 0, self._diff_file2_revno2()), ("1", 0, self._diff_file2_revno1())],
            working_dir="level0",
        )


class TestLogUnicodeDiff(TestLog):
    def test_log_show_diff_non_ascii(self):
        # Smoke test for bug #328007 UnicodeDecodeError on 'log -p'
        message = "Message with \xb5"
        body = b"Body with \xb5\n"
        wt = self.make_branch_and_tree(".")
        self.build_tree_contents([("foo", body)])
        wt.add("foo")
        wt.commit(message=message)
        # check that command won't fail with unicode error
        # don't care about exact output because we have other tests for this
        out, err = self.run_bzr("log -p --long")
        self.assertNotEqual("", out)
        self.assertEqual("", err)
        out, err = self.run_bzr("log -p --short")
        self.assertNotEqual("", out)
        self.assertEqual("", err)
        out, err = self.run_bzr("log -p --line")
        self.assertNotEqual("", out)
        self.assertEqual("", err)


class TestLogEncodings(tests.TestCaseInTempDir):
    _mu = "\xb5"
    _message = "Message with \xb5"

    # Encodings which can encode mu
    good_encodings = [
        "utf-8",
        "latin-1",
        "iso-8859-1",
        "cp437",  # Common windows encoding
        "cp1251",  # Russian windows encoding
        "cp1258",  # Common windows encoding
    ]
    # Encodings which cannot encode mu
    bad_encodings = [
        "ascii",
        "iso-8859-2",
        "koi8_r",
    ]

    def setUp(self):
        super().setUp()
        self.overrideAttr(osutils, "_cached_user_encoding")

    def create_branch(self):
        brz = self.run_bzr
        brz("init")
        self.build_tree_contents([("a", b"some stuff\n")])
        brz("add a")
        brz(["commit", "-m", self._message])

    def try_encoding(self, encoding, fail=False):
        brz = self.run_bzr
        if fail:
            self.assertRaises(UnicodeEncodeError, self._mu.encode, encoding)
            self._message.encode(encoding, "replace")
        else:
            self._message.encode(encoding)

        old_encoding = osutils._cached_user_encoding
        # This test requires that 'run_bzr' uses the current
        # breezy, because we override user_encoding, and expect
        # it to be used
        try:
            osutils._cached_user_encoding = "ascii"
            # We should be able to handle any encoding
            out, err = brz("log", encoding=encoding)
            if not fail:
                # Make sure we wrote mu as we expected it to exist
                self.assertNotEqual(-1, out.find(self._message))
            else:
                self.assertNotEqual(-1, out.find("Message with ?"))
        finally:
            osutils._cached_user_encoding = old_encoding

    def test_log_handles_encoding(self):
        self.create_branch()

        for encoding in self.good_encodings:
            self.try_encoding(encoding)

    def test_log_handles_bad_encoding(self):
        self.create_branch()

        for encoding in self.bad_encodings:
            self.try_encoding(encoding, fail=True)

    def test_stdout_encoding(self):
        brz = self.run_bzr
        osutils._cached_user_encoding = "cp1251"

        brz("init")
        self.build_tree(["a"])
        brz("add a")
        brz(["commit", "-m", "\u0422\u0435\u0441\u0442"])
        stdout, stderr = self.run_bzr_raw("log", encoding="cp866")

        message = stdout.splitlines()[-1]

        # explanation of the check:
        # u'\u0422\u0435\u0441\u0442' is word 'Test' in russian
        # in cp866  encoding this is string '\x92\xa5\xe1\xe2'
        # in cp1251 encoding this is string '\xd2\xe5\xf1\xf2'
        # This test should check that output of log command
        # encoded to sys.stdout.encoding
        test_in_cp866 = b"\x92\xa5\xe1\xe2"
        test_in_cp1251 = b"\xd2\xe5\xf1\xf2"
        # Make sure the log string is encoded in cp866
        self.assertEqual(test_in_cp866, message[2:])
        # Make sure the cp1251 string is not found anywhere
        self.assertEqual(-1, stdout.find(test_in_cp1251))


class TestLogFile(TestLogWithLogCatcher):
    def test_log_local_branch_file(self):
        """We should be able to log files in local treeless branches."""
        tree = self.make_branch_and_tree("tree")
        self.build_tree(["tree/file"])
        tree.add("file")
        tree.commit("revision 1")
        tree.controldir.destroy_workingtree()
        self.run_bzr("log tree/file")

    def prepare_tree(self, complex=False):
        # The complex configuration includes deletes and renames
        tree = self.make_branch_and_tree("parent")
        self.build_tree(["parent/file1", "parent/file2", "parent/file3"])
        tree.add("file1")
        tree.commit("add file1")
        tree.add("file2")
        tree.commit("add file2")
        tree.add("file3")
        tree.commit("add file3")
        child_tree = tree.controldir.sprout("child").open_workingtree()
        self.build_tree_contents([("child/file2", b"hello")])
        child_tree.commit(message="branch 1")
        tree.merge_from_branch(child_tree.branch)
        tree.commit(message="merge child branch")
        if complex:
            tree.remove("file2")
            tree.commit("remove file2")
            tree.rename_one("file3", "file4")
            tree.commit("file3 is now called file4")
            tree.remove("file1")
            tree.commit("remove file1")
        os.chdir("parent")

    # FIXME: It would be good to parametrize the following tests against all
    # formatters. But the revisions selection is not *currently* part of the
    # LogFormatter contract, so using LogCatcher is sufficient -- vila 100118
    def test_log_file1(self):
        self.prepare_tree()
        self.assertLogRevnos(["-n0", "file1"], ["1"])

    def test_log_file2(self):
        self.prepare_tree()
        # file2 full history
        self.assertLogRevnos(["-n0", "file2"], ["4", "3.1.1", "2"])
        # file2 in a merge revision
        self.assertLogRevnos(["-n0", "-r3.1.1", "file2"], ["3.1.1"])
        # file2 in a mainline revision
        self.assertLogRevnos(["-n0", "-r4", "file2"], ["4", "3.1.1"])
        # file2 since a revision
        self.assertLogRevnos(["-n0", "-r3..", "file2"], ["4", "3.1.1"])
        # file2 up to a revision
        self.assertLogRevnos(["-n0", "-r..3", "file2"], ["2"])

    def test_log_file3(self):
        self.prepare_tree()
        self.assertLogRevnos(["-n0", "file3"], ["3"])

    def test_log_file_historical_missing(self):
        # Check logging a deleted file gives an error if the
        # file isn't found at the end or start of the revision range
        self.prepare_tree(complex=True)
        err_msg = "Path unknown at end or start of revision range: file2"
        err = self.run_bzr("log file2", retcode=3)[1]
        self.assertContainsRe(err, err_msg)

    def test_log_file_historical_end(self):
        # Check logging a deleted file is ok if the file existed
        # at the end the revision range
        self.prepare_tree(complex=True)
        self.assertLogRevnos(["-n0", "-r..4", "file2"], ["4", "3.1.1", "2"])

    def test_log_file_historical_start(self):
        # Check logging a deleted file is ok if the file existed
        # at the start of the revision range
        self.prepare_tree(complex=True)
        self.assertLogRevnos(["file1"], [])

    def test_log_file_renamed(self):
        """File matched against revision range, not current tree."""
        self.prepare_tree(complex=True)

        # Check logging a renamed file gives an error by default
        err_msg = "Path unknown at end or start of revision range: file3"
        err = self.run_bzr("log file3", retcode=3)[1]
        self.assertContainsRe(err, err_msg)

        # Check we can see a renamed file if we give the right end revision
        self.assertLogRevnos(["-r..4", "file3"], ["3"])


class TestLogMultiple(TestLogWithLogCatcher):
    def prepare_tree(self):
        tree = self.make_branch_and_tree("parent")
        self.build_tree(
            [
                "parent/file1",
                "parent/file2",
                "parent/dir1/",
                "parent/dir1/file5",
                "parent/dir1/dir2/",
                "parent/dir1/dir2/file3",
                "parent/file4",
            ]
        )
        tree.add("file1")
        tree.commit("add file1")
        tree.add("file2")
        tree.commit("add file2")
        tree.add(["dir1", "dir1/dir2", "dir1/dir2/file3"])
        tree.commit("add file3")
        tree.add("file4")
        tree.commit("add file4")
        tree.add("dir1/file5")
        tree.commit("add file5")
        child_tree = tree.controldir.sprout("child").open_workingtree()
        self.build_tree_contents([("child/file2", b"hello")])
        child_tree.commit(message="branch 1")
        tree.merge_from_branch(child_tree.branch)
        tree.commit(message="merge child branch")
        os.chdir("parent")

    def test_log_files(self):
        """The log for multiple file should only list revs for those files."""
        self.prepare_tree()
        self.assertLogRevnos(
            ["file1", "file2", "dir1/dir2/file3"], ["6", "5.1.1", "3", "2", "1"]
        )

    def test_log_directory(self):
        """The log for a directory should show all nested files."""
        self.prepare_tree()
        self.assertLogRevnos(["dir1"], ["5", "3"])

    def test_log_nested_directory(self):
        """The log for a directory should show all nested files."""
        self.prepare_tree()
        self.assertLogRevnos(["dir1/dir2"], ["3"])

    def test_log_in_nested_directory(self):
        """The log for a directory should show all nested files."""
        self.prepare_tree()
        os.chdir("dir1")
        self.assertLogRevnos(["."], ["5", "3"])

    def test_log_files_and_directories(self):
        """Logging files and directories together should be fine."""
        self.prepare_tree()
        self.assertLogRevnos(["file4", "dir1/dir2"], ["4", "3"])

    def test_log_files_and_dirs_in_nested_directory(self):
        """The log for a directory should show all nested files."""
        self.prepare_tree()
        os.chdir("dir1")
        self.assertLogRevnos(["dir2", "file5"], ["5", "3"])


class MainlineGhostTests(TestLogWithLogCatcher):
    def setUp(self):
        super().setUp()
        tree = self.make_branch_and_tree("")
        tree.set_parent_ids([b"spooky"], allow_leftmost_as_ghost=True)
        tree.add("")
        tree.commit("msg1", rev_id=b"rev1")
        tree.commit("msg2", rev_id=b"rev2")

    def test_log_range(self):
        self.assertLogRevnos(["-r1..2"], ["2", "1"])

    def test_log_norange(self):
        self.assertLogRevnos([], ["2", "1"])

    def test_log_range_open_begin(self):
        (stdout, stderr) = self.run_bzr(["log", "-r..2"], retcode=3)
        self.assertEqual(["2", "1"], [r.revno for r in self.get_captured_revisions()])
        self.assertEqual("brz: ERROR: Further revision history missing.\n", stderr)

    def test_log_range_open_end(self):
        self.assertLogRevnos(["-r1.."], ["2", "1"])


class TestLogMatch(TestLogWithLogCatcher):
    def prepare_tree(self):
        tree = self.make_branch_and_tree("")
        self.build_tree(["/hello.txt", "/goodbye.txt"])
        tree.add("hello.txt")
        tree.commit(message="message1", committer="committer1", authors=["author1"])
        tree.add("goodbye.txt")
        tree.commit(message="message2", committer="committer2", authors=["author2"])

    def test_message(self):
        self.prepare_tree()
        self.assertLogRevnos(["-m", "message1"], ["1"])
        self.assertLogRevnos(["-m", "message2"], ["2"])
        self.assertLogRevnos(["-m", "message"], ["2", "1"])
        self.assertLogRevnos(["-m", "message1", "-m", "message2"], ["2", "1"])
        self.assertLogRevnos(["--match-message", "message1"], ["1"])
        self.assertLogRevnos(["--match-message", "message2"], ["2"])
        self.assertLogRevnos(["--match-message", "message"], ["2", "1"])
        self.assertLogRevnos(
            ["--match-message", "message1", "--match-message", "message2"], ["2", "1"]
        )
        self.assertLogRevnos(["--message", "message1"], ["1"])
        self.assertLogRevnos(["--message", "message2"], ["2"])
        self.assertLogRevnos(["--message", "message"], ["2", "1"])
        self.assertLogRevnos(
            ["--match-message", "message1", "--message", "message2"], ["2", "1"]
        )
        self.assertLogRevnos(
            ["--message", "message1", "--match-message", "message2"], ["2", "1"]
        )

    def test_committer(self):
        self.prepare_tree()
        self.assertLogRevnos(["-m", "committer1"], ["1"])
        self.assertLogRevnos(["-m", "committer2"], ["2"])
        self.assertLogRevnos(["-m", "committer"], ["2", "1"])
        self.assertLogRevnos(["-m", "committer1", "-m", "committer2"], ["2", "1"])
        self.assertLogRevnos(["--match-committer", "committer1"], ["1"])
        self.assertLogRevnos(["--match-committer", "committer2"], ["2"])
        self.assertLogRevnos(["--match-committer", "committer"], ["2", "1"])
        self.assertLogRevnos(
            ["--match-committer", "committer1", "--match-committer", "committer2"],
            ["2", "1"],
        )

    def test_author(self):
        self.prepare_tree()
        self.assertLogRevnos(["-m", "author1"], ["1"])
        self.assertLogRevnos(["-m", "author2"], ["2"])
        self.assertLogRevnos(["-m", "author"], ["2", "1"])
        self.assertLogRevnos(["-m", "author1", "-m", "author2"], ["2", "1"])
        self.assertLogRevnos(["--match-author", "author1"], ["1"])
        self.assertLogRevnos(["--match-author", "author2"], ["2"])
        self.assertLogRevnos(["--match-author", "author"], ["2", "1"])
        self.assertLogRevnos(
            ["--match-author", "author1", "--match-author", "author2"], ["2", "1"]
        )

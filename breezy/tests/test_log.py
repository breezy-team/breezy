# Copyright (C) 2005-2013, 2016 Canonical Ltd
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

import os
from io import StringIO

from .. import branchbuilder, errors, gpg, log, registry, revision, revisionspec, tests
from . import features


class TestLogMixin:
    def wt_commit(self, wt, message, **kwargs):
        """Use some mostly fixed values for commits to simplify tests.

        Tests can use this function to get some commit attributes. The time
        stamp is incremented at each commit.
        """
        if getattr(self, "timestamp", None) is None:
            self.timestamp = 1132617600  # Mon 2005-11-22 00:00:00 +0000
        else:
            self.timestamp += 1  # 1 second between each commit
        kwargs.setdefault("timestamp", self.timestamp)
        kwargs.setdefault("timezone", 0)  # UTC
        kwargs.setdefault("committer", "Joe Foo <joe@foo.com>")

        return wt.commit(message, **kwargs)


class TestCaseForLogFormatter(tests.TestCaseWithTransport, TestLogMixin):
    def setUp(self):
        super().setUp()
        # keep a reference to the "current" custom prop. handler registry
        self.properties_handler_registry = log.properties_handler_registry
        # Use a clean registry for log
        log.properties_handler_registry = registry.Registry()

        def restore():
            log.properties_handler_registry = self.properties_handler_registry

        self.addCleanup(restore)

    def assertFormatterResult(
        self,
        result,
        branch,
        formatter_class,
        formatter_kwargs=None,
        show_log_kwargs=None,
    ):
        logfile = self.make_utf8_encoded_stringio()
        if formatter_kwargs is None:
            formatter_kwargs = {}
        formatter = formatter_class(to_file=logfile, **formatter_kwargs)
        if show_log_kwargs is None:
            show_log_kwargs = {}
        log.show_log(branch, formatter, **show_log_kwargs)
        self.assertEqualDiff(result, logfile.getvalue())

    def make_standard_commit(self, branch_nick, **kwargs):
        wt = self.make_branch_and_tree(".")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        self.build_tree(["a"])
        wt.add(["a"])
        wt.branch.nick = branch_nick
        kwargs.setdefault("committer", "Lorem Ipsum <test@example.com>")
        kwargs.setdefault("authors", ["John Doe <jdoe@example.com>"])
        self.wt_commit(wt, "add a", **kwargs)
        return wt

    def make_commits_with_trailing_newlines(self, wt):
        """Helper method for LogFormatter tests."""
        b = wt.branch
        b.nick = "test"
        self.build_tree_contents([("a", b"hello moto\n")])
        self.wt_commit(wt, "simple log message", rev_id=b"a1")
        self.build_tree_contents([("b", b"goodbye\n")])
        wt.add("b")
        self.wt_commit(wt, "multiline\nlog\nmessage\n", rev_id=b"a2")

        self.build_tree_contents([("c", b"just another manic monday\n")])
        wt.add("c")
        self.wt_commit(wt, "single line with trailing newline\n", rev_id=b"a3")
        return b

    def _prepare_tree_with_merges(self, with_tags=False):
        wt = self.make_branch_and_memory_tree(".")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add("")
        self.wt_commit(wt, "rev-1", rev_id=b"rev-1")
        self.wt_commit(wt, "rev-merged", rev_id=b"rev-2a")
        wt.set_parent_ids([b"rev-1", b"rev-2a"])
        wt.branch.set_last_revision_info(1, b"rev-1")
        self.wt_commit(wt, "rev-2", rev_id=b"rev-2b")
        if with_tags:
            branch = wt.branch
            branch.tags.set_tag("v0.2", b"rev-2b")
            self.wt_commit(wt, "rev-3", rev_id=b"rev-3")
            branch.tags.set_tag("v1.0rc1", b"rev-3")
            branch.tags.set_tag("v1.0", b"rev-3")
        return wt


class LogCatcher(log.LogFormatter):
    """Pull log messages into a list rather than displaying them.

    To simplify testing we save logged revisions here rather than actually
    formatting anything, so that we can precisely check the result without
    being dependent on the formatting.
    """

    supports_merge_revisions = True
    supports_delta = True
    supports_diff = True
    preferred_levels = 0

    def __init__(self, *args, **kwargs):
        kwargs.update({"to_file": None})
        super().__init__(*args, **kwargs)
        self.revisions = []

    def log_revision(self, revision):
        self.revisions.append(revision)


class TestShowLog(tests.TestCaseWithTransport):
    def checkDelta(self, delta, **kw):
        """Check the filenames touched by a delta are as expected.

        Caller only have to pass in the list of files for each part, all
        unspecified parts are considered empty (and checked as such).
        """
        for n in "added", "removed", "renamed", "modified", "unchanged":
            # By default we expect an empty list
            expected = kw.get(n, [])
            # strip out only the path components
            got = [x.path[1] or x.path[0] for x in getattr(delta, n)]
            self.assertEqual(expected, got)

    def assertInvalidRevisonNumber(self, br, start, end):
        lf = LogCatcher()
        self.assertRaises(
            errors.InvalidRevisionNumber,
            log.show_log,
            br,
            lf,
            start_revision=start,
            end_revision=end,
        )

    def test_cur_revno(self):
        wt = self.make_branch_and_tree(".")
        b = wt.branch

        lf = LogCatcher()
        wt.commit("empty commit")
        log.show_log(b, lf, verbose=True, start_revision=1, end_revision=1)

        # Since there is a single revision in the branch all the combinations
        # below should fail.
        self.assertInvalidRevisonNumber(b, 2, 1)
        self.assertInvalidRevisonNumber(b, 1, 2)
        self.assertInvalidRevisonNumber(b, 0, 2)
        self.assertInvalidRevisonNumber(b, -1, 1)
        self.assertInvalidRevisonNumber(b, 1, -1)
        self.assertInvalidRevisonNumber(b, 1, 0)

    def test_empty_branch(self):
        wt = self.make_branch_and_tree(".")

        lf = LogCatcher()
        log.show_log(wt.branch, lf)
        # no entries yet
        self.assertEqual([], lf.revisions)

    def test_empty_commit(self):
        wt = self.make_branch_and_tree(".")

        wt.commit("empty commit")
        lf = LogCatcher()
        log.show_log(wt.branch, lf, verbose=True)
        revs = lf.revisions
        self.assertEqual(1, len(revs))
        self.assertEqual("1", revs[0].revno)
        self.assertEqual("empty commit", revs[0].rev.message)
        self.checkDelta(revs[0].delta)

    def test_simple_commit(self):
        wt = self.make_branch_and_tree(".")
        wt.commit("empty commit")
        self.build_tree(["hello"])
        wt.add("hello")
        wt.commit(
            "add one file",
            committer="\u013d\xf3r\xe9m \xcdp\u0161\xfam <test@example.com>",
        )
        lf = LogCatcher()
        log.show_log(wt.branch, lf, verbose=True)
        self.assertEqual(2, len(lf.revisions))
        # first one is most recent
        log_entry = lf.revisions[0]
        self.assertEqual("2", log_entry.revno)
        self.assertEqual("add one file", log_entry.rev.message)
        self.checkDelta(log_entry.delta, added=["hello"])

    def test_commit_message_with_control_chars(self):
        wt = self.make_branch_and_tree(".")
        msg = "All 8-bit chars: " + "".join([chr(x) for x in range(256)])
        msg = msg.replace("\r", "\n")
        wt.commit(msg)
        lf = LogCatcher()
        log.show_log(wt.branch, lf, verbose=True)
        committed_msg = lf.revisions[0].rev.message
        if wt.branch.repository._revision_serializer.squashes_xml_invalid_characters:
            self.assertNotEqual(msg, committed_msg)
            self.assertGreater(len(committed_msg), len(msg))
        else:
            self.assertEqual(msg, committed_msg)

    def test_commit_message_without_control_chars(self):
        wt = self.make_branch_and_tree(".")
        # escaped.  As ElementTree apparently does some kind of
        # newline conversion, neither LF (\x0A) nor CR (\x0D) are
        # included in the test commit message, even though they are
        # valid XML 1.0 characters.
        msg = "\x09" + "".join([chr(x) for x in range(0x20, 256)])
        wt.commit(msg)
        lf = LogCatcher()
        log.show_log(wt.branch, lf, verbose=True)
        committed_msg = lf.revisions[0].rev.message
        self.assertEqual(msg, committed_msg)

    def test_deltas_in_merge_revisions(self):
        """Check deltas created for both mainline and merge revisions."""
        wt = self.make_branch_and_tree("parent")
        self.build_tree(["parent/file1", "parent/file2", "parent/file3"])
        wt.add("file1")
        wt.add("file2")
        wt.commit(message="add file1 and file2")
        self.run_bzr("branch parent child")
        os.unlink("child/file1")
        with open("child/file2", "wb") as f:
            f.write(b"hello\n")
        self.run_bzr(["commit", "-m", "remove file1 and modify file2", "child"])
        os.chdir("parent")
        self.run_bzr("merge ../child")
        wt.commit("merge child branch")
        os.chdir("..")
        b = wt.branch
        lf = LogCatcher()
        lf.supports_merge_revisions = True
        log.show_log(b, lf, verbose=True)

        revs = lf.revisions
        self.assertEqual(3, len(revs))

        logentry = revs[0]
        self.assertEqual("2", logentry.revno)
        self.assertEqual("merge child branch", logentry.rev.message)
        self.checkDelta(logentry.delta, removed=["file1"], modified=["file2"])

        logentry = revs[1]
        self.assertEqual("1.1.1", logentry.revno)
        self.assertEqual("remove file1 and modify file2", logentry.rev.message)
        self.checkDelta(logentry.delta, removed=["file1"], modified=["file2"])

        logentry = revs[2]
        self.assertEqual("1", logentry.revno)
        self.assertEqual("add file1 and file2", logentry.rev.message)
        self.checkDelta(logentry.delta, added=["file1", "file2"])

    # bug #842695
    @tests.expectedFailure
    def test_bug_842695_log_restricted_to_dir(self):
        # Comments here indicate revision numbers in trunk  # VVVVV
        trunk = self.make_branch_and_tree("this")
        trunk.commit("initial trunk")  # 1
        adder = trunk.controldir.sprout("adder").open_workingtree()
        merger = trunk.controldir.sprout("merger").open_workingtree()
        self.build_tree_contents(
            [
                ("adder/dir/",),
                ("adder/dir/file", b"foo"),
            ]
        )
        adder.add(["dir", "dir/file"])
        adder.commit("added dir")  # 1.1.1
        trunk.merge_from_branch(adder.branch)
        trunk.commit("merged adder into trunk")  # 2
        merger.merge_from_branch(trunk.branch)
        merger.commit("merged trunk into merger")  # 1.2.1
        # Commits are processed in increments of 200 revisions, so
        # make sure the two merges into trunk are in different chunks.
        for i in range(200):
            trunk.commit("intermediate commit %d" % i)  # 3-202
        trunk.merge_from_branch(merger.branch)
        trunk.commit("merged merger into trunk")  # 203
        file_id = trunk.path2id("dir")
        lf = LogCatcher()
        lf.supports_merge_revisions = True
        log.show_log(trunk.branch, lf, file_id)
        self.assertEqual(["2", "1.1.1"], [r.revno for r in lf.revisions])


class TestFormatSignatureValidity(tests.TestCaseWithTransport):
    def verify_revision_signature(self, revid, gpg_strategy):
        return (
            gpg.SIGNATURE_VALID,
            "UTF8 Test \xa1\xb1\xc1\xd1\xe1\xf1 <jrandom@example.com>",
        )

    def test_format_signature_validity_utf(self):
        """Check that GPG signatures containing UTF-8 names are formatted
        correctly.
        """
        self.requireFeature(features.gpg)
        wt = self.make_branch_and_tree(".")
        revid = wt.commit("empty commit")
        repo = wt.branch.repository
        # Monkey patch out checking if this rev is actually signed, since we
        # can't sign it without a heavier TestCase and LoopbackGPGStrategy
        # doesn't care anyways.
        self.overrideAttr(
            repo, "verify_revision_signature", self.verify_revision_signature
        )
        out = log.format_signature_validity(revid, wt.branch)
        self.assertEqual(
            "valid signature from UTF8 Test \xa1\xb1\xc1\xd1\xe1\xf1 <jrandom@example.com>",
            out,
        )


class TestShortLogFormatter(TestCaseForLogFormatter):
    def test_trailing_newlines(self):
        wt = self.make_branch_and_tree(".")
        b = self.make_commits_with_trailing_newlines(wt)
        self.assertFormatterResult(
            b"""\
    3 Joe Foo\t2005-11-22
      single line with trailing newline

    2 Joe Foo\t2005-11-22
      multiline
      log
      message

    1 Joe Foo\t2005-11-22
      simple log message

""",
            b,
            log.ShortLogFormatter,
        )

    def test_short_log_with_merges(self):
        wt = self._prepare_tree_with_merges()
        self.assertFormatterResult(
            b"""\
    2 Joe Foo\t2005-11-22 [merge]
      rev-2

    1 Joe Foo\t2005-11-22
      rev-1

""",
            wt.branch,
            log.ShortLogFormatter,
        )

    def test_short_log_with_merges_and_advice(self):
        wt = self._prepare_tree_with_merges()
        self.assertFormatterResult(
            b"""\
    2 Joe Foo\t2005-11-22 [merge]
      rev-2

    1 Joe Foo\t2005-11-22
      rev-1

Use --include-merged or -n0 to see merged revisions.
""",
            wt.branch,
            log.ShortLogFormatter,
            formatter_kwargs={"show_advice": True},
        )

    def test_short_log_with_merges_and_range(self):
        wt = self._prepare_tree_with_merges()
        self.wt_commit(wt, "rev-3a", rev_id=b"rev-3a")
        wt.branch.set_last_revision_info(2, b"rev-2b")
        wt.set_parent_ids([b"rev-2b", b"rev-3a"])
        self.wt_commit(wt, "rev-3b", rev_id=b"rev-3b")
        self.assertFormatterResult(
            b"""\
    3 Joe Foo\t2005-11-22 [merge]
      rev-3b

    2 Joe Foo\t2005-11-22 [merge]
      rev-2

""",
            wt.branch,
            log.ShortLogFormatter,
            show_log_kwargs={"start_revision": 2, "end_revision": 3},
        )

    def test_short_log_with_tags(self):
        wt = self._prepare_tree_with_merges(with_tags=True)
        self.assertFormatterResult(
            b"""\
    3 Joe Foo\t2005-11-22 {v1.0, v1.0rc1}
      rev-3

    2 Joe Foo\t2005-11-22 {v0.2} [merge]
      rev-2

    1 Joe Foo\t2005-11-22
      rev-1

""",
            wt.branch,
            log.ShortLogFormatter,
        )

    def test_short_log_single_merge_revision(self):
        wt = self._prepare_tree_with_merges()
        revspec = revisionspec.RevisionSpec.from_string("1.1.1")
        rev = revspec.in_history(wt.branch)
        self.assertFormatterResult(
            b"""\
      1.1.1 Joe Foo\t2005-11-22
            rev-merged

""",
            wt.branch,
            log.ShortLogFormatter,
            show_log_kwargs={"start_revision": rev, "end_revision": rev},
        )

    def test_show_ids(self):
        wt = self.make_branch_and_tree("parent")
        self.build_tree(["parent/f1", "parent/f2"])
        wt.add(["f1", "f2"])
        self.wt_commit(wt, "first post", rev_id=b"a")
        child_wt = wt.controldir.sprout("child").open_workingtree()
        self.wt_commit(child_wt, "branch 1 changes", rev_id=b"b")
        wt.merge_from_branch(child_wt.branch)
        self.wt_commit(wt, "merge branch 1", rev_id=b"c")
        self.assertFormatterResult(
            b"""\
    2 Joe Foo\t2005-11-22 [merge]
      revision-id:c
      merge branch 1

          1.1.1 Joe Foo\t2005-11-22
                revision-id:b
                branch 1 changes

    1 Joe Foo\t2005-11-22
      revision-id:a
      first post

""",
            wt.branch,
            log.ShortLogFormatter,
            formatter_kwargs={"levels": 0, "show_ids": True},
        )


class TestShortLogFormatterWithMergeRevisions(TestCaseForLogFormatter):
    def test_short_merge_revs_log_with_merges(self):
        wt = self._prepare_tree_with_merges()
        # Note that the 1.1.1 indenting is in fact correct given that
        # the revision numbers are right justified within 5 characters
        # for mainline revnos and 9 characters for dotted revnos.
        self.assertFormatterResult(
            b"""\
    2 Joe Foo\t2005-11-22 [merge]
      rev-2

          1.1.1 Joe Foo\t2005-11-22
                rev-merged

    1 Joe Foo\t2005-11-22
      rev-1

""",
            wt.branch,
            log.ShortLogFormatter,
            formatter_kwargs={"levels": 0},
        )

    def test_short_merge_revs_log_single_merge_revision(self):
        wt = self._prepare_tree_with_merges()
        revspec = revisionspec.RevisionSpec.from_string("1.1.1")
        rev = revspec.in_history(wt.branch)
        self.assertFormatterResult(
            b"""\
      1.1.1 Joe Foo\t2005-11-22
            rev-merged

""",
            wt.branch,
            log.ShortLogFormatter,
            formatter_kwargs={"levels": 0},
            show_log_kwargs={"start_revision": rev, "end_revision": rev},
        )


class TestLongLogFormatter(TestCaseForLogFormatter):
    def test_verbose_log(self):
        """Verbose log includes changed files.

        bug #4676
        """
        wt = self.make_standard_commit("test_verbose_log", authors=[])
        self.assertFormatterResult(
            b"""\
------------------------------------------------------------
revno: 1
committer: Lorem Ipsum <test@example.com>
branch nick: test_verbose_log
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  add a
added:
  a
""",
            wt.branch,
            log.LongLogFormatter,
            show_log_kwargs={"verbose": True},
        )

    def test_merges_are_indented_by_level(self):
        wt = self.make_branch_and_tree("parent")
        self.wt_commit(wt, "first post")
        child_wt = wt.controldir.sprout("child").open_workingtree()
        self.wt_commit(child_wt, "branch 1")
        smallerchild_wt = wt.controldir.sprout("smallerchild").open_workingtree()
        self.wt_commit(smallerchild_wt, "branch 2")
        child_wt.merge_from_branch(smallerchild_wt.branch)
        self.wt_commit(child_wt, "merge branch 2")
        wt.merge_from_branch(child_wt.branch)
        self.wt_commit(wt, "merge branch 1")
        self.assertFormatterResult(
            b"""\
------------------------------------------------------------
revno: 2 [merge]
committer: Joe Foo <joe@foo.com>
branch nick: parent
timestamp: Tue 2005-11-22 00:00:04 +0000
message:
  merge branch 1
    ------------------------------------------------------------
    revno: 1.1.2 [merge]
    committer: Joe Foo <joe@foo.com>
    branch nick: child
    timestamp: Tue 2005-11-22 00:00:03 +0000
    message:
      merge branch 2
        ------------------------------------------------------------
        revno: 1.2.1
        committer: Joe Foo <joe@foo.com>
        branch nick: smallerchild
        timestamp: Tue 2005-11-22 00:00:02 +0000
        message:
          branch 2
    ------------------------------------------------------------
    revno: 1.1.1
    committer: Joe Foo <joe@foo.com>
    branch nick: child
    timestamp: Tue 2005-11-22 00:00:01 +0000
    message:
      branch 1
------------------------------------------------------------
revno: 1
committer: Joe Foo <joe@foo.com>
branch nick: parent
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  first post
""",
            wt.branch,
            log.LongLogFormatter,
            formatter_kwargs={"levels": 0},
            show_log_kwargs={"verbose": True},
        )

    def test_verbose_merge_revisions_contain_deltas(self):
        wt = self.make_branch_and_tree("parent")
        self.build_tree(["parent/f1", "parent/f2"])
        wt.add(["f1", "f2"])
        self.wt_commit(wt, "first post")
        child_wt = wt.controldir.sprout("child").open_workingtree()
        os.unlink("child/f1")
        self.build_tree_contents([("child/f2", b"hello\n")])
        self.wt_commit(child_wt, "removed f1 and modified f2")
        wt.merge_from_branch(child_wt.branch)
        self.wt_commit(wt, "merge branch 1")
        self.assertFormatterResult(
            b"""\
------------------------------------------------------------
revno: 2 [merge]
committer: Joe Foo <joe@foo.com>
branch nick: parent
timestamp: Tue 2005-11-22 00:00:02 +0000
message:
  merge branch 1
removed:
  f1
modified:
  f2
    ------------------------------------------------------------
    revno: 1.1.1
    committer: Joe Foo <joe@foo.com>
    branch nick: child
    timestamp: Tue 2005-11-22 00:00:01 +0000
    message:
      removed f1 and modified f2
    removed:
      f1
    modified:
      f2
------------------------------------------------------------
revno: 1
committer: Joe Foo <joe@foo.com>
branch nick: parent
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  first post
added:
  f1
  f2
""",
            wt.branch,
            log.LongLogFormatter,
            formatter_kwargs={"levels": 0},
            show_log_kwargs={"verbose": True},
        )

    def test_trailing_newlines(self):
        wt = self.make_branch_and_tree(".")
        b = self.make_commits_with_trailing_newlines(wt)
        self.assertFormatterResult(
            b"""\
------------------------------------------------------------
revno: 3
committer: Joe Foo <joe@foo.com>
branch nick: test
timestamp: Tue 2005-11-22 00:00:02 +0000
message:
  single line with trailing newline
------------------------------------------------------------
revno: 2
committer: Joe Foo <joe@foo.com>
branch nick: test
timestamp: Tue 2005-11-22 00:00:01 +0000
message:
  multiline
  log
  message
------------------------------------------------------------
revno: 1
committer: Joe Foo <joe@foo.com>
branch nick: test
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  simple log message
""",
            b,
            log.LongLogFormatter,
        )

    def test_author_in_log(self):
        """Log includes the author name if it's set in
        the revision properties.
        """
        wt = self.make_standard_commit(
            "test_author_log",
            authors=["John Doe <jdoe@example.com>", "Jane Rey <jrey@example.com>"],
        )
        self.assertFormatterResult(
            b"""\
------------------------------------------------------------
revno: 1
author: John Doe <jdoe@example.com>, Jane Rey <jrey@example.com>
committer: Lorem Ipsum <test@example.com>
branch nick: test_author_log
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  add a
""",
            wt.branch,
            log.LongLogFormatter,
        )

    def test_properties_in_log(self):
        """Log includes the custom properties returned by the registered
        handlers.
        """
        wt = self.make_standard_commit("test_properties_in_log")

        def trivial_custom_prop_handler(revision):
            return {"test_prop": "test_value"}

        # Cleaned up in setUp()
        log.properties_handler_registry.register(
            "trivial_custom_prop_handler", trivial_custom_prop_handler
        )
        self.assertFormatterResult(
            b"""\
------------------------------------------------------------
revno: 1
test_prop: test_value
author: John Doe <jdoe@example.com>
committer: Lorem Ipsum <test@example.com>
branch nick: test_properties_in_log
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  add a
""",
            wt.branch,
            log.LongLogFormatter,
        )

    def test_properties_in_short_log(self):
        """Log includes the custom properties returned by the registered
        handlers.
        """
        wt = self.make_standard_commit("test_properties_in_short_log")

        def trivial_custom_prop_handler(revision):
            return {"test_prop": "test_value"}

        log.properties_handler_registry.register(
            "trivial_custom_prop_handler", trivial_custom_prop_handler
        )
        self.assertFormatterResult(
            b"""\
    1 John Doe\t2005-11-22
      test_prop: test_value
      add a

""",
            wt.branch,
            log.ShortLogFormatter,
        )

    def test_error_in_properties_handler(self):
        """Log includes the custom properties returned by the registered
        handlers.
        """
        wt = self.make_standard_commit(
            "error_in_properties_handler", revprops={"first_prop": "first_value"}
        )
        sio = self.make_utf8_encoded_stringio()
        formatter = log.LongLogFormatter(to_file=sio)

        def trivial_custom_prop_handler(revision):
            raise Exception("a test error")

        log.properties_handler_registry.register(
            "trivial_custom_prop_handler", trivial_custom_prop_handler
        )
        log.show_log(wt.branch, formatter)
        self.assertContainsRe(sio.getvalue(), b"brz: ERROR: Exception: a test error")

    def test_properties_handler_bad_argument(self):
        wt = self.make_standard_commit(
            "bad_argument", revprops={"a_prop": "test_value"}
        )
        sio = self.make_utf8_encoded_stringio()
        formatter = log.LongLogFormatter(to_file=sio)

        def bad_argument_prop_handler(revision):
            return {"custom_prop_name": revision.properties["a_prop"]}

        log.properties_handler_registry.register(
            "bad_argument_prop_handler", bad_argument_prop_handler
        )

        self.assertRaises(AttributeError, formatter.show_properties, "a revision", "")

        revision = wt.branch.repository.get_revision(wt.branch.last_revision())
        formatter.show_properties(revision, "")
        self.assertEqualDiff(b"custom_prop_name: test_value\n", sio.getvalue())

    def test_show_ids(self):
        wt = self.make_branch_and_tree("parent")
        self.build_tree(["parent/f1", "parent/f2"])
        wt.add(["f1", "f2"])
        self.wt_commit(wt, "first post", rev_id=b"a")
        child_wt = wt.controldir.sprout("child").open_workingtree()
        self.wt_commit(child_wt, "branch 1 changes", rev_id=b"b")
        wt.merge_from_branch(child_wt.branch)
        self.wt_commit(wt, "merge branch 1", rev_id=b"c")
        self.assertFormatterResult(
            b"""\
------------------------------------------------------------
revno: 2 [merge]
revision-id: c
parent: a
parent: b
committer: Joe Foo <joe@foo.com>
branch nick: parent
timestamp: Tue 2005-11-22 00:00:02 +0000
message:
  merge branch 1
    ------------------------------------------------------------
    revno: 1.1.1
    revision-id: b
    parent: a
    committer: Joe Foo <joe@foo.com>
    branch nick: child
    timestamp: Tue 2005-11-22 00:00:01 +0000
    message:
      branch 1 changes
------------------------------------------------------------
revno: 1
revision-id: a
committer: Joe Foo <joe@foo.com>
branch nick: parent
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  first post
""",
            wt.branch,
            log.LongLogFormatter,
            formatter_kwargs={"levels": 0, "show_ids": True},
        )


class TestLongLogFormatterWithoutMergeRevisions(TestCaseForLogFormatter):
    def test_long_verbose_log(self):
        """Verbose log includes changed files.

        bug #4676
        """
        wt = self.make_standard_commit("test_long_verbose_log", authors=[])
        self.assertFormatterResult(
            b"""\
------------------------------------------------------------
revno: 1
committer: Lorem Ipsum <test@example.com>
branch nick: test_long_verbose_log
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  add a
added:
  a
""",
            wt.branch,
            log.LongLogFormatter,
            formatter_kwargs={"levels": 1},
            show_log_kwargs={"verbose": True},
        )

    def test_long_verbose_contain_deltas(self):
        wt = self.make_branch_and_tree("parent")
        self.build_tree(["parent/f1", "parent/f2"])
        wt.add(["f1", "f2"])
        self.wt_commit(wt, "first post")
        child_wt = wt.controldir.sprout("child").open_workingtree()
        os.unlink("child/f1")
        self.build_tree_contents([("child/f2", b"hello\n")])
        self.wt_commit(child_wt, "removed f1 and modified f2")
        wt.merge_from_branch(child_wt.branch)
        self.wt_commit(wt, "merge branch 1")
        self.assertFormatterResult(
            b"""\
------------------------------------------------------------
revno: 2 [merge]
committer: Joe Foo <joe@foo.com>
branch nick: parent
timestamp: Tue 2005-11-22 00:00:02 +0000
message:
  merge branch 1
removed:
  f1
modified:
  f2
------------------------------------------------------------
revno: 1
committer: Joe Foo <joe@foo.com>
branch nick: parent
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  first post
added:
  f1
  f2
""",
            wt.branch,
            log.LongLogFormatter,
            formatter_kwargs={"levels": 1},
            show_log_kwargs={"verbose": True},
        )

    def test_long_trailing_newlines(self):
        wt = self.make_branch_and_tree(".")
        b = self.make_commits_with_trailing_newlines(wt)
        self.assertFormatterResult(
            b"""\
------------------------------------------------------------
revno: 3
committer: Joe Foo <joe@foo.com>
branch nick: test
timestamp: Tue 2005-11-22 00:00:02 +0000
message:
  single line with trailing newline
------------------------------------------------------------
revno: 2
committer: Joe Foo <joe@foo.com>
branch nick: test
timestamp: Tue 2005-11-22 00:00:01 +0000
message:
  multiline
  log
  message
------------------------------------------------------------
revno: 1
committer: Joe Foo <joe@foo.com>
branch nick: test
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  simple log message
""",
            b,
            log.LongLogFormatter,
            formatter_kwargs={"levels": 1},
        )

    def test_long_author_in_log(self):
        """Log includes the author name if it's set in
        the revision properties.
        """
        wt = self.make_standard_commit("test_author_log")
        self.assertFormatterResult(
            b"""\
------------------------------------------------------------
revno: 1
author: John Doe <jdoe@example.com>
committer: Lorem Ipsum <test@example.com>
branch nick: test_author_log
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  add a
""",
            wt.branch,
            log.LongLogFormatter,
            formatter_kwargs={"levels": 1},
        )

    def test_long_properties_in_log(self):
        """Log includes the custom properties returned by the registered
        handlers.
        """
        wt = self.make_standard_commit("test_properties_in_log")

        def trivial_custom_prop_handler(revision):
            return {"test_prop": "test_value"}

        log.properties_handler_registry.register(
            "trivial_custom_prop_handler", trivial_custom_prop_handler
        )
        self.assertFormatterResult(
            b"""\
------------------------------------------------------------
revno: 1
test_prop: test_value
author: John Doe <jdoe@example.com>
committer: Lorem Ipsum <test@example.com>
branch nick: test_properties_in_log
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  add a
""",
            wt.branch,
            log.LongLogFormatter,
            formatter_kwargs={"levels": 1},
        )


class TestLineLogFormatter(TestCaseForLogFormatter):
    def test_line_log(self):
        """Line log should show revno.

        bug #5162
        """
        wt = self.make_standard_commit(
            "test-line-log",
            committer="Line-Log-Formatter Tester <test@line.log>",
            authors=[],
        )
        self.assertFormatterResult(
            b"""\
1: Line-Log-Formatte... 2005-11-22 add a
""",
            wt.branch,
            log.LineLogFormatter,
        )

    def test_trailing_newlines(self):
        wt = self.make_branch_and_tree(".")
        b = self.make_commits_with_trailing_newlines(wt)
        self.assertFormatterResult(
            b"""\
3: Joe Foo 2005-11-22 single line with trailing newline
2: Joe Foo 2005-11-22 multiline
1: Joe Foo 2005-11-22 simple log message
""",
            b,
            log.LineLogFormatter,
        )

    def test_line_log_single_merge_revision(self):
        wt = self._prepare_tree_with_merges()
        revspec = revisionspec.RevisionSpec.from_string("1.1.1")
        rev = revspec.in_history(wt.branch)
        self.assertFormatterResult(
            b"""\
1.1.1: Joe Foo 2005-11-22 rev-merged
""",
            wt.branch,
            log.LineLogFormatter,
            show_log_kwargs={"start_revision": rev, "end_revision": rev},
        )

    def test_line_log_with_tags(self):
        wt = self._prepare_tree_with_merges(with_tags=True)
        self.assertFormatterResult(
            b"""\
3: Joe Foo 2005-11-22 {v1.0, v1.0rc1} rev-3
2: Joe Foo 2005-11-22 [merge] {v0.2} rev-2
1: Joe Foo 2005-11-22 rev-1
""",
            wt.branch,
            log.LineLogFormatter,
        )


class TestLineLogFormatterWithMergeRevisions(TestCaseForLogFormatter):
    def test_line_merge_revs_log(self):
        """Line log should show revno.

        bug #5162
        """
        wt = self.make_standard_commit(
            "test-line-log",
            committer="Line-Log-Formatter Tester <test@line.log>",
            authors=[],
        )
        self.assertFormatterResult(
            b"""\
1: Line-Log-Formatte... 2005-11-22 add a
""",
            wt.branch,
            log.LineLogFormatter,
        )

    def test_line_merge_revs_log_single_merge_revision(self):
        wt = self._prepare_tree_with_merges()
        revspec = revisionspec.RevisionSpec.from_string("1.1.1")
        rev = revspec.in_history(wt.branch)
        self.assertFormatterResult(
            b"""\
1.1.1: Joe Foo 2005-11-22 rev-merged
""",
            wt.branch,
            log.LineLogFormatter,
            formatter_kwargs={"levels": 0},
            show_log_kwargs={"start_revision": rev, "end_revision": rev},
        )

    def test_line_merge_revs_log_with_merges(self):
        wt = self._prepare_tree_with_merges()
        self.assertFormatterResult(
            b"""\
2: Joe Foo 2005-11-22 [merge] rev-2
  1.1.1: Joe Foo 2005-11-22 rev-merged
1: Joe Foo 2005-11-22 rev-1
""",
            wt.branch,
            log.LineLogFormatter,
            formatter_kwargs={"levels": 0},
        )


class TestGnuChangelogFormatter(TestCaseForLogFormatter):
    def test_gnu_changelog(self):
        wt = self.make_standard_commit("nicky", authors=[])
        self.assertFormatterResult(
            b"""\
2005-11-22  Lorem Ipsum  <test@example.com>

\tadd a

""",
            wt.branch,
            log.GnuChangelogLogFormatter,
        )

    def test_with_authors(self):
        wt = self.make_standard_commit(
            "nicky",
            authors=["Fooa Fooz <foo@example.com>", "Bari Baro <bar@example.com>"],
        )
        self.assertFormatterResult(
            b"""\
2005-11-22  Fooa Fooz  <foo@example.com>

\tadd a

""",
            wt.branch,
            log.GnuChangelogLogFormatter,
        )

    def test_verbose(self):
        wt = self.make_standard_commit("nicky")
        self.assertFormatterResult(
            b"""\
2005-11-22  John Doe  <jdoe@example.com>

\t* a:

\tadd a

""",
            wt.branch,
            log.GnuChangelogLogFormatter,
            show_log_kwargs={"verbose": True},
        )


class TestShowChangedRevisions(tests.TestCaseWithTransport):
    def test_show_changed_revisions_verbose(self):
        tree = self.make_branch_and_tree("tree_a")
        self.build_tree(["tree_a/foo"])
        tree.add("foo")
        tree.commit("bar", rev_id=b"bar-id")
        s = self.make_utf8_encoded_stringio()
        log.show_changed_revisions(tree.branch, [], [b"bar-id"], s)
        self.assertContainsRe(s.getvalue(), b"bar")
        self.assertNotContainsRe(s.getvalue(), b"foo")


class TestLogFormatter(tests.TestCase):
    def setUp(self):
        super().setUp()
        self.rev = revision.Revision(
            b"a-id",
            parent_ids=[],
            properties={},
            message="",
            committer="",
            timestamp=0,
            timezone=0,
            inventory_sha1=None,
        )
        self.lf = log.LogFormatter(None)

    def test_short_committer(self):
        def assertCommitter(expected, committer):
            self.rev = revision.Revision(
                b"a-id",
                parent_ids=[],
                properties={},
                message="",
                committer=committer,
                timestamp=0,
                timezone=0,
                inventory_sha1=None,
            )
            self.assertEqual(expected, self.lf.short_committer(self.rev))

        assertCommitter("John Doe", "John Doe <jdoe@example.com>")
        assertCommitter("John Smith", "John Smith <jsmith@example.com>")
        assertCommitter("John Smith", "John Smith")
        assertCommitter("jsmith@example.com", "jsmith@example.com")
        assertCommitter("jsmith@example.com", "<jsmith@example.com>")
        assertCommitter("John Smith", "John Smith jsmith@example.com")

    def test_short_author(self):
        def assertAuthor(expected, author):
            self.rev = revision.Revision(
                b"a-id",
                parent_ids=[],
                properties={"author": author},
                message="",
                committer="",
                timestamp=0,
                timezone=0,
                inventory_sha1=None,
            )
            self.assertEqual(expected, self.lf.short_author(self.rev))

        assertAuthor("John Smith", "John Smith <jsmith@example.com>")
        assertAuthor("John Smith", "John Smith")
        assertAuthor("jsmith@example.com", "jsmith@example.com")
        assertAuthor("jsmith@example.com", "<jsmith@example.com>")
        assertAuthor("John Smith", "John Smith jsmith@example.com")

    def test_short_author_from_committer(self):
        self.rev = revision.Revision(
            b"a-id",
            parent_ids=[],
            properties={},
            message="",
            committer="John Doe <jdoe@example.com>",
            timestamp=0,
            timezone=0,
            inventory_sha1=None,
        )
        self.assertEqual("John Doe", self.lf.short_author(self.rev))

    def test_short_author_from_authors(self):
        self.rev = revision.Revision(
            b"a-id",
            parent_ids=[],
            properties={
                "authors": "John Smith <jsmith@example.com>\nJane Rey <jrey@example.com>"
            },
            message="",
            committer="",
            timestamp=0,
            timezone=0,
            inventory_sha1=None,
        )
        self.assertEqual("John Smith", self.lf.short_author(self.rev))


class TestReverseByDepth(tests.TestCase):
    """Test reverse_by_depth behavior.

    This is used to present revisions in forward (oldest first) order in a nice
    layout.

    The tests use lighter revision description to ease reading.
    """

    def assertReversed(self, forward, backward):
        # Transform the descriptions to suit the API: tests use (revno, depth),
        # while the API expects (revid, revno, depth)
        def complete_revisions(l):
            """Transform the description to suit the API.

            Tests use (revno, depth) whil the API expects (revid, revno, depth).
            Since the revid is arbitrary, we just duplicate revno
            """
            return [(r, r, d) for r, d in l]

        forward = complete_revisions(forward)
        backward = complete_revisions(backward)
        self.assertEqual(forward, log.reverse_by_depth(backward))

    def test_mainline_revisions(self):
        self.assertReversed([("1", 0), ("2", 0)], [("2", 0), ("1", 0)])

    def test_merged_revisions(self):
        self.assertReversed(
            [
                ("1", 0),
                ("2", 0),
                ("2.2", 1),
                ("2.1", 1),
            ],
            [
                ("2", 0),
                ("2.1", 1),
                ("2.2", 1),
                ("1", 0),
            ],
        )

    def test_shifted_merged_revisions(self):
        """Test irregular layout.

        Requesting revisions touching a file can produce "holes" in the depths.
        """
        self.assertReversed(
            [
                ("1", 0),
                ("2", 0),
                ("1.1", 2),
                ("1.2", 2),
            ],
            [
                ("2", 0),
                ("1.2", 2),
                ("1.1", 2),
                ("1", 0),
            ],
        )

    def test_merged_without_child_revisions(self):
        """Test irregular layout.

        Revision ranges can produce "holes" in the depths.
        """
        # When a revision of higher depth doesn't follow one of lower depth, we
        # assume a lower depth one is virtually there
        self.assertReversed(
            [("1", 2), ("2", 2), ("3", 3), ("4", 4)],
            [
                ("4", 4),
                ("3", 3),
                ("2", 2),
                ("1", 2),
            ],
        )
        # So we get the same order after reversing below even if the original
        # revisions are not in the same order.
        self.assertReversed(
            [("1", 2), ("2", 2), ("3", 3), ("4", 4)],
            [
                ("3", 3),
                ("4", 4),
                ("2", 2),
                ("1", 2),
            ],
        )


class TestHistoryChange(tests.TestCaseWithTransport):
    def setup_a_tree(self):
        tree = self.make_branch_and_tree("tree")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit("1a", rev_id=b"1a")
        tree.commit("2a", rev_id=b"2a")
        tree.commit("3a", rev_id=b"3a")
        return tree

    def setup_ab_tree(self):
        tree = self.setup_a_tree()
        tree.set_last_revision(b"1a")
        tree.branch.set_last_revision_info(1, b"1a")
        tree.commit("2b", rev_id=b"2b")
        tree.commit("3b", rev_id=b"3b")
        return tree

    def setup_ac_tree(self):
        tree = self.setup_a_tree()
        tree.set_last_revision(revision.NULL_REVISION)
        tree.branch.set_last_revision_info(0, revision.NULL_REVISION)
        tree.commit("1c", rev_id=b"1c")
        tree.commit("2c", rev_id=b"2c")
        tree.commit("3c", rev_id=b"3c")
        return tree

    def test_all_new(self):
        tree = self.setup_ab_tree()
        old, new = log.get_history_change(b"1a", b"3a", tree.branch.repository)
        self.assertEqual([], old)
        self.assertEqual([b"2a", b"3a"], new)

    def test_all_old(self):
        tree = self.setup_ab_tree()
        old, new = log.get_history_change(b"3a", b"1a", tree.branch.repository)
        self.assertEqual([], new)
        self.assertEqual([b"2a", b"3a"], old)

    def test_null_old(self):
        tree = self.setup_ab_tree()
        old, new = log.get_history_change(
            revision.NULL_REVISION, b"3a", tree.branch.repository
        )
        self.assertEqual([], old)
        self.assertEqual([b"1a", b"2a", b"3a"], new)

    def test_null_new(self):
        tree = self.setup_ab_tree()
        old, new = log.get_history_change(
            b"3a", revision.NULL_REVISION, tree.branch.repository
        )
        self.assertEqual([], new)
        self.assertEqual([b"1a", b"2a", b"3a"], old)

    def test_diverged(self):
        tree = self.setup_ab_tree()
        old, new = log.get_history_change(b"3a", b"3b", tree.branch.repository)
        self.assertEqual(old, [b"2a", b"3a"])
        self.assertEqual(new, [b"2b", b"3b"])

    def test_unrelated(self):
        tree = self.setup_ac_tree()
        old, new = log.get_history_change(b"3a", b"3c", tree.branch.repository)
        self.assertEqual(old, [b"1a", b"2a", b"3a"])
        self.assertEqual(new, [b"1c", b"2c", b"3c"])

    def test_show_branch_change(self):
        tree = self.setup_ab_tree()
        s = StringIO()
        log.show_branch_change(tree.branch, s, 3, b"3a")
        self.assertContainsRe(
            s.getvalue(),
            "[*]{60}\nRemoved Revisions:\n(.|\n)*2a(.|\n)*3a(.|\n)*"
            "[*]{60}\n\nAdded Revisions:\n(.|\n)*2b(.|\n)*3b",
        )

    def test_show_branch_change_no_change(self):
        tree = self.setup_ab_tree()
        s = StringIO()
        log.show_branch_change(tree.branch, s, 3, b"3b")
        self.assertEqual(s.getvalue(), "Nothing seems to have changed\n")

    def test_show_branch_change_no_old(self):
        tree = self.setup_ab_tree()
        s = StringIO()
        log.show_branch_change(tree.branch, s, 2, b"2b")
        self.assertContainsRe(s.getvalue(), "Added Revisions:")
        self.assertNotContainsRe(s.getvalue(), "Removed Revisions:")

    def test_show_branch_change_no_new(self):
        tree = self.setup_ab_tree()
        tree.branch.set_last_revision_info(2, b"2b")
        s = StringIO()
        log.show_branch_change(tree.branch, s, 3, b"3b")
        self.assertContainsRe(s.getvalue(), "Removed Revisions:")
        self.assertNotContainsRe(s.getvalue(), "Added Revisions:")


class TestRevisionNotInBranch(TestCaseForLogFormatter):
    def setup_a_tree(self):
        tree = self.make_branch_and_tree("tree")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        kwargs = {
            "committer": "Joe Foo <joe@foo.com>",
            "timestamp": 1132617600,  # Mon 2005-11-22 00:00:00 +0000
            "timezone": 0,  # UTC
        }
        tree.commit("commit 1a", rev_id=b"1a", **kwargs)
        tree.commit("commit 2a", rev_id=b"2a", **kwargs)
        tree.commit("commit 3a", rev_id=b"3a", **kwargs)
        return tree

    def setup_ab_tree(self):
        tree = self.setup_a_tree()
        tree.set_last_revision(b"1a")
        tree.branch.set_last_revision_info(1, b"1a")
        kwargs = {
            "committer": "Joe Foo <joe@foo.com>",
            "timestamp": 1132617600,  # Mon 2005-11-22 00:00:00 +0000
            "timezone": 0,  # UTC
        }
        tree.commit("commit 2b", rev_id=b"2b", **kwargs)
        tree.commit("commit 3b", rev_id=b"3b", **kwargs)
        return tree

    def test_one_revision(self):
        tree = self.setup_ab_tree()
        lf = LogCatcher()
        rev = revisionspec.RevisionInfo(tree.branch, None, b"3a")
        log.show_log(
            tree.branch, lf, verbose=True, start_revision=rev, end_revision=rev
        )
        self.assertEqual(1, len(lf.revisions))
        self.assertEqual(None, lf.revisions[0].revno)  # Out-of-branch
        self.assertEqual(b"3a", lf.revisions[0].rev.revision_id)

    def test_many_revisions(self):
        tree = self.setup_ab_tree()
        lf = LogCatcher()
        start_rev = revisionspec.RevisionInfo(tree.branch, None, b"1a")
        end_rev = revisionspec.RevisionInfo(tree.branch, None, b"3a")
        log.show_log(
            tree.branch,
            lf,
            verbose=True,
            start_revision=start_rev,
            end_revision=end_rev,
        )
        self.assertEqual(3, len(lf.revisions))
        self.assertEqual(None, lf.revisions[0].revno)  # Out-of-branch
        self.assertEqual(b"3a", lf.revisions[0].rev.revision_id)
        self.assertEqual(None, lf.revisions[1].revno)  # Out-of-branch
        self.assertEqual(b"2a", lf.revisions[1].rev.revision_id)
        self.assertEqual("1", lf.revisions[2].revno)  # In-branch

    def test_long_format(self):
        tree = self.setup_ab_tree()
        start_rev = revisionspec.RevisionInfo(tree.branch, None, b"1a")
        end_rev = revisionspec.RevisionInfo(tree.branch, None, b"3a")
        self.assertFormatterResult(
            b"""\
------------------------------------------------------------
revision-id: 3a
committer: Joe Foo <joe@foo.com>
branch nick: tree
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  commit 3a
------------------------------------------------------------
revision-id: 2a
committer: Joe Foo <joe@foo.com>
branch nick: tree
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  commit 2a
------------------------------------------------------------
revno: 1
committer: Joe Foo <joe@foo.com>
branch nick: tree
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  commit 1a
""",
            tree.branch,
            log.LongLogFormatter,
            show_log_kwargs={"start_revision": start_rev, "end_revision": end_rev},
        )

    def test_short_format(self):
        tree = self.setup_ab_tree()
        start_rev = revisionspec.RevisionInfo(tree.branch, None, b"1a")
        end_rev = revisionspec.RevisionInfo(tree.branch, None, b"3a")
        self.assertFormatterResult(
            b"""\
      Joe Foo\t2005-11-22
      revision-id:3a
      commit 3a

      Joe Foo\t2005-11-22
      revision-id:2a
      commit 2a

    1 Joe Foo\t2005-11-22
      commit 1a

""",
            tree.branch,
            log.ShortLogFormatter,
            show_log_kwargs={"start_revision": start_rev, "end_revision": end_rev},
        )

    def test_line_format(self):
        tree = self.setup_ab_tree()
        start_rev = revisionspec.RevisionInfo(tree.branch, None, b"1a")
        end_rev = revisionspec.RevisionInfo(tree.branch, None, b"3a")
        self.assertFormatterResult(
            b"""\
Joe Foo 2005-11-22 commit 3a
Joe Foo 2005-11-22 commit 2a
1: Joe Foo 2005-11-22 commit 1a
""",
            tree.branch,
            log.LineLogFormatter,
            show_log_kwargs={"start_revision": start_rev, "end_revision": end_rev},
        )


class TestLogWithBugs(TestCaseForLogFormatter, TestLogMixin):
    def setUp(self):
        super().setUp()
        log.properties_handler_registry.register(
            "bugs_properties_handler", log._bugs_properties_handler
        )

    def make_commits_with_bugs(self):
        """Helper method for LogFormatter tests."""
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a", "b"])
        tree.add("a")
        self.wt_commit(
            tree,
            "simple log message",
            rev_id=b"a1",
            revprops={"bugs": "test://bug/id fixed"},
        )
        tree.add("b")
        self.wt_commit(
            tree,
            "multiline\nlog\nmessage\n",
            rev_id=b"a2",
            authors=["Joe Bar <joe@bar.com>"],
            revprops={"bugs": "test://bug/id fixed\ntest://bug/2 fixed"},
        )
        return tree

    def test_bug_broken(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["a", "b"])
        tree.add("a")
        self.wt_commit(
            tree,
            "simple log message",
            rev_id=b"a1",
            revprops={"bugs": "test://bua g/id fixed"},
        )

        logfile = self.make_utf8_encoded_stringio()
        formatter = log.LongLogFormatter(to_file=logfile)
        log.show_log(tree.branch, formatter)

        self.assertContainsRe(
            logfile.getvalue(),
            b"brz: ERROR: breezy.bugtracker.InvalidLineInBugsProperty: "
            b"Invalid line in bugs property: 'test://bua g/id fixed'",
        )

        text = logfile.getvalue()
        self.assertEqualDiff(
            text[text.index(b"-" * 60) :],
            b"""\
------------------------------------------------------------
revno: 1
committer: Joe Foo <joe@foo.com>
branch nick: work
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  simple log message
""",
        )

    def test_long_bugs(self):
        tree = self.make_commits_with_bugs()
        self.assertFormatterResult(
            b"""\
------------------------------------------------------------
revno: 2
fixes bugs: test://bug/id test://bug/2
author: Joe Bar <joe@bar.com>
committer: Joe Foo <joe@foo.com>
branch nick: work
timestamp: Tue 2005-11-22 00:00:01 +0000
message:
  multiline
  log
  message
------------------------------------------------------------
revno: 1
fixes bug: test://bug/id
committer: Joe Foo <joe@foo.com>
branch nick: work
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  simple log message
""",
            tree.branch,
            log.LongLogFormatter,
        )

    def test_short_bugs(self):
        tree = self.make_commits_with_bugs()
        self.assertFormatterResult(
            b"""\
    2 Joe Bar\t2005-11-22
      fixes bugs: test://bug/id test://bug/2
      multiline
      log
      message

    1 Joe Foo\t2005-11-22
      fixes bug: test://bug/id
      simple log message

""",
            tree.branch,
            log.ShortLogFormatter,
        )

    def test_wrong_bugs_property(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["foo"])
        self.wt_commit(
            tree,
            "simple log message",
            rev_id=b"a1",
            revprops={"bugs": "test://bug/id invalid_value"},
        )

        logfile = self.make_utf8_encoded_stringio()
        formatter = log.ShortLogFormatter(to_file=logfile)
        log.show_log(tree.branch, formatter)

        lines = logfile.getvalue().splitlines()

        self.assertEqual(lines[0], b"    1 Joe Foo\t2005-11-22")

        self.assertEqual(
            lines[1],
            b"brz: ERROR: breezy.bugtracker.InvalidBugStatus: Invalid "
            b"bug status: 'invalid_value'",
        )

        self.assertEqual(lines[-2], b"      simple log message")

    def test_bugs_handler_present(self):
        self.properties_handler_registry.get("bugs_properties_handler")


class TestLogForAuthors(TestCaseForLogFormatter):
    def setUp(self):
        super().setUp()
        self.wt = self.make_standard_commit(
            "nicky",
            authors=["John Doe <jdoe@example.com>", "Jane Rey <jrey@example.com>"],
        )

    def assertFormatterResult(self, formatter, who, result):
        formatter_kwargs = {}
        if who is not None:
            author_list_handler = log.author_list_registry.get(who)
            formatter_kwargs["author_list_handler"] = author_list_handler
        TestCaseForLogFormatter.assertFormatterResult(
            self, result, self.wt.branch, formatter, formatter_kwargs=formatter_kwargs
        )

    def test_line_default(self):
        self.assertFormatterResult(
            log.LineLogFormatter,
            None,
            b"""\
1: John Doe 2005-11-22 add a
""",
        )

    def test_line_committer(self):
        self.assertFormatterResult(
            log.LineLogFormatter,
            "committer",
            b"""\
1: Lorem Ipsum 2005-11-22 add a
""",
        )

    def test_line_first(self):
        self.assertFormatterResult(
            log.LineLogFormatter,
            "first",
            b"""\
1: John Doe 2005-11-22 add a
""",
        )

    def test_line_all(self):
        self.assertFormatterResult(
            log.LineLogFormatter,
            "all",
            b"""\
1: John Doe, Jane Rey 2005-11-22 add a
""",
        )

    def test_short_default(self):
        self.assertFormatterResult(
            log.ShortLogFormatter,
            None,
            b"""\
    1 John Doe\t2005-11-22
      add a

""",
        )

    def test_short_committer(self):
        self.assertFormatterResult(
            log.ShortLogFormatter,
            "committer",
            b"""\
    1 Lorem Ipsum\t2005-11-22
      add a

""",
        )

    def test_short_first(self):
        self.assertFormatterResult(
            log.ShortLogFormatter,
            "first",
            b"""\
    1 John Doe\t2005-11-22
      add a

""",
        )

    def test_short_all(self):
        self.assertFormatterResult(
            log.ShortLogFormatter,
            "all",
            b"""\
    1 John Doe, Jane Rey\t2005-11-22
      add a

""",
        )

    def test_long_default(self):
        self.assertFormatterResult(
            log.LongLogFormatter,
            None,
            b"""\
------------------------------------------------------------
revno: 1
author: John Doe <jdoe@example.com>, Jane Rey <jrey@example.com>
committer: Lorem Ipsum <test@example.com>
branch nick: nicky
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  add a
""",
        )

    def test_long_committer(self):
        self.assertFormatterResult(
            log.LongLogFormatter,
            "committer",
            b"""\
------------------------------------------------------------
revno: 1
committer: Lorem Ipsum <test@example.com>
branch nick: nicky
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  add a
""",
        )

    def test_long_first(self):
        self.assertFormatterResult(
            log.LongLogFormatter,
            "first",
            b"""\
------------------------------------------------------------
revno: 1
author: John Doe <jdoe@example.com>
committer: Lorem Ipsum <test@example.com>
branch nick: nicky
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  add a
""",
        )

    def test_long_all(self):
        self.assertFormatterResult(
            log.LongLogFormatter,
            "all",
            b"""\
------------------------------------------------------------
revno: 1
author: John Doe <jdoe@example.com>, Jane Rey <jrey@example.com>
committer: Lorem Ipsum <test@example.com>
branch nick: nicky
timestamp: Tue 2005-11-22 00:00:00 +0000
message:
  add a
""",
        )

    def test_gnu_changelog_default(self):
        self.assertFormatterResult(
            log.GnuChangelogLogFormatter,
            None,
            b"""\
2005-11-22  John Doe  <jdoe@example.com>

\tadd a

""",
        )

    def test_gnu_changelog_committer(self):
        self.assertFormatterResult(
            log.GnuChangelogLogFormatter,
            "committer",
            b"""\
2005-11-22  Lorem Ipsum  <test@example.com>

\tadd a

""",
        )

    def test_gnu_changelog_first(self):
        self.assertFormatterResult(
            log.GnuChangelogLogFormatter,
            "first",
            b"""\
2005-11-22  John Doe  <jdoe@example.com>

\tadd a

""",
        )

    def test_gnu_changelog_all(self):
        self.assertFormatterResult(
            log.GnuChangelogLogFormatter,
            "all",
            b"""\
2005-11-22  John Doe  <jdoe@example.com>, Jane Rey  <jrey@example.com>

\tadd a

""",
        )


class TestLogExcludeAncestry(tests.TestCaseWithTransport):
    def make_branch_with_alternate_ancestries(self, relpath="."):
        # See test_merge_sorted_exclude_ancestry below for the difference with
        # bt.per_branch.test_iter_merge_sorted_revision.
        # TestIterMergeSortedRevisionsBushyGraph.
        # make_branch_with_alternate_ancestries
        # and test_merge_sorted_exclude_ancestry
        # See the FIXME in assertLogRevnos too.
        builder = branchbuilder.BranchBuilder(self.get_transport(relpath))
        # 1
        # |\
        # 2 \
        # |  |
        # |  1.1.1
        # |  | \
        # |  |  1.2.1
        # |  | /
        # |  1.1.2
        # | /
        # 3
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"TREE_ROOT", "directory", "")),
            ],
            revision_id=b"1",
        )
        builder.build_snapshot([b"1"], [], revision_id=b"1.1.1")
        builder.build_snapshot([b"1"], [], revision_id=b"2")
        builder.build_snapshot([b"1.1.1"], [], revision_id=b"1.2.1")
        builder.build_snapshot([b"1.1.1", b"1.2.1"], [], revision_id=b"1.1.2")
        builder.build_snapshot([b"2", b"1.1.2"], [], revision_id=b"3")
        builder.finish_series()
        br = builder.get_branch()
        br.lock_read()
        self.addCleanup(br.unlock)
        return br

    def assertLogRevnos(
        self,
        expected_revnos,
        b,
        start,
        end,
        exclude_common_ancestry,
        generate_merge_revisions=True,
    ):
        # FIXME: the layering in log makes it hard to test intermediate levels,
        # I wish adding filters with their parameters was easier...
        # -- vila 20100413
        iter_revs = log._calc_view_revisions(
            b,
            start,
            end,
            direction="reverse",
            generate_merge_revisions=generate_merge_revisions,
            exclude_common_ancestry=exclude_common_ancestry,
        )
        self.assertEqual(expected_revnos, [revid for revid, revno, depth in iter_revs])

    def test_merge_sorted_exclude_ancestry(self):
        b = self.make_branch_with_alternate_ancestries()
        self.assertLogRevnos(
            [b"3", b"1.1.2", b"1.2.1", b"1.1.1", b"2", b"1"],
            b,
            b"1",
            b"3",
            exclude_common_ancestry=False,
        )
        # '2' is part of the '3' ancestry but not part of '1.1.1' ancestry so
        # it should be mentioned even if merge_sort order will make it appear
        # after 1.1.1
        self.assertLogRevnos(
            [b"3", b"1.1.2", b"1.2.1", b"2"],
            b,
            b"1.1.1",
            b"3",
            exclude_common_ancestry=True,
        )

    def test_merge_sorted_simple_revnos_exclude_ancestry(self):
        b = self.make_branch_with_alternate_ancestries()
        self.assertLogRevnos(
            [b"3", b"2"],
            b,
            b"1",
            b"3",
            exclude_common_ancestry=True,
            generate_merge_revisions=False,
        )
        self.assertLogRevnos(
            [b"3", b"1.1.2", b"1.2.1", b"1.1.1", b"2"],
            b,
            b"1",
            b"3",
            exclude_common_ancestry=True,
            generate_merge_revisions=True,
        )


class TestLogDefaults(TestCaseForLogFormatter):
    def test_default_log_level(self):
        """Test to ensure that specifying 'levels=1' to make_log_request_dict
        doesn't get overwritten when using a LogFormatter that supports more
        detail.
        Fixes bug #747958.
        """
        wt = self._prepare_tree_with_merges()
        b = wt.branch

        class CustomLogFormatter(log.LogFormatter):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.revisions = []

            def get_levels(self):
                # log formatter supports all levels:
                return 0

            def log_revision(self, revision):
                self.revisions.append(revision)

        log_formatter = LogCatcher()
        # First request we don't specify number of levels, we should get a
        # sensible default (whatever the LogFormatter handles - which in this
        # case is 0/everything):
        request = log.make_log_request_dict(limit=10)
        log.Logger(b, request).show(log_formatter)
        # should have all three revisions:
        self.assertEqual(len(log_formatter.revisions), 3)

        del log_formatter
        log_formatter = LogCatcher()
        # now explicitly request mainline revisions only:
        request = log.make_log_request_dict(limit=10, levels=1)
        log.Logger(b, request).show(log_formatter)
        # should now only have 2 revisions:
        self.assertEqual(len(log_formatter.revisions), 2)

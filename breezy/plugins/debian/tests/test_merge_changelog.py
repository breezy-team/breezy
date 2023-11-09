#    Copyright (C) 2010 Canonical Ltd
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

"""Tests for the merge_changelog code."""

import logging

from testtools.content import Content
from testtools.content_type import ContentType

from .... import (
    merge,
    tests,
)
from ....tests.features import ExecutableFeature
from ... import debian
from .. import merge_changelog

dpkg_mergechangelogs_feature = ExecutableFeature("dpkg-mergechangelogs")


v_111_2 = b"""\
pseudo-prog (1.1.1-2) unstable; urgency=low

  * New upstream release.
  * Awesome bug fixes.

 -- Joe Foo <joe@example.com>  Thu, 28 Jan 2010 10:45:44 +0000

""".splitlines(True)


v_111_2b = b"""\
pseudo-prog (1.1.1-2) unstable; urgency=low

  * New upstream release.
  * Awesome bug fixes.
  * But more is better

 -- Joe Foo <joe@example.com>  Thu, 28 Jan 2010 10:45:44 +0000

""".splitlines(True)


v_111_2c = b"""\
pseudo-prog (1.1.1-2) unstable; urgency=low

  * New upstream release.
  * Yet another content for 1.1.1-2

 -- Joe Foo <joe@example.com>  Thu, 28 Jan 2010 10:45:44 +0000

""".splitlines(True)


# Merge of 2b and 2c using 2 as the base (b adds a line, c adds a line and
# deletes a line).
v_111_2bc = b"""\
pseudo-prog (1.1.1-2) unstable; urgency=low

  * New upstream release.
  * Yet another content for 1.1.1-2
  * But more is better

 -- Joe Foo <joe@example.com>  Thu, 28 Jan 2010 10:45:44 +0000

""".splitlines(True)


# Merge of 2b and 2c using an empty base. (As calculated by
# dpkg-mergechangelogs.)
v_111_2bc_empty_base = b"""\
pseudo-prog (1.1.1-2) unstable; urgency=low

  * New upstream release.
<<<<<<<
  * Awesome bug fixes.
=======
  * Yet another content for 1.1.1-2
>>>>>>>
  * But more is better

 -- Joe Foo <joe@example.com>  Thu, 28 Jan 2010 10:45:44 +0000

""".splitlines(True)


v_112_1 = b"""\
pseudo-prog (1.1.2-1) unstable; urgency=low

  * New upstream release.
  * No bug fixes :(

 -- Barry Foo <barry@example.com>  Thu, 27 Jan 2010 10:45:44 +0000

""".splitlines(True)


v_001_1 = b"""\
pseudo-prog (0.0.1-1) unstable; urgency=low

  * New project released!!!!
  * No bugs evar

 -- Barry Foo <barry@example.com>  Thu, 27 Jan 2010 10:00:44 +0000

""".splitlines(True)


# Backports from current testtools so that we remain compatible with testtools
# 0.9.2 (the version in lucid).
UTF8_TEXT = ContentType("text", "plain", {"charset": "utf8"})


class TestMergeChangelog(tests.TestCase):
    _test_needs_features = [dpkg_mergechangelogs_feature]

    def setUp(self):
        super(tests.TestCase, self).setUp()
        # Intercept warnings from merge_changelog's logger: this is where
        self.logged_warnings = self.make_utf8_encoded_stringio()
        self.addCleanup(self.addMergeChangelogWarningsDetail)
        handler = logging.StreamHandler(self.logged_warnings)
        handler.setLevel(logging.WARNING)
        logger = logging.getLogger("breezy.plugins.debian.merge_changelog")
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        self.overrideAttr(logger, "propagate", False)

    def addMergeChangelogWarningsDetail(self):
        warnings_log = self.logged_warnings.getvalue()
        if warnings_log:
            self.addDetail(
                "merge_changelog warnings", Content(UTF8_TEXT, lambda: [warnings_log])
            )

    def assertMergeChangelog(
        self,
        expected_lines,
        this_lines,
        other_lines,
        base_lines=None,
        conflicted=False,
        possible_error=False,
    ):
        if base_lines is None:
            base_lines = []
        status, merged_lines = merge_changelog.merge_changelog(
            this_lines, other_lines, base_lines
        )
        if possible_error and status == "not_applicable":
            self.assertContainsRe(
                self.logged_warnings.getvalue(),
                "(?m)dpkg-mergechangelogs failed with status \\d+$",
            )
            return False
        if conflicted:
            self.assertEqual("conflicted", status)
        else:
            self.assertEqual("success", status)
        self.assertEqualDiff(b"".join(expected_lines), b"".join(merged_lines))
        return True

    def test_merge_by_version(self):
        this_lines = v_111_2 + v_001_1
        other_lines = v_112_1 + v_001_1
        expected_lines = v_112_1 + v_111_2 + v_001_1
        self.assertMergeChangelog(expected_lines, this_lines, other_lines)
        self.assertMergeChangelog(expected_lines, other_lines, this_lines)

    def test_this_shorter(self):
        self.assertMergeChangelog(
            v_112_1 + v_111_2 + v_001_1,
            this_lines=v_111_2,
            other_lines=v_112_1 + v_001_1,
            base_lines=[],
        )
        self.assertMergeChangelog(
            v_112_1 + v_111_2 + v_001_1,
            this_lines=v_001_1,
            other_lines=v_112_1 + v_111_2,
            base_lines=[],
        )

    def test_other_shorter(self):
        self.assertMergeChangelog(
            v_112_1 + v_111_2 + v_001_1,
            this_lines=v_112_1 + v_001_1,
            other_lines=v_111_2,
            base_lines=[],
        )
        self.assertMergeChangelog(
            v_112_1 + v_111_2 + v_001_1,
            this_lines=v_112_1 + v_111_2,
            other_lines=v_001_1,
            base_lines=[],
        )

    def test_unsorted(self):
        # The order of entries being merged is unchanged, even if they are not
        # properly sorted.  (This is a merge tool, not a reformatting tool.)
        self.assertMergeChangelog(
            v_111_2 + v_001_1,
            this_lines=v_111_2 + v_001_1,
            other_lines=[],
            base_lines=[],
        )

    def test_3way_merge(self):
        # Check that if one of THIS or OTHER matches BASE, then we select the
        # other content
        self.assertMergeChangelog(
            expected_lines=v_111_2,
            this_lines=v_111_2,
            other_lines=v_111_2b,
            base_lines=v_111_2b,
        )
        self.assertMergeChangelog(
            expected_lines=v_111_2b,
            this_lines=v_111_2,
            other_lines=v_111_2b,
            base_lines=v_111_2,
        )

    def test_3way_conflicted(self):
        self.assertMergeChangelog(
            expected_lines=v_111_2bc,
            this_lines=v_111_2b,
            other_lines=v_111_2c,
            base_lines=v_111_2,
        )
        self.assertMergeChangelog(
            expected_lines=v_111_2bc_empty_base,
            this_lines=v_111_2b,
            other_lines=v_111_2c,
            base_lines=[],
            conflicted=True,
        )

    def test_not_valid_changelog(self):
        invalid_changelog = b"""\
pseudo-prog (1.1.1-2) unstable; urgency=low

  * New upstream release.
  * Awesome bug fixes.

 -- Thu, 28 Jan 2010 10:45:44 +0000

""".splitlines(True)
        # invalid_changelog is missing the author, but dpkg-mergechangelogs
        # copes gracefully with invalid input.
        status, lines = merge_changelog.merge_changelog(
            invalid_changelog, v_111_2, v_111_2
        )
        self.assertEqual("success", status)
        # XXX: ideally we'd expect ''.join(lines) ==
        # ''.join(invalid_changelog), but dpkg-mergechangelogs appears to lose
        # the final line in these examples.
        # <https://bugs.launchpad.net/ubuntu/+source/dpkg/+bug/815704>
        #  - Andrew Bennetts, 25 July 2011.
        # self.assertEqual(''.join(invalid_changelog), ''.join(lines))
        self.assertMergeChangelog(
            v_112_1 + [b"<<<<<<<\n"] + v_111_2 + [b"=======\n>>>>>>>\n"],
            this_lines=v_111_2,
            other_lines=v_112_1,
            base_lines=invalid_changelog,
            conflicted=True,
        )

    def test_invalid_version_starting_non_digit(self):
        """Invalid version without digit first is rejected or correctly merged.

        Versions of dpkg prior to 1.16.0.1 merge such changelogs correctly,
        however then a stricter check was introduced that aborts the script.
        In that case, the result should not be a success with a zero byte
        merge result file. See lp:893495 for such an issue.
        """
        invalid_changelog = b"""\
pseudo-prog (ss-0) unstable; urgency=low

  * New project released!!!!

 -- Barry Foo <barry@example.com>  Thu, 28 Jan 2010 10:00:44 +0000

""".splitlines(True)
        handled = self.assertMergeChangelog(
            expected_lines=v_112_1 + v_111_2 + invalid_changelog,
            this_lines=v_112_1 + invalid_changelog,
            other_lines=v_111_2 + invalid_changelog,
            base_lines=invalid_changelog,
            possible_error=True,
        )
        if not handled:
            # Can't assert on the exact message as it depends on the locale
            self.assertContainsRe(
                self.logged_warnings.getvalue(),
                "dpkg-mergechangelogs: .*ss-0( is not a valid version)?",
            )

    def test_invalid_version_non_ascii(self):
        """Invalid version with non-ascii data is rejected or correctly merged.

        Such a version has always been treated as invalid so fails
        consistently across dpkg versions currently.
        """
        invalid_changelog = b"""\
pseudo-prog (\xc2\xa7) unstable; urgency=low

  * New project released!!!!

 -- Barry Foo <barry@example.com>  Thu, 28 Jan 2010 10:00:44 +0000

""".splitlines(True)
        handled = self.assertMergeChangelog(
            expected_lines=v_112_1 + v_111_2 + invalid_changelog,
            this_lines=v_112_1 + invalid_changelog,
            other_lines=v_111_2 + invalid_changelog,
            base_lines=invalid_changelog,
            possible_error=True,
        )
        if not handled:
            # Can't assert on the exact message as it depends on the locale
            self.assertContainsRe(
                self.logged_warnings.getvalue(),
                "dpkg-mergechangelogs: .*( is not a valid version)?",
            )


class TestChangelogHook(tests.TestCaseWithMemoryTransport):
    _test_needs_features = [dpkg_mergechangelogs_feature]

    def make_params(self):
        builder = self.make_branch_builder("source")
        builder.start_series()
        builder.build_snapshot(
            None,
            [
                ("add", ("", b"TREE_ROOT", "directory", None)),
                ("add", ("debian", b"deb-id", "directory", None)),
                ("add", ("debian/changelog", b"c-id", "file", b"")),
                ("add", ("changelog", b"o-id", "file", b"")),
            ],
        )
        builder.finish_series()
        the_branch = builder.get_branch()

        tree = the_branch.create_memorytree()
        tree.lock_write()
        self.addCleanup(tree.unlock)

        class FakeMerger:
            def __init__(self, this_tree):
                self.this_tree = this_tree

            def get_lines(self, tree, path):
                return tree.get_file_lines(path)

        merger = FakeMerger(tree)
        params_cls = merge.MergeFileHookParams
        from inspect import signature

        params_cls_arg_count = len(signature(params_cls).parameters) + 1
        # Older versions of Breezy required a file_id to be specified.
        if params_cls_arg_count == 7:
            params = params_cls(
                merger,
                ("debian/changelog", "debian/changelog", "debian/changelog"),
                None,
                "file",
                "file",
                "this",
            )
        elif params_cls_arg_count == 8:
            params = params_cls(
                merger,
                b"c-id",
                ("debian/changelog", "debian/changelog", "debian/changelog"),
                None,
                "file",
                "file",
                "this",
            )
        else:
            raise AssertionError(params_cls_arg_count)

        return params, merger

    def test_changelog_merge_hook_successful(self):
        params, merger = self.make_params()
        params.other_lines = [b""]
        params.base_lines = [b""]
        file_merger = debian.changelog_merge_hook_factory(merger)
        result, new_content = file_merger.merge_text(params)
        self.assertEqual("success", result)
        # We ignore the new_content, as we test that elsewhere

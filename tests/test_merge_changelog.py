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

import warnings

try:
    from debian import changelog
except ImportError:
    # Prior to 0.1.15 the debian module was called debian_bundle
    from debian_bundle import changelog

from bzrlib import (
    memorytree,
    merge,
    tests,
    )
from bzrlib.plugins import builddeb
from bzrlib.plugins.builddeb import merge_changelog


v_111_2 = """\
psuedo-prog (1.1.1-2) unstable; urgency=low

  * New upstream release.
  * Awesome bug fixes.

 -- Joe Foo <joe@example.com>  Thu, 28 Jan 2010 10:45:44 +0000

""".splitlines(True)


v_111_2b = """\
psuedo-prog (1.1.1-2) unstable; urgency=low

  * New upstream release.
  * Awesome bug fixes.
  * But more is better

 -- Joe Foo <joe@example.com>  Thu, 28 Jan 2010 10:45:44 +0000

""".splitlines(True)


v_111_2c = """\
psuedo-prog (1.1.1-2) unstable; urgency=low

  * New upstream release.
  * Yet another content for 1.1.1-2

 -- Joe Foo <joe@example.com>  Thu, 28 Jan 2010 10:45:44 +0000

""".splitlines(True)


v_112_1 = """\
psuedo-prog (1.1.2-1) unstable; urgency=low

  * New upstream release.
  * No bug fixes :(

 -- Barry Foo <barry@example.com>  Thu, 27 Jan 2010 10:45:44 +0000

""".splitlines(True)


v_001_1 = """\
psuedo-prog (0.0.1-1) unstable; urgency=low

  * New project released!!!!
  * No bugs evar

 -- Barry Foo <barry@example.com>  Thu, 27 Jan 2010 10:00:44 +0000

""".splitlines(True)


class TestMergeChangelog(tests.TestCase):

    def assertMergeChangelog(self, expected_lines, this_lines, other_lines,
                             base_lines=[], conflicted=False):
        status, merged_lines = merge_changelog.merge_changelog(
                                    this_lines, other_lines, base_lines)
        if conflicted:
            self.assertEqual('conflicted', status)
        else:
            self.assertEqual('success', status)
        self.assertEqualDiff(''.join(expected_lines), ''.join(merged_lines))

    def test_merge_by_version(self):
        this_lines = v_111_2 + v_001_1
        other_lines = v_112_1 + v_001_1
        expected_lines = v_112_1 + v_111_2 + v_001_1
        self.assertMergeChangelog(expected_lines, this_lines, other_lines)
        self.assertMergeChangelog(expected_lines, other_lines, this_lines)

    def test_this_shorter(self):
        self.assertMergeChangelog(v_112_1 + v_111_2 + v_001_1,
            this_lines=v_111_2,
            other_lines=v_112_1 + v_001_1,
            base_lines=[])
        self.assertMergeChangelog(v_112_1 + v_111_2 + v_001_1,
            this_lines=v_001_1,
            other_lines=v_112_1 + v_111_2,
            base_lines=[])

    def test_other_shorter(self):
        self.assertMergeChangelog(v_112_1 + v_111_2 + v_001_1,
            this_lines=v_112_1 + v_001_1,
            other_lines=v_111_2,
            base_lines=[])
        self.assertMergeChangelog(v_112_1 + v_111_2 + v_001_1,
            this_lines=v_112_1 + v_111_2,
            other_lines=v_001_1,
            base_lines=[])

    def test_unsorted(self):
        # Passing in an improperly sorted text should result in a properly
        # sorted one
        self.assertMergeChangelog(v_111_2 + v_001_1,
                                  this_lines = v_001_1 + v_111_2,
                                  other_lines = [],
                                  base_lines = [])

    def test_3way_merge(self):
        # Check that if one of THIS or OTHER matches BASE, then we select the
        # other content
        self.assertMergeChangelog(expected_lines=v_111_2,
                                  this_lines=v_111_2, other_lines=v_111_2b,
                                  base_lines=v_111_2b)
        self.assertMergeChangelog(expected_lines=v_111_2b,
                                  this_lines=v_111_2, other_lines=v_111_2b,
                                  base_lines=v_111_2)

    def test_3way_conflicted(self):
        self.assertMergeChangelog(
            expected_lines=['<<<<<<< TREE\n']
                           + v_111_2b
                           + ['=======\n']
                           + v_111_2c
                           + ['>>>>>>> MERGE-SOURCE\n'],
            this_lines=v_111_2b, other_lines=v_111_2c,
            base_lines=v_111_2,
            conflicted=True)
        self.assertMergeChangelog(
            expected_lines=['<<<<<<< TREE\n']
                           + v_111_2b
                           + ['=======\n']
                           + v_111_2c
                           + ['>>>>>>> MERGE-SOURCE\n'],
            this_lines=v_111_2b, other_lines=v_111_2c,
            base_lines=[],
            conflicted=True)

    def test_not_valid_changelog(self):
        invalid_changelog = """\
psuedo-prog (1.1.1-2) unstable; urgency=low

  * New upstream release.
  * Awesome bug fixes.

 -- Thu, 28 Jan 2010 10:45:44 +0000

""".splitlines(True)
        # Missing the author and we don't have allow_missing_author set
        cl = changelog.Changelog()
        self.assertRaises(changelog.ChangelogParseError,
                          cl.parse_changelog, ''.join(invalid_changelog), strict=True)
        # If strict parsing fails, don't try to do special merging
        self.assertEqual(('not_applicable', None),
            merge_changelog.merge_changelog(invalid_changelog, v_111_2,
                                            v_111_2))
        self.assertEqual(('not_applicable', None),
            merge_changelog.merge_changelog(v_111_2, invalid_changelog,
                                            v_111_2))
        # We are non-strict about parsing BASE, because its contents are not
        # included in the output.
        # This triggers a warning, but we don't want to clutter the test run
        cur_filters = warnings.filters[:]
        warnings.simplefilter('ignore', UserWarning)
        try:
            self.assertMergeChangelog(v_112_1 + v_111_2,
                                      this_lines=v_111_2,
                                      other_lines=v_112_1,
                                      base_lines=invalid_changelog,
                                      )
        finally:
            warnings.filters = cur_filters[:]


class TestChangelogHook(tests.TestCaseWithMemoryTransport):

    def make_params(self):
        builder = self.make_branch_builder('source')
        builder.start_series()
        builder.build_snapshot('A', None, [
            ('add', ('', 'TREE_ROOT', 'directory', None)),
            ('add', ('debian', 'deb-id', 'directory', None)),
            ('add', ('debian/changelog', 'c-id', 'file', '')),
            ('add', ('changelog', 'o-id', 'file', '')),
            ])
        builder.finish_series()
        the_branch = builder.get_branch()

        tree = memorytree.MemoryTree.create_on_branch(the_branch)
        tree.lock_write()
        self.addCleanup(tree.unlock)

        class FakeMerger(object):
            def __init__(self, this_tree):
                self.this_tree = this_tree
            def get_lines(self, tree, file_id):
                return tree.get_file_lines(file_id)

        merger = FakeMerger(tree)
        params = merge.MergeHookParams(merger, 'c-id', None, 'file', 'file',
                                       'this')
        return params, merger


    def test_changelog_merge_hook_successful(self):
        params, merger = self.make_params()
        params.other_lines = ['']
        params.base_lines = ['']
        file_merger = builddeb.changelog_merge_hook_factory(merger)
        result, new_content = file_merger.merge_text(params)
        self.assertEqual('success', result)
        # We ignore the new_content, as we test that elsewhere

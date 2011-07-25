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

try:
    from debian import changelog
except ImportError:
    # Prior to 0.1.15 the debian module was called debian_bundle
    from debian_bundle import changelog

from testtools.content_type import ContentType
from testtools.content import Content

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


# Merge of 2b and 2c using 2 as the base (b adds a line, c adds a line and
# deletes a line).
v_111_2bc = """\
psuedo-prog (1.1.1-2) unstable; urgency=low

  * New upstream release.
  * Yet another content for 1.1.1-2
  * But more is better

 -- Joe Foo <joe@example.com>  Thu, 28 Jan 2010 10:45:44 +0000

""".splitlines(True)


# Merge of 2b and 2c using an empty base. (As calculated by
# dpkg-mergechangelogs.)
v_111_2bc_empty_base = """\
psuedo-prog (1.1.1-2) unstable; urgency=low

  * New upstream release.
<<<<<<<
  * Awesome bug fixes.
=======
  * Yet another content for 1.1.1-2
>>>>>>>
  * But more is better

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


# Backports from current testtools so that we remain compatible with testtools
# 0.9.2 (the version in lucid).
UTF8_TEXT = ContentType('text', 'plain', {'charset': 'utf8'})
def text_content(text):
    """Create a `Content` object from some text.

    This is useful for adding details which are short strings.
    """
    return Content(UTF8_TEXT, lambda: [text.encode('utf8')])


class TestMergeChangelog(tests.TestCase):

    def setUp(self):
        super(tests.TestCase, self).setUp()
        # Intercept warnings from merge_changelog's logger: this is where 
        self.logged_warnings = self.make_utf8_encoded_stringio()
        self.addCleanup(self.addMergeChangelogWarningsDetail)
        handler = logging.StreamHandler(self.logged_warnings)
        handler.setLevel(logging.WARNING)
        logger = logging.getLogger('bzr.plugins.builddeb.merge_changelog')
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        self.overrideAttr(logger, 'propagate', False)

    def addMergeChangelogWarningsDetail(self):
        warnings_log = self.logged_warnings.getvalue()
        if warnings_log:
            self.addDetail(
                'merge_changelog warnings', text_content(warnings_log))

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
        # The order of entries being merged is unchanged, even if they are not
        # properly sorted.  (This is a merge tool, not a reformatting tool.)
        self.assertMergeChangelog(v_111_2 + v_001_1,
                                  this_lines = v_111_2 + v_001_1,
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
            expected_lines=v_111_2bc,
            this_lines=v_111_2b, other_lines=v_111_2c,
            base_lines=v_111_2)
        self.assertMergeChangelog(
            expected_lines=v_111_2bc_empty_base,
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
        # invalid_changelog is missing the author, but dpkg-mergechangelogs
        # copes gracefully with invalid input.
        status, lines = merge_changelog.merge_changelog(
            invalid_changelog, v_111_2, v_111_2)
        self.assertEqual('success', status)
        # XXX: ideally we'd expect ''.join(lines) ==
        # ''.join(invalid_changelog), but dpkg-mergechangelogs appears to lose
        # the final line in these examples.
        # <https://bugs.launchpad.net/ubuntu/+source/dpkg/+bug/815704>
        #  - Andrew Bennetts, 25 July 2011.
        #self.assertEqual(''.join(invalid_changelog), ''.join(lines))
        status, lines = merge_changelog.merge_changelog(
            invalid_changelog, v_111_2, v_111_2)
        self.assertEqual('success', status)
        #self.assertEqual(''.join(invalid_changelog), ''.join(lines))
        self.assertMergeChangelog(v_112_1 + 
                                  ['<<<<<<<\n'] +
                                  v_111_2 +
                                  ['=======\n>>>>>>>\n'],
                                  this_lines=v_111_2,
                                  other_lines=v_112_1,
                                  base_lines=invalid_changelog,
                                  conflicted=True
                                  )


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

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

from bzrlib import (
    memorytree,
    merge,
    tests,
    )
from bzrlib.plugins.builddeb import (
    _use_special_merger,
    changelog_merge_hook,
    merge_changelog,
    )


class TestReadChangelog(tests.TestCase):

    def test_read_changelog(self):
        lines = """\
psuedo-prog (1.1.1-2) unstable; urgency=low

  * New upstream release.
  * Awesome bug fixes.

 -- Joe Foo <joe@example.com> Thu, 28 Jan 2010 10:45:44 +0000
""".splitlines(True)

                
        entries = merge_changelog.read_changelog(lines)
        self.assertEqual(1, len(entries))

    
class TestMergeChangelog(tests.TestCase):

    def assertMergeChangelog(self, expected_lines, this_lines, other_lines):
        merged_lines = merge_changelog.merge_changelog(this_lines, other_lines)
        self.assertEqualDiff(''.join(expected_lines), ''.join(merged_lines))

    def test_merge_by_version(self):
        v_111_2 = """\
psuedo-prog (1.1.1-2) unstable; urgency=low

  * New upstream release.
  * Awesome bug fixes.

 -- Joe Foo <joe@example.com> Thu, 28 Jan 2010 10:45:44 +0000

""".splitlines(True)

        v_112_1 = """\
psuedo-prog (1.1.2-1) unstable; urgency=low

  * New upstream release.
  * No bug fixes :(

 -- Barry Foo <barry@example.com> Thu, 27 Jan 2010 10:45:44 +0000

""".splitlines(True)

        v_001_1 = """\
psuedo-prog (0.0.1-1) unstable; urgency=low

  * New project released!!!!
  * No bugs evar

 -- Barry Foo <barry@example.com> Thu, 27 Jan 2010 10:00:44 +0000

""".splitlines(True)

        this_lines = v_111_2 + v_001_1
        other_lines = v_112_1 + v_001_1
        expected_lines = v_112_1 + v_111_2 + v_001_1
        self.assertMergeChangelog(expected_lines, this_lines, other_lines)
        self.assertMergeChangelog(expected_lines, other_lines, this_lines)


class TestChangelogHook(tests.TestCaseWithMemoryTransport):

    def make_params(self, enable_hook=True):
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
        if not enable_hook:
            the_branch.get_config().set_user_option(
                'deb_changelog_merge_files', '')
        return params

    def test__use_special_merger_creates_attribute(self):
        params = self.make_params(enable_hook=False)
        self.assertFalse(_use_special_merger(params))
        self.assertEqual(set(), params._builddeb_changelog_merge_files)

    def test__use_special_merger_enabled(self):
        params = self.make_params()
        self.assertTrue(_use_special_merger(params))
        self.assertEqual(set(['debian/changelog']),
                         params._builddeb_changelog_merge_files)

    def test__use_special_merger_not_debian_changelog(self):
        params = self.make_params()
        params.file_id = 'o-id'
        self.assertFalse(_use_special_merger(params))
        self.assertEqual(set(['debian/changelog']),
                         params._builddeb_changelog_merge_files)

    def test__use_special_merger_changelog(self):
        params = self.make_params()
        params.file_id = 'o-id'
        params.merger.this_tree.branch.get_config().set_user_option(
                'deb_changelog_merge_files', ['changelog', 'debian/changelog'])
        self.assertTrue(_use_special_merger(params))
        self.assertEqual(set(['changelog', 'debian/changelog']),
                         params._builddeb_changelog_merge_files)

    def test_changelog_merge_hook_ignores_other(self):
        params = self.make_params()
        params.winner = 'other'
        self.assertEqual(('not_applicable', None),
                         changelog_merge_hook(params))

    def test_changelog_merge_hook_ignores_kind_change(self):
        params = self.make_params()
        params.other_kind = 'directory' # No longer a pure file merge
        self.assertEqual(('not_applicable', None),
                         changelog_merge_hook(params))

    def test_changelog_merge_hook_not_enabled(self):
        params = self.make_params(enable_hook=False)
        self.assertEqual(('not_applicable', None),
                         changelog_merge_hook(params))

    def test_changelog_merge_hook_successful(self):
        params = self.make_params()
        params.other_lines = ['']
        result, new_content = changelog_merge_hook(params)
        self.assertEqual('success', result)
        # We ignore the new_content, as we test that elsewhere

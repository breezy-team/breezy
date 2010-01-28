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
    tests,
    )
from bzrlib.plugins.builddeb import merge_changelog


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

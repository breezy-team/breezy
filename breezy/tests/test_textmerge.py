# Copyright (C) 2006 Canonical Ltd
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
#
# Author: Aaron Bentley <aaron.bentley@utoronto.ca>

"""Tests for text merging functionality."""

from breezy.tests import TestCase
from bzrformats.textmerge import Merge2


class TestMerge2(TestCase):
    """Test the Merge2 text merging class."""

    def test_agreed(self):
        lines = b"a\nb\nc\nd\ne\nf\n".splitlines(True)
        mlines = list(Merge2(lines, lines).merge_lines()[0])
        self.assertEqualDiff(mlines, lines)

    def test_conflict(self):
        lines_a = b"a\nb\nc\nd\ne\nf\ng\nh\n".splitlines(True)
        lines_b = b"z\nb\nx\nd\ne\ne\nf\ng\ny\n".splitlines(True)
        expected = (
            b"<\na\n=\nz\n>\nb\n<\nc\n=\nx\n>\nd\ne\n<\n=\ne\n>\nf\ng\n<\nh\n=\ny\n>\n"
        )
        m2 = Merge2(lines_a, lines_b, b"<\n", b">\n", b"=\n")
        mlines = m2.merge_lines()[0]
        self.assertEqualDiff(b"".join(mlines), expected)
        mlines = m2.merge_lines(reprocess=True)[0]
        self.assertEqualDiff(b"".join(mlines), expected)

    def test_reprocess(self):
        struct = [
            ([b"a"], [b"b"]),
            ([b"c"],),
            ([b"d", b"e", b"f"], [b"g", b"e", b"h"]),
            ([b"i"],),
        ]
        expect = [
            ([b"a"], [b"b"]),
            ([b"c"],),
            ([b"d"], [b"g"]),
            ([b"e"],),
            ([b"f"], [b"h"]),
            ([b"i"],),
        ]
        result = Merge2.reprocess_struct(struct)
        self.assertEqual(list(result), expect)

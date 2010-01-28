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
        lines = ['psuedo-prog (1.1.1-2) unstable; urgency=low\n',
                 '\n',
                 '  * New upstream release.\n',
                 '  * Awesome bug fixes.\n',
                 '\n',
                 ' -- Joe Foo <joe@example.com>  '
                    'Thu, 28 Jan 2010 10:45:44 +0000\n',
                 '\n',
                ]
        entries = merge_changelog.read_changelog(lines)
        self.assertEqual(1, len(entries))

    
class TestMergeChangelog(tests.TestCase):

    def test_nothing(self):
        pass

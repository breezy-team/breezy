# Copyright (C) 2006 by Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for the generic Tree.walkdirs interface."""

from bzrlib.tests.tree_implementations import TestCaseWithTree


class TestWalkdirs(TestCaseWithTree):

    def test_walkdir_root(self):
        tree = self.get_tree_with_subdirs_and_all_content_types()
        expected_dirblocks = [
            (('', '', tree.inventory.root.file_id),
            [
             ('0file', '0file', 'file', None, '0file', '2file', 'file'),
             ('1top-dir', '1top-dir', 'directory', None, '1top-dir', '1top-dir', 'directory'),
             (u'2utf\u1234file', u'2utf\u1234file', 'file', None, u'2utf\u1234file', u'0utf\u1234file', 'file'),
             ('symlink', 'symlink', 'symlink', None, 'symlink', 'symlink', 'symlink')
            ]),
            (('1top-dir', '1top-dir', '1top-dir'),
            [('1top-dir/0file-in-1topdir', '0file-in-1topdir', 'file', None, '1top-dir/0file-in-1topdir', '1file-in-1topdir', 'file'),
             ('1top-dir/1dir-in-1topdir', '1dir-in-1topdir', 'directory', None, '1top-dir/1dir-in-1topdir', '0dir-in-1topdir', 'directory'),
            ]),
            (('1top-dir/1dir-in-1topdir', '1top-dir/1dir-in-1topdir', '0dir-in-1topdir'),
            [
            ]),
        ]
        # test that its iterable by iterating
        result = []
        for block in tree.walkdirs():
            result.append(block)
        self.assertEqual(expected_dirblocks, result)

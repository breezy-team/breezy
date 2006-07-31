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

    def get_all_subdirs_expected(self, tree):
        return [
            (('', tree.inventory.root.file_id),
            [
             ('0file', '0file', 'file', None, '2file', 'file'),
             ('1top-dir', '1top-dir', 'directory', None, '1top-dir', 'directory'),
             (u'2utf\u1234file', u'2utf\u1234file', 'file', None, u'0utf\u1234file', 'file'),
             ('symlink', 'symlink', 'symlink', None, 'symlink', 'symlink')
            ]),
            (('1top-dir', '1top-dir'),
            [('1top-dir/0file-in-1topdir', '0file-in-1topdir', 'file', None, '1file-in-1topdir', 'file'),
             ('1top-dir/1dir-in-1topdir', '1dir-in-1topdir', 'directory', None, '0dir-in-1topdir', 'directory'),
            ]),
            (('1top-dir/1dir-in-1topdir', '0dir-in-1topdir'),
            [
            ]),
            ]

    def test_walkdir_root(self):
        tree = self.get_tree_with_subdirs_and_all_content_types()
        expected_dirblocks = self.get_all_subdirs_expected(tree)
        # test that its iterable by iterating
        result = []
        for dirinfo, block in tree.walkdirs():
            newblock = []
            for row in block:
                if row[4] is not None:
                    newblock.append(row[0:3] + (None,) + row[4:])
                else:
                    newblock.append(row)
            result.append((dirinfo, newblock))
        # check each return value for debugging ease.
        for pos, item in enumerate(expected_dirblocks):
            self.assertEqual(item, result[pos])
            
    def test_walkdir_subtree(self):
        tree = self.get_tree_with_subdirs_and_all_content_types()
        expected_dirblocks = self.get_all_subdirs_expected(tree)[1:]
        # test that its iterable by iterating
        result = []
        for dirinfo, block in tree.walkdirs('1top-dir'):
            newblock = []
            for row in block:
                if row[4] is not None:
                    newblock.append(row[0:3] + (None,) + row[4:])
                else:
                    newblock.append(row)
            result.append((dirinfo, newblock))
        # check each return value for debugging ease.
        for pos, item in enumerate(expected_dirblocks):
            self.assertEqual(item, result[pos])

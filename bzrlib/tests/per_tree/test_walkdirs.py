# Copyright (C) 2006, 2007 Canonical Ltd
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

"""Tests for the generic Tree.walkdirs interface."""

import os

from bzrlib import tests
from bzrlib.osutils import has_symlinks
from bzrlib.tests.per_tree import TestCaseWithTree


class TestWalkdirs(TestCaseWithTree):

    def get_all_subdirs_expected(self, tree, symlinks):
        dirblocks = [
            (('', tree.path2id('')),
             [('0file', '0file', 'file', None, '2file', 'file'),
              ('1top-dir', '1top-dir', 'directory', None,
               '1top-dir', 'directory'),
              (u'2utf\u1234file', u'2utf\u1234file', 'file', None,
               u'0utf\u1234file'.encode('utf8'), 'file'),
              ]),
            (('1top-dir', '1top-dir'),
             [('1top-dir/0file-in-1topdir', '0file-in-1topdir',
               'file', None, '1file-in-1topdir', 'file'),
              ('1top-dir/1dir-in-1topdir', '1dir-in-1topdir',
               'directory', None, '0dir-in-1topdir', 'directory'),
              ]),
            (('1top-dir/1dir-in-1topdir', '0dir-in-1topdir'),
             []),
            ]
        if symlinks:
            dirblocks[0][1].append(('symlink', 'symlink', 'symlink', None,
                                    'symlink', 'symlink'))
        return dirblocks

    def test_walkdir_root(self):
        tree = self.get_tree_with_subdirs_and_all_supported_content_types(
            has_symlinks())
        tree.lock_read()
        expected_dirblocks = self.get_all_subdirs_expected(tree, has_symlinks())
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
        tree.unlock()
        # check each return value for debugging ease.
        for pos, item in enumerate(expected_dirblocks):
            self.assertEqual(item, result[pos])
        self.assertEqual(len(expected_dirblocks), len(result))

    def test_walkdir_subtree(self):
        tree = self.get_tree_with_subdirs_and_all_supported_content_types(has_symlinks())
        # test that its iterable by iterating
        result = []
        tree.lock_read()
        expected_dirblocks = self.get_all_subdirs_expected(tree, has_symlinks())[1:]
        for dirinfo, block in tree.walkdirs('1top-dir'):
            newblock = []
            for row in block:
                if row[4] is not None:
                    newblock.append(row[0:3] + (None,) + row[4:])
                else:
                    newblock.append(row)
            result.append((dirinfo, newblock))
        tree.unlock()
        # check each return value for debugging ease.
        for pos, item in enumerate(expected_dirblocks):
            self.assertEqual(item, result[pos])
        self.assertEqual(len(expected_dirblocks), len(result))

    def test_walkdir_versioned_kind(self):
        work_tree = self.make_branch_and_tree('tree')
        work_tree.set_root_id('tree-root')
        self.build_tree(['tree/file', 'tree/dir/'])
        work_tree.add(['file', 'dir'], ['file-id', 'dir-id'])
        os.unlink('tree/file')
        os.rmdir('tree/dir')
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        if tree.path2id('file') is None:
            raise tests.TestNotApplicable(
                'Tree type cannot represent dangling ids.')
        expected = [(('', 'tree-root'), [
            ('dir', 'dir', 'unknown', None, 'dir-id', 'directory'),
            ('file', 'file', 'unknown', None, 'file-id', 'file')]),
            (('dir', 'dir-id'), [])]
        self.assertEqual(expected, list(tree.walkdirs()))

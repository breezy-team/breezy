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

from breezy import tests
from breezy.mutabletree import MutableTree
from breezy.osutils import supports_symlinks
from breezy.tests.per_tree import TestCaseWithTree


class TestWalkdirs(TestCaseWithTree):

    def get_all_subdirs_expected(self, tree, symlinks):
        empty_dirs_present = (tree.has_versioned_directories()
                              or isinstance(tree, MutableTree))
        empty_dirs_are_versioned = tree.has_versioned_directories()
        dirblocks = {}

        dirblocks[''] = [
            ('0file', '0file', 'file', None, 'file'),
            ('1top-dir', '1top-dir', 'directory', None, 'directory'),
            (u'2utf\u1234file', u'2utf\u1234file', 'file', None, 'file')]

        dirblocks['1top-dir'] = [
            ('1top-dir/0file-in-1topdir', '0file-in-1topdir',
             'file', None, 'file')]
        if empty_dirs_present:
            dirblocks['1top-dir'].append(
                ('1top-dir/1dir-in-1topdir', '1dir-in-1topdir', 'directory',
                 None if empty_dirs_are_versioned else os.stat(
                     tree.abspath('1top-dir/1dir-in-1topdir')),
                 'directory' if empty_dirs_are_versioned else None))
            dirblocks['1top-dir/1dir-in-1topdir'] = []
        if symlinks:
            dirblocks[''].append(
                ('symlink', 'symlink', 'symlink', None, 'symlink'))
        return [(path, list(sorted(entries)))
                for (path, entries) in sorted(dirblocks.items())]

    def test_walkdir_root(self):
        tree = self.get_tree_with_subdirs_and_all_supported_content_types(
            supports_symlinks(self.test_dir))
        with tree.lock_read():
            expected_dirblocks = self.get_all_subdirs_expected(
                tree, supports_symlinks(self.test_dir))
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
        self.assertEqual(len(expected_dirblocks), len(result))

    def test_walkdir_subtree(self):
        tree = self.get_tree_with_subdirs_and_all_supported_content_types(
            supports_symlinks(self.test_dir))
        # test that its iterable by iterating
        result = []
        with tree.lock_read():
            expected_dirblocks = self.get_all_subdirs_expected(
                tree, supports_symlinks(self.test_dir))[1:]
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
        self.assertEqual(len(expected_dirblocks), len(result))

    def test_walkdir_versioned_kind(self):
        work_tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file', 'tree/dir/'])
        work_tree.add(['file', 'dir'])
        os.unlink('tree/file')
        os.rmdir('tree/dir')
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        if not tree.supports_file_ids or tree.path2id('file') is None:
            raise tests.TestNotApplicable(
                'Tree type cannot represent dangling ids.')
        expected = [('', ([
            ('dir', 'dir', 'unknown', None, 'directory')]
            if tree.has_versioned_directories() else []) +
            [('file', 'file', 'unknown', None, 'file')])]
        if tree.has_versioned_directories():
            expected.append(('dir', []))
        self.assertEqual(expected, list(tree.walkdirs()))

# Copyright (C) 2010 Canonical Ltd
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

import os
import re

from bzrlib import tests, osutils

class TestGrep(tests.TestCaseWithTransport):
    def _str_contains(self, base, pattern, flags=re.MULTILINE|re.DOTALL):
        res = re.findall(pattern, base, flags)
        return res != []

    def _mk_file(self, path, line_prefix, total_lines, versioned):
        text=''
        for i in range(total_lines):
            text += line_prefix + str(i+1) + "\n"

        open(path, 'w').write(text)
        if versioned:
            self.run_bzr(['add', path])
            self.run_bzr(['ci', '-m', '"' + path + '"'])

    def _update_file(self, path, text, checkin=True):
        """append text to file 'path' and check it in"""
        open(path, 'a').write(text)
        if checkin:
            self.run_bzr(['ci', path, '-m', '"' + path + '"'])

    def _mk_unknown_file(self, path, line_prefix='line', total_lines=10):
        self._mk_file(path, line_prefix, total_lines, versioned=False)

    def _mk_versioned_file(self, path, line_prefix='line', total_lines=10):
        self._mk_file(path, line_prefix, total_lines, versioned=True)

    def _mk_dir(self, path, versioned):
        os.mkdir(path)
        if versioned:
            self.run_bzr(['add', path])
            self.run_bzr(['ci', '-m', '"' + path + '"'])

    def _mk_unknown_dir(self, path):
        self._mk_dir(path, versioned=False)

    def _mk_versioned_dir(self, path):
        self._mk_dir(path, versioned=True)

    def test_basic_unknown_file(self):
        """Search for pattern in specfic file.

        If specified file is unknown, grep it anyway."""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_unknown_file('file0.txt')

        out, err = self.run_bzr(['grep', 'line1', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "file0.txt:line1"))

        out, err = self.run_bzr(['grep', 'line1'])
        self.assertFalse(self._str_contains(out, "file0.txt"))

    def test_ver_basic_file(self):
        """(versioned) Search for pattern in specfic file.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        out, err = self.run_bzr(['grep', '-r', '1', 'line1', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "file0.txt~1:line1"))

    def test_wtree_basic_file(self):
        """(wtree) Search for pattern in specfic file.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        self._update_file('file0.txt', 'ABC\n', checkin=False)

        out, err = self.run_bzr(['grep', 'ABC', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "file0.txt:ABC"))

        out, err = self.run_bzr(['grep', '-r', 'last:1', 'ABC', 'file0.txt'])
        self.assertFalse(self._str_contains(out, "file0.txt"))

    def test_ver_basic_include(self):
        """(versioned) Ensure that --include flag is respected.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.aa')
        self._mk_versioned_file('file0.bb')
        self._mk_versioned_file('file0.cc')
        out, err = self.run_bzr(['grep', '-r', 'last:1',
            '--include', '*.aa', '--include', '*.bb', 'line1'])
        self.assertTrue(self._str_contains(out, "file0.aa~.:line1"))
        self.assertTrue(self._str_contains(out, "file0.bb~.:line1"))
        self.assertFalse(self._str_contains(out, "file0.cc"))

    def test_wtree_basic_include(self):
        """(wtree) Ensure that --include flag is respected.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.aa')
        self._mk_versioned_file('file0.bb')
        self._mk_versioned_file('file0.cc')
        out, err = self.run_bzr(['grep', '--include', '*.aa',
            '--include', '*.bb', 'line1'])
        self.assertTrue(self._str_contains(out, "file0.aa:line1"))
        self.assertTrue(self._str_contains(out, "file0.bb:line1"))
        self.assertFalse(self._str_contains(out, "file0.cc"))

    def test_ver_basic_exclude(self):
        """(versioned) Ensure that --exclude flag is respected.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.aa')
        self._mk_versioned_file('file0.bb')
        self._mk_versioned_file('file0.cc')
        out, err = self.run_bzr(['grep', '-r', 'last:1',
            '--exclude', '*.cc', 'line1'])
        self.assertTrue(self._str_contains(out, "file0.aa~.:line1"))
        self.assertTrue(self._str_contains(out, "file0.bb~.:line1"))
        self.assertFalse(self._str_contains(out, "file0.cc"))

    def test_wtree_basic_exclude(self):
        """(wtree) Ensure that --exclude flag is respected.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.aa')
        self._mk_versioned_file('file0.bb')
        self._mk_versioned_file('file0.cc')
        out, err = self.run_bzr(['grep', '--exclude', '*.cc', 'line1'])
        self.assertTrue(self._str_contains(out, "file0.aa:line1"))
        self.assertTrue(self._str_contains(out, "file0.bb:line1"))
        self.assertFalse(self._str_contains(out, "file0.cc"))

    def test_ver_multiple_files(self):
        """(versioned) Search for pattern in multiple files.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt', total_lines=2)
        self._mk_versioned_file('file1.txt', total_lines=2)
        self._mk_versioned_file('file2.txt', total_lines=2)
        out, err = self.run_bzr(['grep', '-r', 'last:1', 'line[1-2]'])

        self.assertTrue(self._str_contains(out, "file0.txt~.:line1"))
        self.assertTrue(self._str_contains(out, "file0.txt~.:line2"))
        self.assertTrue(self._str_contains(out, "file1.txt~.:line1"))
        self.assertTrue(self._str_contains(out, "file1.txt~.:line2"))
        self.assertTrue(self._str_contains(out, "file2.txt~.:line1"))
        self.assertTrue(self._str_contains(out, "file2.txt~.:line2"))

    def test_multiple_wtree_files(self):
        """(wtree) Search for pattern in multiple files in working tree.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt', total_lines=2)
        self._mk_versioned_file('file1.txt', total_lines=2)
        self._mk_versioned_file('file2.txt', total_lines=2)
        self._update_file('file0.txt', 'HELLO\n', checkin=False)
        self._update_file('file1.txt', 'HELLO\n', checkin=True)
        self._update_file('file2.txt', 'HELLO\n', checkin=False)

        out, err = self.run_bzr(['grep', 'HELLO',
            'file0.txt', 'file1.txt', 'file2.txt'])

        self.assertTrue(self._str_contains(out, "file0.txt:HELLO"))
        self.assertTrue(self._str_contains(out, "file1.txt:HELLO"))
        self.assertTrue(self._str_contains(out, "file2.txt:HELLO"))

        out, err = self.run_bzr(['grep', 'HELLO', '-r', 'last:1',
            'file0.txt', 'file1.txt', 'file2.txt'])

        self.assertFalse(self._str_contains(out, "file0.txt"))
        self.assertTrue(self._str_contains(out, "file1.txt~.:HELLO"))
        self.assertFalse(self._str_contains(out, "file2.txt"))

    def test_ver_null_option(self):
        """(versioned) --null option should use NUL instead of newline.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt', total_lines=3)

        out, err = self.run_bzr(['grep', '-r', 'last:1', '--null', 'line[1-3]'])
        self.assertTrue(out == "file0.txt~1:line1\0file0.txt~1:line2\0file0.txt~1:line3\0")

        out, err = self.run_bzr(['grep', '-r', 'last:1', '-Z', 'line[1-3]'])
        self.assertTrue(out == "file0.txt~1:line1\0file0.txt~1:line2\0file0.txt~1:line3\0")

    def test_wtree_null_option(self):
        """(wtree) --null option should use NUL instead of newline.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt', total_lines=3)

        out, err = self.run_bzr(['grep', '--null', 'line[1-3]'])
        self.assertTrue(out == "file0.txt:line1\0file0.txt:line2\0file0.txt:line3\0")

        out, err = self.run_bzr(['grep', '-Z', 'line[1-3]'])
        self.assertTrue(out == "file0.txt:line1\0file0.txt:line2\0file0.txt:line3\0")

    def test_versioned_file_in_dir_no_recursive(self):
        """(versioned) Should not recurse with --no-recursive"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        out, err = self.run_bzr(['grep', '-r', 'last:1', '--no-recursive', 'line1'])
        self.assertFalse(self._str_contains(out, "file0.txt~.:line1"))

    def test_wtree_file_in_dir_no_recursive(self):
        """(wtree) Should not recurse with --no-recursive"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        out, err = self.run_bzr(['grep', '--no-recursive', 'line1'])
        self.assertFalse(self._str_contains(out, "file0.txt:line1"))

    def test_versioned_file_in_dir_recurse(self):
        """(versioned) Should recurse by default.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        out, err = self.run_bzr(['grep', '-r', '-1', 'line1'])
        self.assertTrue(self._str_contains(out, "^dir0/file0.txt~.:line1"))

    def test_wtree_file_in_dir_recurse(self):
        """(wtree) Should recurse by default.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        out, err = self.run_bzr(['grep', 'line1'])
        self.assertTrue(self._str_contains(out, "^dir0/file0.txt:line1"))

    def test_versioned_file_within_dir(self):
        """(versioned) Search for pattern while in nested dir.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', '-r', 'last:1', 'line1'])
        self.assertTrue(self._str_contains(out, "^file0.txt~.:line1"))

    def test_versioned_include_file_within_dir(self):
        """(versioned) Ensure --include is respected with file within dir.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        self._mk_versioned_file('dir0/file1.aa')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', '-r', 'last:1',
            '--include', '*.aa', 'line1'])
        self.assertTrue(self._str_contains(out, "^file1.aa~.:line1"))
        self.assertFalse(self._str_contains(out, "file0.txt"))

    def test_versioned_exclude_file_within_dir(self):
        """(versioned) Ensure --exclude is respected with file within dir.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        self._mk_versioned_file('dir0/file1.aa')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', '-r', 'last:1',
            '--exclude', '*.txt', 'line1'])
        self.assertTrue(self._str_contains(out, "^file1.aa~.:line1"))
        self.assertFalse(self._str_contains(out, "file0.txt"))

    def test_wtree_file_within_dir(self):
        """(wtree) Search for pattern while in nested dir.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', 'line1'])
        self.assertTrue(self._str_contains(out, "^file0.txt:line1"))

    def test_wtree_include_file_within_dir(self):
        """(wtree) Ensure --include is respected with file within dir.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        self._mk_versioned_file('dir0/file1.aa')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', '--include', '*.aa', 'line1'])
        self.assertTrue(self._str_contains(out, "^file1.aa:line1"))
        self.assertFalse(self._str_contains(out, "file0.txt"))

    def test_wtree_exclude_file_within_dir(self):
        """(wtree) Ensure --exclude is respected with file within dir.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        self._mk_versioned_file('dir0/file1.aa')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', '--exclude', '*.txt', 'line1'])
        self.assertTrue(self._str_contains(out, "^file1.aa:line1"))
        self.assertFalse(self._str_contains(out, "file0.txt"))


    def test_ver_files_from_outside_dir(self):
        """(versioned) Grep for pattern with dirs passed as argument.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')

        self._mk_versioned_dir('dir1')
        self._mk_versioned_file('dir1/file1.txt')

        out, err = self.run_bzr(['grep', '-r', 'last:1', 'line1', 'dir0', 'dir1'])
        self.assertTrue(self._str_contains(out, "^dir0/file0.txt~.:line1"))
        self.assertTrue(self._str_contains(out, "^dir1/file1.txt~.:line1"))

    def test_versioned_include_from_outside_dir(self):
        """(versioned) Ensure --include is respected during recursive search.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.aa')

        self._mk_versioned_dir('dir1')
        self._mk_versioned_file('dir1/file1.bb')

        self._mk_versioned_dir('dir2')
        self._mk_versioned_file('dir2/file2.cc')

        out, err = self.run_bzr(['grep', '-r', 'last:1',
            '--include', '*.aa', '--include', '*.bb', 'line1'])
        self.assertTrue(self._str_contains(out, "^dir0/file0.aa~.:line1"))
        self.assertTrue(self._str_contains(out, "^dir1/file1.bb~.:line1"))
        self.assertFalse(self._str_contains(out, "file1.cc"))

    def test_wtree_include_from_outside_dir(self):
        """(wtree) Ensure --include is respected during recursive search.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.aa')

        self._mk_versioned_dir('dir1')
        self._mk_versioned_file('dir1/file1.bb')

        self._mk_versioned_dir('dir2')
        self._mk_versioned_file('dir2/file2.cc')

        out, err = self.run_bzr(['grep', '--include', '*.aa',
            '--include', '*.bb', 'line1'])
        self.assertTrue(self._str_contains(out, "^dir0/file0.aa:line1"))
        self.assertTrue(self._str_contains(out, "^dir1/file1.bb:line1"))
        self.assertFalse(self._str_contains(out, "file1.cc"))

    def test_versioned_exclude_from_outside_dir(self):
        """(versioned) Ensure --exclude is respected during recursive search.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.aa')

        self._mk_versioned_dir('dir1')
        self._mk_versioned_file('dir1/file1.bb')

        self._mk_versioned_dir('dir2')
        self._mk_versioned_file('dir2/file2.cc')

        out, err = self.run_bzr(['grep', '-r', 'last:1',
            '--exclude', '*.cc', 'line1'])
        self.assertTrue(self._str_contains(out, "^dir0/file0.aa~.:line1"))
        self.assertTrue(self._str_contains(out, "^dir1/file1.bb~.:line1"))
        self.assertFalse(self._str_contains(out, "file1.cc"))

    def test_wtree_exclude_from_outside_dir(self):
        """(wtree) Ensure --exclude is respected during recursive search.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.aa')

        self._mk_versioned_dir('dir1')
        self._mk_versioned_file('dir1/file1.bb')

        self._mk_versioned_dir('dir2')
        self._mk_versioned_file('dir2/file2.cc')

        out, err = self.run_bzr(['grep', '--exclude', '*.cc', 'line1'])
        self.assertTrue(self._str_contains(out, "^dir0/file0.aa:line1"))
        self.assertTrue(self._str_contains(out, "^dir1/file1.bb:line1"))
        self.assertFalse(self._str_contains(out, "file1.cc"))

    def test_workingtree_files_from_outside_dir(self):
        """(wtree) Grep for pattern with dirs passed as argument.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')

        self._mk_versioned_dir('dir1')
        self._mk_versioned_file('dir1/file1.txt')

        out, err = self.run_bzr(['grep', 'line1', 'dir0', 'dir1'])
        self.assertTrue(self._str_contains(out, "^dir0/file0.txt:line1"))
        self.assertTrue(self._str_contains(out, "^dir1/file1.txt:line1"))

    def test_versioned_files_from_outside_dir(self):
        """(versioned) Grep for pattern with dirs passed as argument.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')

        self._mk_versioned_dir('dir1')
        self._mk_versioned_file('dir1/file1.txt')

        out, err = self.run_bzr(['grep', '-r', 'last:1', 'line1', 'dir0', 'dir1'])
        self.assertTrue(self._str_contains(out, "^dir0/file0.txt~.:line1"))
        self.assertTrue(self._str_contains(out, "^dir1/file1.txt~.:line1"))

    def test_wtree_files_from_outside_dir(self):
        """(wtree) Grep for pattern with dirs passed as argument.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')

        self._mk_versioned_dir('dir1')
        self._mk_versioned_file('dir1/file1.txt')

        out, err = self.run_bzr(['grep', 'line1', 'dir0', 'dir1'])
        self.assertTrue(self._str_contains(out, "^dir0/file0.txt:line1"))
        self.assertTrue(self._str_contains(out, "^dir1/file1.txt:line1"))

    def test_versioned_files_from_outside_two_dirs(self):
        """(versioned) Grep for pattern with two levels of nested dir.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')

        self._mk_versioned_dir('dir1')
        self._mk_versioned_file('dir1/file1.txt')

        self._mk_versioned_dir('dir0/dir00')
        self._mk_versioned_file('dir0/dir00/file0.txt')

        out, err = self.run_bzr(['grep', '-r', 'last:1', 'line1', 'dir0/dir00'])
        self.assertTrue(self._str_contains(out, "^dir0/dir00/file0.txt~.:line1"))

        out, err = self.run_bzr(['grep', '-r', 'last:1', 'line1'])
        self.assertTrue(self._str_contains(out, "^dir0/dir00/file0.txt~.:line1"))

    def test_wtree_files_from_outside_two_dirs(self):
        """(wtree) Grep for pattern with two levels of nested dir.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)

        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')

        self._mk_versioned_dir('dir1')
        self._mk_versioned_file('dir1/file1.txt')

        self._mk_versioned_dir('dir0/dir00')
        self._mk_versioned_file('dir0/dir00/file0.txt')

        out, err = self.run_bzr(['grep', 'line1', 'dir0/dir00'])
        self.assertTrue(self._str_contains(out, "^dir0/dir00/file0.txt:line1"))

        out, err = self.run_bzr(['grep', 'line1'])
        self.assertTrue(self._str_contains(out, "^dir0/dir00/file0.txt:line1"))

    def test_versioned_file_within_dir_two_levels(self):
        """(versioned) Search for pattern while in nested dir (two levels).
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_dir('dir0/dir1')
        self._mk_versioned_file('dir0/dir1/file0.txt')
        os.chdir('dir0')

        out, err = self.run_bzr(['grep', '-r', 'last:1', 'line1'])
        self.assertTrue(self._str_contains(out, "^dir1/file0.txt~.:line1"))

        out, err = self.run_bzr(['grep', '-r', 'last:1', '--from-root', 'line1'])
        self.assertTrue(self._str_contains(out, "^dir0/dir1/file0.txt~.:line1"))

        out, err = self.run_bzr(['grep', '-r', 'last:1', '--no-recursive', 'line1'])
        self.assertFalse(self._str_contains(out, "file0.txt"))

    def test_wtree_file_within_dir_two_levels(self):
        """(wtree) Search for pattern while in nested dir (two levels).
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_dir('dir0/dir1')
        self._mk_versioned_file('dir0/dir1/file0.txt')
        os.chdir('dir0')

        out, err = self.run_bzr(['grep', 'line1'])
        self.assertTrue(self._str_contains(out, "^dir1/file0.txt:line1"))

        out, err = self.run_bzr(['grep', '--from-root', 'line1'])
        self.assertTrue(self._str_contains(out, "^dir0/dir1/file0.txt:line1"))

        out, err = self.run_bzr(['grep', '--no-recursive', 'line1'])
        self.assertFalse(self._str_contains(out, "file0.txt"))

    def test_versioned_ignore_case_no_match(self):
        """(versioned) Match fails without --ignore-case.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        out, err = self.run_bzr(['grep', '-r', 'last:1', 'LinE1', 'file0.txt'])
        self.assertFalse(self._str_contains(out, "file0.txt~.:line1"))

    def test_wtree_ignore_case_no_match(self):
        """(wtree) Match fails without --ignore-case.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        out, err = self.run_bzr(['grep', 'LinE1', 'file0.txt'])
        self.assertFalse(self._str_contains(out, "file0.txt:line1"))

    def test_versioned_ignore_case_match(self):
        """(versioned) Match fails without --ignore-case.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        out, err = self.run_bzr(['grep', '-r', 'last:1',
            '-i', 'LinE1', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "file0.txt~.:line1"))
        out, err = self.run_bzr(['grep', '-r', 'last:1',
            '--ignore-case', 'LinE1', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "^file0.txt~.:line1"))

    def test_wtree_ignore_case_match(self):
        """(wtree) Match fails without --ignore-case.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        out, err = self.run_bzr(['grep', '-i', 'LinE1', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "file0.txt:line1"))
        out, err = self.run_bzr(['grep', '--ignore-case', 'LinE1', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "^file0.txt:line1"))

    def test_versioned_from_root_fail(self):
        """(versioned) Match should fail without --from-root.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        self._mk_versioned_dir('dir0')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', '-r', 'last:1', 'line1'])
        self.assertFalse(self._str_contains(out, "file0.txt"))

    def test_wtree_from_root_fail(self):
        """(wtree) Match should fail without --from-root.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        self._mk_versioned_dir('dir0')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', 'line1'])
        self.assertFalse(self._str_contains(out, "file0.txt"))

    def test_versioned_from_root_pass(self):
        """(versioned) Match pass with --from-root.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        self._mk_versioned_dir('dir0')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', '-r', 'last:1',
            '--from-root', 'line1'])
        self.assertTrue(self._str_contains(out, "file0.txt~.:line1"))

    def test_wtree_from_root_pass(self):
        """(wtree) Match pass with --from-root.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        self._mk_versioned_dir('dir0')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', '--from-root', 'line1'])
        self.assertTrue(self._str_contains(out, "file0.txt:line1"))

    def test_versioned_with_line_number(self):
        """(versioned) Search for pattern with --line-number.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')

        out, err = self.run_bzr(['grep', '-r', 'last:1',
            '--line-number', 'line3', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "file0.txt~.:3:line3"))

        out, err = self.run_bzr(['grep', '-r', 'last:1',
            '-n', 'line1', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "file0.txt~.:1:line1"))

    def test_wtree_with_line_number(self):
        """(wtree) Search for pattern with --line-number.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')

        out, err = self.run_bzr(['grep', '--line-number', 'line3', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "file0.txt:3:line3"))

        out, err = self.run_bzr(['grep', '-n', 'line1', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "file0.txt:1:line1"))

    def test_revno_basic_history_grep_file(self):
        """Search for pattern in specific revision number in a file.
        """
        wd = 'foobar0'
        fname = 'file0.txt'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file(fname, total_lines=0)
        self._update_file(fname, text="v2 text\n")
        self._update_file(fname, text="v3 text\n")
        self._update_file(fname, text="v4 text\n")

        # rev 2 should not have text 'v3'
        out, err = self.run_bzr(['grep', '-r', '2', 'v3', fname])
        self.assertFalse(self._str_contains(out, "file0.txt"))

        # rev 3 should not have text 'v3'
        out, err = self.run_bzr(['grep', '-r', '3', 'v3', fname])
        self.assertTrue(self._str_contains(out, "file0.txt~3:v3.*"))

        # rev 3 should not have text 'v3' with line number
        out, err = self.run_bzr(['grep', '-r', '3', '-n', 'v3', fname])
        self.assertTrue(self._str_contains(out, "file0.txt~3:2:v3.*"))

    def test_revno_basic_history_grep_full(self):
        """Search for pattern in specific revision number in a file.
        """
        wd = 'foobar0'
        fname = 'file0.txt'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file(fname, total_lines=0) # rev1
        self._mk_versioned_file('file1.txt')          # rev2
        self._update_file(fname, text="v3 text\n")    # rev3
        self._update_file(fname, text="v4 text\n")    # rev4
        self._update_file(fname, text="v5 text\n")    # rev5

        # rev 2 should not have text 'v3'
        out, err = self.run_bzr(['grep', '-r', '2', 'v3'])
        self.assertFalse(self._str_contains(out, "file0.txt"))

        # rev 3 should not have text 'v3'
        out, err = self.run_bzr(['grep', '-r', '3', 'v3'])
        self.assertTrue(self._str_contains(out, "file0.txt~3:v3"))

        # rev 3 should not have text 'v3' with line number
        out, err = self.run_bzr(['grep', '-r', '3', '-n', 'v3'])
        self.assertTrue(self._str_contains(out, "file0.txt~3:1:v3"))

    def test_revno_versioned_file_in_dir(self):
        """Grep specific version of file withing dir.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')                      # rev1
        self._mk_versioned_file('dir0/file0.txt')           # rev2
        self._update_file('dir0/file0.txt', "v3 text\n")    # rev3
        self._update_file('dir0/file0.txt', "v4 text\n")    # rev4
        self._update_file('dir0/file0.txt', "v5 text\n")    # rev5

        # v4 should not be present in revno 3
        out, err = self.run_bzr(['grep', '-r', 'last:3', 'v4'])
        self.assertFalse(self._str_contains(out, "^dir0/file0.txt"))

        # v4 should be present in revno 4
        out, err = self.run_bzr(['grep', '-r', 'last:2', 'v4'])
        self.assertTrue(self._str_contains(out, "^dir0/file0.txt~4:v4"))

    def test_revno_range_basic_history_grep(self):
        """Search for pattern in revision range for file.
        """
        wd = 'foobar0'
        fname = 'file0.txt'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file(fname, total_lines=0) # rev1
        self._mk_versioned_file('file1.txt')          # rev2
        self._update_file(fname, text="v3 text\n")    # rev3
        self._update_file(fname, text="v4 text\n")    # rev4
        self._update_file(fname, text="v5 text\n")    # rev5
        self._update_file(fname, text="v6 text\n")    # rev6

        out, err = self.run_bzr(['grep', '-r', '1..', 'v3'])
        self.assertTrue(self._str_contains(out, "file0.txt~3:v3"))
        self.assertTrue(self._str_contains(out, "file0.txt~4:v3"))
        self.assertTrue(self._str_contains(out, "file0.txt~5:v3"))

        out, err = self.run_bzr(['grep', '-r', '1..5', 'v3'])
        self.assertTrue(self._str_contains(out, "file0.txt~3:v3"))
        self.assertTrue(self._str_contains(out, "file0.txt~4:v3"))
        self.assertTrue(self._str_contains(out, "file0.txt~5:v3"))
        self.assertFalse(self._str_contains(out, "file0.txt~6:v3"))

    def test_revno_range_versioned_file_in_dir(self):
        """Grep rev-range for pattern for file withing a dir.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')                      # rev1
        self._mk_versioned_file('dir0/file0.txt')           # rev2
        self._update_file('dir0/file0.txt', "v3 text\n")    # rev3
        self._update_file('dir0/file0.txt', "v4 text\n")    # rev4
        self._update_file('dir0/file0.txt', "v5 text\n")    # rev5
        self._update_file('dir0/file0.txt', "v6 text\n")    # rev6

        out, err = self.run_bzr(['grep', '-r', '2..5', 'v3'])
        self.assertTrue(self._str_contains(out, "^dir0/file0.txt~3:v3"))
        self.assertTrue(self._str_contains(out, "^dir0/file0.txt~4:v3"))
        self.assertTrue(self._str_contains(out, "^dir0/file0.txt~5:v3"))
        self.assertFalse(self._str_contains(out, "^dir0/file0.txt~6:v3"))

    def test_revno_range_versioned_file_from_outside_dir(self):
        """Grep rev-range for pattern from outside dir.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')                      # rev1
        self._mk_versioned_file('dir0/file0.txt')           # rev2
        self._update_file('dir0/file0.txt', "v3 text\n")    # rev3
        self._update_file('dir0/file0.txt', "v4 text\n")    # rev4
        self._update_file('dir0/file0.txt', "v5 text\n")    # rev5
        self._update_file('dir0/file0.txt', "v6 text\n")    # rev6

        out, err = self.run_bzr(['grep', '-r', '2..5', 'v3', 'dir0'])
        self.assertTrue(self._str_contains(out, "^dir0/file0.txt~3:v3"))
        self.assertTrue(self._str_contains(out, "^dir0/file0.txt~4:v3"))
        self.assertTrue(self._str_contains(out, "^dir0/file0.txt~5:v3"))
        self.assertFalse(self._str_contains(out, "^dir0/file0.txt~6:v3"))

    def test_levels(self):
        """--levels=0 should show findings from merged revision.
        """
        wd0 = 'foobar0'
        wd1 = 'foobar1'

        self.make_branch_and_tree(wd0)
        os.chdir(wd0)
        self._mk_versioned_file('file0.txt')
        os.chdir('..')

        out, err = self.run_bzr(['branch', wd0, wd1])
        os.chdir(wd1)
        self._mk_versioned_file('file1.txt')
        os.chdir(osutils.pathjoin('..', wd0))

        out, err = self.run_bzr(['merge', osutils.pathjoin('..', wd1)])
        out, err = self.run_bzr(['ci', '-m', 'merged'])

        out, err = self.run_bzr(['grep', 'line1'])
        self.assertTrue(self._str_contains(out, "file0.txt:line1"))
        self.assertTrue(self._str_contains(out, "file1.txt:line1"))

        # levels should be ignored by wtree grep
        out, err = self.run_bzr(['grep', '--levels=0', 'line1'])
        self.assertTrue(self._str_contains(out, "file0.txt:line1"))
        self.assertTrue(self._str_contains(out, "file1.txt:line1"))

        out, err = self.run_bzr(['grep', '-r', 'last:1', '--levels=0', 'line1'])
        self.assertTrue(self._str_contains(out, "file0.txt~2:line1"))
        self.assertTrue(self._str_contains(out, "file1.txt~2:line1"))
        self.assertTrue(self._str_contains(out, "file0.txt~1.1.1:line1"))
        self.assertTrue(self._str_contains(out, "file1.txt~1.1.1:line1"))

        out, err = self.run_bzr(['grep', '-r',  '-1', '-n', '--levels=0', 'line1'])
        self.assertTrue(self._str_contains(out, "file0.txt~2:1:line1"))
        self.assertTrue(self._str_contains(out, "file1.txt~2:1:line1"))
        self.assertTrue(self._str_contains(out, "file0.txt~1.1.1:1:line1"))
        self.assertTrue(self._str_contains(out, "file1.txt~1.1.1:1:line1"))

    def test_versioned_binary_file_grep(self):
        """(versioned) Grep for pattern in binary file.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        self._update_file('file0.txt', "\x00lineNN\x00\n")
        out, err = self.run_bzr(['grep', '-r', 'last:1',
            'lineNN', 'file0.txt'])
        self.assertFalse(self._str_contains(out, "file0.txt"))
        self.assertTrue(self._str_contains(err, "Binary file.*file0.txt.*skipped"))

    def test_wtree_binary_file_grep(self):
        """(wtree) Grep for pattern in binary file.
        """
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        self._update_file('file0.txt', "\x00lineNN\x00\n")
        out, err = self.run_bzr(['grep', 'lineNN', 'file0.txt'])
        self.assertFalse(self._str_contains(out, "file0.txt:line1"))
        self.assertTrue(self._str_contains(err, "Binary file.*file0.txt.*skipped"))


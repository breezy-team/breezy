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

    def _update_file(self, path, text):
        """append text to file 'path' and check it in"""
        open(path, 'a').write(text)
        self.run_bzr(['ci', '-m', '"' + path + '"'])

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
        """search for pattern in specfic file. should issue warning."""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('filex.txt') # force rev to revno:1 and not revno:0
        self._mk_unknown_file('file0.txt')
        out, err = self.run_bzr(['grep', 'line1', 'file0.txt'])
        self.assertFalse(self._str_contains(out, "file0.txt:line1"))
        self.assertTrue(self._str_contains(err, "warning: skipped.*file0.txt.*\."))

    def test_revno0(self):
        """search for pattern in when only revno0 is present"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)   # only revno 0 in branch
        os.chdir(wd)
        out, err = self.run_bzr(['grep', 'line1'], retcode=3)
        self.assertTrue(self._str_contains(err, "ERROR: No revisions found"))

    def test_basic_versioned_file(self):
        """search for pattern in specfic file"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        out, err = self.run_bzr(['grep', 'line1', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "file0.txt:line1"))
        self.assertFalse(self._str_contains(err, "warning: skipped.*file0.txt.*\."))

    def test_multiple_files(self):
        """search for pattern in multiple files"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt', total_lines=2)
        self._mk_versioned_file('file1.txt', total_lines=2)
        self._mk_versioned_file('file2.txt', total_lines=2)
        out, err = self.run_bzr(['grep', 'line[1-2]'])

        self.assertTrue(self._str_contains(out, "file0.txt:line1"))
        self.assertTrue(self._str_contains(out, "file0.txt:line2"))
        self.assertTrue(self._str_contains(out, "file1.txt:line1"))
        self.assertTrue(self._str_contains(out, "file1.txt:line2"))
        self.assertTrue(self._str_contains(out, "file2.txt:line1"))
        self.assertTrue(self._str_contains(out, "file2.txt:line2"))

    def test_null_option(self):
        """--null option should use NUL instead of newline"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt', total_lines=3)

        out, err = self.run_bzr(['grep', '--null', 'line[1-3]'])
        self.assertTrue(out == "file0.txt:line1\0file0.txt:line2\0file0.txt:line3\0")

        out, err = self.run_bzr(['grep', '-Z', 'line[1-3]'])
        self.assertTrue(out == "file0.txt:line1\0file0.txt:line2\0file0.txt:line3\0")

    def test_versioned_file_in_dir_no_recurse(self):
        """should not recurse without --no-recurse"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        out, err = self.run_bzr(['grep', '--no-recurse', 'line1'])
        self.assertFalse(self._str_contains(out, "file0.txt:line1"))

    def test_versioned_file_in_dir_recurse(self):
        """should recurse by default"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        out, err = self.run_bzr(['grep', 'line1'])
        self.assertTrue(self._str_contains(out, "^dir0/file0.txt:line1"))

    def test_versioned_file_within_dir(self):
        """search for pattern while in nested dir"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', 'line1'])
        self.assertTrue(self._str_contains(out, "^file0.txt:line1"))

    def test_versioned_files_from_outside_dir(self):
        """grep for pattern with dirs passed as argument"""
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
        """grep for pattern with dirs passed as argument"""
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
        """grep for pattern with two levels of nested dir"""
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
        """search for pattern while in nested dir (two levels)"""
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

        out, err = self.run_bzr(['grep', '--no-recurse', 'line1'])
        self.assertFalse(self._str_contains(out, "file0.txt"))

    def test_ignore_case_no_match(self):
        """match fails without --ignore-case"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        out, err = self.run_bzr(['grep', 'LinE1', 'file0.txt'])
        self.assertFalse(self._str_contains(out, "file0.txt:line1"))

    def test_ignore_case_match(self):
        """match fails without --ignore-case"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        out, err = self.run_bzr(['grep', '-i', 'LinE1', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "file0.txt:line1"))
        out, err = self.run_bzr(['grep', '--ignore-case', 'LinE1', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "^file0.txt:line1"))

    def test_from_root_fail(self):
        """match should fail without --from-root"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        self._mk_versioned_dir('dir0')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', 'line1'])
        self.assertFalse(self._str_contains(out, ".*file0.txt:line1"))

    def test_from_root_pass(self):
        """match pass with --from-root"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        self._mk_versioned_dir('dir0')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', '--from-root', 'line1'])
        self.assertTrue(self._str_contains(out, ".*file0.txt:line1"))

    def test_with_line_number(self):
        """search for pattern with --line-number"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')

        out, err = self.run_bzr(['grep', '--line-number', 'line3', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "file0.txt:3:line3"))

        out, err = self.run_bzr(['grep', '-n', 'line1', 'file0.txt'])
        self.assertTrue(self._str_contains(out, "file0.txt:1:line1"))

    def test_revno_basic_history_grep_file(self):
        """search for pattern in specific revision number in a file"""
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
        """search for pattern in specific revision number in a file"""
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
        """we create a file 'foobar0/dir0/file0.txt' and grep specific version of content"""
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
        """search for pattern in revision range for file"""
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
        """we create a file 'foobar0/dir0/file0.txt' and grep rev-range for pattern"""
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
        """grep rev-range for pattern from outside dir"""
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
        """levels=0 should show findings from merged revision"""
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

        out, err = self.run_bzr(['grep', '--levels=0', 'line1'])
        self.assertTrue(self._str_contains(out, "file0.txt~2:line1"))
        self.assertTrue(self._str_contains(out, "file1.txt~2:line1"))
        self.assertTrue(self._str_contains(out, "file0.txt~1.1.1:line1"))
        self.assertTrue(self._str_contains(out, "file1.txt~1.1.1:line1"))

        out, err = self.run_bzr(['grep', '-n', '--levels=0', 'line1'])
        self.assertTrue(self._str_contains(out, "file0.txt~2:1:line1"))
        self.assertTrue(self._str_contains(out, "file1.txt~2:1:line1"))
        self.assertTrue(self._str_contains(out, "file0.txt~1.1.1:1:line1"))
        self.assertTrue(self._str_contains(out, "file1.txt~1.1.1:1:line1"))

    def test_binary_file_grep(self):
        """grep for pattern in binary file"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        self._update_file('file0.txt', "\x00lineNN\x00\n")
        out, err = self.run_bzr(['grep', 'lineNN', 'file0.txt'])
        self.assertFalse(self._str_contains(out, "file0.txt:line1"))
        self.assertTrue(self._str_contains(err, "Binary file.*file0.txt.*skipped"))



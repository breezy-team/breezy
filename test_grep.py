# Copyright (C) 2010 Canonical Ltd
# Copyright (C) 2010 Parth Malwankar <parth.malwankar@gmail.com>
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

from bzrlib import tests

class TestGrep(tests.TestCaseWithTransport):
    def _str_contains(self, base, pattern):
        return re.search(pattern, base) != None

    def _mk_file(self, path, total_lines, line_prefix, versioned):
        text=''
        for i in range(total_lines):
            text += line_prefix + str(i+1) + "\n"

        open(path, 'w').write(text)
        if versioned:
            self.run_bzr(['add', path])
            self.run_bzr(['ci', '-m', '"' + path + '" added'])

    def _mk_unversioned_file(self, path, line_prefix='line', total_lines=10):
        self._mk_file(path, total_lines, line_prefix, versioned=False)

    def _mk_versioned_file(self, path, line_prefix='line', total_lines=10):
        self._mk_file(path, total_lines, line_prefix, versioned=True)

    def _mk_dir(self, path, versioned):
        os.mkdir(path)
        if versioned:
            self.run_bzr(['add', path])
            self.run_bzr(['ci', '-m', '"' + path + '" added'])

    def _mk_unversioned_dir(self, path):
        self._mk_dir(path, versioned=True)

    def _mk_versioned_dir(self, path):
        self._mk_dir(path, versioned=True)

    def test_basic_unversioned_file(self):
        """search for pattern in specfic file"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_unversioned_file('file0.txt')
        out, err = self.run_bzr(['grep', 'line1', 'file0.txt'])
        self.assertTrue(out, self._str_contains(out, "file0.txt:1:line1"))
        self.assertTrue(err, self._str_contains(err, "warning:.*file0.txt.*not versioned\."))

    def test_basic_versioned_file(self):
        """search for pattern in specfic file"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        out, err = self.run_bzr(['grep', 'line1', 'file0.txt'])
        self.assertTrue(out, self._str_contains(out, "file0.txt:1:line1"))
        self.assertFalse(err, self._str_contains(err, "warning:.*file0.txt.*not versioned\."))

    def test_versioned_file_in_dir_no_recurse(self):
        """should not recurse without -R"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        out, err = self.run_bzr(['grep', 'line1'])
        self.assertFalse(out, self._str_contains(out, ".*file0.txt:1:line1"))

    def test_versioned_file_in_dir_recurse(self):
        """should find pattern in hierarchy with -R"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_dir('dir0')
        self._mk_versioned_file('dir0/file0.txt')
        out, err = self.run_bzr(['grep', '-R', 'line1'])
        self.assertTrue(out, self._str_contains(out, "dir0/file0.txt:1:line1"))

    def test_ignore_case_no_match(self):
        """match fails without --ignore-case"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        out, err = self.run_bzr(['grep', 'LinE1', 'file0.txt'])
        self.assertFalse(out, self._str_contains(out, "file0.txt:1:line1"))

    def test_ignore_case_match(self):
        """match fails without --ignore-case"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        out, err = self.run_bzr(['grep', '-i', 'LinE1', 'file0.txt'])
        self.assertTrue(out, self._str_contains(out, "file0.txt:1:line1"))

    def test_from_root_fail(self):
        """match should fail without --from-root"""
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        self._mk_versioned_dir('dir0')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', 'line1'])
        self.assertFalse(out, self._str_contains(out, ".*file0.txt:1:line1"))

    def test_from_root_pass(self):
        """match pass with --from-root"""
        raise tests.KnownFailure("--from-root not implemented yet!")
        wd = 'foobar0'
        self.make_branch_and_tree(wd)
        os.chdir(wd)
        self._mk_versioned_file('file0.txt')
        self._mk_versioned_dir('dir0')
        os.chdir('dir0')
        out, err = self.run_bzr(['grep', '--from-root', 'line1'])
        self.assertTrue(out, self._str_contains(out, ".*file0.txt:1:line1"))



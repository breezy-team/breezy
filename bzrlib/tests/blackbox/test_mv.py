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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Test for 'bzr mv'"""

import os

from bzrlib import (
    osutils,
    workingtree,
    )
from bzrlib.tests import (
    TestCaseWithTransport,
    TestSkipped,
    )


class TestMove(TestCaseWithTransport):

    def test_mv_modes(self):
        """Test two modes of operation for mv"""
        tree = self.make_branch_and_tree('.')
        files = self.build_tree(['a', 'c', 'subdir/'])
        tree.add(['a', 'c', 'subdir'])

        self.run_bzr('mv', 'a', 'b')
        self.failUnlessExists('b')
        self.failIfExists('a')

        self.run_bzr('mv', 'b', 'subdir')
        self.failUnlessExists('subdir/b')
        self.failIfExists('b')

        self.run_bzr('mv', 'subdir/b', 'a')
        self.failUnlessExists('a')
        self.failIfExists('subdir/b')

        self.run_bzr('mv', 'a', 'c', 'subdir')
        self.failUnlessExists('subdir/a')
        self.failUnlessExists('subdir/c')
        self.failIfExists('a')
        self.failIfExists('c')

        self.run_bzr('mv', 'subdir/a', 'subdir/newa')
        self.failUnlessExists('subdir/newa')
        self.failIfExists('subdir/a')

    def test_mv_unversioned(self):
        self.build_tree(['unversioned.txt'])
        self.run_bzr_error(
            ["^bzr: ERROR: can't rename: old name .* is not versioned$"],
            'mv', 'unversioned.txt', 'elsewhere')

    def test_mv_nonexisting(self):
        self.run_bzr_error(
            ["^bzr: ERROR: can't rename: old name .* is not versioned$"],
            'mv', 'doesnotexist', 'somewhereelse')

    def test_mv_unqualified(self):
        self.run_bzr_error(['^bzr: ERROR: missing file argument$'], 'mv')
        
    def test_mv_invalid(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['test.txt', 'sub1/'])
        tree.add(['test.txt'])

        self.run_bzr_error(
            ["^bzr: ERROR: destination .* is not a versioned directory$"],
            'mv', 'test.txt', 'sub1')
        
        self.run_bzr_error(
            ["^bzr: ERROR: destination .* is not a versioned directory$"],
            'mv', 'test.txt', 'sub1/hello.txt')
        
    def test_mv_dirs(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['hello.txt', 'sub1/'])
        tree.add(['hello.txt', 'sub1'])

        self.run_bzr('mv', 'sub1', 'sub2')
        self.failUnlessExists('sub2')
        self.failIfExists('sub1')
        self.run_bzr('mv', 'hello.txt', 'sub2')
        self.failUnlessExists("sub2/hello.txt")
        self.failIfExists("hello.txt")

        tree.read_working_inventory()
        tree.commit('commit with some things moved to subdirs')

        self.build_tree(['sub1/'])
        tree.add(['sub1'])
        self.run_bzr('mv', 'sub2/hello.txt', 'sub1')
        self.failIfExists('sub2/hello.txt')
        self.failUnlessExists('sub1/hello.txt')
        self.run_bzr('mv', 'sub2', 'sub1')
        self.failIfExists('sub2')
        self.failUnlessExists('sub1/sub2')

    def test_mv_relative(self):
        self.build_tree(['sub1/', 'sub1/sub2/', 'sub1/hello.txt'])
        tree = self.make_branch_and_tree('.')
        tree.add(['sub1', 'sub1/sub2', 'sub1/hello.txt'])
        tree.commit('initial tree')

        os.chdir('sub1/sub2')
        self.run_bzr('mv', '../hello.txt', '.')
        self.failUnlessExists('./hello.txt')
        tree.read_working_inventory()
        tree.commit('move to parent directory')

        os.chdir('..')

        self.run_bzr('mv', 'sub2/hello.txt', '.')
        self.failUnlessExists('hello.txt')

    def test_mv_smoke_aliases(self):
        # just test that aliases for mv exist, if their behaviour is changed in
        # the future, then extend the tests.
        self.build_tree(['a'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a'])

        self.run_bzr('move', 'a', 'b')
        self.run_bzr('rename', 'b', 'a')

    def test_mv_through_symlinks(self):
        if not osutils.has_symlinks():
            raise TestSkipped('Symlinks are not supported on this platform')
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b'])
        os.symlink('a', 'c')
        os.symlink('.', 'd')
        tree.add(['a', 'a/b', 'c'], ['a-id', 'b-id', 'c-id'])
        self.run_bzr('mv', 'c/b', 'b')
        tree = workingtree.WorkingTree.open('.')
        self.assertEqual('b-id', tree.path2id('b'))

    def test_mv_already_moved_file(self):
        """a is in repository, b does not exist. User does
        mv a b; bzr mv a b"""
        self.build_tree(['a', 'b'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a'])
        tree.commit('initial commit')

        os.rename('a', 'b')
        self.run_bzr('mv', 'a', 'b')
        self.failIfExists('a')
        self.failUnlessExists('b')

    def test_mv_already_moved_file_to_versioned_target(self):
        """a and b are in the repository. User does
        rm b; mv a b; bzr mv a b"""
        self.build_tree(['a', 'b'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a', 'b'])
        tree.commit('initial commit')
    
        os.remove('a')
        self.run_bzr_error(
            ["^bzr: ERROR: can't rename: new name .* is already versioned$"],
            'mv', 'a', 'b')
        self.failIfExists('a')
        self.failUnlessExists('b')

    def test_mv_already_moved_file_into_subdir(self):
        """a and sub1/ are in the repository. User does
        mv a sub1/a; bzr mv a sub1/a"""
        self.build_tree(['a', 'sub1/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a', 'sub1'])
        tree.commit('initial commit')
        
        os.rename('a', 'sub1/a')
        self.run_bzr('mv', 'a', 'sub1/a')
        self.failIfExists('a')
        self.failUnlessExists('sub1/a')

    def test_mv_already_moved_file_into_unversioned_subdir(self):
        """a is in the repository, sub1/ is not. User does
        mv a sub1/a; bzr mv a sub1/a"""
        self.build_tree(['a', 'sub1/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a'])
        tree.commit('initial commit')

        os.rename('a', 'sub1/a')
        self.run_bzr_error(
            ["^bzr: ERROR: destination .* is not a versioned directory$"],
            'mv', 'a', 'sub1/a')
        self.failIfExists('a')
        self.failUnlessExists('sub1/a')

    def test_mv_already_moved_files_into_subdir(self):
        """a1, a2, sub1 are in the repository. User does
        mv a1 sub1/.; bzr mv a1 a2 sub1"""
        self.build_tree(['a1', 'a2', 'sub1/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'a2', 'sub1'])
        tree.commit('initial commit')

        os.rename('a1', 'sub1/a1')
        self.run_bzr('mv', 'a1', 'a2', 'sub1')
        self.failIfExists('a1')
        self.failIfExists('a2')
        self.failUnlessExists('sub1/a1')
        self.failUnlessExists('sub1/a2')
        
    def test_mv_already_moved_files_into_unversioned_subdir(self):
        """a1, a2 are in the repository, sub1 is not. User does
        mv a1 sub1/.; bzr mv a1 a2 sub1"""
        self.build_tree(['a1', 'a2', 'sub1/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'a2'])
        tree.commit('initial commit')

        os.rename('a1', 'sub1/a1')
        self.run_bzr_error(
            ["^bzr: ERROR: destination .* is not a versioned directory$"],
            'mv', 'a1', 'a2', 'sub1')
        self.failIfExists('a1')
        self.failUnlessExists('a2')
        self.failUnlessExists('sub1/a1')
        self.failIfExists('sub1/a2')

    def test_mv_already_moved_file_forcing_after(self):
        """a is in the repository, b does not exist. User does
        mv a b; touch a; bzr mv a b"""
        self.build_tree(['a', 'b'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a'])
        tree.commit('initial commit')

        self.run_bzr_error(
            ["^bzr: ERROR: can't rename: both, old name .* and new name .*"
             " exist. Use option '--after' to force rename."],
            'mv', 'a', 'b')
        self.failUnlessExists('a')
        self.failUnlessExists('b')

    def test_mv_already_moved_file_using_after(self):
        """a is in the repository, b does not exist. User does
        mv a b; touch a; bzr mv a b --after"""
        self.build_tree(['a', 'b'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a'])
        tree.commit('initial commit')

        self.run_bzr('mv', 'a', 'b', '--after')
        self.failUnlessExists('a')
        self.failUnlessExists('b')

    def test_mv_already_moved_files_forcing_after(self):
        """a1, a2, sub1 are in the repository, sub1/a1, sub1/a2
        do not exist. User does
        mv a* sub1; touch a1; touch a2; bzr mv a1 a2 sub1"""
        self.build_tree(['a1', 'a2', 'sub1/', 'sub1/a1', 'sub1/a2'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'a2', 'sub1'])
        tree.commit('initial commit')

        self.run_bzr_error(
            ["^bzr: ERROR: can't rename: both, old name .* and new name .*"
             " exist. Use option '--after' to force rename."],
            'mv', 'a1', 'a2', 'sub1')
        self.failUnlessExists('a1')
        self.failUnlessExists('a2')
        self.failUnlessExists('sub1/a1')
        self.failUnlessExists('sub1/a2')
        
    def test_mv_already_moved_files_using_after(self):
        """a1, a2, sub1 are in the repository, sub1/a1, sub1/a2
        do not exist. User does
        mv a* sub1; touch a1; touch a2; bzr mv a1 a2 sub1 --after"""
        self.build_tree(['a1', 'a2', 'sub1/', 'sub1/a1', 'sub1/a2'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'a2', 'sub1'])
        tree.commit('initial commit')

        self.run_bzr('mv', 'a1', 'a2', 'sub1', '--after')
        self.failUnlessExists('a1')
        self.failUnlessExists('a2')
        self.failUnlessExists('sub1/a1')
        self.failUnlessExists('sub1/a2')


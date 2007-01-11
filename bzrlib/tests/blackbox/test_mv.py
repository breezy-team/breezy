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
from bzrlib.osutils import (
    splitpath
    )

class TestMove(TestCaseWithTransport):

    def assertInWorkingTree(self,path):
        tree = workingtree.WorkingTree.open('.')
        self.assertNotNone(tree.path2id(path),path+' not in working tree.')

    def assertNotInWorkingTree(self,path):
        tree = workingtree.WorkingTree.open('.')
        self.assertNone(tree.path2id(path),path+' in working tree.')

    def assertMoved(self,from_path,to_path):
        """Assert that to_path is existing and versioned but from_path not. """
        self.failIfExists(from_path)
        self.assertNotInWorkingTree(from_path)

        self.failUnlessExists(to_path)
        self.assertInWorkingTree(to_path)

    def test_mv_modes(self):
        """Test two modes of operation for mv"""
        tree = self.make_branch_and_tree('.')
        files = self.build_tree(['a', 'c', 'subdir/'])
        tree.add(['a', 'c', 'subdir'])

        self.run_bzr('mv', 'a', 'b')
        self.assertMoved('a','b')

        self.run_bzr('mv', 'b', 'subdir')
        self.assertMoved('b','subdir/b')

        self.run_bzr('mv', 'subdir/b', 'a')
        self.assertMoved('subdir/b','a')

        self.run_bzr('mv', 'a', 'c', 'subdir')
        self.assertMoved('a','subdir/a')
        self.assertMoved('c','subdir/c')

        self.run_bzr('mv', 'subdir/a', 'subdir/newa')
        self.assertMoved('subdir/a','subdir/newa')

    def test_mv_unversioned(self):
        self.build_tree(['unversioned.txt'])
        self.run_bzr_error(
            ["^bzr: ERROR: Could not rename unversioned.txt => elsewhere."
             " .*unversioned.txt is not versioned$"],
            'mv', 'unversioned.txt', 'elsewhere')

    def test_mv_nonexisting(self):
        self.run_bzr_error(
            ["^bzr: ERROR: Could not rename doesnotexist => somewhereelse."
             " .*doesnotexist is not versioned$"],
            'mv', 'doesnotexist', 'somewhereelse')

    def test_mv_unqualified(self):
        self.run_bzr_error(['^bzr: ERROR: missing file argument$'], 'mv')

    def test_mv_invalid(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['test.txt', 'sub1/'])
        tree.add(['test.txt'])

        self.run_bzr_error(
            ["^bzr: ERROR: Could not move to sub1: sub1 is not versioned$"],
            'mv', 'test.txt', 'sub1')

        self.run_bzr_error(
            ["^bzr: ERROR: Could not move test.txt => .*hello.txt: "
             "sub1 is not versioned$"],
            'mv', 'test.txt', 'sub1/hello.txt')

    def test_mv_dirs(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['hello.txt', 'sub1/'])
        tree.add(['hello.txt', 'sub1'])

        self.run_bzr('mv', 'sub1', 'sub2')
        self.assertMoved('sub1','sub2')

        self.run_bzr('mv', 'hello.txt', 'sub2')
        self.assertMoved('hello.txt','sub2/hello.txt')

        tree.read_working_inventory()

        self.build_tree(['sub1/'])
        tree.add(['sub1'])
        self.run_bzr('mv', 'sub2/hello.txt', 'sub1')
        self.assertMoved('sub2/hello.txt','sub1/hello.txt')

        self.run_bzr('mv', 'sub2', 'sub1')
        self.assertMoved('sub2','sub1/sub2')

    def test_mv_relative(self):
        self.build_tree(['sub1/', 'sub1/sub2/', 'sub1/hello.txt'])
        tree = self.make_branch_and_tree('.')
        tree.add(['sub1', 'sub1/sub2', 'sub1/hello.txt'])

        os.chdir('sub1/sub2')
        self.run_bzr('mv', '../hello.txt', '.')
        self.failUnlessExists('./hello.txt')
        tree.read_working_inventory()

        os.chdir('..')
        self.run_bzr('mv', 'sub2/hello.txt', '.')
        os.chdir('..')
        self.assertMoved('sub1/sub2/hello.txt','sub1/hello.txt')

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
        """Test bzr mv original_file to moved_file.

        Tests if a file which has allready been moved by an external tool,
        is handled correctly by bzr mv.
        Setup: a is in the working tree, b does not exist.
        User does: mv a b; bzr mv a b

        """
        self.build_tree(['a'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a'])

        os.rename('a', 'b')
        self.run_bzr('mv', 'a', 'b')
        self.assertMoved('a','b')

    def test_mv_already_moved_file_to_versioned_target(self):
        """Test bzr mv existing_file to versioned_file.

        Tests if an attempt to move an existing versioned file
        to another versiond file will fail.
        Setup: a and b are in the working tree.
        User does: rm b; mv a b; bzr mv a b

        """
        self.build_tree(['a', 'b'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a', 'b'])

        os.remove('b')
        os.rename('a', 'b')
        self.run_bzr_error(
            ["^bzr: ERROR: Could not move a => b. b is already versioned$"],
            'mv', 'a', 'b')
        #check that nothing changed
        self.failIfExists('a')
        self.failUnlessExists('b')

    def test_mv_already_moved_file_into_subdir(self):
        """Test bzr mv original_file to versioned_directory/file.

        Tests if a file which has already been moved into a versioned
        directory by an external tool, is handled correctly by bzr mv.
        Setup: a and sub/ are in the working tree.
        User does: mv a sub/a; bzr mv a sub/a

        """
        self.build_tree(['a', 'sub/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a', 'sub'])

        os.rename('a', 'sub/a')
        self.run_bzr('mv', 'a', 'sub/a')
        self.assertMoved('a','sub/a')

    def test_mv_already_moved_file_into_unversioned_subdir(self):
        """Test bzr mv original_file to unversioned_directory/file.

        Tests if an attempt to move an existing versioned file
        into an unversioned directory will fail.
        Setup: a is in the working tree, sub/ is not.
        User does: mv a sub/a; bzr mv a sub/a

        """
        self.build_tree(['a', 'sub/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a'])

        os.rename('a', 'sub/a')
        self.run_bzr_error(
            ["^bzr: ERROR: Could not move a => a: sub is not versioned$"],
            'mv', 'a', 'sub/a')
        self.failIfExists('a')
        self.failUnlessExists('sub/a')

    def test_mv_already_moved_files_into_subdir(self):
        """Test bzr mv original_files to versioned_directory.

        Tests if files which has already been moved into a versioned
        directory by an external tool, is handled correctly by bzr mv.
        Setup: a1, a2, sub are in the working tree.
        User does: mv a1 sub/.; bzr mv a1 a2 sub

        """
        self.build_tree(['a1', 'a2', 'sub/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'a2', 'sub'])

        os.rename('a1', 'sub/a1')
        self.run_bzr('mv', 'a1', 'a2', 'sub')
        self.assertMoved('a1','sub/a1')
        self.assertMoved('a2','sub/a2')

    def test_mv_already_moved_files_into_unversioned_subdir(self):
        """Test bzr mv original_file to unversioned_directory.

        Tests if an attempt to move existing versioned file
        into an unversioned directory will fail.
        Setup: a1, a2 are in the working tree, sub is not.
        User does: mv a1 sub/.; bzr mv a1 a2 sub

        """
        self.build_tree(['a1', 'a2', 'sub/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'a2'])

        os.rename('a1', 'sub/a1')
        self.run_bzr_error(
            ["^bzr: ERROR: Could not move to sub. sub is not versioned$"],
            'mv', 'a1', 'a2', 'sub')
        self.failIfExists('a1')
        self.failUnlessExists('sub/a1')
        self.failUnlessExists('a2')
        self.failIfExists('sub/a2')

    def test_mv_already_moved_file_forcing_after(self):
        """Test bzr mv versioned_file to unversioned_file.

        Tests if an attempt to move an existing versioned file to an existing
        unversioned file will fail, informing the user to use the --after
        option to force this.
        Setup: a is in the working tree, b not versioned.
        User does: mv a b; touch a; bzr mv a b

        """
        self.build_tree(['a', 'b'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a'])

        os.rename('a', 'b')
        self.build_tree(['a']) #touch a
        self.run_bzr_error(
            ["^bzr: ERROR: Could not rename a => b: Files exist: a b:"
             " \(Use --after to update the Bazaar id\)$"],
            'mv', 'a', 'b')
        self.failUnlessExists('a')
        self.failUnlessExists('b')

    def test_mv_already_moved_file_using_after(self):
        """Test bzr mv --after versioned_file to unversioned_file.

        Tests if an existing versioned file can be forced to move to an
        existing unversioned file using the --after option. With the result
        that bazaar considers the unversioned_file to be moved from
        versioned_file and versioned_file will become unversioned.
        Setup: a is in the working tree and b exists.
        User does: mv a b; touch a; bzr mv a b --after
        Resulting in a => b and a is unknown.

        """
        self.build_tree(['a', 'b'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a'])
        os.rename('a', 'b')
        self.build_tree(['a']) #touch a

        self.run_bzr('mv', 'a', 'b', '--after')
        self.failUnlessExists('a')
        self.assertNotInWorkingTree('a')#a should be unknown now.
        self.failUnlessExists('b')
        self.assertInWorkingTree('b')

    def test_mv_already_moved_files_forcing_after(self):
        """Test bzr mv versioned_files to directory/unversioned_file.

        Tests if an attempt to move an existing versioned file to an existing
        unversioned file in some other directory will fail, informing the user
        to use the --after option to force this.

        Setup: a1, a2, sub are versioned and in the working tree,
               sub/a1, sub/a2 are in working tree.
        User does: mv a* sub; touch a1; touch a2; bzr mv a1 a2 sub

        """
        self.build_tree(['a1', 'a2', 'sub/', 'sub/a1', 'sub/a2'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'a2', 'sub'])
        os.rename('a1', 'sub/a1')
        os.rename('a2', 'sub/a2')
        self.build_tree(['a1']) #touch a1
        self.build_tree(['a2']) #touch a2

        self.run_bzr_error(
            ["^bzr: ERROR: Could not rename a1 => a1: Files exist: a1 .*a1:"
             " \(Use --after to update the Bazaar id\)$"],
            'mv', 'a1', 'a2', 'sub')
        self.failUnlessExists('a1')
        self.failUnlessExists('a2')
        self.failUnlessExists('sub/a1')
        self.failUnlessExists('sub/a2')

    def test_mv_already_moved_files_using_after(self):
        """Test bzr mv --after versioned_file to directory/unversioned_file.

        Tests if an existing versioned file can be forced to move to an
        existing unversioned file in some other directory using the --after
        option. With the result that bazaar considers
        directory/unversioned_file to be moved from versioned_file and
        versioned_file will become unversioned.

        Setup: a1, a2, sub are versioned and in the working tree,
               sub/a1, sub/a2 are in working tree.
        User does: mv a* sub; touch a1; touch a2; bzr mv a1 a2 sub --after

        """
        self.build_tree(['a1', 'a2', 'sub/', 'sub/a1', 'sub/a2'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'a2', 'sub'])
        os.rename('a1', 'sub/a1')
        os.rename('a2', 'sub/a2')
        self.build_tree(['a1']) #touch a1
        self.build_tree(['a2']) #touch a2

        self.run_bzr('mv', 'a1', 'a2', 'sub', '--after')
        self.failUnlessExists('a1')
        self.failUnlessExists('a2')
        self.failUnlessExists('sub/a1')
        self.failUnlessExists('sub/a2')
        self.assertInWorkingTree('sub/a1')
        self.assertInWorkingTree('sub/a2')
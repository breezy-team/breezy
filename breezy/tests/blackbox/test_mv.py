# Copyright (C) 2006-2012, 2016 Canonical Ltd
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

"""Test for 'brz mv'"""

import os

import breezy.branch
from breezy import (
    osutils,
    workingtree,
    )

from breezy.tests import (
    TestCaseWithTransport,
    script,
    )
from breezy.tests.features import (
    CaseInsensitiveFilesystemFeature,
    SymlinkFeature,
    UnicodeFilenameFeature,
    )


class TestMove(TestCaseWithTransport):

    def assertMoved(self, from_path, to_path):
        """Assert that to_path is existing and versioned but from_path not. """
        self.assertPathDoesNotExist(from_path)
        self.assertNotInWorkingTree(from_path)

        self.assertPathExists(to_path)
        self.assertInWorkingTree(to_path)

    def test_mv_modes(self):
        """Test two modes of operation for mv"""
        tree = self.make_branch_and_tree('.')
        files = self.build_tree(['a', 'c', 'subdir/'])
        tree.add(['a', 'c', 'subdir'])

        self.run_bzr('mv a b')
        self.assertMoved('a', 'b')

        self.run_bzr('mv b subdir')
        self.assertMoved('b', 'subdir/b')

        self.run_bzr('mv subdir/b a')
        self.assertMoved('subdir/b', 'a')

        self.run_bzr('mv a c subdir')
        self.assertMoved('a', 'subdir/a')
        self.assertMoved('c', 'subdir/c')

        self.run_bzr('mv subdir/a subdir/newa')
        self.assertMoved('subdir/a', 'subdir/newa')

    def test_mv_unversioned(self):
        self.build_tree(['unversioned.txt'])
        self.run_bzr_error(
            ["^brz: ERROR: Could not rename unversioned.txt => elsewhere."
             " .*unversioned.txt is not versioned\\.$"],
            'mv unversioned.txt elsewhere')

    def test_mv_nonexisting(self):
        self.run_bzr_error(
            ["^brz: ERROR: Could not rename doesnotexist => somewhereelse."
             " .*doesnotexist is not versioned\\.$"],
            'mv doesnotexist somewhereelse')

    def test_mv_unqualified(self):
        self.run_bzr_error(['^brz: ERROR: missing file argument$'], 'mv')

    def test_mv_invalid(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['test.txt', 'sub1/'])
        tree.add(['test.txt'])

        self.run_bzr_error(
            ["^brz: ERROR: Could not move to sub1: sub1 is not versioned\\.$"],
            'mv test.txt sub1')

        self.run_bzr_error(
            ["^brz: ERROR: Could not move test.txt => .*hello.txt: "
             "sub1 is not versioned\\.$"],
            'mv test.txt sub1/hello.txt')

    def test_mv_dirs(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['hello.txt', 'sub1/'])
        tree.add(['hello.txt', 'sub1'])

        self.run_bzr('mv sub1 sub2')
        self.assertMoved('sub1', 'sub2')

        self.run_bzr('mv hello.txt sub2')
        self.assertMoved('hello.txt', 'sub2/hello.txt')

        self.build_tree(['sub1/'])
        tree.add(['sub1'])
        self.run_bzr('mv sub2/hello.txt sub1')
        self.assertMoved('sub2/hello.txt', 'sub1/hello.txt')

        self.run_bzr('mv sub2 sub1')
        self.assertMoved('sub2', 'sub1/sub2')

    def test_mv_relative(self):
        self.build_tree(['sub1/', 'sub1/sub2/', 'sub1/hello.txt'])
        tree = self.make_branch_and_tree('.')
        tree.add(['sub1', 'sub1/sub2', 'sub1/hello.txt'])

        self.run_bzr('mv ../hello.txt .', working_dir='sub1/sub2')
        self.assertPathExists('sub1/sub2/hello.txt')

        self.run_bzr('mv sub2/hello.txt .', working_dir='sub1')
        self.assertMoved('sub1/sub2/hello.txt', 'sub1/hello.txt')

    def test_mv_change_case_file(self):
        # test for bug #77740 (mv unable change filename case on Windows)
        tree = self.make_branch_and_tree('.')
        self.build_tree(['test.txt'])
        tree.add(['test.txt'])
        self.run_bzr('mv test.txt Test.txt')
        # we can't use failUnlessExists on case-insensitive filesystem
        # so try to check shape of the tree
        shape = sorted(os.listdir(u'.'))
        self.assertEqual(['.bzr', 'Test.txt'], shape)
        self.assertInWorkingTree('Test.txt')
        self.assertNotInWorkingTree('test.txt')

    def test_mv_change_case_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo/'])
        tree.add(['foo'])
        self.run_bzr('mv foo Foo')
        # we can't use failUnlessExists on case-insensitive filesystem
        # so try to check shape of the tree
        shape = sorted(os.listdir(u'.'))
        self.assertEqual(['.bzr', 'Foo'], shape)
        self.assertInWorkingTree('Foo')
        self.assertNotInWorkingTree('foo')

    def test_mv_change_case_dir_w_files(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo/', 'foo/bar'])
        tree.add(['foo'])
        self.run_bzr('mv foo Foo')
        # we can't use failUnlessExists on case-insensitive filesystem
        # so try to check shape of the tree
        shape = sorted(os.listdir(u'.'))
        self.assertEqual(['.bzr', 'Foo'], shape)
        self.assertInWorkingTree('Foo')
        self.assertNotInWorkingTree('foo')

    def test_mv_file_to_wrong_case_dir(self):
        self.requireFeature(CaseInsensitiveFilesystemFeature)
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo/', 'bar'])
        tree.add(['foo', 'bar'])
        out, err = self.run_bzr('mv bar Foo', retcode=3)
        self.assertEqual('', out)
        self.assertEqual(
            'brz: ERROR: Could not move to Foo: Foo is not versioned.\n',
            err)

    def test_mv_smoke_aliases(self):
        # just test that aliases for mv exist, if their behaviour is changed in
        # the future, then extend the tests.
        self.build_tree(['a'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a'])

        self.run_bzr('move a b')
        self.run_bzr('rename b a')

    def test_mv_no_root(self):
        tree = self.make_branch_and_tree('.')
        self.run_bzr_error(
            ["brz: ERROR: can not move root of branch"],
            'mv . a')

    def test_mv_through_symlinks(self):
        self.requireFeature(SymlinkFeature(self.test_dir))
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b'])
        os.symlink('a', 'c')
        os.symlink('.', 'd')
        tree.add(['a', 'a/b', 'c'], ids=[b'a-id', b'b-id', b'c-id'])
        self.run_bzr('mv c/b b')
        tree = workingtree.WorkingTree.open('.')
        self.assertEqual(b'b-id', tree.path2id('b'))

    def test_mv_already_moved_file(self):
        """Test brz mv original_file to moved_file.

        Tests if a file which has allready been moved by an external tool,
        is handled correctly by brz mv.
        Setup: a is in the working tree, b does not exist.
        User does: mv a b; brz mv a b
        """
        self.build_tree(['a'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a'])

        osutils.rename('a', 'b')
        self.run_bzr('mv a b')
        self.assertMoved('a', 'b')

    def test_mv_already_moved_file_to_versioned_target(self):
        """Test brz mv existing_file to versioned_file.

        Tests if an attempt to move an existing versioned file
        to another versiond file will fail.
        Setup: a and b are in the working tree.
        User does: rm b; mv a b; brz mv a b
        """
        self.build_tree(['a', 'b'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a', 'b'])

        os.remove('b')
        osutils.rename('a', 'b')
        self.run_bzr_error(
            ["^brz: ERROR: Could not move a => b. b is already versioned\\.$"],
            'mv a b')
        # check that nothing changed
        self.assertPathDoesNotExist('a')
        self.assertPathExists('b')

    def test_mv_already_moved_file_into_subdir(self):
        """Test brz mv original_file to versioned_directory/file.

        Tests if a file which has already been moved into a versioned
        directory by an external tool, is handled correctly by brz mv.
        Setup: a and sub/ are in the working tree.
        User does: mv a sub/a; brz mv a sub/a
        """
        self.build_tree(['a', 'sub/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a', 'sub'])

        osutils.rename('a', 'sub/a')
        self.run_bzr('mv a sub/a')
        self.assertMoved('a', 'sub/a')

    def test_mv_already_moved_file_into_unversioned_subdir(self):
        """Test brz mv original_file to unversioned_directory/file.

        Tests if an attempt to move an existing versioned file
        into an unversioned directory will fail.
        Setup: a is in the working tree, sub/ is not.
        User does: mv a sub/a; brz mv a sub/a
        """
        self.build_tree(['a', 'sub/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a'])

        osutils.rename('a', 'sub/a')
        self.run_bzr_error(
            ["^brz: ERROR: Could not move a => a: sub is not versioned\\.$"],
            'mv a sub/a')
        self.assertPathDoesNotExist('a')
        self.assertPathExists('sub/a')

    def test_mv_already_moved_files_into_subdir(self):
        """Test brz mv original_files to versioned_directory.

        Tests if files which has already been moved into a versioned
        directory by an external tool, is handled correctly by brz mv.
        Setup: a1, a2, sub are in the working tree.
        User does: mv a1 sub/.; brz mv a1 a2 sub
        """
        self.build_tree(['a1', 'a2', 'sub/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'a2', 'sub'])

        osutils.rename('a1', 'sub/a1')
        self.run_bzr('mv a1 a2 sub')
        self.assertMoved('a1', 'sub/a1')
        self.assertMoved('a2', 'sub/a2')

    def test_mv_already_moved_files_into_unversioned_subdir(self):
        """Test brz mv original_file to unversioned_directory.

        Tests if an attempt to move existing versioned file
        into an unversioned directory will fail.
        Setup: a1, a2 are in the working tree, sub is not.
        User does: mv a1 sub/.; brz mv a1 a2 sub
        """
        self.build_tree(['a1', 'a2', 'sub/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'a2'])

        osutils.rename('a1', 'sub/a1')
        self.run_bzr_error(
            ["^brz: ERROR: Could not move to sub. sub is not versioned\\.$"],
            'mv a1 a2 sub')
        self.assertPathDoesNotExist('a1')
        self.assertPathExists('sub/a1')
        self.assertPathExists('a2')
        self.assertPathDoesNotExist('sub/a2')

    def test_mv_already_moved_file_forcing_after(self):
        """Test brz mv versioned_file to unversioned_file.

        Tests if an attempt to move an existing versioned file to an existing
        unversioned file will fail, informing the user to use the --after
        option to force this.
        Setup: a is in the working tree, b not versioned.
        User does: mv a b; touch a; brz mv a b
        """
        self.build_tree(['a', 'b'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a'])

        osutils.rename('a', 'b')
        self.build_tree(['a'])  # touch a
        self.run_bzr_error(
            ["^brz: ERROR: Could not rename a => b because both files exist."
             " \\(Use --after to tell brz about a rename that has already"
             " happened\\)$"],
            'mv a b')
        self.assertPathExists('a')
        self.assertPathExists('b')

    def test_mv_already_moved_file_using_after(self):
        """Test brz mv --after versioned_file to unversioned_file.

        Tests if an existing versioned file can be forced to move to an
        existing unversioned file using the --after option. With the result
        that bazaar considers the unversioned_file to be moved from
        versioned_file and versioned_file will become unversioned.
        Setup: a is in the working tree and b exists.
        User does: mv a b; touch a; brz mv a b --after
        Resulting in a => b and a is unknown.
        """
        self.build_tree(['a', 'b'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a'])
        osutils.rename('a', 'b')
        self.build_tree(['a'])  # touch a

        self.run_bzr('mv a b --after')
        self.assertPathExists('a')
        self.assertNotInWorkingTree('a')  # a should be unknown now.
        self.assertPathExists('b')
        self.assertInWorkingTree('b')

    def test_mv_already_moved_files_forcing_after(self):
        """Test brz mv versioned_files to directory/unversioned_file.

        Tests if an attempt to move an existing versioned file to an existing
        unversioned file in some other directory will fail, informing the user
        to use the --after option to force this.

        Setup: a1, a2, sub are versioned and in the working tree,
               sub/a1, sub/a2 are in working tree.
        User does: mv a* sub; touch a1; touch a2; brz mv a1 a2 sub
        """
        self.build_tree(['a1', 'a2', 'sub/', 'sub/a1', 'sub/a2'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'a2', 'sub'])
        osutils.rename('a1', 'sub/a1')
        osutils.rename('a2', 'sub/a2')
        self.build_tree(['a1'])  # touch a1
        self.build_tree(['a2'])  # touch a2

        self.run_bzr_error(
            ["^brz: ERROR: Could not rename a1 => sub/a1 because both files"
             " exist. \\(Use --after to tell brz about a rename that has already"
             " happened\\)$"],
            'mv a1 a2 sub')
        self.assertPathExists('a1')
        self.assertPathExists('a2')
        self.assertPathExists('sub/a1')
        self.assertPathExists('sub/a2')

    def test_mv_already_moved_files_using_after(self):
        """Test brz mv --after versioned_file to directory/unversioned_file.

        Tests if an existing versioned file can be forced to move to an
        existing unversioned file in some other directory using the --after
        option. With the result that bazaar considers
        directory/unversioned_file to be moved from versioned_file and
        versioned_file will become unversioned.

        Setup: a1, a2, sub are versioned and in the working tree,
               sub/a1, sub/a2 are in working tree.
        User does: mv a* sub; touch a1; touch a2; brz mv a1 a2 sub --after
        """
        self.build_tree(['a1', 'a2', 'sub/', 'sub/a1', 'sub/a2'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a1', 'a2', 'sub'])
        osutils.rename('a1', 'sub/a1')
        osutils.rename('a2', 'sub/a2')
        self.build_tree(['a1'])  # touch a1
        self.build_tree(['a2'])  # touch a2

        self.run_bzr('mv a1 a2 sub --after')
        self.assertPathExists('a1')
        self.assertPathExists('a2')
        self.assertPathExists('sub/a1')
        self.assertPathExists('sub/a2')
        self.assertInWorkingTree('sub/a1')
        self.assertInWorkingTree('sub/a2')

    def test_mv_already_moved_directory(self):
        """Use `brz mv a b` to mark a directory as renamed.

        https://bugs.launchpad.net/bzr/+bug/107967/
        """
        self.build_tree(['a/', 'c/'])
        tree = self.make_branch_and_tree('.')
        tree.add(['a', 'c'])
        osutils.rename('a', 'b')
        osutils.rename('c', 'd')
        # mv a b should work just like it does for already renamed files
        self.run_bzr('mv a b')
        self.assertPathDoesNotExist('a')
        self.assertNotInWorkingTree('a')
        self.assertPathExists('b')
        self.assertInWorkingTree('b')
        # and --after should work, too (technically it's ignored)
        self.run_bzr('mv --after c d')
        self.assertPathDoesNotExist('c')
        self.assertNotInWorkingTree('c')
        self.assertPathExists('d')
        self.assertInWorkingTree('d')

    def make_abcd_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/c'])
        tree.add(['a', 'c'])
        tree.commit('record old names')
        osutils.rename('tree/a', 'tree/b')
        osutils.rename('tree/c', 'tree/d')
        return tree

    def test_mv_auto(self):
        self.make_abcd_tree()
        out, err = self.run_bzr('mv --auto', working_dir='tree')
        self.assertEqual(out, '')
        self.assertEqual(err, 'a => b\nc => d\n')
        tree = workingtree.WorkingTree.open('tree')
        self.assertTrue(tree.is_versioned('b'))
        self.assertTrue(tree.is_versioned('d'))

    def test_mv_auto_one_path(self):
        self.make_abcd_tree()
        out, err = self.run_bzr('mv --auto tree')
        self.assertEqual(out, '')
        self.assertEqual(err, 'a => b\nc => d\n')
        tree = workingtree.WorkingTree.open('tree')
        self.assertTrue(tree.is_versioned('b'))
        self.assertTrue(tree.is_versioned('d'))

    def test_mv_auto_two_paths(self):
        self.make_abcd_tree()
        out, err = self.run_bzr('mv --auto tree tree2', retcode=3)
        self.assertEqual('brz: ERROR: Only one path may be specified to'
                         ' --auto.\n', err)

    def test_mv_auto_dry_run(self):
        self.make_abcd_tree()
        out, err = self.run_bzr('mv --auto --dry-run', working_dir='tree')
        self.assertEqual(out, '')
        self.assertEqual(err, 'a => b\nc => d\n')
        tree = workingtree.WorkingTree.open('tree')
        self.assertTrue(tree.is_versioned('a'))
        self.assertTrue(tree.is_versioned('c'))

    def test_mv_no_auto_dry_run(self):
        self.make_abcd_tree()
        out, err = self.run_bzr('mv c d --dry-run',
                                working_dir='tree', retcode=3)
        self.assertEqual('brz: ERROR: --dry-run requires --auto.\n', err)

    def test_mv_auto_after(self):
        self.make_abcd_tree()
        out, err = self.run_bzr('mv --auto --after', working_dir='tree',
                                retcode=3)
        self.assertEqual('brz: ERROR: --after cannot be specified with'
                         ' --auto.\n', err)

    def test_mv_quiet(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['aaa'])
        tree.add(['aaa'])
        out, err = self.run_bzr('mv --quiet aaa bbb')
        self.assertEqual(out, '')
        self.assertEqual(err, '')

    def test_mv_readonly_lightweight_checkout(self):
        branch = self.make_branch('foo')
        branch = breezy.branch.Branch.open(self.get_readonly_url('foo'))
        tree = branch.create_checkout('tree', lightweight=True)
        self.build_tree(['tree/path'])
        tree.add('path')
        # If this fails, the tree is trying to acquire a branch lock, which it
        # shouldn't.
        self.run_bzr(['mv', 'tree/path', 'tree/path2'])

    def test_mv_unversioned_non_ascii(self):
        """Clear error on mv of an unversioned non-ascii file, see lp:707954"""
        self.requireFeature(UnicodeFilenameFeature)
        tree = self.make_branch_and_tree(".")
        self.build_tree([u"\xA7"])
        out, err = self.run_bzr_error(["Could not rename", "not versioned"],
                                      ["mv", u"\xA7", "b"])

    def test_mv_removed_non_ascii(self):
        """Clear error on mv of a removed non-ascii file, see lp:898541"""
        self.requireFeature(UnicodeFilenameFeature)
        tree = self.make_branch_and_tree(".")
        self.build_tree([u"\xA7"])
        tree.add([u"\xA7"])
        tree.commit(u"Adding \xA7")
        os.remove(u"\xA7")
        out, err = self.run_bzr_error(["Could not rename", "not exist"],
                                      ["mv", u"\xA7", "b"])

    def test_dupe_move(self):
        self.script_runner = script.ScriptRunner()
        self.script_runner.run_script(self, '''
        $ brz init brz-bug
        Created a standalone tree (format: 2a)
        $ cd brz-bug
        $ mkdir dir
        $ brz add
        adding dir
        $ echo text >> dir/test.txt
        $ brz add
        adding dir/test.txt
        $ brz ci -m "Add files"
        2>Committing to: .../brz-bug/
        2>added dir
        2>added dir/test.txt
        2>Committed revision 1.
        $ mv dir dir2
        $ mv dir2/test.txt dir2/test2.txt
        $ brz st
        removed:
          dir/
          dir/test.txt
        unknown:
          dir2/
        $ brz mv dir dir2
        dir => dir2
        $ brz st
        removed:
          dir/test.txt
        renamed:
          dir/ => dir2/
        unknown:
          dir2/test2.txt
        $ brz mv dir/test.txt dir2/test2.txt
        dir/test.txt => dir2/test2.txt
        ''')

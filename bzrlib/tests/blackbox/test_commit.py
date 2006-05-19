# Copyright (C) 2005, 2006 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Tests for the commit CLI of bzr."""

import os
import re
import sys

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import BzrCommandError
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree


class TestCommit(ExternalBase):

    def test_05_empty_commit(self):
        """Commit of tree with no versioned files should fail"""
        # If forced, it should succeed, but this is not tested here.
        self.runbzr("init")
        self.build_tree(['hello.txt'])
        self.runbzr("commit -m empty", retcode=3)

    def test_commit_with_path(self):
        """Commit tree with path of root specified"""
        self.run_bzr('init', 'a')
        self.build_tree(['a/a_file'])
        self.run_bzr('add', 'a/a_file')
        self.run_bzr('commit', '-m', 'first commit', 'a')

        self.run_bzr('branch', 'a', 'b')
        self.build_tree_contents([('b/a_file', 'changes in b')])
        self.run_bzr('commit', '-m', 'first commit in b', 'b')

        self.build_tree_contents([('a/a_file', 'new contents')])
        self.run_bzr('commit', '-m', 'change in a', 'a')

        os.chdir('b')
        self.run_bzr('merge', '../a', retcode=1) # will conflict
        os.chdir('..')
        self.run_bzr('resolved', 'b/a_file')
        self.run_bzr('commit', '-m', 'merge into b', 'b')


    def test_10_verbose_commit(self):
        """Add one file and examine verbose commit output"""
        self.runbzr("init")
        self.build_tree(['hello.txt'])
        self.runbzr("add hello.txt")
        out,err = self.run_bzr("commit", "-m", "added")
        self.assertEqual('', out)
        self.assertEqual('added hello.txt\n'
                         'Committed revision 1.\n',
                         err)

    def prepare_simple_history(self):
        """Prepare and return a working tree with one commit of one file"""
        # Commit with modified file should say so
        wt = BzrDir.create_standalone_workingtree('.')
        self.build_tree(['hello.txt', 'extra.txt'])
        wt.add(['hello.txt'])
        wt.commit(message='added')
        return wt

    def test_verbose_commit_modified(self):
        # Verbose commit of modified file should say so
        wt = self.prepare_simple_history()
        self.build_tree_contents([('hello.txt', 'new contents')])
        out, err = self.run_bzr("commit", "-m", "modified")
        self.assertEqual('', out)
        self.assertEqual('modified hello.txt\n'
                         'Committed revision 2.\n',
                         err)

    def test_verbose_commit_renamed(self):
        # Verbose commit of renamed file should say so
        wt = self.prepare_simple_history()
        wt.rename_one('hello.txt', 'gutentag.txt')
        out, err = self.run_bzr("commit", "-m", "renamed")
        self.assertEqual('', out)
        self.assertEqual('renamed hello.txt => gutentag.txt\n'
                         'Committed revision 2.\n',
                         err)

    def test_verbose_commit_moved(self):
        # Verbose commit of file moved to new directory should say so
        wt = self.prepare_simple_history()
        os.mkdir('subdir')
        wt.add(['subdir'])
        wt.rename_one('hello.txt', 'subdir/hello.txt')
        out, err = self.run_bzr("commit", "-m", "renamed")
        self.assertEqual('', out)
        self.assertEqualDiff('added subdir\n'
                             'renamed hello.txt => subdir/hello.txt\n'
                             'Committed revision 2.\n',
                             err)

    def test_verbose_commit_with_unknown(self):
        """Unknown files should not be listed by default in verbose output"""
        # Is that really the best policy?
        wt = BzrDir.create_standalone_workingtree('.')
        self.build_tree(['hello.txt', 'extra.txt'])
        wt.add(['hello.txt'])
        out,err = self.run_bzr("commit", "-m", "added")
        self.assertEqual('', out)
        self.assertEqual('added hello.txt\n'
                         'Committed revision 1.\n',
                         err)

    def test_verbose_commit_with_unchanged(self):
        """Unchanged files should not be listed by default in verbose output"""
        self.runbzr("init")
        self.build_tree(['hello.txt', 'unchanged.txt'])
        self.runbzr('add unchanged.txt')
        self.runbzr('commit -m unchanged unchanged.txt')
        self.runbzr("add hello.txt")
        out,err = self.run_bzr("commit", "-m", "added")
        self.assertEqual('', out)
        self.assertEqual('added hello.txt\n'
                         'Committed revision 2.\n',
                         err)

    def test_commit_merge_reports_all_modified_files(self):
        # the commit command should show all the files that are shown by
        # bzr diff or bzr status when committing, even when they were not
        # changed by the user but rather through doing a merge.
        this_tree = self.make_branch_and_tree('this')
        # we need a bunch of files and dirs, to perform one action on each.
        self.build_tree([
            'this/dirtorename/',
            'this/dirtoreparent/',
            'this/dirtoleave/',
            'this/dirtoremove/',
            'this/filetoreparent',
            'this/filetorename',
            'this/filetomodify',
            'this/filetoremove',
            'this/filetoleave']
            )
        this_tree.add([
            'dirtorename',
            'dirtoreparent',
            'dirtoleave',
            'dirtoremove',
            'filetoreparent',
            'filetorename',
            'filetomodify',
            'filetoremove',
            'filetoleave']
            )
        this_tree.commit('create_files')
        other_dir = this_tree.bzrdir.sprout('other')
        other_tree = other_dir.open_workingtree()
        other_tree.lock_write()
        # perform the needed actions on the files and dirs.
        try:
            other_tree.rename_one('dirtorename', 'renameddir')
            other_tree.rename_one('dirtoreparent', 'renameddir/reparenteddir')
            other_tree.rename_one('filetorename', 'renamedfile')
            other_tree.rename_one('filetoreparent', 'renameddir/reparentedfile')
            other_tree.remove(['dirtoremove', 'filetoremove'])
            self.build_tree_contents([
                ('other/newdir/', ),
                ('other/filetomodify', 'new content'),
                ('other/newfile', 'new file content')])
            other_tree.add('newfile')
            other_tree.add('newdir/')
            other_tree.commit('modify all sample files and dirs.')
        finally:
            other_tree.unlock()
        self.merge(other_tree.branch, this_tree)
        os.chdir('this')
        out,err = self.run_bzr("commit", "-m", "added")
        os.chdir('..')
        self.assertEqual('', out)
        self.assertEqualDiff(
            'modified filetomodify\n'
            'added newdir\n'
            'added newfile\n'
            'renamed dirtorename => renameddir\n'
            'renamed dirtoreparent => renameddir/reparenteddir\n'
            'renamed filetoreparent => renameddir/reparentedfile\n'
            'renamed filetorename => renamedfile\n'
            'deleted dirtoremove\n'
            'deleted filetoremove\n'
            'Committed revision 2.\n',
            err)

    def test_empty_commit_message(self):
        self.runbzr("init")
        file('foo.c', 'wt').write('int main() {}')
        self.runbzr(['add', 'foo.c'])
        self.runbzr(["commit", "-m", ""] , retcode=3)

    def test_other_branch_commit(self):
        # this branch is to ensure consistent behaviour, whether we're run
        # inside a branch, or not.
        os.mkdir('empty_branch')
        os.chdir('empty_branch')
        self.runbzr('init')
        os.mkdir('branch')
        os.chdir('branch')
        self.runbzr('init')
        file('foo.c', 'wt').write('int main() {}')
        file('bar.c', 'wt').write('int main() {}')
        os.chdir('..')
        self.runbzr(['add', 'branch/foo.c'])
        self.runbzr(['add', 'branch'])
        # can't commit files in different trees; sane error
        self.runbzr('commit -m newstuff branch/foo.c .', retcode=3)
        self.runbzr('commit -m newstuff branch/foo.c')
        self.runbzr('commit -m newstuff branch')
        self.runbzr('commit -m newstuff branch', retcode=3)

    def test_out_of_date_tree_commit(self):
        # check we get an error code and a clear message committing with an out
        # of date checkout
        self.make_branch_and_tree('branch')
        # make a checkout
        self.runbzr('checkout --lightweight branch checkout')
        # commit to the original branch to make the checkout out of date
        self.runbzr('commit --unchanged -m message branch')
        # now commit to the checkout should emit
        # ERROR: Out of date with the branch, 'bzr update' is suggested
        output = self.runbzr('commit --unchanged -m checkout_message '
                             'checkout', retcode=3)
        self.assertEqual(output,
                         ('',
                          "bzr: ERROR: Working tree is out of date, please run "
                          "'bzr update'.\n"))

    def test_local_commit_unbound(self):
        # a --local commit on an unbound branch is an error
        self.make_branch_and_tree('.')
        out, err = self.run_bzr('commit', '--local', retcode=3)
        self.assertEqualDiff('', out)
        self.assertEqualDiff('bzr: ERROR: Cannot perform local-only commits '
                             'on unbound branches.\n', err)

    def test_commit_a_text_merge_in_a_checkout(self):
        # checkouts perform multiple actions in a transaction across bond
        # branches and their master, and have been observed to fail in the
        # past. This is a user story reported to fail in bug #43959 where 
        # a merge done in a checkout (using the update command) failed to
        # commit correctly.
        self.run_bzr('init', 'trunk')

        self.run_bzr('checkout', 'trunk', 'u1')
        self.build_tree_contents([('u1/hosts', 'initial contents')])
        self.run_bzr('add', 'u1/hosts')
        self.run_bzr('commit', '-m', 'add hosts', 'u1')

        self.run_bzr('checkout', 'trunk', 'u2')
        self.build_tree_contents([('u2/hosts', 'altered in u2')])
        self.run_bzr('commit', '-m', 'checkin from u2', 'u2')

        # make an offline commits
        self.build_tree_contents([('u1/hosts', 'first offline change in u1')])
        self.run_bzr('commit', '-m', 'checkin offline', '--local', 'u1')

        # now try to pull in online work from u2, and then commit our offline
        # work as a merge
        # retcode 1 as we expect a text conflict
        self.run_bzr('update', 'u1', retcode=1)
        self.run_bzr('resolved', 'u1/hosts')
        # add a text change here to represent resolving the merge conflicts in
        # favour of a new version of the file not identical to either the u1
        # version or the u2 version.
        self.build_tree_contents([('u1/hosts', 'merge resolution\n')])
        self.run_bzr('commit', '-m', 'checkin merge of the offline work from u1', 'u1')

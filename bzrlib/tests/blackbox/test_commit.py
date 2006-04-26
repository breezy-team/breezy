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
        self.assertEqual('renamed gutentag.txt\n'
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
                             'renamed subdir/hello.txt\n'
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

    def test_16_verbose_commit_with_unchanged(self):
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

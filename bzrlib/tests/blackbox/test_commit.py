# Copyright (C) 2005, 2006 by Canonical Ltd
# -*- coding: utf-8 -*-

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

from cStringIO import StringIO
import os
import re
import shutil
import sys

from bzrlib.branch import Branch
import bzrlib.bzrdir as bzrdir
from bzrlib.errors import BzrCommandError
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree


class TestCommit(ExternalBase):

    def test_empty_commit(self):
        self.runbzr("init")
        self.build_tree(['hello.txt'])
        self.runbzr("commit -m empty", retcode=3)
        self.runbzr("add hello.txt")
        self.runbzr("commit -m added")       

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
        self.runbzr('checkout branch checkout')
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

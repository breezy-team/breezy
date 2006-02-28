# Copyright (C) 2005 by Canonical Ltd
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


"""Black-box tests for bzr diff.
"""

import os

import bzrlib
from bzrlib.branch import Branch
from bzrlib.tests.blackbox import ExternalBase


class TestDiff(ExternalBase):
    def example_branch(test):
        # FIXME: copied from test_too_much -- share elsewhere?
        test.runbzr('init')
        file('hello', 'wt').write('foo')
        test.runbzr('add hello')
        test.runbzr('commit -m setup hello')
        file('goodbye', 'wt').write('baz')
        test.runbzr('add goodbye')
        test.runbzr('commit -m setup goodbye')

    def test_diff(self):
        self.example_branch()
        file('hello', 'wt').write('hello world!')
        self.runbzr('commit -m fixing hello')
        output = self.runbzr('diff -r 2..3', backtick=1, retcode=1)
        self.assert_('\n+hello world!' in output)
        output = self.runbzr('diff -r last:3..last:1', backtick=1, retcode=1)
        self.assert_('\n+baz' in output)
        file('moo', 'wb').write('moo')
        self.runbzr('add moo')
        os.unlink('moo')
        self.runbzr('diff')

    def example_branches(self):
        self.build_tree(['branch1/', 'branch1/file'], line_endings='binary')
        self.capture('init branch1')
        self.capture('add branch1/file')
        self.run_bzr_captured(['commit', '-m', 'add file', 'branch1'])
        self.capture('branch branch1 branch2')
        print >> open('branch2/file', 'wb'), 'new content'
        self.run_bzr_captured(['commit', '-m', 'update file', 'branch2'])

    def test_diff_branches(self):
        self.example_branches()
        # should open branch1 and diff against branch2, 
        output = self.run_bzr_captured(['diff', '-r', 'branch:branch2', 
                                        'branch1'],
                                       retcode=1)
        self.assertEquals(("=== modified file 'file'\n"
                           "--- file\t\n"
                           "+++ file\t\n"
                           "@@ -1,1 +1,1 @@\n"
                           "-new content\n"
                           "+contents of branch1/file\n"
                           "\n", ''), output)
        output = self.run_bzr_captured(['diff', 'branch2', 'branch1'],
                                       retcode=1)
        self.assertEqualDiff(("=== modified file 'file'\n"
                              "--- file\t\n"
                              "+++ file\t\n"
                              "@@ -1,1 +1,1 @@\n"
                              "-new content\n"
                              "+contents of branch1/file\n"
                              "\n", ''), output)

    def example_branch2(self):
        self.build_tree(['branch1/', 'branch1/file1'], line_endings='binary')
        self.capture('init branch1')
        self.capture('add branch1/file1')
        print >> open('branch1/file1', 'wb'), 'original line'
        self.run_bzr_captured(['commit', '-m', 'first commit', 'branch1'])
        
        print >> open('branch1/file1', 'wb'), 'repo line'
        self.run_bzr_captured(['commit', '-m', 'second commit', 'branch1'])

    def test_diff_to_working_tree(self):
        self.example_branch2()
        
        print >> open('branch1/file1', 'wb'), 'new line'
        output = self.run_bzr_captured(['diff', '-r', '1..', 'branch1'], retcode=1)
        self.assertTrue('\n-original line\n+new line\n' in output[0])


class TestCheckoutDiff(TestDiff):

    def example_branch(self):
        super(TestCheckoutDiff, self).example_branch()
        self.runbzr('checkout . checkout')
        os.chdir('checkout')

    def example_branch2(self):
        super(TestCheckoutDiff, self).example_branch2()
        os.mkdir('checkouts')
        self.runbzr('checkout branch1 checkouts/branch1')
        os.chdir('checkouts')

    def example_branches(self):
        super(TestCheckoutDiff, self).example_branches()
        os.mkdir('checkouts')
        self.runbzr('checkout branch1 checkouts/branch1')
        self.runbzr('checkout branch2 checkouts/branch2')
        os.chdir('checkouts')

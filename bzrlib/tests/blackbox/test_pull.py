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


"""Black-box tests for bzr pull.
"""

import os
import sys

from bzrlib.branch import Branch
from bzrlib.tests.blackbox import ExternalBase

class TestPull(ExternalBase):

    def example_branch(test):
        test.runbzr('init')
        file('hello', 'wt').write('foo')
        test.runbzr('add hello')
        test.runbzr('commit -m setup hello')
        file('goodbye', 'wt').write('baz')
        test.runbzr('add goodbye')
        test.runbzr('commit -m setup goodbye')

    def test_pull(self):
        """Pull changes from one branch to another."""
        os.mkdir('a')
        os.chdir('a')

        self.example_branch()
        self.runbzr('pull', retcode=3)
        self.runbzr('missing', retcode=3)
        self.runbzr('missing .')
        self.runbzr('missing')
        if sys.platform not in ('win32', 'cygwin'):
            # This is equivalent to doing "bzr pull ."
            # Which means that bzr creates 2 branches grabbing
            # the same location, and tries to pull.
            # However, 2 branches mean 2 locks on the same file
            # which ultimately implies a deadlock.
            # (non windows platforms allow multiple locks on the
            # same file by the same calling process)
            self.runbzr('pull')
        self.runbzr('pull /', retcode=3)
        if sys.platform not in ('win32', 'cygwin'):
            self.runbzr('pull')

        os.chdir('..')
        self.runbzr('branch a b')
        os.chdir('b')
        self.runbzr('pull')
        os.mkdir('subdir')
        self.runbzr('add subdir')
        self.runbzr('commit -m blah --unchanged')
        os.chdir('../a')
        a = Branch.open('.')
        b = Branch.open('../b')
        self.assertEquals(a.revision_history(), b.revision_history()[:-1])
        self.runbzr('pull ../b')
        self.assertEquals(a.revision_history(), b.revision_history())
        self.runbzr('commit -m blah2 --unchanged')
        os.chdir('../b')
        self.runbzr('commit -m blah3 --unchanged')
        # no overwrite
        self.runbzr('pull ../a', retcode=3)
        os.chdir('..')
        self.runbzr('branch b overwriteme')
        os.chdir('overwriteme')
        self.runbzr('pull --overwrite ../a')
        overwritten = Branch.open('.')
        self.assertEqual(overwritten.revision_history(),
                         a.revision_history())
        os.chdir('../a')
        self.runbzr('merge ../b')
        self.runbzr('commit -m blah4 --unchanged')
        os.chdir('../b/subdir')
        self.runbzr('pull ../../a')
        self.assertEquals(a.revision_history()[-1], b.revision_history()[-1])
        self.runbzr('commit -m blah5 --unchanged')
        self.runbzr('commit -m blah6 --unchanged')
        os.chdir('..')
        self.runbzr('pull ../a')
        os.chdir('../a')
        self.runbzr('commit -m blah7 --unchanged')
        self.runbzr('merge ../b')
        self.runbzr('commit -m blah8 --unchanged')
        self.runbzr('pull ../b')
        self.runbzr('pull ../b')

    def test_pull_revision(self):
        """Pull some changes from one branch to another."""
        os.mkdir('a')
        os.chdir('a')

        self.example_branch()
        file('hello2', 'wt').write('foo')
        self.runbzr('add hello2')
        self.runbzr('commit -m setup hello2')
        file('goodbye2', 'wt').write('baz')
        self.runbzr('add goodbye2')
        self.runbzr('commit -m setup goodbye2')

        os.chdir('..')
        self.runbzr('branch -r 1 a b')
        os.chdir('b')
        self.runbzr('pull -r 2')
        a = Branch.open('../a')
        b = Branch.open('.')
        self.assertEquals(a.revno(),4)
        self.assertEquals(b.revno(),2)
        self.runbzr('pull -r 3')
        self.assertEquals(b.revno(),3)
        self.runbzr('pull -r 4')
        self.assertEquals(a.revision_history(), b.revision_history())


    def test_overwrite_uptodate(self):
        # Make sure pull --overwrite overwrites
        # even if the target branch has merged
        # everything already.
        bzr = self.run_bzr

        def get_rh(expected_len):
            rh = self.capture('revision-history')
            # Make sure we don't have trailing empty revisions
            rh = rh.strip().split('\n')
            self.assertEqual(len(rh), expected_len)
            return rh

        os.mkdir('a')
        os.chdir('a')
        bzr('init')
        open('foo', 'wb').write('original\n')
        bzr('add', 'foo')
        bzr('commit', '-m', 'initial commit')

        os.chdir('..')
        bzr('branch', 'a', 'b')

        os.chdir('a')
        open('foo', 'wb').write('changed\n')
        bzr('commit', '-m', 'later change')

        open('foo', 'wb').write('another\n')
        bzr('commit', '-m', 'a third change')

        rev_history_a = get_rh(3)

        os.chdir('../b')
        bzr('merge', '../a')
        bzr('commit', '-m', 'merge')

        rev_history_b = get_rh(2)

        bzr('pull', '--overwrite', '../a')
        rev_history_b = get_rh(3)

        self.assertEqual(rev_history_b, rev_history_a)

    def test_overwrite_children(self):
        # Make sure pull --overwrite sets the revision-history
        # to be identical to the pull source, even if we have convergence
        bzr = self.run_bzr

        def get_rh(expected_len):
            rh = self.capture('revision-history')
            # Make sure we don't have trailing empty revisions
            rh = rh.strip().split('\n')
            self.assertEqual(len(rh), expected_len)
            return rh

        os.mkdir('a')
        os.chdir('a')
        bzr('init')
        open('foo', 'wb').write('original\n')
        bzr('add', 'foo')
        bzr('commit', '-m', 'initial commit')

        os.chdir('..')
        bzr('branch', 'a', 'b')

        os.chdir('a')
        open('foo', 'wb').write('changed\n')
        bzr('commit', '-m', 'later change')

        open('foo', 'wb').write('another\n')
        bzr('commit', '-m', 'a third change')

        rev_history_a = get_rh(3)

        os.chdir('../b')
        bzr('merge', '../a')
        bzr('commit', '-m', 'merge')

        rev_history_b = get_rh(2)

        os.chdir('../a')
        open('foo', 'wb').write('a fourth change\n')
        bzr('commit', '-m', 'a fourth change')

        rev_history_a = get_rh(4)

        # With convergence, we could just pull over the
        # new change, but with --overwrite, we want to switch our history
        os.chdir('../b')
        bzr('pull', '--overwrite', '../a')
        rev_history_b = get_rh(4)

        self.assertEqual(rev_history_b, rev_history_a)



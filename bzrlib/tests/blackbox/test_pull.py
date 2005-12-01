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


"""Black-box tests for bzr.

These check that it behaves properly when it's invoked through the regular
command-line interface. This doesn't actually run a new interpreter but 
rather starts again from the run_bzr function.
"""


# XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
# Note: Please don't add new tests here, it's too big and bulky.  Instead add
# them into small suites in bzrlib.tests.blackbox.test_FOO for the particular
# UI command/aspect that is being tested.


from cStringIO import StringIO
import os
import re
import shutil
import sys

from bzrlib.branch import Branch
from bzrlib.clone import copy_branch
from bzrlib.errors import BzrCommandError
from bzrlib.osutils import has_symlinks
from bzrlib.tests.HTTPTestUtil import TestCaseWithWebserver
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
        self.runbzr('pull')
        self.runbzr('pull /', retcode=3)
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



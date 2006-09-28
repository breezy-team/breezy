# Copyright (C) 2005 by Canonical Ltd
# -*- coding: utf-8 -*-
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


"""Black-box tests for bzr pull."""

import os
import sys

from bzrlib.branch import Branch
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.uncommit import uncommit


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
        # this will work on windows because we check for the same branch
        # in pull - if it fails, it is a regression
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

    def test_pull_remember(self):
        """Pull changes from one branch to another and test parent location."""
        transport = self.get_transport()
        tree_a = self.make_branch_and_tree('branch_a')
        branch_a = tree_a.branch
        self.build_tree(['branch_a/a'])
        tree_a.add('a')
        tree_a.commit('commit a')
        tree_b = branch_a.bzrdir.sprout('branch_b').open_workingtree()
        branch_b = tree_b.branch
        tree_c = branch_a.bzrdir.sprout('branch_c').open_workingtree()
        branch_c = tree_c.branch
        self.build_tree(['branch_a/b'])
        tree_a.add('b')
        tree_a.commit('commit b')
        # reset parent
        parent = branch_b.get_parent()
        branch_b.set_parent(None)
        self.assertEqual(None, branch_b.get_parent())
        # test pull for failure without parent set
        os.chdir('branch_b')
        out = self.runbzr('pull', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: No pull location known or specified.\n'))
        # test implicit --remember when no parent set, this pull conflicts
        self.build_tree(['d'])
        tree_b.add('d')
        tree_b.commit('commit d')
        out = self.runbzr('pull ../branch_a', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: These branches have diverged.  Use the merge command to reconcile them.\n'))
        self.assertEquals(branch_b.get_parent(), parent)
        # test implicit --remember after resolving previous failure
        uncommit(branch=branch_b, tree=tree_b)
        transport.delete('branch_b/d')
        self.runbzr('pull')
        self.assertEquals(branch_b.get_parent(), parent)
        # test explicit --remember
        self.runbzr('pull ../branch_c --remember')
        self.assertEquals(branch_b.get_parent(),
                          branch_c.bzrdir.root_transport.base)

    def test_pull_bundle(self):
        from bzrlib.testament import Testament
        # Build up 2 trees and prepare for a pull
        tree_a = self.make_branch_and_tree('branch_a')
        f = open('branch_a/a', 'wb')
        f.write('hello')
        f.close()
        tree_a.add('a')
        tree_a.commit('message')

        tree_b = tree_a.bzrdir.sprout('branch_b').open_workingtree()

        # Make a change to 'a' that 'b' can pull
        f = open('branch_a/a', 'wb')
        f.write('hey there')
        f.close()
        tree_a.commit('message')

        # Create the bundle for 'b' to pull
        os.chdir('branch_a')
        bundle_file = open('../bundle', 'wb')
        bundle_file.write(self.run_bzr('bundle', '../branch_b')[0])
        bundle_file.close()

        os.chdir('../branch_b')
        output = self.run_bzr('pull', '../bundle')
        self.assertEqual('', output[0])
        self.assertEqual('All changes applied successfully.\n'
                         '1 revision(s) pulled.\n', output[1])

        self.assertEqualDiff(tree_a.branch.revision_history(),
                             tree_b.branch.revision_history())

        testament_a = Testament.from_revision(tree_a.branch.repository,
                                              tree_a.get_parent_ids()[0])
        testament_b = Testament.from_revision(tree_b.branch.repository,
                                              tree_b.get_parent_ids()[0])
        self.assertEqualDiff(testament_a.as_text(),
                             testament_b.as_text())

        # it is legal to attempt to pull an already-merged bundle
        output = self.run_bzr('pull', '../bundle')
        self.assertEqual('', output[0])
        self.assertEqual('0 revision(s) pulled.\n', output[1])

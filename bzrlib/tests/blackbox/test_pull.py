# Copyright (C) 2005, 2006 Canonical Ltd
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
from bzrlib.osutils import pathjoin
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.uncommit import uncommit
from bzrlib.workingtree import WorkingTree
from bzrlib import urlutils


class TestPull(ExternalBase):

    def example_branch(self, path='.'):
        tree = self.make_branch_and_tree(path)
        self.build_tree_contents([
            (pathjoin(path, 'hello'),   'foo'),
            (pathjoin(path, 'goodbye'), 'baz')])
        tree.add('hello')
        tree.commit(message='setup')
        tree.add('goodbye')
        tree.commit(message='setup')
        return tree

    def test_pull(self):
        """Pull changes from one branch to another."""
        a_tree = self.example_branch('a')
        os.chdir('a')
        self.run_bzr('pull', retcode=3)
        self.run_bzr('missing', retcode=3)
        self.run_bzr('missing .')
        self.run_bzr('missing')
        # this will work on windows because we check for the same branch
        # in pull - if it fails, it is a regression
        self.run_bzr('pull')
        self.run_bzr('pull /', retcode=3)
        if sys.platform not in ('win32', 'cygwin'):
            self.run_bzr('pull')

        os.chdir('..')
        b_tree = a_tree.bzrdir.sprout('b').open_workingtree()
        os.chdir('b')
        self.run_bzr('pull')
        os.mkdir('subdir')
        b_tree.add('subdir')
        b_tree.commit(message='blah', allow_pointless=True)

        os.chdir('..')
        a = Branch.open('a')
        b = Branch.open('b')
        self.assertEqual(a.revision_history(), b.revision_history()[:-1])

        os.chdir('a')
        self.run_bzr('pull ../b')
        self.assertEqual(a.revision_history(), b.revision_history())
        a_tree.commit(message='blah2', allow_pointless=True)
        b_tree.commit(message='blah3', allow_pointless=True)
        # no overwrite
        os.chdir('../b')
        self.run_bzr('pull ../a', retcode=3)
        os.chdir('..')
        b_tree.bzrdir.sprout('overwriteme')
        os.chdir('overwriteme')
        self.run_bzr('pull --overwrite ../a')
        overwritten = Branch.open('.')
        self.assertEqual(overwritten.revision_history(),
                         a.revision_history())
        os.chdir('../a')
        self.run_bzr('merge ../b')
        a_tree.commit(message="blah4", allow_pointless=True)
        os.chdir('../b/subdir')
        self.run_bzr('pull ../../a')
        self.assertEqual(a.revision_history()[-1], b.revision_history()[-1])
        sub_tree = WorkingTree.open_containing('.')[0]
        sub_tree.commit(message="blah5", allow_pointless=True)
        sub_tree.commit(message="blah6", allow_pointless=True)
        os.chdir('..')
        self.run_bzr('pull ../a')
        os.chdir('../a')
        a_tree.commit(message="blah7", allow_pointless=True)
        a_tree.merge_from_branch(b_tree.branch)
        a_tree.commit(message="blah8", allow_pointless=True)
        self.run_bzr('pull ../b')
        self.run_bzr('pull ../b')

    def test_pull_dash_d(self):
        self.example_branch('a')
        self.make_branch_and_tree('b')
        self.make_branch_and_tree('c')
        # pull into that branch
        self.run_bzr('pull -d b a')
        # pull into a branch specified by a url
        c_url = urlutils.local_path_to_url('c')
        self.assertStartsWith(c_url, 'file://')
        self.run_bzr(['pull', '-d', c_url, 'a'])

    def test_pull_revision(self):
        """Pull some changes from one branch to another."""
        a_tree = self.example_branch('a')
        self.build_tree_contents([
            ('a/hello2',   'foo'),
            ('a/goodbye2', 'baz')])
        a_tree.add('hello2')
        a_tree.commit(message="setup")
        a_tree.add('goodbye2')
        a_tree.commit(message="setup")

        b_tree = a_tree.bzrdir.sprout('b',
                   revision_id=a_tree.branch.get_rev_id(1)).open_workingtree()
        os.chdir('b')
        self.run_bzr('pull -r 2')
        a = Branch.open('../a')
        b = Branch.open('.')
        self.assertEqual(a.revno(),4)
        self.assertEqual(b.revno(),2)
        self.run_bzr('pull -r 3')
        self.assertEqual(b.revno(),3)
        self.run_bzr('pull -r 4')
        self.assertEqual(a.revision_history(), b.revision_history())


    def test_overwrite_uptodate(self):
        # Make sure pull --overwrite overwrites
        # even if the target branch has merged
        # everything already.
        a_tree = self.make_branch_and_tree('a')
        self.build_tree_contents([('a/foo', 'original\n')])
        a_tree.add('foo')
        a_tree.commit(message='initial commit')

        b_tree = a_tree.bzrdir.sprout('b').open_workingtree()

        self.build_tree_contents([('a/foo', 'changed\n')])
        a_tree.commit(message='later change')

        self.build_tree_contents([('a/foo', 'a third change')])
        a_tree.commit(message='a third change')

        rev_history_a = a_tree.branch.revision_history()
        self.assertEqual(len(rev_history_a), 3)

        b_tree.merge_from_branch(a_tree.branch)
        b_tree.commit(message='merge')

        self.assertEqual(len(b_tree.branch.revision_history()), 2)

        os.chdir('b')
        self.run_bzr('pull --overwrite ../a')
        rev_history_b = b_tree.branch.revision_history()
        self.assertEqual(len(rev_history_b), 3)

        self.assertEqual(rev_history_b, rev_history_a)

    def test_overwrite_children(self):
        # Make sure pull --overwrite sets the revision-history
        # to be identical to the pull source, even if we have convergence
        a_tree = self.make_branch_and_tree('a')
        self.build_tree_contents([('a/foo', 'original\n')])
        a_tree.add('foo')
        a_tree.commit(message='initial commit')

        b_tree = a_tree.bzrdir.sprout('b').open_workingtree()

        self.build_tree_contents([('a/foo', 'changed\n')])
        a_tree.commit(message='later change')

        self.build_tree_contents([('a/foo', 'a third change')])
        a_tree.commit(message='a third change')

        self.assertEqual(len(a_tree.branch.revision_history()), 3)

        b_tree.merge_from_branch(a_tree.branch)
        b_tree.commit(message='merge')

        self.assertEqual(len(b_tree.branch.revision_history()), 2)

        self.build_tree_contents([('a/foo', 'a fourth change\n')])
        a_tree.commit(message='a fourth change')

        rev_history_a = a_tree.branch.revision_history()
        self.assertEqual(len(rev_history_a), 4)

        # With convergence, we could just pull over the
        # new change, but with --overwrite, we want to switch our history
        os.chdir('b')
        self.run_bzr('pull --overwrite ../a')
        rev_history_b = b_tree.branch.revision_history()
        self.assertEqual(len(rev_history_b), 4)

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
        out = self.run_bzr('pull', retcode=3)
        self.assertEqual(out,
                ('','bzr: ERROR: No pull location known or specified.\n'))
        # test implicit --remember when no parent set, this pull conflicts
        self.build_tree(['d'])
        tree_b.add('d')
        tree_b.commit('commit d')
        out = self.run_bzr('pull ../branch_a', retcode=3)
        self.assertEqual(out,
                ('','bzr: ERROR: These branches have diverged.'
                    ' Use the merge command to reconcile them.\n'))
        self.assertEqual(branch_b.get_parent(), parent)
        # test implicit --remember after resolving previous failure
        uncommit(branch=branch_b, tree=tree_b)
        transport.delete('branch_b/d')
        self.run_bzr('pull')
        self.assertEqual(branch_b.get_parent(), parent)
        # test explicit --remember
        self.run_bzr('pull ../branch_c --remember')
        self.assertEqual(branch_b.get_parent(),
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
        self.run_bzr('bundle ../branch_b -o ../bundle')

        os.chdir('../branch_b')
        out, err = self.run_bzr('pull ../bundle')
        self.assertEqual(out,
                         'Now on revision 2.\n')
        self.assertEqual(err,
                ' M  a\nAll changes applied successfully.\n')

        self.assertEqualDiff(tree_a.branch.revision_history(),
                             tree_b.branch.revision_history())

        testament_a = Testament.from_revision(tree_a.branch.repository,
                                              tree_a.get_parent_ids()[0])
        testament_b = Testament.from_revision(tree_b.branch.repository,
                                              tree_b.get_parent_ids()[0])
        self.assertEqualDiff(testament_a.as_text(),
                             testament_b.as_text())

        # it is legal to attempt to pull an already-merged bundle
        out, err = self.run_bzr('pull ../bundle')
        self.assertEqual(err, '')
        self.assertEqual(out, 'No revisions to pull.\n')

    def test_pull_verbose_no_files(self):
        """Pull --verbose should not list modified files"""
        tree_a = self.make_branch_and_tree('tree_a')
        self.build_tree(['tree_a/foo'])
        tree_a.add('foo')
        tree_a.commit('bar')
        tree_b = self.make_branch_and_tree('tree_b')
        out = self.run_bzr('pull --verbose -d tree_b tree_a')[0]
        self.assertContainsRe(out, 'bar')
        self.assertNotContainsRe(out, 'added:')
        self.assertNotContainsRe(out, 'foo')

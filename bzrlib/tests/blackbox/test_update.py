# Copyright (C) 2006 by Canonical Ltd
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


"""Tests for the update command of bzr."""

import os

from bzrlib import branch, bzrdir
from bzrlib.tests import TestSkipped
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree


class TestUpdate(ExternalBase):

    def test_update_standalone_trivial(self):
        self.runbzr("init")
        out, err = self.runbzr('update')
        self.assertEqual('Tree is up to date at revision 0.\n', err)
        self.assertEqual('', out)

    def test_update_standalone_trivial_with_alias_up(self):
        self.runbzr("init")
        out, err = self.runbzr('up')
        self.assertEqual('Tree is up to date at revision 0.\n', err)
        self.assertEqual('', out)

    def test_update_up_to_date_light_checkout(self):
        self.make_branch_and_tree('branch')
        self.runbzr('checkout --lightweight branch checkout')
        out, err = self.runbzr('update checkout')
        self.assertEqual('Tree is up to date at revision 0.\n', err)
        self.assertEqual('', out)

    def test_update_up_to_date_checkout(self):
        self.make_branch_and_tree('branch')
        self.run_bzr('checkout', 'branch', 'checkout')
        out, err = self.run_bzr('update', 'checkout')
        self.assertEqual('Tree is up to date at revision 0.\n', err)
        self.assertEqual('', out)

    def test_update_out_of_date_standalone_tree(self):
        # FIXME the default format has to change for this to pass
        # because it currently uses the branch last-revision marker.
        self.make_branch_and_tree('branch')
        # make a checkout
        self.runbzr('checkout --lightweight branch checkout')
        self.build_tree(['checkout/file'])
        self.runbzr('add checkout/file')
        self.runbzr('commit -m add-file checkout')
        # now branch should be out of date
        out,err = self.runbzr('update branch')
        self.assertEqual('', out)
        self.assertEqual('All changes applied successfully.\n'
                         'Updated to revision 1.\n', err)
        self.failUnlessExists('branch/file')

    def test_update_out_of_date_light_checkout(self):
        self.make_branch_and_tree('branch')
        # make two checkouts
        self.runbzr('checkout --lightweight branch checkout')
        self.runbzr('checkout --lightweight branch checkout2')
        self.build_tree(['checkout/file'])
        self.runbzr('add checkout/file')
        self.runbzr('commit -m add-file checkout')
        # now checkout2 should be out of date
        out,err = self.runbzr('update checkout2')
        self.assertEqual('All changes applied successfully.\n'
                         'Updated to revision 1.\n',
                         err)
        self.assertEqual('', out)

    def test_update_conflicts_returns_2(self):
        self.make_branch_and_tree('branch')
        # make two checkouts
        self.runbzr('checkout --lightweight branch checkout')
        self.build_tree(['checkout/file'])
        self.runbzr('add checkout/file')
        self.runbzr('commit -m add-file checkout')
        self.runbzr('checkout --lightweight branch checkout2')
        # now alter file in checkout
        a_file = file('checkout/file', 'wt')
        a_file.write('Foo')
        a_file.close()
        self.runbzr('commit -m checnge-file checkout')
        # now checkout2 should be out of date
        # make a local change to file
        a_file = file('checkout2/file', 'wt')
        a_file.write('Bar')
        a_file.close()
        out,err = self.runbzr('update checkout2', retcode=1)
        self.assertEqual(['1 conflicts encountered.',
                          'Updated to revision 2.'],
                         err.split('\n')[1:3])
        self.assertContainsRe(err, 'Text conflict in file\n')
        self.assertEqual('', out)

    def test_smoke_update_checkout_bound_branch_local_commits(self):
        # smoke test for doing an update of a checkout of a bound
        # branch with local commits.
        master = self.make_branch_and_tree('master')
        # make a bound branch
        self.run_bzr('checkout', 'master', 'child')
        # get an object form of child
        child = WorkingTree.open('child')
        # check that out
        self.run_bzr('checkout', '--lightweight', 'child', 'checkout')
        # get an object form of the checkout to manipulate
        wt = WorkingTree.open('checkout')
        # change master
        a_file = file('master/file', 'wt')
        a_file.write('Foo')
        a_file.close()
        master.add(['file'])
        master_tip = master.commit('add file')
        # change child
        a_file = file('child/file_b', 'wt')
        a_file.write('Foo')
        a_file.close()
        child.add(['file_b'])
        child_tip = child.commit('add file_b', local=True)
        # check checkout
        a_file = file('checkout/file_c', 'wt')
        a_file.write('Foo')
        a_file.close()
        wt.add(['file_c'])

        # now, update checkout ->
        # get all three files and a pending merge.
        out, err = self.run_bzr('update', 'checkout')
        self.assertEqual('', out)
        self.assertContainsRe(err, 'Updated to revision 1.\n'
                                   'Your local commits will now show as'
                                   ' pending merges')
        self.assertEqual([master_tip, child_tip], wt.get_parent_ids())
        self.failUnlessExists('checkout/file')
        self.failUnlessExists('checkout/file_b')
        self.failUnlessExists('checkout/file_c')
        self.assertTrue(wt.has_filename('file_c'))

    def test_update_with_merges(self):
        # Test that 'bzr update' works correctly when you have
        # an update in the master tree, and a lightweight checkout
        # which has merged another branch
        master = self.make_branch_and_tree('master')
        self.build_tree(['master/file'])
        master.add(['file'])
        master.commit('one', rev_id='m1')

        self.build_tree(['checkout1/'])
        checkout_dir = bzrdir.BzrDirMetaFormat1().initialize('checkout1')
        branch.BranchReferenceFormat().initialize(checkout_dir, master.branch)
        checkout1 = checkout_dir.create_workingtree('m1')

        # Create a second branch, with an extra commit
        other = master.bzrdir.sprout('other').open_workingtree()
        self.build_tree(['other/file2'])
        other.add(['file2'])
        other.commit('other2', rev_id='o2')

        # Create a new commit in the master branch
        self.build_tree(['master/file3'])
        master.add(['file3'])
        master.commit('f3', rev_id='m2')

        # Merge the other branch into checkout
        os.chdir('checkout1')
        self.run_bzr('merge', '../other')

        self.assertEqual(['o2'], checkout1.get_parent_ids()[1:])

        # At this point, 'commit' should fail, because we are out of date
        self.run_bzr_error(["please run 'bzr update'"],
                           'commit', '-m', 'merged')

        # This should not report about local commits being pending
        # merges, because they were real merges
        out, err = self.run_bzr('update')
        self.assertEqual('', out)
        self.assertEqual('All changes applied successfully.\n'
                         'Updated to revision 2.\n', err)

        # The pending merges should still be there
        self.assertEqual(['o2'], checkout1.get_parent_ids()[1:])

    def test_update_dash_r(self):
        # Test that 'bzr update' works correctly when you have
        # an update in the master tree, and a lightweight checkout
        # which has merged another branch
        master = self.make_branch_and_tree('master')
        os.chdir('master')
        self.build_tree(['./file1'])
        master.add(['file1'])
        master.commit('one', rev_id='m1')
        self.build_tree(['./file2'])
        master.add(['file2'])
        master.commit('two', rev_id='m2')
        
        out, err = self.run_bzr('update', '-r', '1')
        self.assertEqual('', out)
        self.assertEqual('All changes applied successfully.\n'
                         'Updated to revision 1.\n', err)
        self.failUnlessExists('./file1')
        self.failIfExists('./file2')
        self.check_file_contents('.bzr/checkout/last-revision',
                                 'm1')

    def test_update_dash_r_outside_history(self):
        # Test that 'bzr update' works correctly when you have
        # an update in the master tree, and a lightweight checkout
        # which has merged another branch
        master = self.make_branch_and_tree('master')
        self.build_tree(['master/file1'])
        master.add(['file1'])
        master.commit('one', rev_id='m1')

        # Create a second branch, with an extra commit
        other = master.bzrdir.sprout('other').open_workingtree()
        self.build_tree(['other/file2'])
        other.add(['file2'])
        other.commit('other2', rev_id='o2')

        os.chdir('master')
        self.run_bzr('merge', '../other')
        master.commit('merge', rev_id='merge')

        out, err = self.run_bzr('update', '-r', 'revid:o2',
                                retcode=3)
        self.assertEqual('', out)
        self.assertEqual('bzr: ERROR: branch has no revision o2\n'
                         'bzr update --revision works only'
                         ' for a revision in the branch history\n',
                         err)

    def test_update_dash_r_in_master(self):
        # Test that 'bzr update' works correctly when you have
        # an update in the master tree,
        master = self.make_branch_and_tree('master')
        self.build_tree(['master/file1'])
        master.add(['file1'])
        master.commit('one', rev_id='m1')

        self.run_bzr('checkout', 'master', 'checkout')

        # add a revision in the master.
        self.build_tree(['master/file2'])
        master.add(['file2'])
        master.commit('two', rev_id='m2')

        os.chdir('checkout')
        out, err = self.run_bzr('update', '-r', 'revid:m2')
        self.assertEqual('', out)
        self.assertEqual('All changes applied successfully.\n'
                         'Updated to revision 2.\n', err)

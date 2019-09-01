# Copyright (C) 2007-2012, 2016 Canonical Ltd
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

from breezy import (
    controldir,
    errors,
    tests,
    workingtree,
    )
from breezy.tests.script import TestCaseWithTransportAndScript


class TestReconfigure(TestCaseWithTransportAndScript):

    def test_no_type(self):
        branch = self.make_branch('branch')
        self.run_bzr_error(['No target configuration specified'],
                           'reconfigure branch')

    def test_branch_to_tree(self):
        branch = self.make_branch('branch')
        self.run_bzr('reconfigure --tree branch')
        tree = workingtree.WorkingTree.open('branch')

    def test_tree_to_branch(self):
        tree = self.make_branch_and_tree('tree')
        self.run_bzr('reconfigure --branch tree')
        self.assertRaises(errors.NoWorkingTree,
                          workingtree.WorkingTree.open, 'tree')

    def test_branch_to_specified_checkout(self):
        branch = self.make_branch('branch')
        parent = self.make_branch('parent')
        self.run_bzr('reconfigure branch --checkout --bind-to parent')

    def test_force(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        tree.add('file')
        self.run_bzr_error(['Working tree ".*" has uncommitted changes'],
                           'reconfigure --branch tree')
        self.run_bzr('reconfigure --force --branch tree')

    def test_lightweight_checkout_to_checkout(self):
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('checkout', lightweight=True)
        self.run_bzr('reconfigure --checkout checkout')

    def test_lightweight_checkout_to_tree(self):
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('checkout', lightweight=True)
        self.run_bzr('reconfigure --tree checkout')

    def test_no_args(self):
        branch = self.make_branch('branch')
        self.run_bzr_error(['No target configuration specified'],
                           'reconfigure', working_dir='branch')

    def test_checkout_to_lightweight_checkout(self):
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('checkout')
        self.run_bzr('reconfigure --lightweight-checkout checkout')

    def test_standalone_to_use_shared(self):
        self.build_tree(['repo/'])
        tree = self.make_branch_and_tree('repo/tree')
        repo = self.make_repository('repo', shared=True)
        self.run_bzr('reconfigure --use-shared', working_dir='repo/tree')
        tree = workingtree.WorkingTree.open('repo/tree')
        self.assertNotEqual(tree.controldir.root_transport.base,
                            tree.branch.repository.controldir.root_transport.base)

    def test_use_shared_to_standalone(self):
        repo = self.make_repository('repo', shared=True)
        branch = controldir.ControlDir.create_branch_convenience('repo/tree')
        self.assertNotEqual(branch.controldir.root_transport.base,
                            branch.repository.controldir.root_transport.base)
        self.run_bzr('reconfigure --standalone', working_dir='repo/tree')
        tree = workingtree.WorkingTree.open('repo/tree')
        self.assertEqual(tree.controldir.root_transport.base,
                         tree.branch.repository.controldir.root_transport.base)

    def test_make_with_trees(self):
        repo = self.make_repository('repo', shared=True)
        repo.set_make_working_trees(False)
        self.run_bzr('reconfigure --with-trees', working_dir='repo')
        self.assertIs(True, repo.make_working_trees())

    def test_make_with_trees_already_trees(self):
        repo = self.make_repository('repo', shared=True)
        repo.set_make_working_trees(True)
        self.run_bzr_error([" already creates working trees"],
                           'reconfigure --with-trees repo')

    def test_make_without_trees(self):
        repo = self.make_repository('repo', shared=True)
        repo.set_make_working_trees(True)
        self.run_bzr('reconfigure --with-no-trees', working_dir='repo')
        self.assertIs(False, repo.make_working_trees())

    def test_make_without_trees_already_no_trees(self):
        repo = self.make_repository('repo', shared=True)
        repo.set_make_working_trees(False)
        self.run_bzr_error([" already doesn't create working trees"],
                           'reconfigure --with-no-trees repo')

    def test_make_with_trees_nonshared_repo(self):
        branch = self.make_branch('branch')
        self.run_bzr_error(
            ["Requested reconfiguration of '.*' is not supported"],
            'reconfigure --with-trees branch')

    def test_make_without_trees_leaves_tree_alone(self):
        repo = self.make_repository('repo', shared=True)
        branch = controldir.ControlDir.create_branch_convenience('repo/branch')
        tree = workingtree.WorkingTree.open('repo/branch')
        self.build_tree(['repo/branch/foo'])
        tree.add('foo')
        self.run_bzr('reconfigure --with-no-trees --force',
                     working_dir='repo/branch')
        self.assertPathExists('repo/branch/foo')
        tree = workingtree.WorkingTree.open('repo/branch')

    def test_shared_format_to_standalone(self, format=None):
        repo = self.make_repository('repo', shared=True, format=format)
        branch = controldir.ControlDir.create_branch_convenience('repo/tree')
        self.assertNotEqual(branch.controldir.root_transport.base,
                            branch.repository.controldir.root_transport.base)
        tree = workingtree.WorkingTree.open('repo/tree')
        self.build_tree_contents([('repo/tree/file', b'foo\n')])
        tree.add(['file'])
        tree.commit('added file')
        self.run_bzr('reconfigure --standalone', working_dir='repo/tree')
        tree = workingtree.WorkingTree.open('repo/tree')
        self.build_tree_contents([('repo/tree/file', b'bar\n')])
        self.check_file_contents('repo/tree/file', b'bar\n')
        self.run_bzr('revert', working_dir='repo/tree')
        self.check_file_contents('repo/tree/file', b'foo\n')
        self.assertEqual(tree.controldir.root_transport.base,
                         tree.branch.repository.controldir.root_transport.base)

    def test_shared_knit_to_standalone(self):
        self.test_shared_format_to_standalone('knit')

    def test_shared_pack092_to_standalone(self):
        self.test_shared_format_to_standalone('pack-0.92')

    def test_shared_rich_root_pack_to_standalone(self):
        self.test_shared_format_to_standalone('rich-root-pack')

    def test_lightweight_format_checkout_to_tree(self, format=None):
        branch = self.make_branch('branch', format=format)
        checkout = branch.create_checkout('checkout', lightweight=True)
        tree = workingtree.WorkingTree.open('checkout')
        self.build_tree_contents([('checkout/file', b'foo\n')])
        tree.add(['file'])
        tree.commit('added file')
        self.run_bzr('reconfigure --tree', working_dir='checkout')
        tree = workingtree.WorkingTree.open('checkout')
        self.build_tree_contents([('checkout/file', b'bar\n')])
        self.check_file_contents('checkout/file', b'bar\n')
        self.run_bzr('revert', working_dir='checkout')
        self.check_file_contents('checkout/file', b'foo\n')

    def test_lightweight_knit_checkout_to_tree(self):
        self.test_lightweight_format_checkout_to_tree('knit')

    def test_lightweight_pack092_checkout_to_tree(self):
        self.test_lightweight_format_checkout_to_tree('pack-0.92')

    def test_lightweight_rich_root_pack_checkout_to_tree(self):
        self.test_lightweight_format_checkout_to_tree('rich-root-pack')

    def test_branch_and_use_shared(self):
        self.run_script("""\
$ brz init -q branch
$ echo foo > branch/foo
$ brz add -q branch/foo
$ brz commit -q -m msg branch
$ brz init-shared-repo -q .
$ brz reconfigure --branch --use-shared branch
$ brz info branch
Repository branch (format: ...)
Location:
  shared repository: .
  repository branch: branch
""")

    def test_use_shared_and_branch(self):
        self.run_script("""\
$ brz init -q branch
$ echo foo > branch/foo
$ brz add -q branch/foo
$ brz commit -q -m msg branch
$ brz init-shared-repo -q .
$ brz reconfigure --use-shared --branch branch
$ brz info branch
Repository branch (format: ...)
Location:
  shared repository: .
  repository branch: branch
""")


class TestReconfigureStacking(tests.TestCaseWithTransport):

    def test_reconfigure_stacking(self):
        """Test a fairly realistic scenario for stacking:

         * make a branch with some history
         * branch it
         * make the second branch stacked on the first
         * commit in the second
         * then make the second unstacked, so it has to fill in history from
           the original fallback lying underneath its original content

        See discussion in <https://bugs.launchpad.net/bzr/+bug/391411>
        """
        # there are also per_branch tests that exercise remote operation etc
        tree_1 = self.make_branch_and_tree('b1', format='2a')
        self.build_tree(['b1/foo'])
        tree_1.add(['foo'])
        tree_1.commit('add foo')
        branch_1 = tree_1.branch
        # now branch and commit again
        bzrdir_2 = tree_1.controldir.sprout('b2')
        tree_2 = bzrdir_2.open_workingtree()
        branch_2 = tree_2.branch
        # now reconfigure to be stacked
        out, err = self.run_bzr('reconfigure --stacked-on b1 b2')
        self.assertContainsRe(out, '^.*/b2/ is now stacked on ../b1\n$')
        self.assertEqual('', err)
        # can also give the absolute URL of the branch, and it gets stored
        # as a relative path if possible
        out, err = self.run_bzr('reconfigure --stacked-on %s b2'
                                % (self.get_url('b1'),))
        self.assertContainsRe(out, '^.*/b2/ is now stacked on ../b1\n$')
        self.assertEqual('', err)
        # Refresh the branch as 'reconfigure' modified it
        branch_2 = branch_2.controldir.open_branch()
        # It should be given a relative URL to the destination, if possible,
        # because that's most likely to work across different transports
        self.assertEqual('../b1', branch_2.get_stacked_on_url())
        # commit, and it should be stored into b2's repo
        self.build_tree_contents([('foo', b'new foo')])
        tree_2.commit('update foo')
        # Now turn it off again
        out, err = self.run_bzr('reconfigure --unstacked b2')
        self.assertContainsRe(out,
                              '^.*/b2/ is now not stacked\n$')
        self.assertEqual('', err)
        # Refresh the branch as 'reconfigure' modified it
        branch_2 = branch_2.controldir.open_branch()
        self.assertRaises(errors.NotStacked, branch_2.get_stacked_on_url)

    # XXX: Needs a test for reconfiguring stacking and shape at the same time;
    # no branch at location; stacked-on is not a branch; quiet mode.
    # -- mbp 20090706

# Copyright (C) 2005,2006 by Canonical Ltd
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


"""Black-box tests for bzr branch."""

import os

import bzrlib.branch
import bzrlib.bzrdir
from bzrlib.tests.blackbox import ExternalBase


class TestBranch(ExternalBase):

    def example_branch(test):
        test.runbzr('init')
        file('hello', 'wt').write('foo')
        test.runbzr('add hello')
        test.runbzr('commit -m setup hello')
        file('goodbye', 'wt').write('baz')
        test.runbzr('add goodbye')
        test.runbzr('commit -m setup goodbye')

    def test_branch(self):
        """Branch from one branch to another."""
        os.mkdir('a')
        os.chdir('a')
        self.example_branch()
        os.chdir('..')
        self.runbzr('branch a b')
        b = bzrlib.branch.Branch.open('b')
        self.assertEqual('b\n', b.control_files.get_utf8('branch-name').read())
        self.runbzr('branch a c -r 1')
        os.chdir('b')
        self.runbzr('commit -m foo --unchanged')
        os.chdir('..')

    def test_branch_basis(self):
        # ensure that basis really does grab from the basis by having incomplete source
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        source = self.make_branch_and_tree('source')
        # this gives us an incomplete repository
        tree.bzrdir.open_repository().copy_content_into(source.branch.repository)
        tree.commit('revision 2', rev_id='2', allow_pointless=True)
        tree.bzrdir.open_branch().copy_content_into(source.branch)
        tree.copy_content_into(source)
        self.assertFalse(source.branch.repository.has_revision('2'))
        dir = source.bzrdir
        self.runbzr('branch source target --basis commit_tree')
        target = bzrlib.bzrdir.BzrDir.open('target')
        self.assertEqual('2', target.open_branch().last_revision())
        self.assertEqual('2', target.open_workingtree().last_revision())
        self.assertTrue(target.open_branch().repository.has_revision('2'))



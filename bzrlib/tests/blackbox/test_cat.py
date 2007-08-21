# Copyright (C) 2005 Canonical Ltd
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


"""Black-box tests for bzr cat.
"""

import os

from bzrlib.tests.blackbox import TestCaseWithTransport

class TestCat(TestCaseWithTransport):

    def test_cat(self):
        tree = self.make_branch_and_tree('branch')
        self.build_tree_contents([('branch/a', 'foo\n')])
        tree.add('a')
        os.chdir('branch')
        # 'bzr cat' without an option should cat the last revision
        self.run_bzr('cat', 'a', retcode=3)

        tree.commit(message='1')
        self.build_tree_contents([('a', 'baz\n')])

        self.assertEquals(self.run_bzr('cat', 'a')[0], 'foo\n')

        tree.commit(message='2')
        self.assertEquals(self.run_bzr('cat', 'a')[0], 'baz\n')
        self.assertEquals(self.run_bzr('cat', 'a', '-r', '1')[0], 'foo\n')
        self.assertEquals(self.run_bzr('cat', 'a', '-r', '-1')[0], 'baz\n')

        rev_id = tree.branch.last_revision()

        self.assertEquals(self.run_bzr('cat', 'a', '-r', 'revid:%s' % rev_id)[0], 'baz\n')

        os.chdir('..')

        self.assertEquals(self.run_bzr('cat', 'branch/a', '-r', 'revno:1:branch')[0],
                          'foo\n')
        self.run_bzr('cat', 'a', retcode=3)
        self.run_bzr('cat', 'a', '-r', 'revno:1:branch-that-does-not-exist', retcode=3)

    def test_cat_different_id(self):
        """'cat' works with old and new files"""
        tree = self.make_branch_and_tree('.')
        # the files are named after their path in the revision and
        # current trees later in the test case
        # a-rev-tree is special because it appears in both the revision
        # tree and the working tree
        self.build_tree_contents([('a-rev-tree', 'foo\n'),
            ('c-rev', 'baz\n'), ('d-rev', 'bar\n')])
        tree.lock_write()
        try:
            tree.add(['a-rev-tree', 'c-rev', 'd-rev'])
            tree.commit('add test files')
            # remove currently uses self._write_inventory - 
            # work around that for now.
            tree.flush()
            tree.remove(['d-rev'])
            tree.rename_one('a-rev-tree', 'b-tree')
            tree.rename_one('c-rev', 'a-rev-tree')
        finally:
            # calling bzr as another process require free lock on win32
            tree.unlock()

        # 'b-tree' is not present in the old tree.
        self.run_bzr_error(["^bzr: ERROR: u?'b-tree' "
                            "is not present in revision .+$"],
                           'cat b-tree --name-from-revision')

        # get to the old file automatically
        out, err = self.run_bzr('cat d-rev')
        self.assertEqual('bar\n', out)
        self.assertEqual('', err)

        out, err = self.run_bzr('cat a-rev-tree --name-from-revision')
        self.assertEqual('foo\n', out)
        self.assertEqual('', err)

        out, err = self.run_bzr('cat a-rev-tree')
        self.assertEqual('baz\n', out)
        self.assertEqual('', err)

    def test_remote_cat(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['README'])
        wt.add('README')
        wt.commit('Making sure there is a basis_tree available')

        url = self.get_readonly_url() + '/README'
        out, err = self.run_bzr(['cat', url])
        self.assertEqual('contents of README\n', out)

    def test_cat_no_working_tree(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['README'])
        wt.add('README')
        wt.commit('Making sure there is a basis_tree available')
        wt.branch.bzrdir.destroy_workingtree()

        url = self.get_readonly_url() + '/README'
        out, err = self.run_bzr(['cat', url])
        self.assertEqual('contents of README\n', out)
        

# Copyright (C) 2012 Canonical Ltd
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

from bzrlib import (
    errors,
    )
from bzrlib.tests.per_tree import TestCaseWithTree

class IdTests(TestCaseWithTree):

    def setUp(self):
        super(IdTests, self).setUp()
        work_a = self.make_branch_and_tree('wta')
        self.build_tree(['wta/bla', 'wta/dir/', 'wta/dir/file'])
        work_a.add(['bla', 'dir', 'dir/file'], ['bla-id', 'dir-id', 'file-id'])
        work_a.commit('add files')
        self.tree_a = self.workingtree_to_test_tree(work_a)

    def test_path2id(self):
        self.assertEquals('bla-id', self.tree_a.path2id('bla'))
        self.assertEquals('dir-id', self.tree_a.path2id('dir'))
        self.assertIs(None, self.tree_a.path2id('idontexist'))

    def test_path2id_list(self):
        self.assertEquals('bla-id', self.tree_a.path2id(['bla']))
        self.assertEquals('dir-id', self.tree_a.path2id(['dir']))
        self.assertEquals('file-id', self.tree_a.path2id(['dir', 'file']))
        self.assertEquals(self.tree_a.get_root_id(),
            self.tree_a.path2id([]))
        self.assertIs(None, self.tree_a.path2id(['idontexist']))
        self.assertIs(None, self.tree_a.path2id(['dir', 'idontexist']))

    def test_id2path(self):
        self.addCleanup(self.tree_a.lock_read().unlock)
        self.assertEquals('bla', self.tree_a.id2path('bla-id'))
        self.assertEquals('dir', self.tree_a.id2path('dir-id'))
        self.assertEquals('dir/file', self.tree_a.id2path('file-id'))
        self.assertRaises(errors.NoSuchId, self.tree_a.id2path, 'nonexistant')

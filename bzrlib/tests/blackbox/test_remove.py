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


import os

from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree


class TestRemove(ExternalBase):

    def test_remove_deleted(self):
        self.runbzr("init")
        self.build_tree(['a'])
        self.runbzr(['add', 'a'])
        self.runbzr(['commit', '-m', 'added a'])
        os.unlink('a')
        self.runbzr(['remove', 'a'])

    def test_remove_new(self):
        self.build_tree(['filefile',
                         'dir/',
                         'dir/filefilefile'])
        wt = self.make_branch_and_tree('.')
        wt.add(['filefile', 'dir', 'dir/filefilefile'], 
               ['filefile-id', 'dir-id', 'filefilefile-id'])
        self.assertEqual(wt.path2id('filefile'), 'filefile-id')
        self.assertEqual(wt.path2id('dir/filefilefile'), 'filefilefile-id')
        self.assertEqual(wt.path2id('dir'), 'dir-id')
        self.runbzr('remove --new')
        wt = WorkingTree.open('.')
        self.assertIs(wt.path2id('filefile'), None)
        self.assertIs(wt.path2id('dir/filefilefile'), None)
        self.assertIs(wt.path2id('dir'), None)
        wt.add(['filefile', 'dir', 'dir/filefilefile'], 
               ['filefile-id', 'dir-id', 'filefilefile-id'])
        self.assertEqual(wt.path2id('filefile'), 'filefile-id')
        self.assertEqual(wt.path2id('dir/filefilefile'), 'filefilefile-id')
        self.assertEqual(wt.path2id('dir'), 'dir-id')
        self.runbzr('remove --new dir')
        wt = WorkingTree.open('.')
        self.assertEqual(wt.path2id('filefile'), 'filefile-id')
        self.assertIs(wt.path2id('dir/filefilefile'), None)
        self.assertIs(wt.path2id('dir'), None)
        self.runbzr('remove --new .')
        wt = WorkingTree.open('.')
        self.assertIs(wt.path2id('filefile'), None)
        self.runbzr('remove --new .', retcode=3)

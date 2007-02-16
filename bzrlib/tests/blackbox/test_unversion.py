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
from bzrlib import osutils

_id='-id'
a='a'
b='b/'
c='b/c'
files=(a,b,c)


class TestUnversion(ExternalBase):

    def __init__(self, methodName='runTest'):
        super(TestUnversion, self).__init__(methodName)
        self.cmd = 'unversion'
        self.shape = None

    def _make_tree(self,files):
        tree = self.make_branch_and_tree('.')
        self.build_tree(files)
        for f in files:
            id=f+_id
            tree.add(f, id)
            self.assertEqual(tree.path2id(f), id)
            self.failUnlessExists(f)
            self.assertInWorkingTree(f)
        return tree

    def assertCommandPerformedOnFiles(self,files):
        for f in files:
            id=f+_id
            self.failUnlessExists(f)
            self.assertNotInWorkingTree(f)

    def test_command_no_files_specified(self):
        self.build_tree([])
        tree = self.make_branch_and_tree('.')

        (out,err) = self.runbzr(self.cmd, retcode=3)
        self.assertEquals(err.strip(),
            "bzr: ERROR: Specify one or more files to unversion, or use --new."
            )

        (out,err) = self.runbzr(self.cmd+' --new', retcode=3)
        self.assertEquals(err.strip(),"bzr: ERROR: No matching files.")
        (out,err) = self.runbzr(self.cmd+' --new .', retcode=3)
        self.assertEquals(err.strip(),"bzr: ERROR: No matching files.")

    def test_command_on_invalid_files(self):
        self.build_tree([a])
        tree = self.make_branch_and_tree('.')

        (out,err) = self.runbzr(self.cmd + ' .')
        self.assertEquals(out.strip(), "")
        self.assertEquals(err.strip(), "")

        (out,err) = self.runbzr(self.cmd + ' a')
        #print "out =",out.strip()
        #print "err =",err.strip()
        self.assertEquals(out.strip(), "")
        self.assertEquals(err.strip(), "a is not versioned.")

        (out,err) = self.runbzr(self.cmd + ' b')
        #print "out =",out.strip()
        #print "err =",err.strip()
        self.assertEquals(out.strip(), "")
        self.assertEquals(err.strip(), "b is not versioned.")

    def test_command_one_file(self):
        self.build_tree([a])
        tree = self.make_branch_and_tree('.')
        tree.add(a)
        self.assertInWorkingTree(a)
        self.runbzr([self.cmd, a])
        self.assertCommandPerformedOnFiles([a])

    def test_command_on_deleted(self):
        self.runbzr("init")
        self.build_tree([a])
        self.runbzr(['add', a])
        self.runbzr(['commit', '-m', 'added a'])
        os.unlink(a)
        self.assertInWorkingTree(a)
        self.runbzr([self.cmd, a])
        self.assertNotInWorkingTree(a)

    def test_command_with_new(self):
        tree = self._make_tree(files)

        self.runbzr(self.cmd+' --new')
        self.assertCommandPerformedOnFiles(files)

    def test_command_with_new_in_dir1(self):
        tree = self._make_tree(files)
        self.runbzr(self.cmd+' --new '+b)
        tree = WorkingTree.open('.')
        self.assertInWorkingTree(a)
        self.assertEqual(tree.path2id(a), a+_id)
        self.assertCommandPerformedOnFiles([b,c])

    def test_command_with_new_in_dir2(self):
        tree = self._make_tree(files)
        self.runbzr(self.cmd+' --new .')
        tree = WorkingTree.open('.')
        self.assertCommandPerformedOnFiles([a])
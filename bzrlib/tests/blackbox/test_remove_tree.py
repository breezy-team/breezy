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


"""Black-box tests for bzr remove-tree.
"""

import os

from bzrlib.tests.blackbox import ExternalBase

class TestRemoveTree(ExternalBase):

    def _present(self, f):
        self.assertEquals(os.path.exists(f), True)

    def _absent(self, f):
        self.assertEquals(os.path.exists(f), False)


    def test_remove_tree(self):

        def bzr(*args, **kwargs):
            return self.run_bzr(*args, **kwargs)[0]

        os.mkdir('branch1')
        os.chdir('branch1')
        bzr('init')
        f=open('foo','wb')
        f.write("foo\n")
        f.close()
        bzr('add', 'foo')

        bzr('commit', '-m', '1')

        os.chdir("..")

        self._present("branch1/foo")
        bzr('branch', 'branch1', 'branch2')
        self._present("branch2/foo")
        bzr('checkout', 'branch1', 'branch3')
        self._present("branch3/foo")
        bzr('checkout', '--lightweight', 'branch1', 'branch4')
        self._present("branch4/foo")

        # branch1 == branch
        # branch2 == branch of branch1
        # branch3 == checkout of branch1
        # branch4 == lightweight checkout of branch1

        # bzr remove-tree (CWD)
        os.chdir("branch1")
        bzr('remove-tree')
        os.chdir("..")
        self._absent("branch1/foo")

        # bzr remove-tree (path)
        bzr('remove-tree', 'branch2')
        self._absent("branch2/foo")

        # bzr remove-tree (checkout)
        bzr('remove-tree', 'branch3')
        self._absent("branch3/foo")

        # bzr remove-tree (lightweight checkout, refuse)
        bzr('remove-tree', 'branch4', retcode=3)
        self._present("branch4/foo")

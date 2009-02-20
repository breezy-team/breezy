# Copyright (C) 2005 by Aaron Bentley
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
from StringIO import StringIO
from unittest import makeSuite

from bzrlib.bzrdir import BzrDir
from bzrlib.osutils import has_symlinks
from bzrlib.tests import TestCaseInTempDir

from bzrlib.plugins.bzrtools.clean_tree import clean_tree, iter_deletables

class TestCleanTree(TestCaseInTempDir):
    def test_symlinks(self):
        if has_symlinks() is False:
            return
        os.mkdir('branch')
        BzrDir.create_standalone_workingtree('branch')
        os.symlink(os.path.realpath('no-die-please'), 'branch/die-please')
        os.mkdir('no-die-please')
        assert os.path.exists('branch/die-please')
        os.mkdir('no-die-please/child')

        clean_tree('branch', unknown=True, no_prompt=True)
        assert os.path.exists('no-die-please')
        assert os.path.exists('no-die-please/child')

    def test_iter_deletable(self):
        """Files are selected for deletion appropriately"""
        os.mkdir('branch')
        tree = BzrDir.create_standalone_workingtree('branch')
        f = file('branch/.bzrignore', 'wb')
        try:
            f.write('*~\n*.pyc\n.bzrignore\n')
        finally:
            f.close()
        file('branch/file.BASE', 'wb').write('contents')
        tree.lock_write()
        try:
            self.assertEqual(len(list(iter_deletables(tree, unknown=True))), 1)
            file('branch/file', 'wb').write('contents')
            file('branch/file~', 'wb').write('contents')
            file('branch/file.pyc', 'wb').write('contents')

            dels = sorted([r for a,r in iter_deletables(tree, unknown=True)])
            assert sorted(['file', 'file.BASE']) == dels

            dels = [r for a,r in iter_deletables(tree, detritus=True)]
            assert sorted(['file~', 'file.BASE']) == dels

            dels = [r for a,r in iter_deletables(tree, ignored=True)]
            assert sorted(['file~', 'file.pyc', '.bzrignore']) == dels

            dels = [r for a,r in iter_deletables(tree, unknown=False)]
            assert [] == dels
        finally:
            tree.unlock()

def test_suite():
    return makeSuite(TestCleanTree)

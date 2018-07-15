# Copyright (C) 2005-2010 Canonical Ltd
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
#


"""Tests of the 'brz clean-tree' command."""


import os

from breezy import ignores
from breezy.tests import TestCaseWithTransport
from breezy.tests.script import run_script


class TestBzrTools(TestCaseWithTransport):

    @staticmethod
    def touch(filename):
        with open(filename, 'wb') as my_file:
            my_file.write(b'')

    def test_clean_tree(self):
        self.run_bzr('init')
        self.run_bzr('ignore *~')
        self.run_bzr('ignore *.pyc')
        self.touch('name')
        self.touch('name~')
        self.assertPathExists('name~')
        self.touch('name.pyc')
        self.run_bzr('clean-tree --force')
        self.assertPathExists('name~')
        self.assertPathDoesNotExist('name')
        self.touch('name')
        self.run_bzr('clean-tree --detritus --force')
        self.assertPathExists('name')
        self.assertPathDoesNotExist('name~')
        self.assertPathExists('name.pyc')
        self.run_bzr('clean-tree --ignored --force')
        self.assertPathExists('name')
        self.assertPathDoesNotExist('name.pyc')
        self.run_bzr('clean-tree --unknown --force')
        self.assertPathDoesNotExist('name')
        self.touch('name')
        self.touch('name~')
        self.touch('name.pyc')
        self.run_bzr('clean-tree --unknown --ignored --force')
        self.assertPathDoesNotExist('name')
        self.assertPathDoesNotExist('name~')
        self.assertPathDoesNotExist('name.pyc')

    def test_clean_tree_nested_bzrdir(self):
        # clean-tree should not blindly delete nested bzrdirs (branches)
        # bug https://bugs.launchpad.net/bzr/+bug/572098
        # so it will play well with scmproj/bzr-externals plugins.
        wt1 = self.make_branch_and_tree('.')
        wt2 = self.make_branch_and_tree('foo')
        wt3 = self.make_branch_and_tree('bar')
        ignores.tree_ignores_add_patterns(wt1, ['./foo'])
        self.run_bzr(['clean-tree', '--unknown', '--force'])
        self.assertPathExists('foo')
        self.assertPathExists('bar')
        self.run_bzr(['clean-tree', '--ignored', '--force'])
        self.assertPathExists('foo')
        self.assertPathExists('bar')

    def test_clean_tree_directory(self):
        """Test --directory option"""
        tree = self.make_branch_and_tree('a')
        self.build_tree(['a/added', 'a/unknown', 'a/ignored'])
        tree.add('added')
        self.run_bzr('clean-tree -d a --unknown --ignored --force')
        self.assertPathDoesNotExist('a/unknown')
        self.assertPathDoesNotExist('a/ignored')
        self.assertPathExists('a/added')

    def test_clean_tree_interactive(self):
        wt = self.make_branch_and_tree('.')
        self.touch('bar')
        self.touch('foo')
        run_script(self, """
        $ brz clean-tree
        bar
        foo
        2>Are you sure you wish to delete these? ([y]es, [n]o): no
        <n
        Canceled
        """)
        self.assertPathExists('bar')
        self.assertPathExists('foo')
        run_script(self, """
        $ brz clean-tree
        bar
        foo
        2>Are you sure you wish to delete these? ([y]es, [n]o): yes
        <y
        2>deleting paths:
        2>  bar
        2>  foo
        """)
        self.assertPathDoesNotExist('bar')
        self.assertPathDoesNotExist('foo')

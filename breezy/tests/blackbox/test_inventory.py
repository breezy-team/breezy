# Copyright (C) 2006 Canonical Ltd
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

"""Black-box tests for 'brz inventory'."""

import os

from breezy.tests import TestCaseWithTransport


class TestInventory(TestCaseWithTransport):

    def setUp(self):
        super(TestInventory, self).setUp()

        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b/', 'b/c'])

        tree.add(['a', 'b', 'b/c'], ids=[b'a-id', b'b-id', b'c-id'])
        tree.commit('init', rev_id=b'one')
        self.tree = tree

    def assertInventoryEqual(self, expected, args=None, **kwargs):
        """Test that the output of 'brz inventory' is as expected.

        Any arguments supplied will be passed to run_bzr.
        """
        command = 'inventory'
        if args is not None:
            command += ' ' + args
        out, err = self.run_bzr(command, **kwargs)
        self.assertEqual(expected, out)
        self.assertEqual('', err)

    def test_inventory(self):
        self.assertInventoryEqual('a\nb\nb/c\n')

    def test_inventory_include_root(self):
        self.assertInventoryEqual('\na\nb\nb/c\n', '--include-root')
        self.assertInventoryEqual('b\nb/c\n', '--include-root b')

    def test_inventory_kind(self):
        self.assertInventoryEqual('a\nb/c\n', '--kind file')
        self.assertInventoryEqual('b\n', '--kind directory')

    def test_inventory_show_ids(self):
        expected = ''.join(('%-50s %s\n' % (path, file_id))
                           for path, file_id in
                           [('a', 'a-id'),
                            ('b', 'b-id'),
                            ('b/c', 'c-id')
                            ]
                           )
        self.assertInventoryEqual(expected, '--show-ids')

    def test_inventory_specific_files(self):
        self.assertInventoryEqual('a\n', 'a')
        self.assertInventoryEqual('b\nb/c\n', 'b b/c')
        # 'brz inventory' recurses into subdirectories
        self.assertInventoryEqual('b\nb/c\n', 'b')

    def test_inventory_mixed(self):
        """Test that we get expected results when mixing parameters"""
        a_line = '%-50s %s\n' % ('a', 'a-id')
        b_line = '%-50s %s\n' % ('b', 'b-id')
        c_line = '%-50s %s\n' % ('b/c', 'c-id')

        self.assertInventoryEqual('', '--kind directory a')
        self.assertInventoryEqual(a_line + c_line, '--kind file --show-ids')
        self.assertInventoryEqual(c_line, '--kind file --show-ids b b/c')

    def test_in_subdir(self):
        os.chdir('b')
        # TODO: jam 20060922 Maybe inventory should return the paths as
        #       relative to '.', rather than relative to root

        # a plain 'inventory' returns all files
        self.assertInventoryEqual('a\nb\nb/c\n')
        # But passing '.' will only return paths underneath here
        self.assertInventoryEqual('b\nb/c\n', '.')

    def test_inventory_revision(self):
        self.build_tree(['b/d', 'e'])
        self.tree.add(['b/d', 'e'], ids=[b'd-id', b'e-id'])
        self.tree.commit('add files')

        self.tree.rename_one('b/d', 'd')
        self.tree.commit('rename b/d => d')

        # Passing just -r returns the inventory of that revision
        self.assertInventoryEqual('a\nb\nb/c\n', '-r 1')
        self.assertInventoryEqual('a\nb\nb/c\nb/d\ne\n', '-r 2')

        # Passing a path will lookup the path in the old and current locations
        self.assertInventoryEqual('b/d\n', '-r 2 b/d')
        self.assertInventoryEqual('b/d\n', '-r 2 d')

        self.tree.rename_one('e', 'b/e')
        self.tree.commit('rename e => b/e')

        # When supplying just a directory paths that are now,
        # or used to be, in that directory are shown
        self.assertInventoryEqual('b\nb/c\nb/d\ne\n', '-r 2 b')

    def test_missing_file(self):
        self.run_bzr_error([r'Path\(s\) are not versioned: no-such-file'],
                           'inventory no-such-file')

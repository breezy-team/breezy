# Copyright (C) 2009 Canonical Ltd
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
    branch as _mod_branch,
    controldir,
    )
from bzrlib.tests import TestCaseWithTransport


class TestReference(TestCaseWithTransport):

    def get_default_format(self):
        format = controldir.format_registry.make_bzrdir('1.9')
        format.set_branch_format(_mod_branch.BzrBranchFormat8())
        return format

    def test_no_args_lists(self):
        branch = self.make_branch('branch')
        branch.set_reference_info('file-id', 'path', 'http://example.org')
        branch.set_reference_info('file-id2', 'lath', 'http://example.org/2')
        out, err = self.run_bzr('reference', working_dir='branch')
        lines = out.splitlines()
        self.assertEqual('lath http://example.org/2', lines[0])
        self.assertEqual('path http://example.org', lines[1])

    def make_tree_with_reference(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/newpath'])
        tree.add('newpath', 'file-id')
        tree.branch.set_reference_info('file-id', 'path', 'http://example.org')
        tree.branch.set_reference_info('file-id2', 'lath',
                                       'http://example.org/2')
        return tree

    def test_uses_working_tree_location(self):
        tree = self.make_tree_with_reference()
        out, err = self.run_bzr('reference', working_dir='tree')
        self.assertContainsRe(out, 'newpath http://example.org\n')

    def test_uses_basis_tree_location(self):
        tree = self.make_tree_with_reference()
        tree.commit('add newpath')
        tree.bzrdir.destroy_workingtree()
        out, err = self.run_bzr('reference', working_dir='tree')
        self.assertContainsRe(out, 'newpath http://example.org\n')

    def test_one_arg_displays(self):
        tree = self.make_tree_with_reference()
        out, err = self.run_bzr('reference newpath', working_dir='tree')
        self.assertEqual('newpath http://example.org\n', out)

    def test_one_arg_uses_containing_tree(self):
        tree = self.make_tree_with_reference()
        out, err = self.run_bzr('reference tree/newpath')
        self.assertEqual('newpath http://example.org\n', out)

    def test_two_args_sets(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        tree.add('file', 'file-id')
        out, err = self.run_bzr('reference tree/file http://example.org')
        path, location = tree.branch.get_reference_info('file-id')
        self.assertEqual('http://example.org', location)
        self.assertEqual('file', path)
        self.assertEqual('', out)
        self.assertEqual('', err)

    def test_missing_file(self):
        tree = self.make_branch_and_tree('tree')
        out, err = self.run_bzr('reference file http://example.org',
                                working_dir='tree', retcode=3)
        self.assertEqual('bzr: ERROR: file is not versioned.\n', err)

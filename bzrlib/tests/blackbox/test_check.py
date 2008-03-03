# Copyright (C) 2007 Canonical Ltd
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

"""Tests for the 'check' CLI command."""

from bzrlib.tests.blackbox import ExternalBase


class TestCheck(ExternalBase):

    def test_check_no_tree(self):
        self.make_branch('.')
        self.run_bzr('check')

    def test_check_initial_tree(self):
        self.make_branch_and_tree('.')
        self.run_bzr('check')

    def test_check_one_commit_tree(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('hallelujah')
        self.run_bzr('check')

    def test_check_branch(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('foo')
        out, err = self.run_bzr('check --branch')
        self.assertContainsRe(err, r"^Checking branch at '.*'\.\n"
                                   r"checked branch.*\n$")

    def test_check_repository(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('foo')
        out, err = self.run_bzr('check --repo')
        self.assertStartsWith(err, "Checking repository at '")

    def test_check_tree(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('foo')
        out, err = self.run_bzr('check --tree')
        self.assertStartsWith(err, "Checking working tree at '")

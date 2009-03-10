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

from bzrlib.tests import ChrootedTestCase
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
        out, err = self.run_bzr('check')
        self.assertContainsRe(err, r"^Checking working tree at '.*'\.\n"
                                   r"Checking repository at '.*'\.\n"
                                   r"checked repository.*\n"
                                   r"     1 revisions\n"
                                   r"     0 file-ids\n"
                                   r"     0 unique file texts\n"
                                   r"     0 repeated file texts\n"
                                   r"     0 unreferenced text versions\n"
                                   r"Checking branch at '.*'\.\n"
                                   r"checked branch.*\n$")

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
        self.assertContainsRe(err, r"^Checking repository at '.*'\.\n"
                                   r"checked repository.*\n"
                                   r"     1 revisions\n"
                                   r"     0 file-ids\n"
                                   r"     0 unique file texts\n"
                                   r"     0 repeated file texts\n"
                                   r"     0 unreferenced text versions$")

    def test_check_tree(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('foo')
        out, err = self.run_bzr('check --tree')
        self.assertContainsRe(err, r"^Checking working tree at '.*'\.\n$")

    def test_partial_check(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('foo')
        out, err = self.run_bzr('check --tree --branch')
        self.assertContainsRe(err, r"^Checking working tree at '.*'\.\n"
                                   r"Checking branch at '.*'\.\n"
                                   r"checked branch.*\n$")

    def test_check_missing_tree(self):
        branch = self.make_branch('.')
        out, err = self.run_bzr('check --tree')
        self.assertEqual(err, "No working tree found at specified location.\n")

    def test_check_missing_partial(self):
        branch = self.make_branch('.')
        out, err = self.run_bzr('check --tree --branch')
        self.assertContainsRe(err,
            r"^No working tree found at specified location\.\n"
            r"Checking branch at '.*'\.\n"
            r"checked branch.*\n$")

    def test_check_missing_branch_in_shared_repo(self):
        self.make_repository('shared', shared=True)
        out, err = self.run_bzr('check --branch shared')
        self.assertEqual(err, "No branch found at specified location.\n")


class ChrootedCheckTests(ChrootedTestCase):

    def test_check_missing_branch(self):
        out, err = self.run_bzr(
            'check --branch %s' % self.get_readonly_url(''))
        self.assertEqual(err, "No branch found at specified location.\n")

    def test_check_missing_repository(self):
        out, err = self.run_bzr('check --repo %s' % self.get_readonly_url(''))
        self.assertEqual(err, "No repository found at specified location.\n")

    def test_check_missing_everything(self):
        out, err = self.run_bzr('check %s' % self.get_readonly_url(''))
        self.assertEqual(err, "No working tree found at specified location.\n"
                              "No branch found at specified location.\n"
                              "No repository found at specified location.\n")

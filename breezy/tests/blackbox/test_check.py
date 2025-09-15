# Copyright (C) 2007-2010 Canonical Ltd
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

"""Tests for the 'check' CLI command."""

from breezy.tests import ChrootedTestCase, TestCaseWithTransport


class TestCheck(TestCaseWithTransport):
    def test_check_no_tree(self):
        self.make_branch(".")
        self.run_bzr("check")

    def test_check_initial_tree(self):
        self.make_branch_and_tree(".")
        self.run_bzr("check")

    def test_check_one_commit_tree(self):
        tree = self.make_branch_and_tree(".")
        tree.commit("hallelujah")
        _out, err = self.run_bzr("check")
        self.assertContainsRe(err, r"Checking working tree at '.*'\.\n")
        self.assertContainsRe(err, r"Checking repository at '.*'\.\n")
        # the root directory may be in the texts for rich root formats
        self.assertContainsRe(
            err, r"checked repository.*\n" r"     1 revisions\n" r"     [01] file-ids\n"
        )
        self.assertContainsRe(err, r"Checking branch at '.*'\.\n")
        self.assertContainsRe(err, r"checked branch.*")

    def test_check_branch(self):
        tree = self.make_branch_and_tree(".")
        tree.commit("foo")
        _out, err = self.run_bzr("check --branch")
        self.assertContainsRe(err, r"^Checking branch at '.*'\.\n" r"checked branch.*")

    def test_check_repository(self):
        tree = self.make_branch_and_tree(".")
        tree.commit("foo")
        _out, err = self.run_bzr("check --repo")
        self.assertContainsRe(
            err,
            r"^Checking repository at '.*'\.\n"
            r"checked repository.*\n"
            r"     1 revisions\n"
            r"     [01] file-ids\n",
        )

    def test_check_tree(self):
        tree = self.make_branch_and_tree(".")
        tree.commit("foo")
        _out, err = self.run_bzr("check --tree")
        self.assertContainsRe(err, r"^Checking working tree at '.*'\.\n$")

    def test_partial_check(self):
        tree = self.make_branch_and_tree(".")
        tree.commit("foo")
        _out, err = self.run_bzr("check --tree --branch")
        self.assertContainsRe(
            err,
            r"^Checking working tree at '.*'\.\n"
            r"Checking branch at '.*'\.\n"
            r"checked branch.*",
        )

    def test_check_missing_tree(self):
        self.make_branch(".")
        _out, err = self.run_bzr("check --tree")
        self.assertEqual(err, "No working tree found at specified location.\n")

    def test_check_missing_partial(self):
        self.make_branch(".")
        _out, err = self.run_bzr("check --tree --branch")
        self.assertContainsRe(
            err,
            r"Checking branch at '.*'\.\n"
            r"No working tree found at specified location\.\n"
            r"checked branch.*",
        )

    def test_check_missing_branch_in_shared_repo(self):
        self.make_repository("shared", shared=True)
        _out, err = self.run_bzr("check --branch shared")
        self.assertEqual(err, "No branch found at specified location.\n")


class ChrootedCheckTests(ChrootedTestCase):
    def test_check_missing_branch(self):
        _out, err = self.run_bzr(f"check --branch {self.get_readonly_url('')}")
        self.assertEqual(err, "No branch found at specified location.\n")

    def test_check_missing_repository(self):
        _out, err = self.run_bzr(f"check --repo {self.get_readonly_url('')}")
        self.assertEqual(err, "No repository found at specified location.\n")

    def test_check_missing_everything(self):
        _out, err = self.run_bzr(f"check {self.get_readonly_url('')}")
        self.assertEqual(
            err,
            "No working tree found at specified location.\n"
            "No branch found at specified location.\n"
            "No repository found at specified location.\n",
        )

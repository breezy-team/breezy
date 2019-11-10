#    test_merge_upstream.py -- Testsuite for builddeb's upstream merging.
#    Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
#
#    This file is part of bzr-builddeb.
#
#    bzr-builddeb is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    bzr-builddeb is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with bzr-builddeb; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

from __future__ import absolute_import

from debian.changelog import Changelog, Version

from ....tests import (
    TestCase,
    TestCaseWithTransport,
    )

from ..merge_upstream import (
    changelog_add_new_version,
    upstream_merge_changelog_line,
    package_version,
    )


class TestPackageVersion(TestCase):

    def test_simple_debian(self):
        self.assertEquals(
            Version("1.2-1"),
            package_version("1.2", "debian"))

    def test_simple_ubuntu(self):
        self.assertEquals(
            Version("1.2-0ubuntu1"),
            package_version("1.2", "ubuntu"))

    def test_debian_with_dash(self):
        self.assertEquals(
            Version("1.2-0ubuntu1-1"),
            package_version("1.2-0ubuntu1", "debian"))

    def test_ubuntu_with_dash(self):
        self.assertEquals(
            Version("1.2-1-0ubuntu1"),
            package_version("1.2-1", "ubuntu"))

    def test_ubuntu_with_epoch(self):
        self.assertEquals(
            Version("3:1.2-1-0ubuntu1"),
            package_version("1.2-1", "ubuntu", "3"))


class UpstreamMergeChangelogLineTests(TestCase):

    def test_release(self):
        self.assertEquals(
            "New upstream release.",
            upstream_merge_changelog_line("1.0"))

    def test_bzr_snapshot(self):
        self.assertEquals(
            "New upstream snapshot.",
            upstream_merge_changelog_line("1.0+bzr3"))

    def test_git_snapshot(self):
        self.assertEquals(
            "New upstream snapshot.",
            upstream_merge_changelog_line("1.0~git20101212"))

    def test_plus(self):
        self.assertEquals(
            "New upstream release.",
            upstream_merge_changelog_line("1.0+dfsg1"))


class ChangelogAddNewVersionTests(TestCaseWithTransport):

    def test_add_new(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.mkdir("debian")
        changelog_add_new_version(tree, '', "1.0", "sid", None, "somepkg")
        # changelog_add_new_version will version the changelog if it was
        # created
        with open('debian/changelog', 'rb') as f:
            cl = Changelog(f)
        self.assertEquals(cl._blocks[0].package, "somepkg")
        self.assertEquals(cl._blocks[0].distributions, "UNRELEASED")
        self.assertEquals(cl._blocks[0].version, Version("1.0-1"))
        self.assertEquals(
            [], list(tree.filter_unversioned_files(["debian/changelog"])))

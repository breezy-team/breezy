#    test_dep3.py -- Blackbox tests for dep3-patch.
#    Copyright (C) 2011 Canonical Ltd.
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


"""Blackbox tests for "bzr dep3-patch"."""

from .....tests.blackbox import ExternalBase

import os


class TestDep3Patch(ExternalBase):

    def setUp(self):
        super(TestDep3Patch, self).setUp()
        self.upstream_tree = self.make_branch_and_tree("upstream")
        self.upstream_tree.commit(message="initial commit")
        packaging = self.upstream_tree.controldir.sprout("packaging")
        self.packaging_tree = packaging.open_workingtree()
        feature = self.upstream_tree.controldir.sprout("feature")
        self.feature_tree = feature.open_workingtree()

    def test_nothing_to_do(self):
        (out, err) = self.run_bzr("dep3-patch -d packaging feature", retcode=3)
        self.assertEquals("brz: ERROR: No unmerged revisions\n", err)
        self.assertEquals("", out)

    def test_simple(self):
        # If there is a single revision the commit message from
        # that revision will be used.
        self.build_tree_contents([("feature/foo", "bar\n")])
        self.feature_tree.add("foo")
        self.feature_tree.commit(message="A message", timestamp=1304850124,
            timezone=0, authors=["Jelmer <jelmer@debian.org>"], rev_id=b"therevid")
        (out, err) = self.run_bzr("dep3-patch -d packaging feature")
        self.assertEqualDiff(out, "Description: A message\n"
            "Origin: commit, revision id: therevid\n"
            "Author: Jelmer <jelmer@debian.org>\n"
            "Last-Update: 2011-05-08\n"
            "X-Bzr-Revision-Id: therevid\n"
            "\n"
            "=== added file 'foo'\n"
            "--- old/foo\t1970-01-01 00:00:00 +0000\n"
            "+++ new/foo\t2011-05-08 10:22:04 +0000\n"
            "@@ -0,0 +1,1 @@\n"
            "+bar\n"
            "\n")

    def test_uses_single_revision_commit(self):
        # If there is a single revision the commit message from
        # that revision will be used.
        self.feature_tree.commit(message="A message", timestamp=1304850124,
            timezone=0, authors=["Jelmer <jelmer@debian.org>"])
        (out, err) = self.run_bzr("dep3-patch -d packaging feature")
        self.assertContainsRe(out, "Description: A message\n")

    def test_uses_config_description(self):
        config = self.feature_tree.branch.get_config()
        config.set_user_option("description", "What this does")
        self.feature_tree.commit(message="a message")
        (out, err) = self.run_bzr("dep3-patch -d packaging feature")
        self.assertContainsRe(out, "Description: What this does\n")

    def test_upstream_branch(self):
        os.mkdir('packaging/.bzr-builddeb/')
        with open('packaging/.bzr-builddeb/local.conf', 'w') as f:
            f.write('[BUILDDEB]\nupstream-branch = %s\n' %
                    self.upstream_tree.branch.base)
        self.feature_tree.commit(message="a message")
        (out, err) = self.run_bzr("dep3-patch -d packaging feature")
        self.assertContainsRe(out, "Applied-Upstream: no\n")

    def test_upstream_branch_disabled(self):
        os.mkdir('packaging/.bzr-builddeb/')
        with open('packaging/.bzr-builddeb/local.conf', 'w') as f:
            f.write('[BUILDDEB]\nupstream-branch = %s\n' %
                    self.upstream_tree.branch.base)
        self.feature_tree.commit(message="a message")
        (out, err) = self.run_bzr("dep3-patch --no-upstream-check -d packaging feature")
        self.assertNotContainsRe(out, "Applied-Upstream")

    def test_range(self):
        # A range of revisions can be specified.
        self.build_tree_contents([("feature/foo", "bar\n")])
        self.feature_tree.add("foo")
        self.feature_tree.commit(message="Another message", timestamp=1304850124,
            timezone=0, authors=["Jelmer <jelmer@debian.org>"], rev_id=b"baserevid")
        self.build_tree_contents([("feature/foo", "bla\n")])
        self.feature_tree.commit(message="A message", timestamp=1304850124,
            timezone=0, authors=["Jelmer <jelmer@debian.org>"], rev_id=b"therevid")
        (out, err) = self.run_bzr("dep3-patch -c -1 -d packaging feature")
        self.assertEqualDiff(out, "Description: A message\n"
            "Origin: commit, revision id: therevid\n"
            "Author: Jelmer <jelmer@debian.org>\n"
            "Last-Update: 2011-05-08\n"
            "X-Bzr-Revision-Id: therevid\n"
            "\n"
            "=== modified file 'foo'\n"
            "--- old/foo\t2011-05-08 10:22:04 +0000\n"
            "+++ new/foo\t2011-05-08 10:22:04 +0000\n"
            "@@ -1,1 +1,1 @@\n"
            "-bar\n"
            "+bla\n"
            "\n")

    def test_open_ended_range(self):
        # If there is a single revision the commit message from
        # that revision will be used.
        self.feature_tree.commit(message="A message", timestamp=1304850124,
            timezone=0, authors=["Jelmer <jelmer@debian.org>"])
        (out, err) = self.run_bzr("dep3-patch -d packaging feature -r-2..")
        self.assertContainsRe(out, "Description: A message\n")

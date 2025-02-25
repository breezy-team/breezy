#    test_config.py -- Tests for builddeb's config.py
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

from ....branch import Branch
from ..config import (
    BUILD_TYPE_MERGE,
    DebBuildConfig,
)
from . import TestCaseWithTransport


class DebBuildConfigTests(TestCaseWithTransport):
    def setUp(self):
        super().setUp()
        self.tree = self.make_branch_and_tree(".")
        self.branch = self.tree.branch
        with open("default.conf", "w") as f:
            f.write("[" + DebBuildConfig.section + "]\n")
            # shouldn't be read as it needs to be trusted
            f.write("builder = invalid builder\n")
            f.write("build-dir = default build dir\n")
            f.write("orig-dir = default orig dir\n")
            f.write("result-dir = default result dir\n")
        with open("user.conf", "w") as f:
            f.write("[" + DebBuildConfig.section + "]\n")
            f.write("builder = valid builder\n")
            f.write("quick-builder = valid quick builder\n")
            f.write("orig-dir = user orig dir\n")
            f.write("result-dir = user result dir\n")
        with open(".bzr/branch/branch.conf", "w") as f:
            f.write("[" + DebBuildConfig.section + "]\n")
            f.write("quick-builder = invalid quick builder\n")
            f.write("result-dir = branch result dir\n")
        self.tree.add(["default.conf", "user.conf"])
        self.config = DebBuildConfig(
            [("user.conf", True), ("default.conf", False)], branch=self.branch
        )

    def test_secure_not_from_untrusted(self):
        self.assertEqual(self.config.builder, "valid builder")

    def test_secure_not_from_branch(self):
        self.assertEqual(self.config.quick_builder, "valid quick builder")

    def test_branch_over_all(self):
        self.assertEqual(self.config.result_dir, "branch result dir")

    def test_hierarchy(self):
        self.assertEqual(self.config.orig_dir, "user orig dir")
        self.assertEqual(self.config.build_dir, "default build dir")

    def test_no_entry(self):
        self.assertEqual(self.config.merge, False)
        self.assertEqual(self.config.build_type, None)

    def test_parse_error(self):
        with open("invalid.conf", "w") as f:
            f.write("[" + DebBuildConfig.section + "\n")
        DebBuildConfig([("invalid.conf", True, "invalid.conf")])

    def test_upstream_metadata(self):
        cfg = DebBuildConfig([], tree=self.branch.basis_tree())
        self.assertIs(None, cfg.upstream_branch)

        self.build_tree_contents(
            [
                ("debian/",),
                ("debian/upstream/",),
                (
                    "debian/upstream/metadata",
                    b"Name: example\n"
                    b"Repository: http://example.com/foo\n"
                    b"Repository-Tag-Prefix: exampl-\n",
                ),
            ]
        )
        self.tree.add(["debian", "debian/upstream", "debian/upstream/metadata"])

        cfg = DebBuildConfig([], tree=self.tree)
        self.assertEqual("http://example.com/foo", cfg.upstream_branch)
        self.assertEqual("tag:exampl-$UPSTREAM_VERSION", cfg.export_upstream_revision)

    def test_upstream_metadata_multidoc(self):
        cfg = DebBuildConfig([], tree=self.branch.basis_tree())
        self.assertIs(None, cfg.upstream_branch)

        self.build_tree_contents(
            [
                ("debian/",),
                ("debian/upstream/",),
                (
                    "debian/upstream/metadata",
                    b"---\n"
                    b"---\n"
                    b"Name: example\n"
                    b"Repository: http://example.com/foo\n"
                    b"Repository-Tag-Prefix: exampl-\n",
                ),
            ]
        )
        self.tree.add(["debian", "debian/upstream", "debian/upstream/metadata"])

        cfg = DebBuildConfig([], tree=self.tree)
        self.assertEqual("http://example.com/foo", cfg.upstream_branch)
        self.assertEqual("tag:exampl-$UPSTREAM_VERSION", cfg.export_upstream_revision)

    def test_invalid_upstream_metadata(self):
        cfg = DebBuildConfig([], tree=self.branch.basis_tree())
        self.assertIs(None, cfg.upstream_branch)

        self.build_tree_contents(
            [
                ("debian/",),
                ("debian/upstream/",),
                ("debian/upstream/metadata", b"debian/changelog.blah"),
            ]
        )
        self.tree.add(["debian", "debian/upstream", "debian/upstream/metadata"])

        # We just ignore the upstream metadata file in this case
        config = DebBuildConfig([], tree=self.tree)
        self.assertEqual([], config._config_files)


try:
    from ...svn.config import SubversionBuildPackageConfig  # noqa: F401
except ImportError:
    pass
else:
    from ...svn.tests import SubversionTestCase

    class DebuildSvnBpTests(SubversionTestCase):
        if not getattr(SubversionTestCase, "make_svn_branch", None):

            def make_svn_branch(self, relpath):
                repos_url = self.make_repository(relpath)
                return Branch.open(repos_url)

        def test_from_properties(self):
            branch = self.make_svn_branch("d")

            cfg = DebBuildConfig([], tree=branch.basis_tree())
            self.assertEqual(False, cfg.merge)

            dc = self.get_commit_editor(branch.base)
            d = dc.add_dir("debian")
            d.change_prop("mergeWithUpstream", "1")
            d.change_prop("svn-bp:origDir", "someorigdir")
            dc.close()

            cfg = DebBuildConfig([], tree=branch.basis_tree())
            self.assertEqual(True, cfg.merge)
            self.assertEqual(BUILD_TYPE_MERGE, cfg.build_type)
            self.assertEqual("someorigdir", cfg.orig_dir)

        def test_from_svn_layout_file(self):
            branch = self.make_svn_branch("d")

            cfg = DebBuildConfig([], tree=branch.basis_tree())
            self.assertEqual(False, cfg.merge)

            with self.get_commit_editor(branch.base) as dc:
                d = dc.add_dir("debian")
                f = d.add_file("debian/svn-layout")
                f.modify(b"origDir = someorigdir\n")

            cfg = DebBuildConfig([], tree=branch.basis_tree())
            self.assertEqual("someorigdir", cfg.orig_dir)

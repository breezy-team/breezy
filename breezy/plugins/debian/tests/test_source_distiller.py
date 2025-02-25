#    test_source_distiller.py -- Getting the source to build from a branch
#    Copyright (C) 2008 Canonical Ltd.
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

import os

from debian.changelog import Version

from ....transport import FileExists
from ..source_distiller import (
    FullSourceDistiller,
    MergeModeDistiller,
    NativeSourceDistiller,
)
from ..upstream import MissingUpstreamTarball
from . import (
    SourcePackageBuilder,
    TestCaseWithTransport,
)
from .test_upstream import (
    _MissingUpstreamProvider,
    _SimpleUpstreamProvider,
    _TouchUpstreamProvider,
)


class NativeSourceDistillerTests(TestCaseWithTransport):
    def test_distill_target_exists(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_read()
        self.addCleanup(wt.unlock)
        sd = NativeSourceDistiller(wt, "")
        self.build_tree(["target/"])
        self.assertRaises(FileExists, sd.distill, "target")

    def test_distill_revision_tree(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(["a"])
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add(["a"])
        wt.commit("one")
        rev_tree = wt.basis_tree()
        sd = NativeSourceDistiller(rev_tree, "")
        sd.distill("target")
        self.assertPathExists("target")
        self.assertPathExists("target/a")

    def test_distill_removes_builddeb_dir(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(["a", ".bzr-builddeb/", ".bzr-builddeb/default.conf"])
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add(["a", ".bzr-builddeb/", ".bzr-builddeb/default.conf"])
        wt.commit("one")
        rev_tree = wt.basis_tree()
        sd = NativeSourceDistiller(rev_tree, "")
        sd.distill("target")
        self.assertPathExists("target")
        self.assertPathExists("target/a")
        self.assertPathDoesNotExist("target/.bzr-builddeb")

    def test_distill_working_tree_with_symlinks(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(["a"])
        os.symlink("a", "b")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add(["a", "b"])
        sd = NativeSourceDistiller(wt, "")
        sd.distill("target")
        self.assertPathExists("target")
        self.assertPathExists("target/a")
        self.assertPathExists("target/b")


class FullSourceDistillerTests(TestCaseWithTransport):
    def test_distill_target_exists(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_read()
        self.addCleanup(wt.unlock)
        sd = FullSourceDistiller(wt, "", None)
        self.build_tree(["target/"])
        self.assertRaises(FileExists, sd.distill, "target")

    def test_distill_no_tarball(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_read()
        self.addCleanup(wt.unlock)
        sd = FullSourceDistiller(wt, "", _MissingUpstreamProvider())
        self.assertRaises(MissingUpstreamTarball, sd.distill, "target")

    def test_distill_tarball_exists(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_read()
        self.addCleanup(wt.unlock)
        sd = FullSourceDistiller(wt, "", _TouchUpstreamProvider("tarball"))
        sd.distill("target")
        self.assertPathExists("tarball")

    def test_distill_revision_tree(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        self.build_tree(["a", ".bzr-builddeb"])
        wt.add(["a", ".bzr-builddeb"])
        sd = FullSourceDistiller(wt, "", _TouchUpstreamProvider("tarball"))
        sd.distill("target")
        self.assertPathExists("tarball")
        self.assertPathExists("target")
        self.assertPathExists("target/a")
        self.assertPathDoesNotExist("target/.bzr-builddeb")

    def test_distill_working_tree_with_symlinks(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(["a"])
        os.symlink("a", "b")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add(["a", "b"])
        sd = FullSourceDistiller(wt, "", _TouchUpstreamProvider("tarball"))
        sd.distill("target")
        self.assertPathExists("target")
        self.assertPathExists("target/a")
        self.assertPathExists("target/b")


class MergeModeDistillerTests(TestCaseWithTransport):
    def make_tarball(self, name, version):
        builder = SourcePackageBuilder(name, version)
        builder.add_upstream_file("a")
        builder.add_default_control()
        builder.build()

    def test_distill_target_exists(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_read()
        self.addCleanup(wt.unlock)
        sd = MergeModeDistiller(wt, "", None)
        self.build_tree(["target/"])
        self.assertRaises(FileExists, sd.distill, "target")

    def test_distill_no_tarball(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_read()
        self.addCleanup(wt.unlock)
        sd = MergeModeDistiller(
            wt, "", _SimpleUpstreamProvider("package", "0.1-1", "tarballs")
        )
        self.assertRaises(MissingUpstreamTarball, sd.distill, "target")

    def test_distill_tarball_exists(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_read()
        self.addCleanup(wt.unlock)
        name = "package"
        version = Version("0.1-1")
        self.make_tarball(name, version)
        sd = MergeModeDistiller(
            wt, "", _SimpleUpstreamProvider(name, version.upstream_version, ".")
        )
        sd.distill("target/foo")
        self.assertPathExists(f"target/{name}_{version.upstream_version}.orig.tar.gz")
        self.assertPathExists("target/foo/a")

    def test_distill_exports_branch(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        self.build_tree(["debian/", "debian/a", ".bzr-builddeb"])
        wt.add(["debian/", "debian/a", ".bzr-builddeb"])
        name = "package"
        version = Version("0.1-1")
        self.make_tarball(name, version)
        sd = MergeModeDistiller(
            wt, "", _SimpleUpstreamProvider(name, version.upstream_version, ".")
        )
        sd.distill("target/")
        self.assertPathExists("target/debian/a")
        self.assertPathDoesNotExist("target/.bzr-builddeb")

    def test_distill_removes_debian(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        self.build_tree(["debian/", "debian/a", ".bzr-builddeb"])
        wt.add(["debian/", "debian/a", ".bzr-builddeb"])
        name = "package"
        version = Version("0.1-1")
        builder = SourcePackageBuilder(name, version)
        builder.add_upstream_file("a")
        builder.add_upstream_file("debian/foo")
        builder.add_default_control()
        builder.build()
        sd = MergeModeDistiller(
            wt, "", _SimpleUpstreamProvider(name, version.upstream_version, ".")
        )
        sd.distill("target/")
        self.assertPathExists("target/a")
        self.assertPathDoesNotExist("target/debian/foo")

    def test_distill_top_level(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        self.build_tree(["b", ".bzr-builddeb"])
        wt.add(["b", ".bzr-builddeb"])
        name = "package"
        version = Version("0.1-1")
        self.make_tarball(name, version)
        sd = MergeModeDistiller(
            wt,
            "",
            _SimpleUpstreamProvider(name, version.upstream_version, "."),
            top_level=True,
        )
        sd.distill("target/")
        self.assertPathExists("target/a")
        self.assertPathExists("target/debian/b")
        self.assertPathDoesNotExist("target/debian/.bzr-builddeb")
        self.assertPathDoesNotExist("target/.bzr-builddeb")
        self.assertPathDoesNotExist("target/b")

    def test_distill_use_existing(self):
        wt = self.make_branch_and_tree(".")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        self.build_tree(["debian/", "debian/a", ".bzr-builddeb"])
        wt.add(["debian/", "debian/a", ".bzr-builddeb"])
        name = "package"
        version = Version("0.1-1")
        self.make_tarball(name, version)
        sd = MergeModeDistiller(
            wt,
            "",
            _SimpleUpstreamProvider(name, version.upstream_version, "."),
            use_existing=True,
        )
        self.build_tree(["target/", "target/b", "target/debian/", "target/debian/b"])
        sd.distill("target/")
        self.assertPathExists("target/b")
        self.assertPathExists("target/debian/a")
        self.assertPathDoesNotExist("target/a")
        self.assertPathDoesNotExist("target/debian/b")

    def test_distill_working_tree_with_symlinks(self):
        wt = self.make_branch_and_tree(".")
        self.build_tree(["debian/", "debian/a"])
        os.symlink("a", "debian/b")
        wt.lock_write()
        self.addCleanup(wt.unlock)
        wt.add(["debian", "debian/a", "debian/b"])
        name = "package"
        version = Version("0.1-1")
        self.make_tarball(name, version)
        sd = MergeModeDistiller(
            wt, "", _SimpleUpstreamProvider(name, version.upstream_version, ".")
        )
        sd.distill("target")
        self.assertPathExists("target")
        self.assertPathExists("target/debian/a")
        self.assertPathExists("target/debian/b")

#    test_builddeb.py -- Blackbox tests for builddeb.
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

import os
import shutil
import subprocess
import tarfile

from .....transport import get_transport
from .. import BuilddebTestCase, Version
from ..test_import_dsc import PristineTarFeature


class TestBaseImportDsc(BuilddebTestCase):
    def _upstream_dir(self, package_name, upstream_version):
        return package_name + "-" + upstream_version

    upstream_dir = property(
        lambda self: self._upstream_dir(self.package_name, self.upstream_version)
    )

    def _upstream_tarball_name(self, package_name, upstream_version):
        return package_name + "_" + upstream_version + ".orig.tar.gz"

    upstream_tarball_name = property(
        lambda self: self._upstream_tarball_name(
            self.package_name, self.upstream_version
        )
    )

    def make_unpacked_upstream_source(self, transport=None):
        if transport is None:
            transport = get_transport(self.upstream_dir)
        transport.ensure_base()
        self.build_tree(["README"], transport=transport)

    def make_upstream_tarball(self, upstream_version=None):
        if upstream_version is None:
            upstream_version = self.upstream_version
        upstream_dir = self._upstream_dir(self.package_name, upstream_version)
        self.make_unpacked_upstream_source(get_transport(upstream_dir))
        tar = tarfile.open(
            self._upstream_tarball_name(self.package_name, upstream_version), "w:gz"
        )
        try:
            tar.add(upstream_dir)
        finally:
            tar.close()
        return upstream_dir

    def make_debian_dir(self, debian_dir, version=None):
        os.mkdir(debian_dir)
        cl = self.make_changelog(version=version)
        self.write_changelog(cl, os.path.join(debian_dir, "changelog"))
        with open(os.path.join(debian_dir, "control"), "w") as f:
            f.write("Source: {}\n".format(self.package_name))
            f.write("Maintainer: none\n")
            f.write("Standards-Version: 3.7.2\n")
            f.write("\n")
            f.write("Package: {}\n".format(self.package_name))
            f.write("Architecture: all\n")

    def make_real_source_package(self, version=None):
        if version is None:
            version = self.package_version
        version = Version(version)
        upstream_version = version.upstream_version
        upstream_dir = self.make_upstream_tarball(upstream_version)
        debian_dir = os.path.join(upstream_dir, "debian")
        self.make_debian_dir(debian_dir, version=version)
        proc = subprocess.Popen(
            "dpkg-source -b --format=1.0 {}".format(upstream_dir),
            shell=True,
            stdout=subprocess.PIPE,
        )
        proc.wait()
        self.assertEqual(proc.returncode, 0)
        shutil.rmtree(upstream_dir)
        dsc_name = f"{self.package_name}_{version}.dsc"
        return dsc_name


class TestImportDsc(TestBaseImportDsc):
    def test_import_dsc_incremental(self):
        self.requireFeature(PristineTarFeature)
        tree = self.make_branch_and_tree(".")
        dsc_name = self.make_real_source_package(version="0.1-1")
        self.run_bzr("import-dsc {}".format(dsc_name))
        dsc_name = self.make_real_source_package(version="0.2-1")
        self.run_bzr("import-dsc {}".format(dsc_name))
        tree.lock_read()
        expected_shape = ["README", "debian/", "debian/changelog", "debian/control"]
        try:
            if getattr(self, "check_tree_shape", None):
                self.check_tree_shape(tree, expected_shape)
            else:
                self.check_inventory_shape(tree.inventory, expected_shape)
        finally:
            tree.unlock()
        self.assertEqual(3, tree.branch.revno())

    def test_import_dsc(self):
        self.requireFeature(PristineTarFeature)
        dsc_name = self.make_real_source_package()
        tree = self.make_branch_and_tree(".")
        self.run_bzr("import-dsc {}".format(dsc_name))
        tree.lock_read()
        expected_shape = ["README", "debian/", "debian/changelog", "debian/control"]
        try:
            if getattr(self, "check_tree_shape", None):
                self.check_tree_shape(tree, expected_shape)
            else:
                self.check_inventory_shape(tree.inventory, expected_shape)
        finally:
            tree.unlock()
        self.assertEqual(2, tree.branch.revno())

    def test_import_no_files(self):
        self.make_branch_and_tree(".")
        self.make_real_source_package()
        self.run_bzr_error(
            ["You must give the location of at least one source package."], "import-dsc"
        )

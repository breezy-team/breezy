# Copyright (C) 2011 Canonical Ltd
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

import os
import tarfile
import zipfile

from breezy import errors
from breezy.tests import features
from breezy.tests.per_tree import TestCaseWithTree


class ArchiveTests:
    def test_export(self):
        work_a = self.make_branch_and_tree("wta")
        self.build_tree_contents([("wta/file", b"a\nb\nc\nd\n"), ("wta/dir", b"")])
        work_a.add("file")
        work_a.add("dir")
        work_a.commit("add file")
        tree_a = self.workingtree_to_test_tree(work_a)
        output_path = "output"
        with open(output_path, "wb") as f:
            f.writelines(tree_a.archive(self.format, output_path))
        names = self.get_export_names(output_path)
        self.assertIn("file", names)
        self.assertIn("dir", names)

    def test_export_symlink(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        work_a = self.make_branch_and_tree("wta")
        os.symlink("target", "wta/link")
        work_a.add("link")
        work_a.commit("add link")
        tree_a = self.workingtree_to_test_tree(work_a)
        output_path = "output"
        with open(output_path, "wb") as f:
            f.writelines(tree_a.archive(self.format, output_path))
        names = self.get_export_names(output_path)
        self.assertIn("link", names)

    def get_output_names(self, path):
        raise NotImplementedError(self.get_output_names)


class TestTar(ArchiveTests, TestCaseWithTree):
    format = "tar"

    def get_export_names(self, path):
        tf = tarfile.open(path)
        try:
            return tf.getnames()
        finally:
            tf.close()


class TestTgz(ArchiveTests, TestCaseWithTree):
    format = "tgz"

    def get_export_names(self, path):
        tf = tarfile.open(path)
        try:
            return tf.getnames()
        finally:
            tf.close()


class TestZip(ArchiveTests, TestCaseWithTree):
    format = "zip"

    def get_export_names(self, path):
        zf = zipfile.ZipFile(path)
        try:
            return zf.namelist()
        finally:
            zf.close()

    def test_export_symlink(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        work_a = self.make_branch_and_tree("wta")
        os.symlink("target", "wta/link")
        work_a.add("link")
        work_a.commit("add link")
        tree_a = self.workingtree_to_test_tree(work_a)
        output_path = "output"
        with open(output_path, "wb") as f:
            f.writelines(tree_a.archive(self.format, output_path))
        names = self.get_export_names(output_path)
        self.assertIn("link.lnk", names)


class GenericArchiveTests(TestCaseWithTree):
    def test_dir_invalid(self):
        work_a = self.make_branch_and_tree("wta")
        self.build_tree_contents([("wta/file", b"a\nb\nc\nd\n"), ("wta/dir", b"")])
        work_a.add("file")
        work_a.add("dir")
        work_a.commit("add file")
        tree_a = self.workingtree_to_test_tree(work_a)

        self.assertRaises(errors.NoSuchExportFormat, tree_a.archive, "dir", "foo")

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

from breezy.export import export
from breezy import osutils
from breezy import tests
from breezy.tests.per_tree import TestCaseWithTree
from breezy.tests import (
    features,
    )


class ExportTest(object):

    def prepare_export(self):
        work_a = self.make_branch_and_tree('wta')
        self.build_tree_contents(
            [('wta/file', b'a\nb\nc\nd\n'), ('wta/dir', b'')])
        work_a.add('file')
        work_a.add('dir')
        work_a.commit('add file')
        tree_a = self.workingtree_to_test_tree(work_a)
        export(tree_a, 'output', self.exporter)

    def prepare_symlink_export(self):
        self.requireFeature(features.SymlinkFeature)
        work_a = self.make_branch_and_tree('wta')
        os.symlink('target', 'wta/link')
        work_a.add('link')
        work_a.commit('add link')
        tree_a = self.workingtree_to_test_tree(work_a)
        export(tree_a, 'output', self.exporter)

    def test_export(self):
        self.prepare_export()
        names = self.get_export_names()
        self.assertIn('output/file', names)
        self.assertIn('output/dir', names)

    def test_export_symlink(self):
        self.prepare_symlink_export()
        names = self.get_export_names()
        self.assertIn('output/link', names)


class TestTar(ExportTest, TestCaseWithTree):

    exporter = 'tar'

    def get_export_names(self):
        tf = tarfile.open('output')
        try:
            return tf.getnames()
        finally:
            tf.close()


class TestZip(ExportTest, TestCaseWithTree):

    exporter = 'zip'

    def get_export_names(self):
        zf = zipfile.ZipFile('output')
        try:
            return zf.namelist()
        finally:
            zf.close()

    def test_export_symlink(self):
        self.prepare_symlink_export()
        names = self.get_export_names()
        self.assertIn('output/link.lnk', names)


class TestDir(ExportTest, TestCaseWithTree):

    exporter = 'dir'

    def get_export_names(self):
        return [osutils.pathjoin('output', name)
                for name in os.listdir('output')]

# Copyright (C) 2011, 2016 Canonical Ltd
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

"""Tests for ContentFilterTree"""

import tarfile
import zipfile

from .. import (
    export,
    filter_tree,
    tests,
    )
from . import (
    fixtures,
    )
from .test_filters import _stack_1


class TestFilterTree(tests.TestCaseWithTransport):

    def make_tree(self):
        self.underlying_tree = fixtures.make_branch_and_populated_tree(
            self)

        def stack_callback(path):
            return _stack_1
        self.filter_tree = filter_tree.ContentFilterTree(
            self.underlying_tree, stack_callback)
        return self.filter_tree

    def test_get_file_text(self):
        self.make_tree()
        self.assertEqual(
            self.underlying_tree.get_file_text('hello'),
            b'hello world')
        self.assertEqual(
            self.filter_tree.get_file_text('hello'),
            b'HELLO WORLD')

    def test_tar_export_content_filter_tree(self):
        # TODO: this could usefully be run generically across all exporters.
        self.make_tree()
        export.export(self.filter_tree, "out.tgz")
        ball = tarfile.open("out.tgz", "r:gz")
        self.assertEqual(
            b'HELLO WORLD',
            ball.extractfile('out/hello').read())

    def test_zip_export_content_filter_tree(self):
        self.make_tree()
        export.export(self.filter_tree, 'out.zip')
        zipf = zipfile.ZipFile('out.zip', 'r')
        self.assertEqual(
            b'HELLO WORLD',
            zipf.read('out/hello'))

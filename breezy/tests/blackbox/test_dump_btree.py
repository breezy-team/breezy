# Copyright (C) 2008, 2009, 2010 Canonical Ltd
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
#

"""Tests of the 'brz dump-btree' command."""

from breezy import (
    tests,
    )
from breezy.bzr import (
    btree_index,
    )
from breezy.tests import (
    http_server,
    )


class TestDumpBtree(tests.TestCaseWithTransport):

    def create_sample_btree_index(self):
        builder = btree_index.BTreeBuilder(
            reference_lists=1, key_elements=2)
        builder.add_node((b'test', b'key1'), b'value',
                         (((b'ref', b'entry'),),))
        builder.add_node((b'test', b'key2'), b'value2',
                         (((b'ref', b'entry2'),),))
        builder.add_node((b'test2', b'key3'), b'value3',
                         (((b'ref', b'entry3'),),))
        out_f = builder.finish()
        try:
            self.build_tree_contents([('test.btree', out_f.read())])
        finally:
            out_f.close()

    def test_dump_btree_smoke(self):
        self.create_sample_btree_index()
        out, err = self.run_bzr('dump-btree test.btree')
        self.assertEqualDiff(
            "(('test', 'key1'), 'value', ((('ref', 'entry'),),))\n"
            "(('test', 'key2'), 'value2', ((('ref', 'entry2'),),))\n"
            "(('test2', 'key3'), 'value3', ((('ref', 'entry3'),),))\n",
            out)

    def test_dump_btree_http_smoke(self):
        self.transport_readonly_server = http_server.HttpServer
        self.create_sample_btree_index()
        url = self.get_readonly_url('test.btree')
        out, err = self.run_bzr(['dump-btree', url])
        self.assertEqualDiff(
            "(('test', 'key1'), 'value', ((('ref', 'entry'),),))\n"
            "(('test', 'key2'), 'value2', ((('ref', 'entry2'),),))\n"
            "(('test2', 'key3'), 'value3', ((('ref', 'entry3'),),))\n",
            out)

    def test_dump_btree_raw_smoke(self):
        self.create_sample_btree_index()
        out, err = self.run_bzr('dump-btree test.btree --raw')
        self.assertEqualDiff(
            'Root node:\n'
            'B+Tree Graph Index 2\n'
            'node_ref_lists=1\n'
            'key_elements=2\n'
            'len=3\n'
            'row_lengths=1\n'
            '\n'
            'Page 0\n'
            'type=leaf\n'
            'test\0key1\0ref\0entry\0value\n'
            'test\0key2\0ref\0entry2\0value2\n'
            'test2\0key3\0ref\0entry3\0value3\n'
            '\n',
            out)

    def test_dump_btree_no_refs_smoke(self):
        # A BTree index with no ref lists (such as *.cix) can be dumped without
        # errors.
        builder = btree_index.BTreeBuilder(
            reference_lists=0, key_elements=2)
        builder.add_node((b'test', b'key1'), b'value')
        out_f = builder.finish()
        try:
            self.build_tree_contents([('test.btree', out_f.read())])
        finally:
            out_f.close()
        out, err = self.run_bzr('dump-btree test.btree')

    def create_sample_empty_btree_index(self):
        builder = btree_index.BTreeBuilder(
            reference_lists=1, key_elements=2)
        out_f = builder.finish()
        try:
            self.build_tree_contents([('test.btree', out_f.read())])
        finally:
            out_f.close()

    def test_dump_empty_btree_smoke(self):
        self.create_sample_empty_btree_index()
        out, err = self.run_bzr('dump-btree test.btree')
        self.assertEqualDiff("", out)

    def test_dump_empty_btree_http_smoke(self):
        self.transport_readonly_server = http_server.HttpServer
        self.create_sample_empty_btree_index()
        url = self.get_readonly_url('test.btree')
        out, err = self.run_bzr(['dump-btree', url])
        self.assertEqualDiff("", out)

    def test_dump_empty_btree_raw_smoke(self):
        self.create_sample_empty_btree_index()
        out, err = self.run_bzr('dump-btree test.btree --raw')
        self.assertEqualDiff(
            'Root node:\n'
            'B+Tree Graph Index 2\n'
            'node_ref_lists=1\n'
            'key_elements=2\n'
            'len=0\n'
            'row_lengths=\n'
            '\n'
            'Page 0\n'
            '(empty)\n',
            out)

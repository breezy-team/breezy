# Copyright (C) 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for indices."""

from bzrlib import errors
from bzrlib.index import *
from bzrlib.tests import TestCaseWithMemoryTransport


class TestGraphIndexBuilder(TestCaseWithMemoryTransport):

    def test_build_index_empty(self):
        builder = GraphIndexBuilder()
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual("Bazaar Graph Index 1\nnode_ref_lists=0\n\n", contents)

    def test_build_index_one_reference_list_empty(self):
        builder = GraphIndexBuilder(reference_lists=1)
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual("Bazaar Graph Index 1\nnode_ref_lists=1\n\n", contents)

    def test_build_index_two_reference_list_empty(self):
        builder = GraphIndexBuilder(reference_lists=2)
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual("Bazaar Graph Index 1\nnode_ref_lists=2\n\n", contents)

    def test_build_index_one_node(self):
        builder = GraphIndexBuilder()
        builder.add_node('akey', (), 'data')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual("Bazaar Graph Index 1\nnode_ref_lists=0\n"
            "akey\x00\x00\x00data\n\n", contents)

    def test_add_node_empty_value(self):
        builder = GraphIndexBuilder()
        builder.add_node('akey', (), '')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual("Bazaar Graph Index 1\nnode_ref_lists=0\n"
            "akey\x00\x00\x00\n\n", contents)

    def test_build_index_two_nodes_sorted(self):
        # the highest sorted node comes first.
        builder = GraphIndexBuilder()
        # use three to have a good chance of glitching dictionary hash
        # lookups etc. Insert in randomish order that is not correct
        # and not the reverse of the correct order.
        builder.add_node('2002', (), 'data')
        builder.add_node('2000', (), 'data')
        builder.add_node('2001', (), 'data')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual("Bazaar Graph Index 1\nnode_ref_lists=0\n"
            "2000\x00\x00\x00data\n"
            "2001\x00\x00\x00data\n"
            "2002\x00\x00\x00data\n"
            "\n", contents)

    def test_build_index_reference_lists_are_included_one(self):
        builder = GraphIndexBuilder(reference_lists=1)
        builder.add_node('key', ([], ), 'data')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual("Bazaar Graph Index 1\nnode_ref_lists=1\n"
            "key\x00\x00\x00data\n"
            "\n", contents)

    def test_build_index_reference_lists_are_included_two(self):
        builder = GraphIndexBuilder(reference_lists=2)
        builder.add_node('key', ([], []), 'data')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual("Bazaar Graph Index 1\nnode_ref_lists=2\n"
            "key\x00\x00\t\x00data\n"
            "\n", contents)

    def test_node_references_are_byte_offsets(self):
        builder = GraphIndexBuilder(reference_lists=1)
        builder.add_node('reference', ([], ), 'data')
        builder.add_node('key', (['reference'], ), 'data')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual("Bazaar Graph Index 1\nnode_ref_lists=1\n"
            "key\x00\x0051\x00data\n"
            "reference\x00\x00\x00data\n"
            "\n", contents)

    def test_node_references_are_cr_delimited(self):
        builder = GraphIndexBuilder(reference_lists=1)
        builder.add_node('reference', ([], ), 'data')
        builder.add_node('reference2', ([], ), 'data')
        builder.add_node('key', (['reference', 'reference2'], ), 'data')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual("Bazaar Graph Index 1\nnode_ref_lists=1\n"
            "key\x00\x0054\r71\x00data\n"
            "reference\x00\x00\x00data\n"
            "reference2\x00\x00\x00data\n"
            "\n", contents)

    def test_multiple_reference_lists_are_tab_delimited(self):
        builder = GraphIndexBuilder(reference_lists=2)
        builder.add_node('keference', ([], []), 'data')
        builder.add_node('rey', (['keference'], ['keference']), 'data')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual("Bazaar Graph Index 1\nnode_ref_lists=2\n"
            "keference\x00\x00\t\x00data\n"
            "rey\x00\x0038\t38\x00data\n"
            "\n", contents)

    def test_add_node_referencing_missing_key_makes_absent(self):
        builder = GraphIndexBuilder(reference_lists=1)
        builder.add_node('rey', (['beference', 'aeference2'], ), 'data')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual("Bazaar Graph Index 1\nnode_ref_lists=1\n"
            "aeference2\x00a\x00\x00\n"
            "beference\x00a\x00\x00\n"
            "rey\x00\x0053\r38\x00data\n"
            "\n", contents)

    def test_node_references_three_digits(self):
        # test the node digit expands as needed.
        builder = GraphIndexBuilder(reference_lists=1)
        references = map(str, reversed(range(9)))
        builder.add_node('2-key', (references, ), '')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual("Bazaar Graph Index 1\nnode_ref_lists=1\n"
            "0\x00a\x00\x00\n"
            "1\x00a\x00\x00\n"
            "2\x00a\x00\x00\n"
            "2-key\x00\x00130\r124\r118\r112\r106\r100\r050\r044\r038\x00\n"
            "3\x00a\x00\x00\n"
            "4\x00a\x00\x00\n"
            "5\x00a\x00\x00\n"
            "6\x00a\x00\x00\n"
            "7\x00a\x00\x00\n"
            "8\x00a\x00\x00\n"
            "\n", contents)

    def test_absent_has_no_reference_overhead(self):
        # the offsets after an absent record should be correct when there are
        # >1 reference lists.
        builder = GraphIndexBuilder(reference_lists=2)
        builder.add_node('parent', (['aail', 'zther'], []), '')
        stream = builder.finish()
        contents = stream.read()
        self.assertEqual("Bazaar Graph Index 1\nnode_ref_lists=2\n"
            "aail\x00a\x00\x00\n"
            "parent\x00\x0038\r63\t\x00\n"
            "zther\x00a\x00\x00\n"
            "\n", contents)

    def test_add_node_bad_key(self):
        builder = GraphIndexBuilder()
        for bad_char in '\t\n\x0b\x0c\r\x00 ':
            self.assertRaises(errors.BadIndexKey, builder.add_node,
                'a%skey' % bad_char, (), 'data')
        self.assertRaises(errors.BadIndexKey, builder.add_node,
                '', (), 'data')

    def test_add_node_bad_data(self):
        builder = GraphIndexBuilder()
        self.assertRaises(errors.BadIndexValue, builder.add_node, 'akey',
            (), 'data\naa')
        self.assertRaises(errors.BadIndexValue, builder.add_node, 'akey',
            (), 'data\x00aa')

    def test_add_node_bad_mismatched_ref_lists_length(self):
        builder = GraphIndexBuilder()
        self.assertRaises(errors.BadIndexValue, builder.add_node, 'akey',
            ([], ), 'data aa')
        builder = GraphIndexBuilder(reference_lists=1)
        self.assertRaises(errors.BadIndexValue, builder.add_node, 'akey',
            (), 'data aa')
        self.assertRaises(errors.BadIndexValue, builder.add_node, 'akey',
            ([], []), 'data aa')
        builder = GraphIndexBuilder(reference_lists=2)
        self.assertRaises(errors.BadIndexValue, builder.add_node, 'akey',
            (), 'data aa')
        self.assertRaises(errors.BadIndexValue, builder.add_node, 'akey',
            ([], ), 'data aa')
        self.assertRaises(errors.BadIndexValue, builder.add_node, 'akey',
            ([], [], []), 'data aa')

    def test_add_node_bad_key_in_reference_lists(self):
        # first list, first key - trivial
        builder = GraphIndexBuilder(reference_lists=1)
        self.assertRaises(errors.BadIndexKey, builder.add_node, 'akey',
            (['a key'], ), 'data aa')
        # need to check more than the first key in the list
        self.assertRaises(errors.BadIndexKey, builder.add_node, 'akey',
            (['agoodkey', 'this is a bad key'], ), 'data aa')
        # and if there is more than one list it should be getting checked
        # too
        builder = GraphIndexBuilder(reference_lists=2)
        self.assertRaises(errors.BadIndexKey, builder.add_node, 'akey',
            ([], ['a bad key']), 'data aa')

    def test_add_duplicate_key(self):
        builder = GraphIndexBuilder()
        builder.add_node('key', (), 'data')
        self.assertRaises(errors.BadIndexDuplicateKey, builder.add_node, 'key',
            (), 'data')

    def test_add_key_after_referencing_key(self):
        builder = GraphIndexBuilder(reference_lists=1)
        builder.add_node('key', (['reference'], ), 'data')
        builder.add_node('reference', ([],), 'data')


class TestGraphIndex(TestCaseWithMemoryTransport):

    def make_index(self, ref_lists=0, nodes=[]):
        builder = GraphIndexBuilder(ref_lists)
        for node, references, value in nodes:
            builder.add_node(node, references, value)
        stream = builder.finish()
        trans = self.get_transport()
        trans.put_file('index', stream)
        return GraphIndex(trans, 'index')

    def test_open_bad_index_no_error(self):
        trans = self.get_transport()
        trans.put_bytes('name', "not an index\n")
        index = GraphIndex(trans, 'name')

    def test_iter_all_entries_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_all_entries()))

    def test_iter_all_entries_simple(self):
        index = self.make_index(nodes=[('name', (), 'data')])
        self.assertEqual([('name', (), 'data')],
            list(index.iter_all_entries()))

    def test_iter_all_entries_references_resolved(self):
        index = self.make_index(1, nodes=[
            ('name', (['ref'], ), 'data'),
            ('ref', ([], ), 'refdata')])
        self.assertEqual(set([('name', (('ref',),), 'data'),
            ('ref', ((), ), 'refdata')]),
            set(index.iter_all_entries()))

    def test_iteration_absent_skipped(self):
        index = self.make_index(1, nodes=[
            ('name', (['ref'], ), 'data')])
        self.assertEqual(set([('name', (('ref',),), 'data')]),
            set(index.iter_all_entries()))
        self.assertEqual(set([('name', (('ref',),), 'data')]),
            set(index.iter_entries(['name'])))
        self.assertEqual([], list(index.iter_entries(['ref'])))

    def test_iter_all_keys(self):
        index = self.make_index(1, nodes=[
            ('name', (['ref'], ), 'data'),
            ('ref', ([], ), 'refdata')])
        self.assertEqual(set([('name', (('ref',),), 'data'),
            ('ref', ((), ), 'refdata')]),
            set(index.iter_entries(['name', 'ref'])))

    def test_iter_nothing_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_entries([])))

    def test_iter_missing_entry_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_entries(['a'])))

    def test_validate_bad_index_errors(self):
        trans = self.get_transport()
        trans.put_bytes('name', "not an index\n")
        index = GraphIndex(trans, 'name')
        self.assertRaises(errors.BadIndexFormatSignature, index.validate)

    def test_validate_bad_node_refs(self):
        index = self.make_index(2)
        trans = self.get_transport()
        content = trans.get_bytes('index')
        # change the options line to end with a rather than a parseable number
        new_content = content[:-2] + 'a\n\n'
        trans.put_bytes('index', new_content)
        self.assertRaises(errors.BadIndexOptions, index.validate)

    def test_validate_missing_end_line_empty(self):
        index = self.make_index(2)
        trans = self.get_transport()
        content = trans.get_bytes('index')
        # truncate the last byte
        trans.put_bytes('index', content[:-1])
        self.assertRaises(errors.BadIndexData, index.validate)

    def test_validate_missing_end_line_nonempty(self):
        index = self.make_index(2, [('key', ([], []), '')])
        trans = self.get_transport()
        content = trans.get_bytes('index')
        # truncate the last byte
        trans.put_bytes('index', content[:-1])
        self.assertRaises(errors.BadIndexData, index.validate)

    def test_validate_empty(self):
        index = self.make_index()
        index.validate()

    def test_validate_no_refs_content(self):
        index = self.make_index(nodes=[('key', (), 'value')])
        index.validate()


class TestCombinedGraphIndex(TestCaseWithMemoryTransport):

    def make_index(self, name, ref_lists=0, nodes=[]):
        builder = GraphIndexBuilder(ref_lists)
        for node, references, value in nodes:
            builder.add_node(node, references, value)
        stream = builder.finish()
        trans = self.get_transport()
        trans.put_file(name, stream)
        return GraphIndex(trans, name)

    def test_open_missing_index_no_error(self):
        trans = self.get_transport()
        index1 = GraphIndex(trans, 'missing')
        index = CombinedGraphIndex([index1])

    def test_add_index(self):
        index = CombinedGraphIndex([])
        index1 = self.make_index('name', nodes=[('key', (), '')])
        index.insert_index(0, index1)
        self.assertEqual([('key', (), '')], list(index.iter_all_entries()))

    def test_iter_all_entries_empty(self):
        index = CombinedGraphIndex([])
        self.assertEqual([], list(index.iter_all_entries()))

    def test_iter_all_entries_children_empty(self):
        index1 = self.make_index('name')
        index = CombinedGraphIndex([index1])
        self.assertEqual([], list(index.iter_all_entries()))

    def test_iter_all_entries_simple(self):
        index1 = self.make_index('name', nodes=[('name', (), 'data')])
        index = CombinedGraphIndex([index1])
        self.assertEqual([('name', (), 'data')],
            list(index.iter_all_entries()))

    def test_iter_all_entries_two_indices(self):
        index1 = self.make_index('name1', nodes=[('name', (), 'data')])
        index2 = self.make_index('name2', nodes=[('2', (), '')])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual([('name', (), 'data'),
            ('2', (), '')],
            list(index.iter_all_entries()))

    def test_iter_entries_two_indices_dup_key(self):
        index1 = self.make_index('name1', nodes=[('name', (), 'data')])
        index2 = self.make_index('name2', nodes=[('name', (), 'data')])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual([('name', (), 'data')],
            list(index.iter_entries(['name'])))

    def test_iter_all_entries_two_indices_dup_key(self):
        index1 = self.make_index('name1', nodes=[('name', (), 'data')])
        index2 = self.make_index('name2', nodes=[('name', (), 'data')])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual([('name', (), 'data')],
            list(index.iter_all_entries()))

    def test_iter_nothing_empty(self):
        index = CombinedGraphIndex([])
        self.assertEqual([], list(index.iter_entries([])))

    def test_iter_nothing_children_empty(self):
        index1 = self.make_index('name')
        index = CombinedGraphIndex([index1])
        self.assertEqual([], list(index.iter_entries([])))

    def test_iter_all_keys(self):
        index1 = self.make_index('1', 1, nodes=[
            ('name', (['ref'], ), 'data')])
        index2 = self.make_index('2', 1, nodes=[
            ('ref', ([], ), 'refdata')])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual(set([('name', (('ref',),), 'data'),
            ('ref', ((), ), 'refdata')]),
            set(index.iter_entries(['name', 'ref'])))
 
    def test_iter_all_keys_dup_entry(self):
        index1 = self.make_index('1', 1, nodes=[
            ('name', (['ref'], ), 'data'),
            ('ref', ([], ), 'refdata')])
        index2 = self.make_index('2', 1, nodes=[
            ('ref', ([], ), 'refdata')])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual(set([('name', (('ref',),), 'data'),
            ('ref', ((), ), 'refdata')]),
            set(index.iter_entries(['name', 'ref'])))
 
    def test_iter_missing_entry_empty(self):
        index = CombinedGraphIndex([])
        self.assertEqual([], list(index.iter_entries(['a'])))

    def test_iter_missing_entry_one_index(self):
        index1 = self.make_index('1')
        index = CombinedGraphIndex([index1])
        self.assertEqual([], list(index.iter_entries(['a'])))

    def test_iter_missing_entry_two_index(self):
        index1 = self.make_index('1')
        index2 = self.make_index('2')
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual([], list(index.iter_entries(['a'])))
 
    def test_iter_entry_present_one_index_only(self):
        index1 = self.make_index('1', nodes=[('key', (), '')])
        index2 = self.make_index('2', nodes=[])
        index = CombinedGraphIndex([index1, index2])
        self.assertEqual([('key', (), '')],
            list(index.iter_entries(['key'])))
        # and in the other direction
        index = CombinedGraphIndex([index2, index1])
        self.assertEqual([('key', (), '')],
            list(index.iter_entries(['key'])))

    def test_validate_bad_child_index_errors(self):
        trans = self.get_transport()
        trans.put_bytes('name', "not an index\n")
        index1 = GraphIndex(trans, 'name')
        index = CombinedGraphIndex([index1])
        self.assertRaises(errors.BadIndexFormatSignature, index.validate)

    def test_validate_empty(self):
        index = CombinedGraphIndex([])
        index.validate()


class TestInMemoryGraphIndex(TestCaseWithMemoryTransport):

    def make_index(self, ref_lists=0, nodes=[]):
        result = InMemoryGraphIndex(ref_lists)
        result.add_nodes(nodes)
        return result

    def test_add_nodes(self):
        index = self.make_index(1)
        index.add_nodes([('name', ([],), 'data')])
        index.add_nodes([('name2', ([],), ''), ('name3', (['r'],), '')])
        self.assertEqual(set([
            ('name', ((),), 'data'),
            ('name2', ((),), ''),
            ('name3', (('r',),), ''),
            ]), set(index.iter_all_entries()))

    def test_iter_all_entries_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_all_entries()))

    def test_iter_all_entries_simple(self):
        index = self.make_index(nodes=[('name', (), 'data')])
        self.assertEqual([('name', (), 'data')],
            list(index.iter_all_entries()))

    def test_iter_all_entries_references(self):
        index = self.make_index(1, nodes=[
            ('name', (['ref'], ), 'data'),
            ('ref', ([], ), 'refdata')])
        self.assertEqual(set([('name', (('ref',),), 'data'),
            ('ref', ((), ), 'refdata')]),
            set(index.iter_all_entries()))

    def test_iteration_absent_skipped(self):
        index = self.make_index(1, nodes=[
            ('name', (['ref'], ), 'data')])
        self.assertEqual(set([('name', (('ref',),), 'data')]),
            set(index.iter_all_entries()))
        self.assertEqual(set([('name', (('ref',),), 'data')]),
            set(index.iter_entries(['name'])))
        self.assertEqual([], list(index.iter_entries(['ref'])))

    def test_iter_all_keys(self):
        index = self.make_index(1, nodes=[
            ('name', (['ref'], ), 'data'),
            ('ref', ([], ), 'refdata')])
        self.assertEqual(set([('name', (('ref',),), 'data'),
            ('ref', ((), ), 'refdata')]),
            set(index.iter_entries(['name', 'ref'])))

    def test_iter_nothing_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_entries([])))

    def test_iter_missing_entry_empty(self):
        index = self.make_index()
        self.assertEqual([], list(index.iter_entries(['a'])))

    def test_validate_empty(self):
        index = self.make_index()
        index.validate()

    def test_validate_no_refs_content(self):
        index = self.make_index(nodes=[('key', (), 'value')])
        index.validate()



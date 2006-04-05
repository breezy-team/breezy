# Copyright (C) 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


import os

from bzrlib.tests import TestCaseWithTransport, TestCase
from bzrlib.branch import Branch
from bzrlib.conflicts import *
from bzrlib.errors import NotConflicted


# TODO: Test commit with some added, and added-but-missing files
# RBC 20060124 is that not tested in test_commit.py ?

example_conflicts = [ 
    ContentsConflict('patha', 'ida'), 
    TextConflict('patha'),
    PathConflict('pathb', 'pathc', 'idb'),
    DuplicateID('Unversioned existing file', 'pathc', 'pathc2', 'idc', 'idc'),
    DuplicateEntry('Moved existing file to',  'pathdd.moved', 'pathd', 'idd', 
                   None),
    ParentLoop('Cancelled move', 'pathe', 'path2e', None, 'id2e'),
    UnversionedParent('Versioned directory', 'pathf', 'idf'),
    MissingParent('Not deleting', 'pathg', 'idg'),
]


class TestConflicts(TestCaseWithTransport):

    def test_conflicts(self):
        """Conflicts are detected properly"""
        tree = self.make_branch_and_tree('.')
        b = tree.branch
        file('hello', 'w').write('hello world4')
        file('hello.THIS', 'w').write('hello world2')
        file('hello.BASE', 'w').write('hello world1')
        file('hello.OTHER', 'w').write('hello world3')
        file('hello.sploo.BASE', 'w').write('yellow world')
        file('hello.sploo.OTHER', 'w').write('yellow world2')
        self.assertEqual(len(list(tree.list_files())), 6)
        conflicts = list(tree.conflict_lines())
        self.assertEqual(len(conflicts), 2)
        self.assert_('hello' in conflicts[0].path)
        self.assert_('hello.sploo' in conflicts[1].path)
        restore('hello')
        restore('hello.sploo')
        self.assertEqual(len(list(tree.conflict_lines())), 0)
        self.assertFileEqual('hello world2', 'hello')
        assert not os.path.lexists('hello.sploo')
        self.assertRaises(NotConflicted, restore, 'hello')
        self.assertRaises(NotConflicted, restore, 'hello.sploo')


class TestConflictStanzas(TestCase):
    def test_stanza_roundtrip(self):
        processed = list(stanza_conflicts(conflict_stanzas(example_conflicts)))
        for o,p in zip(processed, example_conflicts):
            self.assertEqual(o, p)

    def test_stanzification(self):
        for stanza in conflict_stanzas(example_conflicts):
            try:
                self.assertStartsWith(stanza['file_id'], 'id')
            except KeyError:
                pass
            self.assertStartsWith(stanza['path'], 'path')
            try:
                self.assertStartsWith(stanza['conflict_file_id'], 'id')
                self.assertStartsWith(stanza['conflict_file_path'], 'path')
            except KeyError:
                pass

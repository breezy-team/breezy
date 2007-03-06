# Copyright (C) 2005 Canonical Ltd
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


import os

from bzrlib import bzrdir
from bzrlib.tests import TestCaseWithTransport, TestCase
from bzrlib.branch import Branch
from bzrlib.conflicts import (MissingParent, ContentsConflict, TextConflict,
        PathConflict, DuplicateID, DuplicateEntry, ParentLoop, UnversionedParent,
        ConflictList, 
        restore)
from bzrlib.errors import NotConflicted


# TODO: Test commit with some added, and added-but-missing files
# RBC 20060124 is that not tested in test_commit.py ?

# The order of 'path' here is important - do not let it
# be a sorted list.
# u'\xe5' == a with circle
# '\xc3\xae' == u'\xee' == i with hat
# So these are u'pathg' and 'idg' only with a circle and a hat. (shappo?)
example_conflicts = ConflictList([ 
    MissingParent('Not deleting', u'p\xe5thg', '\xc3\xaedg'),
    ContentsConflict(u'p\xe5tha', None, '\xc3\xaeda'), 
    TextConflict(u'p\xe5tha'),
    PathConflict(u'p\xe5thb', u'p\xe5thc', '\xc3\xaedb'),
    DuplicateID('Unversioned existing file', u'p\xe5thc', u'p\xe5thc2',
                '\xc3\xaedc', '\xc3\xaedc'),
    DuplicateEntry('Moved existing file to',  u'p\xe5thdd.moved', u'p\xe5thd',
                   '\xc3\xaedd', None),
    ParentLoop('Cancelled move', u'p\xe5the', u'p\xe5th2e',
               None, '\xc3\xaed2e'),
    UnversionedParent('Versioned directory', u'p\xe5thf', '\xc3\xaedf'),
])


class TestConflicts(TestCaseWithTransport):

    def test_conflicts(self):
        """Conflicts are detected properly"""
        tree = self.make_branch_and_tree('.',
            format=bzrdir.BzrDirFormat6())
        b = tree.branch
        file('hello', 'w').write('hello world4')
        file('hello.THIS', 'w').write('hello world2')
        file('hello.BASE', 'w').write('hello world1')
        file('hello.OTHER', 'w').write('hello world3')
        file('hello.sploo.BASE', 'w').write('yellow world')
        file('hello.sploo.OTHER', 'w').write('yellow world2')
        self.assertEqual(len(list(tree.list_files())), 6)
        conflicts = tree.conflicts()
        self.assertEqual(len(conflicts), 2)
        self.assert_('hello' in conflicts[0].path)
        self.assert_('hello.sploo' in conflicts[1].path)
        restore('hello')
        restore('hello.sploo')
        self.assertEqual(len(tree.conflicts()), 0)
        self.assertFileEqual('hello world2', 'hello')
        assert not os.path.lexists('hello.sploo')
        self.assertRaises(NotConflicted, restore, 'hello')
        self.assertRaises(NotConflicted, restore, 'hello.sploo')

    def test_resolve_conflict_dir(self):
        tree = self.make_branch_and_tree('.')
        b = tree.branch
        file('hello', 'w').write('hello world4')
        tree.add('hello', 'q')
        file('hello.THIS', 'w').write('hello world2')
        file('hello.BASE', 'w').write('hello world1')
        os.mkdir('hello.OTHER')
        l = ConflictList([TextConflict('hello')])
        l.remove_files(tree)


class TestConflictStanzas(TestCase):

    def test_stanza_roundtrip(self):
        # write and read our example stanza.
        stanza_iter = example_conflicts.to_stanzas()
        processed = ConflictList.from_stanzas(stanza_iter)
        for o, p in zip(processed, example_conflicts):
            self.assertEqual(o, p)

            self.assertIsInstance(o.path, unicode)

            if o.file_id is not None:
                self.assertIsInstance(o.file_id, str)

            conflict_file_path = getattr(o, 'conflict_file_path', None)
            if conflict_file_path is not None:
                self.assertIsInstance(conflict_file_path, unicode)

            conflict_file_id = getattr(o, 'conflict_file_id', None)
            if conflict_file_id is not None:
                self.assertIsInstance(conflict_file_id, str)

    def test_stanzification(self):
        for stanza in example_conflicts.to_stanzas():
            if 'file_id' in stanza:
                # In Stanza form, the file_id has to be unicode.
                self.assertStartsWith(stanza['file_id'], u'\xeed')
            self.assertStartsWith(stanza['path'], u'p\xe5th')
            if 'conflict_file_path' in stanza:
                self.assertStartsWith(stanza['conflict_file_path'], u'p\xe5th')
            if 'conflict_file_id' in stanza:
                self.assertStartsWith(stanza['conflict_file_id'], u'\xeed')

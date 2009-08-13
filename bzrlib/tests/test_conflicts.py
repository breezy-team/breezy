# Copyright (C) 2005, 2006, 2007, 2008, 2009 Canonical Ltd
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

from bzrlib import (
    bzrdir,
    conflicts,
    errors,
    tests,
    )
from bzrlib.conflicts import (
    ConflictList,
    ContentsConflict,
    DuplicateID,
    DuplicateEntry,
    MissingParent,
    NonDirectoryParent,
    ParentLoop,
    PathConflict,
    TextConflict,
    UnversionedParent,
    resolve,
    restore,
    )


# TODO: Test commit with some added, and added-but-missing files
# RBC 20060124 is that not tested in test_commit.py ?

# The order of 'path' here is important - do not let it
# be a sorted list.
# u'\xe5' == a with circle
# '\xc3\xae' == u'\xee' == i with hat
# So these are u'path' and 'id' only with a circle and a hat. (shappo?)
example_conflicts = conflicts.ConflictList(
    [conflicts.MissingParent('Not deleting', u'p\xe5thg', '\xc3\xaedg'),
     conflicts.ContentsConflict(u'p\xe5tha', None, '\xc3\xaeda'),
     conflicts.TextConflict(u'p\xe5tha'),
     conflicts.PathConflict(u'p\xe5thb', u'p\xe5thc', '\xc3\xaedb'),
     conflicts.DuplicateID('Unversioned existing file',
                           u'p\xe5thc', u'p\xe5thc2',
                           '\xc3\xaedc', '\xc3\xaedc'),
    conflicts.DuplicateEntry('Moved existing file to',
                             u'p\xe5thdd.moved', u'p\xe5thd',
                             '\xc3\xaedd', None),
    conflicts.ParentLoop('Cancelled move', u'p\xe5the', u'p\xe5th2e',
                         None, '\xc3\xaed2e'),
    conflicts.UnversionedParent('Versioned directory',
                                u'p\xe5thf', '\xc3\xaedf'),
    conflicts.NonDirectoryParent('Created directory',
                                 u'p\xe5thg', '\xc3\xaedg'),
])


class TestConflictStanzas(tests.TestCase):

    def test_stanza_roundtrip(self):
        # write and read our example stanza.
        stanza_iter = example_conflicts.to_stanzas()
        processed = conflicts.ConflictList.from_stanzas(stanza_iter)
        for o, p in zip(processed, example_conflicts):
            self.assertEqual(o, p)

            self.assertIsInstance(o.path, unicode)

            if o.file_id is not None:
                self.assertIsInstance(o.file_id, str)

            conflict_path = getattr(o, 'conflict_path', None)
            if conflict_path is not None:
                self.assertIsInstance(conflict_path, unicode)

            conflict_file_id = getattr(o, 'conflict_file_id', None)
            if conflict_file_id is not None:
                self.assertIsInstance(conflict_file_id, str)

    def test_stanzification(self):
        for stanza in example_conflicts.to_stanzas():
            if 'file_id' in stanza:
                # In Stanza form, the file_id has to be unicode.
                self.assertStartsWith(stanza['file_id'], u'\xeed')
            self.assertStartsWith(stanza['path'], u'p\xe5th')
            if 'conflict_path' in stanza:
                self.assertStartsWith(stanza['conflict_path'], u'p\xe5th')
            if 'conflict_file_id' in stanza:
                self.assertStartsWith(stanza['conflict_file_id'], u'\xeed')


class TestConflicts(tests.TestCaseWithTransport):

    def test_conflicts(self):
        """Conflicts are detected properly"""
        tree = self.make_branch_and_tree('.',
            format=bzrdir.BzrDirFormat6())
        file('hello', 'w').write('hello world4')
        file('hello.THIS', 'w').write('hello world2')
        file('hello.BASE', 'w').write('hello world1')
        file('hello.OTHER', 'w').write('hello world3')
        file('hello.sploo.BASE', 'w').write('yellow world')
        file('hello.sploo.OTHER', 'w').write('yellow world2')
        tree.lock_read()
        self.assertEqual(6, len(list(tree.list_files())))
        tree.unlock()
        conflicts = tree.conflicts()
        self.assertEqual(2, len(conflicts))
        self.assert_('hello' in conflicts[0].path)
        self.assert_('hello.sploo' in conflicts[1].path)
        restore('hello')
        restore('hello.sploo')
        self.assertEqual(0, len(tree.conflicts()))
        self.assertFileEqual('hello world2', 'hello')
        self.assertFalse(os.path.lexists('hello.sploo'))
        self.assertRaises(errors.NotConflicted, restore, 'hello')
        self.assertRaises(errors.NotConflicted, restore, 'hello.sploo')

    def test_resolve_conflict_dir(self):
        tree = self.make_branch_and_tree('.')
        file('hello', 'w').write('hello world4')
        tree.add('hello', 'q')
        file('hello.THIS', 'w').write('hello world2')
        file('hello.BASE', 'w').write('hello world1')
        os.mkdir('hello.OTHER')
        l = ConflictList([TextConflict('hello')])
        l.remove_files(tree)

    def test_select_conflicts(self):
        tree = self.make_branch_and_tree('.')
        tree_conflicts = conflicts.ConflictList(
            [conflicts.ContentsConflict('foo'),
             conflicts.ContentsConflict('bar')])
        self.assertEqual(
            (conflicts.ConflictList([conflicts.ContentsConflict('bar')]),
             conflicts.ConflictList([conflicts.ContentsConflict('foo')])),
            tree_conflicts.select_conflicts(tree, ['foo']))
        self.assertEqual((conflicts.ConflictList(), tree_conflicts),
                         tree_conflicts.select_conflicts(tree, [''],
                         ignore_misses=True, recurse=True))
        tree_conflicts = conflicts.ConflictList(
            [conflicts.ContentsConflict('foo/baz'),
             conflicts.ContentsConflict('bar')])
        self.assertEqual(
            (conflicts.ConflictList([conflicts.ContentsConflict('bar')]),
             conflicts.ConflictList([conflicts.ContentsConflict('foo/baz')])),
            tree_conflicts.select_conflicts(tree, ['foo'],
                                            recurse=True,
                                            ignore_misses=True))
        tree_conflicts = conflicts.ConflictList(
            [conflicts.PathConflict('qux', 'foo/baz')])
        self.assertEqual((conflicts.ConflictList(), tree_conflicts),
                         tree_conflicts.select_conflicts(tree, ['foo'],
                                                         recurse=True,
                                                         ignore_misses=True))
        self.assertEqual((tree_conflicts, conflicts.ConflictList()),
                         tree_conflicts.select_conflicts(tree, ['foo'],
                                                         ignore_misses=True))

    def test_resolve_conflicts_recursive(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/hello'])
        tree.add(['dir', 'dir/hello'])
        tree.set_conflicts(conflicts.ConflictList(
                [conflicts.TextConflict('dir/hello')]))
        resolve(tree, ['dir'], recursive=False, ignore_misses=True)
        self.assertEqual(conflicts.ConflictList(
                [conflicts.TextConflict('dir/hello')]),
                         tree.conflicts())
        resolve(tree, ['dir'], recursive=True, ignore_misses=True)
        self.assertEqual(conflicts.ConflictList([]),
                         tree.conflicts())



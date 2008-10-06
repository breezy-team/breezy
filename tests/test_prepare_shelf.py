# Copyright (C) 2008 Aaron Bentley <aaron@aaronbentley.com>
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import os

from bzrlib import tests
from bzrlib.plugins.shelf2 import prepare_shelf


class TestPrepareShelf(tests.TestCaseWithTransport):

    def test_shelve_rename(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        tree.add(['foo'], ['foo-id'])
        tree.commit('foo')
        tree.rename_one('foo', 'bar')
        creator = prepare_shelf.ShelfCreator(tree)
        self.addCleanup(creator.finalize)
        self.assertEqual([('rename', 'foo-id', 'foo', 'bar')], list(creator))
        creator.shelve_rename('foo-id')
        work_trans_id = creator.work_transform.trans_id_file_id('foo-id')
        self.assertEqual('foo', creator.work_transform.final_name(
                         work_trans_id))
        shelf_trans_id = creator.shelf_transform.trans_id_file_id('foo-id')
        self.assertEqual('bar', creator.shelf_transform.final_name(
                         shelf_trans_id))

    def test_shelve_move(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo/', 'bar/', 'foo/baz'])
        tree.add(['foo', 'bar', 'foo/baz'], ['foo-id', 'bar-id', 'baz-id'])
        tree.commit('foo')
        tree.rename_one('foo/baz', 'bar/baz')
        creator = prepare_shelf.ShelfCreator(tree)
        self.addCleanup(creator.finalize)
        self.assertEqual([('rename', 'baz-id', 'foo/baz', 'bar/baz')],
                         list(creator))
        creator.shelve_rename('baz-id')
        work_trans_id = creator.work_transform.trans_id_file_id('baz-id')
        work_foo = creator.work_transform.trans_id_file_id('foo-id')
        self.assertEqual(work_foo, creator.work_transform.final_parent(
                         work_trans_id))
        shelf_trans_id = creator.shelf_transform.trans_id_file_id('baz-id')
        shelf_bar = creator.shelf_transform.trans_id_file_id('bar-id')
        self.assertEqual(shelf_bar, creator.shelf_transform.final_parent(
                         shelf_trans_id))
        creator.transform()
        self.assertEqual('foo/baz', tree.id2path('baz-id'))

    def assertShelvedFileEqual(self, expected_content, creator, file_id):
        s_trans_id = creator.shelf_transform.trans_id_file_id(file_id)
        shelf_file = creator.shelf_transform._limbo_name(s_trans_id)
        self.assertFileEqual(expected_content, shelf_file)

    def test_shelve_content_change(self):
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree_contents([('foo', 'a\n')])
        tree.add('foo', 'foo-id')
        tree.commit('Committed foo')
        self.build_tree_contents([('foo', 'b\na\nc\n')])
        creator = prepare_shelf.ShelfCreator(tree)
        self.addCleanup(creator.finalize)
        self.assertEqual([('modify text', 'foo-id')], list(creator))
        creator.shelve_text('foo-id', 'a\nc\n')
        creator.transform()
        self.assertFileEqual('a\nc\n', 'foo')
        self.assertShelvedFileEqual('b\na\n', creator, 'foo-id')

    def test_shelve_creation(self):
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit('Empty tree')
        self.build_tree_contents([('foo', 'a\n'), ('bar/',)])
        tree.add(['foo', 'bar'], ['foo-id', 'bar-id'])
        creator = prepare_shelf.ShelfCreator(tree)
        self.addCleanup(creator.finalize)
        self.assertEqual([('add file', 'bar-id', 'directory'),
                          ('add file', 'foo-id', 'file')],
                          sorted(list(creator)))
        creator.shelve_creation('foo-id', 'file')
        creator.shelve_creation('bar-id', 'directory')
        creator.transform()
        self.assertRaises(StopIteration,
                          tree.iter_entries_by_dir(['foo-id']).next)
        s_trans_id = creator.shelf_transform.trans_id_file_id('foo-id')
        self.assertEqual('foo-id',
                         creator.shelf_transform.final_file_id(s_trans_id))
        self.failIfExists('foo')
        self.failIfExists('bar')
        self.assertShelvedFileEqual('a\n', creator, 'foo-id')
        s_bar_trans_id = creator.shelf_transform.trans_id_file_id('bar-id')
        self.assertEqual('directory',
            creator.shelf_transform.final_kind(s_bar_trans_id))

    def test_shelve_symlink_creation(self):
        self.requireFeature(tests.SymlinkFeature)
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit('Empty tree')
        os.symlink('bar', 'foo')
        tree.add('foo', 'foo-id')
        creator = prepare_shelf.ShelfCreator(tree)
        self.addCleanup(creator.finalize)
        self.assertEqual([('add file', 'foo-id', 'symlink')], list(creator))
        creator.shelve_creation('foo-id', 'symlink')
        creator.transform()
        s_trans_id = creator.shelf_transform.trans_id_file_id('foo-id')
        self.failIfExists('foo')
        limbo_name = creator.shelf_transform._limbo_name(s_trans_id)
        self.assertEqual('bar', os.readlink(limbo_name))

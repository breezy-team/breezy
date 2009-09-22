# Copyright (C) 2008 Canonical Ltd
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


from cStringIO import StringIO
import os
import sys

from bzrlib import (
    errors,
    shelf_ui,
    revision,
    tests,
)


class ExpectShelver(shelf_ui.Shelver):
    """A variant of Shelver that intercepts console activity, for testing."""

    def __init__(self, work_tree, target_tree, diff_writer=None,
                 auto=False, auto_apply=False, file_list=None, message=None,
                 destroy=False, reporter=None):
        shelf_ui.Shelver.__init__(self, work_tree, target_tree, diff_writer,
                                  auto, auto_apply, file_list, message,
                                  destroy, reporter=reporter)
        self.expected = []
        self.diff_writer = StringIO()

    def expect(self, prompt, response):
        self.expected.append((prompt, response))

    def prompt(self, message):
        try:
            prompt, response = self.expected.pop(0)
        except IndexError:
            raise AssertionError('Unexpected prompt: %s' % message)
        if prompt != message:
            raise AssertionError('Wrong prompt: %s' % message)
        return response


LINES_AJ = 'a\nb\nc\nd\ne\nf\ng\nh\ni\nj\n'


LINES_ZY = 'z\nb\nc\nd\ne\nf\ng\nh\ni\ny\n'


LINES_AY = 'a\nb\nc\nd\ne\nf\ng\nh\ni\ny\n'


class TestShelver(tests.TestCaseWithTransport):

    def create_shelvable_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/foo', LINES_AJ)])
        tree.add('foo', 'foo-id')
        tree.commit('added foo')
        self.build_tree_contents([('tree/foo', LINES_ZY)])
        return tree

    def test_unexpected_prompt_failure(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        e = self.assertRaises(AssertionError, shelver.run)
        self.assertEqual('Unexpected prompt: Shelve? [yNfq?]', str(e))

    def test_wrong_prompt_failure(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('foo', 'y')
        e = self.assertRaises(AssertionError, shelver.run)
        self.assertEqual('Wrong prompt: Shelve? [yNfq?]', str(e))

    def test_shelve_not_diff(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve? [yNfq?]', 'n')
        shelver.expect('Shelve? [yNfq?]', 'n')
        # No final shelving prompt because no changes were selected
        shelver.run()
        self.assertFileEqual(LINES_ZY, 'tree/foo')

    def test_shelve_diff_no(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve? [yNfq?]', 'y')
        shelver.expect('Shelve? [yNfq?]', 'y')
        shelver.expect('Shelve 2 change(s)? [yNfq?]', 'n')
        shelver.run()
        self.assertFileEqual(LINES_ZY, 'tree/foo')

    def test_shelve_diff(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve? [yNfq?]', 'y')
        shelver.expect('Shelve? [yNfq?]', 'y')
        shelver.expect('Shelve 2 change(s)? [yNfq?]', 'y')
        shelver.run()
        self.assertFileEqual(LINES_AJ, 'tree/foo')

    def test_shelve_one_diff(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve? [yNfq?]', 'y')
        shelver.expect('Shelve? [yNfq?]', 'n')
        shelver.expect('Shelve 1 change(s)? [yNfq?]', 'y')
        shelver.run()
        self.assertFileEqual(LINES_AY, 'tree/foo')

    def test_shelve_binary_change(self):
        tree = self.create_shelvable_tree()
        self.build_tree_contents([('tree/foo', '\x00')])
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve binary changes? [yNfq?]', 'y')
        shelver.expect('Shelve 1 change(s)? [yNfq?]', 'y')
        shelver.run()
        self.assertFileEqual(LINES_AJ, 'tree/foo')

    def test_shelve_rename(self):
        tree = self.create_shelvable_tree()
        tree.rename_one('foo', 'bar')
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve renaming "foo" => "bar"? [yNfq?]', 'y')
        shelver.expect('Shelve? [yNfq?]', 'y')
        shelver.expect('Shelve? [yNfq?]', 'y')
        shelver.expect('Shelve 3 change(s)? [yNfq?]', 'y')
        shelver.run()
        self.assertFileEqual(LINES_AJ, 'tree/foo')

    def test_shelve_deletion(self):
        tree = self.create_shelvable_tree()
        os.unlink('tree/foo')
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve removing file "foo"? [yNfq?]', 'y')
        shelver.expect('Shelve 1 change(s)? [yNfq?]', 'y')
        shelver.run()
        self.assertFileEqual(LINES_AJ, 'tree/foo')

    def test_shelve_creation(self):
        tree = self.make_branch_and_tree('tree')
        tree.commit('add tree root')
        self.build_tree(['tree/foo'])
        tree.add('foo')
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve adding file "foo"? [yNfq?]', 'y')
        shelver.expect('Shelve 1 change(s)? [yNfq?]', 'y')
        shelver.run()
        self.failIfExists('tree/foo')

    def test_shelve_kind_change(self):
        tree = self.create_shelvable_tree()
        os.unlink('tree/foo')
        os.mkdir('tree/foo')
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve changing "foo" from file to directory? [yNfq?]',
                       'y')
        shelver.expect('Shelve 1 change(s)? [yNfq?]', 'y')

    def test_shelve_modify_target(self):
        self.requireFeature(tests.SymlinkFeature)
        tree = self.create_shelvable_tree()
        os.symlink('bar', 'tree/baz')
        tree.add('baz', 'baz-id')
        tree.commit("Add symlink")
        os.unlink('tree/baz')
        os.symlink('vax', 'tree/baz')
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve changing target of "baz" from "bar" to '
                '"vax"? [yNfq?]', 'y')
        shelver.expect('Shelve 1 change(s)? [yNfq?]', 'y')
        shelver.run()
        self.assertEqual('bar', os.readlink('tree/baz'))

    def test_shelve_finish(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve? [yNfq?]', 'f')
        shelver.expect('Shelve 2 change(s)? [yNfq?]', 'y')
        shelver.run()
        self.assertFileEqual(LINES_AJ, 'tree/foo')

    def test_shelve_quit(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve? [yNfq?]', 'q')
        self.assertRaises(errors.UserAbort, shelver.run)
        self.assertFileEqual(LINES_ZY, 'tree/foo')

    def test_shelve_all(self):
        tree = self.create_shelvable_tree()
        shelver = ExpectShelver.from_args(sys.stdout, all=True,
            directory='tree')
        try:
            shelver.run()
        finally:
            shelver.work_tree.unlock()
        self.assertFileEqual(LINES_AJ, 'tree/foo')

    def test_shelve_filename(self):
        tree = self.create_shelvable_tree()
        self.build_tree(['tree/bar'])
        tree.add('bar')
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree(), file_list=['bar'])
        shelver.expect('Shelve adding file "bar"? [yNfq?]', 'y')
        shelver.expect('Shelve 1 change(s)? [yNfq?]', 'y')
        shelver.run()

    def test_shelve_help(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree())
        shelver.expect('Shelve? [yNfq?]', '?')
        shelver.expect('Shelve? [(y)es, (N)o, (f)inish, or (q)uit]', 'f')
        shelver.expect('Shelve 2 change(s)? [yNfq?]', 'y')
        shelver.run()

    def test_shelve_distroy(self):
        tree = self.create_shelvable_tree()
        shelver = shelf_ui.Shelver.from_args(sys.stdout, all=True,
                                             directory='tree', destroy=True)
        try:
            shelver.run()
        finally:
            shelver.work_tree.unlock()
        self.assertIs(None, tree.get_shelf_manager().last_shelf())
        self.assertFileEqual(LINES_AJ, 'tree/foo')

    @staticmethod
    def shelve_all(tree, target_revision_id):
        tree.lock_write()
        try:
            target = tree.branch.repository.revision_tree(target_revision_id)
            shelver = shelf_ui.Shelver(tree, target, auto=True,
                                       auto_apply=True)
            shelver.run()
        finally:
            tree.unlock()

    def test_shelve_old_root_deleted(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree1.commit('add root')
        tree2 = self.make_branch_and_tree('tree2')
        rev2 = tree2.commit('add root')
        tree1.merge_from_branch(tree2.branch,
                                from_revision=revision.NULL_REVISION)
        tree1.commit('Replaced root entry')
        # This is essentially assertNotRaises(InconsistentDelta)
        self.expectFailure('Cannot shelve replacing a root entry',
                           self.assertRaises, AssertionError,
                           self.assertRaises, errors.InconsistentDelta,
                           self.shelve_all, tree1, rev2)

    def test_shelve_split(self):
        outer_tree = self.make_branch_and_tree('outer')
        outer_tree.commit('Add root')
        inner_tree = self.make_branch_and_tree('outer/inner')
        rev2 = inner_tree.commit('Add root')
        outer_tree.subsume(inner_tree)
        # This is essentially assertNotRaises(ValueError).
        # The ValueError is 'None is not a valid file id'.
        self.expectFailure('Cannot shelve a join back to the inner tree.',
                           self.assertRaises, AssertionError,
                           self.assertRaises, ValueError, self.shelve_all,
                           outer_tree, rev2)


class TestApplyReporter(TestShelver):

    def test_shelve_not_diff(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree(),
                                reporter=shelf_ui.ApplyReporter())
        shelver.expect('Apply change? [yNfq?]', 'n')
        shelver.expect('Apply change? [yNfq?]', 'n')
        # No final shelving prompt because no changes were selected
        shelver.run()
        self.assertFileEqual(LINES_ZY, 'tree/foo')

    def test_shelve_diff_no(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree(),
                                reporter=shelf_ui.ApplyReporter())
        shelver.expect('Apply change? [yNfq?]', 'y')
        shelver.expect('Apply change? [yNfq?]', 'y')
        shelver.expect('Apply 2 change(s)? [yNfq?]', 'n')
        shelver.run()
        self.assertFileEqual(LINES_ZY, 'tree/foo')

    def test_shelve_diff(self):
        tree = self.create_shelvable_tree()
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree(),
                                reporter=shelf_ui.ApplyReporter())
        shelver.expect('Apply change? [yNfq?]', 'y')
        shelver.expect('Apply change? [yNfq?]', 'y')
        shelver.expect('Apply 2 change(s)? [yNfq?]', 'y')
        shelver.run()
        self.assertFileEqual(LINES_AJ, 'tree/foo')

    def test_shelve_binary_change(self):
        tree = self.create_shelvable_tree()
        self.build_tree_contents([('tree/foo', '\x00')])
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree(),
                                reporter=shelf_ui.ApplyReporter())
        shelver.expect('Apply binary changes? [yNfq?]', 'y')
        shelver.expect('Apply 1 change(s)? [yNfq?]', 'y')
        shelver.run()
        self.assertFileEqual(LINES_AJ, 'tree/foo')

    def test_shelve_rename(self):
        tree = self.create_shelvable_tree()
        tree.rename_one('foo', 'bar')
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree(),
                                reporter=shelf_ui.ApplyReporter())
        shelver.expect('Rename "bar" => "foo"? [yNfq?]', 'y')
        shelver.expect('Apply change? [yNfq?]', 'y')
        shelver.expect('Apply change? [yNfq?]', 'y')
        shelver.expect('Apply 3 change(s)? [yNfq?]', 'y')
        shelver.run()
        self.assertFileEqual(LINES_AJ, 'tree/foo')

    def test_shelve_deletion(self):
        tree = self.create_shelvable_tree()
        os.unlink('tree/foo')
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree(),
                                reporter=shelf_ui.ApplyReporter())
        shelver.expect('Add file "foo"? [yNfq?]', 'y')
        shelver.expect('Apply 1 change(s)? [yNfq?]', 'y')
        shelver.run()
        self.assertFileEqual(LINES_AJ, 'tree/foo')

    def test_shelve_creation(self):
        tree = self.make_branch_and_tree('tree')
        tree.commit('add tree root')
        self.build_tree(['tree/foo'])
        tree.add('foo')
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree(),
                                reporter=shelf_ui.ApplyReporter())
        shelver.expect('Delete file "foo"? [yNfq?]', 'y')
        shelver.expect('Apply 1 change(s)? [yNfq?]', 'y')
        shelver.run()
        self.failIfExists('tree/foo')

    def test_shelve_kind_change(self):
        tree = self.create_shelvable_tree()
        os.unlink('tree/foo')
        os.mkdir('tree/foo')
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree(),
                               reporter=shelf_ui.ApplyReporter())
        shelver.expect('Change "foo" from directory to a file? [yNfq?]', 'y')
        shelver.expect('Apply 1 change(s)? [yNfq?]', 'y')

    def test_shelve_modify_target(self):
        self.requireFeature(tests.SymlinkFeature)
        tree = self.create_shelvable_tree()
        os.symlink('bar', 'tree/baz')
        tree.add('baz', 'baz-id')
        tree.commit("Add symlink")
        os.unlink('tree/baz')
        os.symlink('vax', 'tree/baz')
        tree.lock_tree_write()
        self.addCleanup(tree.unlock)
        shelver = ExpectShelver(tree, tree.basis_tree(),
                                reporter=shelf_ui.ApplyReporter())
        shelver.expect('Change target of "baz" from "vax" to "bar"? [yNfq?]',
                       'y')
        shelver.expect('Apply 1 change(s)? [yNfq?]', 'y')
        shelver.run()
        self.assertEqual('bar', os.readlink('tree/baz'))


class TestUnshelver(tests.TestCaseWithTransport):

    def create_tree_with_shelf(self):
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        try:
            self.build_tree_contents([('tree/foo', LINES_AJ)])
            tree.add('foo', 'foo-id')
            tree.commit('added foo')
            self.build_tree_contents([('tree/foo', LINES_ZY)])
            shelf_ui.Shelver(tree, tree.basis_tree(), auto_apply=True,
                             auto=True).run()
        finally:
            tree.unlock()
        return tree

    def test_unshelve(self):
        tree = self.create_tree_with_shelf()
        tree.lock_write()
        self.addCleanup(tree.unlock)
        manager = tree.get_shelf_manager()
        shelf_ui.Unshelver(tree, manager, 1, True, True, True).run()
        self.assertFileEqual(LINES_ZY, 'tree/foo')

    def test_unshelve_args(self):
        tree = self.create_tree_with_shelf()
        unshelver = shelf_ui.Unshelver.from_args(directory='tree')
        try:
            unshelver.run()
        finally:
            unshelver.tree.unlock()
        self.assertFileEqual(LINES_ZY, 'tree/foo')
        self.assertIs(None, tree.get_shelf_manager().last_shelf())

    def test_unshelve_args_dry_run(self):
        tree = self.create_tree_with_shelf()
        unshelver = shelf_ui.Unshelver.from_args(directory='tree',
            action='dry-run')
        try:
            unshelver.run()
        finally:
            unshelver.tree.unlock()
        self.assertFileEqual(LINES_AJ, 'tree/foo')
        self.assertEqual(1, tree.get_shelf_manager().last_shelf())

    def test_unshelve_args_delete_only(self):
        tree = self.make_branch_and_tree('tree')
        manager = tree.get_shelf_manager()
        shelf_file = manager.new_shelf()[1]
        try:
            shelf_file.write('garbage')
        finally:
            shelf_file.close()
        unshelver = shelf_ui.Unshelver.from_args(directory='tree',
                                                 action='delete-only')
        try:
            unshelver.run()
        finally:
            unshelver.tree.unlock()
        self.assertIs(None, manager.last_shelf())

    def test_unshelve_args_invalid_shelf_id(self):
        tree = self.make_branch_and_tree('tree')
        manager = tree.get_shelf_manager()
        shelf_file = manager.new_shelf()[1]
        try:
            shelf_file.write('garbage')
        finally:
            shelf_file.close()
        self.assertRaises(errors.InvalidShelfId,
            shelf_ui.Unshelver.from_args, directory='tree',
            action='delete-only', shelf_id='foo')

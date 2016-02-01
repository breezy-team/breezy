# Copyright (C) 2006-2012, 2016 Canonical Ltd
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

"""Tests for repository commit builder."""

import os

from bzrlib import (
    config,
    errors,
    inventory,
    osutils,
    repository,
    revision as _mod_revision,
    tests,
    )
from bzrlib.tests import per_repository
from bzrlib.tests import (
    features,
    )


class TestCommitBuilder(per_repository.TestCaseWithRepository):

    def test_get_commit_builder(self):
        branch = self.make_branch('.')
        branch.repository.lock_write()
        builder = branch.repository.get_commit_builder(
            branch, [], branch.get_config_stack())
        self.assertIsInstance(builder, repository.CommitBuilder)
        self.assertTrue(builder.random_revid)
        branch.repository.commit_write_group()
        branch.repository.unlock()

    def record_root(self, builder, tree):
        if builder.record_root_entry is True:
            tree.lock_read()
            try:
                ie = tree.root_inventory.root
            finally:
                tree.unlock()
            parent_tree = tree.branch.repository.revision_tree(
                              _mod_revision.NULL_REVISION)
            parent_invs = []
            builder.record_entry_contents(ie, parent_invs, '', tree,
                tree.path_content_summary(''))

    def test_finish_inventory_with_record_root(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            builder = tree.branch.get_commit_builder([])
            if not builder.supports_record_entry_contents:
                raise tests.TestNotApplicable("CommitBuilder doesn't support "
                    "record_entry_contents")
            repo = tree.branch.repository
            self.record_root(builder, tree)
            builder.finish_inventory()
            repo.commit_write_group()
        finally:
            tree.unlock()

    def test_finish_inventory_record_iter_changes(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            builder = tree.branch.get_commit_builder([])
            try:
                list(builder.record_iter_changes(tree, tree.last_revision(),
                    tree.iter_changes(tree.basis_tree())))
                builder.finish_inventory()
            except:
                builder.abort()
                raise
            repo = tree.branch.repository
            repo.commit_write_group()
        finally:
            tree.unlock()

    def test_abort_record_entry_contents(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            builder = tree.branch.get_commit_builder([])
            if not builder.supports_record_entry_contents:
                raise tests.TestNotApplicable("CommitBuilder doesn't support "
                    "record_entry_contents")
            self.record_root(builder, tree)
            builder.finish_inventory()
            builder.abort()
        finally:
            tree.unlock()

    def test_abort_record_iter_changes(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            builder = tree.branch.get_commit_builder([])
            try:
                basis = tree.basis_tree()
                last_rev = tree.last_revision()
                changes = tree.iter_changes(basis)
                list(builder.record_iter_changes(tree, last_rev, changes))
                builder.finish_inventory()
            finally:
                builder.abort()
        finally:
            tree.unlock()

    def test_commit_lossy(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            builder = tree.branch.get_commit_builder([], lossy=True)
            list(builder.record_iter_changes(tree, tree.last_revision(),
                tree.iter_changes(tree.basis_tree())))
            builder.finish_inventory()
            rev_id = builder.commit('foo bar blah')
        finally:
            tree.unlock()
        rev = tree.branch.repository.get_revision(rev_id)
        self.assertEqual('foo bar blah', rev.message)

    def test_commit_message(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            builder = tree.branch.get_commit_builder([])
            list(builder.record_iter_changes(tree, tree.last_revision(),
                tree.iter_changes(tree.basis_tree())))
            builder.finish_inventory()
            rev_id = builder.commit('foo bar blah')
        finally:
            tree.unlock()
        rev = tree.branch.repository.get_revision(rev_id)
        self.assertEqual('foo bar blah', rev.message)

    def test_updates_branch(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            builder = tree.branch.get_commit_builder([])
            list(builder.record_iter_changes(tree, tree.last_revision(),
                tree.iter_changes(tree.basis_tree())))
            builder.finish_inventory()
            will_update_branch = builder.updates_branch
            rev_id = builder.commit('might update the branch')
        finally:
            tree.unlock()
        actually_updated_branch = (tree.branch.last_revision() == rev_id)
        self.assertEqual(actually_updated_branch, will_update_branch)

    def test_commit_with_revision_id_record_entry_contents(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            # use a unicode revision id to test more corner cases.
            # The repository layer is meant to handle this.
            revision_id = u'\xc8abc'.encode('utf8')
            try:
                try:
                    builder = tree.branch.get_commit_builder([],
                        revision_id=revision_id)
                except errors.NonAsciiRevisionId:
                    revision_id = 'abc'
                    builder = tree.branch.get_commit_builder([],
                        revision_id=revision_id)
            except errors.CannotSetRevisionId:
                # This format doesn't support supplied revision ids
                return
            if not builder.supports_record_entry_contents:
                raise tests.TestNotApplicable("CommitBuilder doesn't support "
                    "record_entry_contents")
            self.assertFalse(builder.random_revid)
            self.record_root(builder, tree)
            builder.finish_inventory()
            self.assertEqual(revision_id, builder.commit('foo bar'))
        finally:
            tree.unlock()
        self.assertTrue(tree.branch.repository.has_revision(revision_id))
        # the revision id must be set on the inventory when saving it. This
        # does not precisely test that - a repository that wants to can add it
        # on deserialisation, but thats all the current contract guarantees
        # anyway.
        self.assertEqual(revision_id,
            tree.branch.repository.get_inventory(revision_id).revision_id)

    def test_commit_with_revision_id_record_iter_changes(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            # use a unicode revision id to test more corner cases.
            # The repository layer is meant to handle this.
            revision_id = u'\xc8abc'.encode('utf8')
            try:
                try:
                    builder = tree.branch.get_commit_builder([],
                        revision_id=revision_id)
                except errors.NonAsciiRevisionId:
                    revision_id = 'abc'
                    builder = tree.branch.get_commit_builder([],
                        revision_id=revision_id)
            except errors.CannotSetRevisionId:
                # This format doesn't support supplied revision ids
                return
            self.assertFalse(builder.random_revid)
            try:
                list(builder.record_iter_changes(tree, tree.last_revision(),
                    tree.iter_changes(tree.basis_tree())))
                builder.finish_inventory()
            except:
                builder.abort()
                raise
            self.assertEqual(revision_id, builder.commit('foo bar'))
        finally:
            tree.unlock()
        self.assertTrue(tree.branch.repository.has_revision(revision_id))
        # the revision id must be set on the inventory when saving it. This
        # does not precisely test that - a repository that wants to can add it
        # on deserialisation, but thats all the current contract guarantees
        # anyway.
        self.assertEqual(revision_id,
            tree.branch.repository.revision_tree(revision_id).get_revision_id())

    def test_commit_without_root_errors(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            builder = tree.branch.get_commit_builder([])
            def do_commit():
                try:
                    list(builder.record_iter_changes(
                        tree, tree.last_revision(), []))
                    builder.finish_inventory()
                except:
                    builder.abort()
                    raise
                else:
                    builder.commit("msg")
            self.assertRaises(errors.RootMissing, do_commit)
        finally:
            tree.unlock()

    def test_commit_without_root_or_record_iter_changes_errors(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            self.build_tree(['foo'])
            tree.add('foo', 'foo-id')
            builder = tree.branch.get_commit_builder([])
            if not builder.supports_record_entry_contents:
                raise tests.TestNotApplicable("CommitBuilder doesn't support "
                    "record_entry_contents")
            entry = tree.root_inventory['foo-id']
            self.assertRaises(errors.RootMissing,
                builder.record_entry_contents, entry, [], 'foo', tree,
                    tree.path_content_summary('foo'))
            builder.abort()
        finally:
            tree.unlock()

    def test_commit_unchanged_root_record_entry_contents(self):
        tree = self.make_branch_and_tree(".")
        old_revision_id = tree.commit('')
        tree.lock_write()
        parent_tree = tree.basis_tree()
        parent_tree.lock_read()
        self.addCleanup(parent_tree.unlock)
        builder = tree.branch.get_commit_builder([old_revision_id])
        try:
            if not builder.supports_record_entry_contents:
                raise tests.TestNotApplicable("CommitBuilder doesn't support "
                    "record_entry_contents")
            builder.will_record_deletes()
            ie = inventory.make_entry('directory', '', None,
                    tree.get_root_id())
            delta, version_recorded, fs_hash = builder.record_entry_contents(
                ie, [parent_tree.root_inventory], '', tree,
                tree.path_content_summary(''))
            # Regardless of repository root behaviour we should consider this a
            # pointless commit.
            self.assertFalse(builder.any_changes())
            self.assertFalse(version_recorded)
            # if the repository format recorded a new root revision, that
            # should be in the delta
            got_new_revision = ie.revision != old_revision_id
            if got_new_revision:
                self.assertEqual(('', '', ie.file_id, ie), delta)
                # The delta should be tracked
                self.assertEqual(delta, builder.get_basis_delta()[-1])
            else:
                self.assertEqual(None, delta)
            # Directories do not get hashed.
            self.assertEqual(None, fs_hash)
            builder.abort()
        except:
            builder.abort()
            tree.unlock()
            raise
        else:
            tree.unlock()

    def test_commit_unchanged_root_record_iter_changes(self):
        tree = self.make_branch_and_tree(".")
        old_revision_id = tree.commit('')
        tree.lock_write()
        builder = tree.branch.get_commit_builder([old_revision_id])
        try:
            list(builder.record_iter_changes(tree, old_revision_id, []))
            # Regardless of repository root behaviour we should consider this a
            # pointless commit.
            self.assertFalse(builder.any_changes())
            builder.finish_inventory()
            builder.commit('')
            builder_tree = builder.revision_tree()
            new_root_id = builder_tree.get_root_id()
            new_root_revision = builder_tree.get_file_revision(new_root_id)
            if tree.branch.repository.supports_rich_root():
                # We should not have seen a new root revision
                self.assertEqual(old_revision_id, new_root_revision)
            else:
                # We should see a new root revision
                self.assertNotEqual(old_revision_id, new_root_revision)
        finally:
            tree.unlock()

    def test_commit_record_entry_contents(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            builder = tree.branch.get_commit_builder([])
            if not builder.supports_record_entry_contents:
                raise tests.TestNotApplicable("CommitBuilder doesn't "
                    "support record_entry_contents")
            self.record_root(builder, tree)
            builder.finish_inventory()
            rev_id = builder.commit('foo bar')
        finally:
            tree.unlock()
        self.assertNotEqual(None, rev_id)
        self.assertTrue(tree.branch.repository.has_revision(rev_id))
        # the revision id must be set on the inventory when saving it. This does not
        # precisely test that - a repository that wants to can add it on deserialisation,
        # but thats all the current contract guarantees anyway.
        self.assertEqual(rev_id, tree.branch.repository.get_inventory(rev_id).revision_id)

    def test_get_basis_delta(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["foo"])
        tree.add(["foo"], ["foo-id"])
        old_revision_id = tree.commit("added foo")
        tree.lock_write()
        try:
            self.build_tree(['bar'])
            tree.add(['bar'], ['bar-id'])
            basis = tree.branch.repository.revision_tree(old_revision_id)
            basis.lock_read()
            self.addCleanup(basis.unlock)
            builder = tree.branch.get_commit_builder([old_revision_id])
            total_delta = []
            try:
                if not builder.supports_record_entry_contents:
                    raise tests.TestNotApplicable("CommitBuilder doesn't "
                        "support record_entry_contents")
                parent_invs = [basis.root_inventory]
                builder.will_record_deletes()
                if builder.record_root_entry:
                    ie = basis.root_inventory.root.copy()
                    delta, _, _ = builder.record_entry_contents(ie, parent_invs,
                        '', tree, tree.path_content_summary(''))
                    if delta is not None:
                        total_delta.append(delta)
                delta = builder.record_delete("foo", "foo-id")
                total_delta.append(delta)
                new_bar = inventory.make_entry('file', 'bar',
                    parent_id=tree.get_root_id(), file_id='bar-id')
                delta, _, _ = builder.record_entry_contents(new_bar, parent_invs,
                    'bar', tree, tree.path_content_summary('bar'))
                total_delta.append(delta)
                # All actions should have been recorded in the basis_delta
                self.assertEqual(total_delta, builder.get_basis_delta())
                builder.finish_inventory()
                builder.commit('delete foo, add bar')
            except:
                tree.branch.repository.abort_write_group()
                raise
        finally:
            tree.unlock()

    def test_get_basis_delta_without_notification(self):
        tree = self.make_branch_and_tree(".")
        old_revision_id = tree.commit('')
        tree.lock_write()
        try:
            parent_tree = tree.basis_tree()
            parent_tree.lock_read()
            self.addCleanup(parent_tree.unlock)
            builder = tree.branch.get_commit_builder([old_revision_id])
            # It is an error to expect builder.get_basis_delta() to be correct,
            # if you have not also called will_record_deletes() to indicate you
            # will be calling record_delete() when appropriate
            self.assertRaises(AssertionError, builder.get_basis_delta)
            tree.branch.repository.abort_write_group()
        finally:
            tree.unlock()

    def test_record_delete(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["foo"])
        tree.add(["foo"], ["foo-id"])
        rev_id = tree.commit("added foo")
        # Remove the inventory details for foo-id, because
        # record_entry_contents ends up copying root verbatim.
        tree.unversion(["foo-id"])
        tree.lock_write()
        try:
            basis = tree.branch.repository.revision_tree(rev_id)
            builder = tree.branch.get_commit_builder([rev_id])
            try:
                if not builder.supports_record_entry_contents:
                    raise tests.TestNotApplicable("CommitBuilder doesn't "
                        "support record_entry_contents")
                builder.will_record_deletes()
                if builder.record_root_entry is True:
                    parent_invs = [basis.root_inventory]
                    del basis.root_inventory.root.children['foo']
                    builder.record_entry_contents(basis.root_inventory.root,
                        parent_invs, '', tree, tree.path_content_summary(''))
                # the delta should be returned, and recorded in _basis_delta
                delta = builder.record_delete("foo", "foo-id")
                self.assertEqual(("foo", None, "foo-id", None), delta)
                self.assertEqual(delta, builder.get_basis_delta()[-1])
                builder.finish_inventory()
                rev_id2 = builder.commit('delete foo')
            except:
                tree.branch.repository.abort_write_group()
                raise
        finally:
            tree.unlock()
        rev_tree = builder.revision_tree()
        rev_tree.lock_read()
        self.addCleanup(rev_tree.unlock)
        self.assertFalse(rev_tree.path2id('foo'))

    def test_record_delete_record_iter_changes(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["foo"])
        tree.add(["foo"], ["foo-id"])
        rev_id = tree.commit("added foo")
        tree.lock_write()
        try:
            builder = tree.branch.get_commit_builder([rev_id])
            try:
                builder.will_record_deletes()
                delete_change = ('foo-id', ('foo', None), True, (True, False),
                    (tree.path2id(''), None), ('foo', None), ('file', None),
                    (False, None))
                list(builder.record_iter_changes(tree, rev_id,
                    [delete_change]))
                self.assertEqual(("foo", None, "foo-id", None),
                    builder.get_basis_delta()[0])
                self.assertTrue(builder.any_changes())
                builder.finish_inventory()
                rev_id2 = builder.commit('delete foo')
            except:
                builder.abort()
                raise
        finally:
            tree.unlock()
        rev_tree = builder.revision_tree()
        rev_tree.lock_read()
        self.addCleanup(rev_tree.unlock)
        self.assertFalse(rev_tree.path2id('foo'))

    def test_record_delete_without_notification(self):
        tree = self.make_branch_and_tree(".")
        self.build_tree(["foo"])
        tree.add(["foo"], ["foo-id"])
        rev_id = tree.commit("added foo")
        tree.lock_write()
        try:
            builder = tree.branch.get_commit_builder([rev_id])
            try:
                if not builder.supports_record_entry_contents:
                    raise tests.TestNotApplicable("CommitBuilder doesn't "
                        "support record_entry_contents")
                self.record_root(builder, tree)
                self.assertRaises(AssertionError,
                    builder.record_delete, "foo", "foo-id")
            finally:
                tree.branch.repository.abort_write_group()
        finally:
            tree.unlock()

    def test_revision_tree_record_entry_contents(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            builder = tree.branch.get_commit_builder([])
            if not builder.supports_record_entry_contents:
                raise tests.TestNotApplicable("CommitBuilder doesn't "
                    "support record_entry_contents")
            self.record_root(builder, tree)
            builder.finish_inventory()
            rev_id = builder.commit('foo bar')
        finally:
            tree.unlock()
        rev_tree = builder.revision_tree()
        # Just a couple simple tests to ensure that it actually follows
        # the RevisionTree api.
        self.assertEqual(rev_id, rev_tree.get_revision_id())
        self.assertEqual([], rev_tree.get_parent_ids())

    def test_revision_tree_record_iter_changes(self):
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            builder = tree.branch.get_commit_builder([])
            try:
                list(builder.record_iter_changes(tree,
                    _mod_revision.NULL_REVISION,
                    tree.iter_changes(tree.basis_tree())))
                builder.finish_inventory()
                rev_id = builder.commit('foo bar')
            except:
                builder.abort()
                raise
            rev_tree = builder.revision_tree()
            # Just a couple simple tests to ensure that it actually follows
            # the RevisionTree api.
            self.assertEqual(rev_id, rev_tree.get_revision_id())
            self.assertEqual((), tuple(rev_tree.get_parent_ids()))
        finally:
            tree.unlock()

    def test_root_entry_has_revision(self):
        # test the root revision created and put in the basis
        # has the right rev id.
        # XXX: RBC 20081118 - this test is too big, it depends on the exact
        # behaviour of tree methods and so on; it should be written to the
        # commit builder interface directly.
        tree = self.make_branch_and_tree('.')
        rev_id = tree.commit('message')
        basis_tree = tree.basis_tree()
        basis_tree.lock_read()
        self.addCleanup(basis_tree.unlock)
        self.assertEqual(rev_id,
            basis_tree.get_file_revision(basis_tree.get_root_id()))

    def _get_revtrees(self, tree, revision_ids):
        tree.lock_read()
        try:
            trees = list(tree.branch.repository.revision_trees(revision_ids))
            for _tree in trees:
                _tree.lock_read()
                self.addCleanup(_tree.unlock)
            return trees
        finally:
            tree.unlock()

    def test_last_modified_revision_after_commit_root_unchanged(self):
        # commiting without changing the root does not change the
        # last modified except on non-rich-root-repositories.
        tree = self.make_branch_and_tree('.')
        rev1 = tree.commit('')
        rev2 = tree.commit('')
        tree1, tree2 = self._get_revtrees(tree, [rev1, rev2])
        self.assertEqual(rev1, tree1.get_file_revision(tree1.get_root_id()))
        if tree.branch.repository.supports_rich_root():
            self.assertEqual(rev1,
                tree2.get_file_revision(tree2.get_root_id()))
        else:
            self.assertEqual(rev2,
                tree2.get_file_revision(tree2.get_root_id()))

    def _add_commit_check_unchanged(self, tree, name, mini_commit=None):
        tree.add([name], [name + 'id'])
        self._commit_check_unchanged(tree, name, name + 'id',
            mini_commit=mini_commit)

    def _commit_check_unchanged(self, tree, name, file_id, mini_commit=None):
        rev1 = tree.commit('')
        if mini_commit is None:
            mini_commit = self.mini_commit
        rev2 = mini_commit(tree, name, name, False, False)
        tree1, tree2 = self._get_revtrees(tree, [rev1, rev2])
        self.assertEqual(rev1, tree1.get_file_revision(file_id))
        self.assertEqual(rev1, tree2.get_file_revision(file_id))
        expected_graph = {}
        expected_graph[(file_id, rev1)] = ()
        self.assertFileGraph(expected_graph, tree, (file_id, rev1))

    def test_last_modified_revision_after_commit_dir_unchanged(self):
        # committing without changing a dir does not change the last modified.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/'])
        self._add_commit_check_unchanged(tree, 'dir')

    def test_last_modified_revision_after_commit_dir_unchanged_ric(self):
        # committing without changing a dir does not change the last modified.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/'])
        self._add_commit_check_unchanged(tree, 'dir',
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_commit_dir_contents_unchanged(self):
        # committing without changing a dir does not change the last modified
        # of the dir even the dirs contents are changed.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/'])
        tree.add(['dir'], ['dirid'])
        rev1 = tree.commit('')
        self.build_tree(['dir/content'])
        tree.add(['dir/content'], ['contentid'])
        rev2 = tree.commit('')
        tree1, tree2 = self._get_revtrees(tree, [rev1, rev2])
        self.assertEqual(rev1, tree1.get_file_revision('dirid'))
        self.assertEqual(rev1, tree2.get_file_revision('dirid'))
        file_id = 'dirid'
        expected_graph = {}
        expected_graph[(file_id, rev1)] = ()
        self.assertFileGraph(expected_graph, tree, (file_id, rev1))

    def test_last_modified_revision_after_commit_file_unchanged(self):
        # committing without changing a file does not change the last modified.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        self._add_commit_check_unchanged(tree, 'file')

    def test_last_modified_revision_after_commit_file_unchanged_ric(self):
        # committing without changing a file does not change the last modified.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        self._add_commit_check_unchanged(tree, 'file',
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_commit_link_unchanged(self):
        # committing without changing a link does not change the last modified.
        self.requireFeature(features.SymlinkFeature)
        tree = self.make_branch_and_tree('.')
        os.symlink('target', 'link')
        self._add_commit_check_unchanged(tree, 'link')

    def test_last_modified_revision_after_commit_link_unchanged_ric(self):
        # committing without changing a link does not change the last modified.
        self.requireFeature(features.SymlinkFeature)
        tree = self.make_branch_and_tree('.')
        os.symlink('target', 'link')
        self._add_commit_check_unchanged(tree, 'link',
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_commit_reference_unchanged(self):
        # committing without changing a subtree does not change the last
        # modified.
        tree = self.make_branch_and_tree('.')
        subtree = self.make_reference('reference')
        try:
            tree.add_reference(subtree)
            self._commit_check_unchanged(tree, 'reference',
                subtree.get_root_id())
        except errors.UnsupportedOperation:
            return

    def test_last_modified_revision_after_commit_reference_unchanged_ric(self):
        # committing without changing a subtree does not change the last
        # modified.
        tree = self.make_branch_and_tree('.')
        subtree = self.make_reference('reference')
        try:
            tree.add_reference(subtree)
            self._commit_check_unchanged(tree, 'reference',
                subtree.get_root_id(),
                mini_commit=self.mini_commit_record_iter_changes)
        except errors.UnsupportedOperation:
            return

    def _add_commit_renamed_check_changed(self, tree, name,
        expect_fs_hash=False, mini_commit=None):
        def rename():
            tree.rename_one(name, 'new_' + name)
        self._add_commit_change_check_changed(tree, name, rename,
            expect_fs_hash=expect_fs_hash, mini_commit=mini_commit)

    def _commit_renamed_check_changed(self, tree, name, file_id,
        expect_fs_hash=False, mini_commit=None):
        def rename():
            tree.rename_one(name, 'new_' + name)
        self._commit_change_check_changed(tree, name, file_id, rename,
            expect_fs_hash=expect_fs_hash, mini_commit=mini_commit)

    def test_last_modified_revision_after_rename_dir_changes(self):
        # renaming a dir changes the last modified.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/'])
        self._add_commit_renamed_check_changed(tree, 'dir')

    def test_last_modified_revision_after_rename_dir_changes_ric(self):
        # renaming a dir changes the last modified.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/'])
        self._add_commit_renamed_check_changed(tree, 'dir',
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_rename_file_changes(self):
        # renaming a file changes the last modified.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        self._add_commit_renamed_check_changed(tree, 'file',
            expect_fs_hash=True)

    def test_last_modified_revision_after_rename_file_changes_ric(self):
        # renaming a file changes the last modified.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        self._add_commit_renamed_check_changed(tree, 'file',
            expect_fs_hash=True,
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_rename_link_changes(self):
        # renaming a link changes the last modified.
        self.requireFeature(features.SymlinkFeature)
        tree = self.make_branch_and_tree('.')
        os.symlink('target', 'link')
        self._add_commit_renamed_check_changed(tree, 'link')

    def test_last_modified_revision_after_rename_link_changes_ric(self):
        # renaming a link changes the last modified.
        self.requireFeature(features.SymlinkFeature)
        tree = self.make_branch_and_tree('.')
        os.symlink('target', 'link')
        self._add_commit_renamed_check_changed(tree, 'link',
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_rename_ref_changes(self):
        # renaming a reference changes the last modified.
        tree = self.make_branch_and_tree('.')
        subtree = self.make_reference('reference')
        try:
            tree.add_reference(subtree)
            self._commit_renamed_check_changed(tree, 'reference',
                subtree.get_root_id())
        except errors.UnsupportedOperation:
            return

    def test_last_modified_revision_after_rename_ref_changes_ric(self):
        # renaming a reference changes the last modified.
        tree = self.make_branch_and_tree('.')
        subtree = self.make_reference('reference')
        try:
            tree.add_reference(subtree)
            self._commit_renamed_check_changed(tree, 'reference',
                subtree.get_root_id(),
                mini_commit=self.mini_commit_record_iter_changes)
        except errors.UnsupportedOperation:
            return

    def _add_commit_reparent_check_changed(self, tree, name,
        expect_fs_hash=False, mini_commit=None):
        self.build_tree(['newparent/'])
        tree.add(['newparent'])
        def reparent():
            tree.rename_one(name, 'newparent/new_' + name)
        self._add_commit_change_check_changed(tree, name, reparent,
            expect_fs_hash=expect_fs_hash, mini_commit=mini_commit)

    def test_last_modified_revision_after_reparent_dir_changes(self):
        # reparenting a dir changes the last modified.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/'])
        self._add_commit_reparent_check_changed(tree, 'dir')

    def test_last_modified_revision_after_reparent_dir_changes_ric(self):
        # reparenting a dir changes the last modified.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/'])
        self._add_commit_reparent_check_changed(tree, 'dir',
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_reparent_file_changes(self):
        # reparenting a file changes the last modified.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        self._add_commit_reparent_check_changed(tree, 'file',
            expect_fs_hash=True)

    def test_last_modified_revision_after_reparent_file_changes_ric(self):
        # reparenting a file changes the last modified.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        self._add_commit_reparent_check_changed(tree, 'file',
            expect_fs_hash=True,
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_reparent_link_changes(self):
        # reparenting a link changes the last modified.
        self.requireFeature(features.SymlinkFeature)
        tree = self.make_branch_and_tree('.')
        os.symlink('target', 'link')
        self._add_commit_reparent_check_changed(tree, 'link')

    def test_last_modified_revision_after_reparent_link_changes_ric(self):
        # reparenting a link changes the last modified.
        self.requireFeature(features.SymlinkFeature)
        tree = self.make_branch_and_tree('.')
        os.symlink('target', 'link')
        self._add_commit_reparent_check_changed(tree, 'link',
            mini_commit=self.mini_commit_record_iter_changes)

    def _add_commit_change_check_changed(self, tree, name, changer,
        expect_fs_hash=False, mini_commit=None, file_id=None):
        if file_id is None:
            file_id = name + 'id'
        tree.add([name], [file_id])
        self._commit_change_check_changed(
            tree, name, file_id,
            changer, expect_fs_hash=expect_fs_hash, mini_commit=mini_commit)

    def _commit_change_check_changed(self, tree, name, file_id, changer,
        expect_fs_hash=False, mini_commit=None):
        rev1 = tree.commit('')
        changer()
        if mini_commit is None:
            mini_commit = self.mini_commit
        rev2 = mini_commit(tree, name, tree.id2path(file_id),
            expect_fs_hash=expect_fs_hash)
        tree1, tree2 = self._get_revtrees(tree, [rev1, rev2])
        self.assertEqual(rev1, tree1.get_file_revision(file_id))
        self.assertEqual(rev2, tree2.get_file_revision(file_id))
        expected_graph = {}
        expected_graph[(file_id, rev1)] = ()
        expected_graph[(file_id, rev2)] = ((file_id, rev1),)
        self.assertFileGraph(expected_graph, tree, (file_id, rev2))

    def mini_commit(self, tree, name, new_name, records_version=True,
        delta_against_basis=True, expect_fs_hash=False):
        """Perform a miniature commit looking for record entry results.

        :param tree: The tree to commit.
        :param name: The path in the basis tree of the tree being committed.
        :param new_name: The path in the tree being committed.
        :param records_version: True if the commit of new_name is expected to
            record a new version.
        :param delta_against_basis: True of the commit of new_name is expected
            to have a delta against the basis.
        :param expect_fs_hash: True or false to indicate whether we expect a
            file hash to be returned from the record_entry_contents call.
        """
        tree.lock_write()
        try:
            # mini manual commit here so we can check the return of
            # record_entry_contents.
            parent_ids = tree.get_parent_ids()
            builder = tree.branch.get_commit_builder(parent_ids)
            try:
                if not builder.supports_record_entry_contents:
                    raise tests.TestNotApplicable("CommitBuilder doesn't "
                        "support record_entry_contents")
                builder.will_record_deletes()
                parent_tree = tree.basis_tree()
                parent_tree.lock_read()
                self.addCleanup(parent_tree.unlock)
                parent_invs = [parent_tree.root_inventory]
                for parent_id in parent_ids[1:]:
                    parent_invs.append(tree.branch.repository.revision_tree(
                        parent_id).root_inventory)
                # root
                builder.record_entry_contents(
                    inventory.make_entry('directory', '', None,
                        tree.get_root_id()), parent_invs, '', tree,
                        tree.path_content_summary(''))
                def commit_id(file_id):
                    old_ie = tree.root_inventory[file_id]
                    path = tree.id2path(file_id)
                    ie = inventory.make_entry(tree.kind(file_id), old_ie.name,
                        old_ie.parent_id, file_id)
                    content_summary = tree.path_content_summary(path)
                    if content_summary[0] == 'tree-reference':
                        content_summary = content_summary[:3] + (
                            tree.get_reference_revision(file_id),)
                    return builder.record_entry_contents(ie, parent_invs, path,
                        tree, content_summary)

                file_id = tree.path2id(new_name)
                parent_id = tree.root_inventory[file_id].parent_id
                if parent_id != tree.get_root_id():
                    commit_id(parent_id)
                # because a change of some sort is meant to have occurred,
                # recording the entry must return True.
                delta, version_recorded, fs_hash = commit_id(file_id)
                if records_version:
                    self.assertTrue(version_recorded)
                else:
                    self.assertFalse(version_recorded)
                if expect_fs_hash:
                    tree_file_stat = tree.get_file_with_stat(file_id)
                    tree_file_stat[0].close()
                    self.assertEqual(2, len(fs_hash))
                    self.assertEqual(tree.get_file_sha1(file_id), fs_hash[0])
                    self.assertEqualStat(tree_file_stat[1], fs_hash[1])
                else:
                    self.assertEqual(None, fs_hash)
                new_entry = builder.new_inventory[file_id]
                if delta_against_basis:
                    expected_delta = (name, new_name, file_id, new_entry)
                    # The delta should be recorded
                    self.assertEqual(expected_delta,
                        builder.get_basis_delta()[-1])
                else:
                    expected_delta = None
                self.assertEqual(expected_delta, delta)
                builder.finish_inventory()
            except:
                builder.abort()
                raise
            else:
                rev2 = builder.commit('')
        except:
            tree.unlock()
            raise
        try:
            tree.set_parent_ids([rev2])
        finally:
            tree.unlock()
        return rev2

    def mini_commit_record_iter_changes(self, tree, name, new_name,
        records_version=True, delta_against_basis=True, expect_fs_hash=False):
        """Perform a miniature commit looking for record entry results.

        This version uses the record_iter_changes interface.
        
        :param tree: The tree to commit.
        :param name: The path in the basis tree of the tree being committed.
        :param new_name: The path in the tree being committed.
        :param records_version: True if the commit of new_name is expected to
            record a new version.
        :param delta_against_basis: True of the commit of new_name is expected
            to have a delta against the basis.
        :param expect_fs_hash: If true, looks for a fs hash output from
            record_iter_changes.
        """
        tree.lock_write()
        try:
            # mini manual commit here so we can check the return of
            # record_entry_contents.
            parent_ids = tree.get_parent_ids()
            builder = tree.branch.get_commit_builder(parent_ids)
            builder.will_record_deletes()
            parent_tree = tree.basis_tree()
            parent_tree.lock_read()
            self.addCleanup(parent_tree.unlock)
            parent_trees = [parent_tree]
            for parent_id in parent_ids[1:]:
                parent_trees.append(tree.branch.repository.revision_tree(
                    parent_id))
            changes = list(tree.iter_changes(parent_tree))
            result = list(builder.record_iter_changes(tree, parent_ids[0],
                changes))
            file_id = tree.path2id(new_name)
            if expect_fs_hash:
                tree_file_stat = tree.get_file_with_stat(file_id)
                tree_file_stat[0].close()
                self.assertLength(1, result)
                result = result[0]
                self.assertEqual(result[:2], (file_id, new_name))
                self.assertEqual(result[2][0], tree.get_file_sha1(file_id))
                self.assertEqualStat(result[2][1], tree_file_stat[1])
            else:
                self.assertEqual([], result)
            self.assertIs(None, builder.new_inventory)
            builder.finish_inventory()
            if tree.branch.repository._format.supports_full_versioned_files:
                inv_key = (builder._new_revision_id,)
                inv_sha1 = tree.branch.repository.inventories.get_sha1s(
                                [inv_key])[inv_key]
                self.assertEqual(inv_sha1, builder.inv_sha1)
            self.assertIs(None, builder.new_inventory)
            rev2 = builder.commit('')
            delta = builder.get_basis_delta()
            delta_dict = dict((change[2], change) for change in delta)
            version_recorded = (file_id in delta_dict and
                delta_dict[file_id][3] is not None and
                delta_dict[file_id][3].revision == rev2)
            if records_version:
                self.assertTrue(version_recorded)
            else:
                self.assertFalse(version_recorded)

            new_inventory = builder.revision_tree().root_inventory
            new_entry = new_inventory[file_id]
            if delta_against_basis:
                expected_delta = (name, new_name, file_id, new_entry)
                self.assertEqual(expected_delta, delta_dict[file_id])
            else:
                expected_delta = None
                self.assertFalse(version_recorded)
            tree.set_parent_ids([rev2])
        except:
            builder.abort()
            tree.unlock()
            raise
        else:
            tree.unlock()
        return rev2

    def assertFileGraph(self, expected_graph, tree, tip):
        # all the changes that have occured should be in the ancestry
        # (closest to a public per-file graph API we have today)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        g = dict(tree.branch.repository.get_file_graph().iter_ancestry([tip]))
        self.assertEqual(expected_graph, g)

    def test_last_modified_revision_after_content_file_changes(self):
        # altering a file changes the last modified.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        def change_file():
            tree.put_file_bytes_non_atomic('fileid', 'new content')
        self._add_commit_change_check_changed(tree, 'file', change_file,
            expect_fs_hash=True)

    def test_last_modified_revision_after_content_file_changes_ric(self):
        # altering a file changes the last modified.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['file'])
        def change_file():
            tree.put_file_bytes_non_atomic('fileid', 'new content')
        self._add_commit_change_check_changed(tree, 'file', change_file,
            expect_fs_hash=True,
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_content_link_changes(self):
        # changing a link changes the last modified.
        self.requireFeature(features.SymlinkFeature)
        tree = self.make_branch_and_tree('.')
        os.symlink('target', 'link')
        def change_link():
            os.unlink('link')
            os.symlink('newtarget', 'link')
        self._add_commit_change_check_changed(tree, 'link', change_link)

    def _test_last_mod_rev_after_content_link_changes_ric(
        self, link, target, newtarget, file_id=None):
        if file_id is None:
            file_id = link
        # changing a link changes the last modified.
        self.requireFeature(features.SymlinkFeature)
        tree = self.make_branch_and_tree('.')
        os.symlink(target, link)
        def change_link():
            os.unlink(link)
            os.symlink(newtarget, link)
        self._add_commit_change_check_changed(
            tree, link, change_link,
            mini_commit=self.mini_commit_record_iter_changes,
            file_id=file_id)

    def test_last_modified_rev_after_content_link_changes_ric(self):
        self._test_last_mod_rev_after_content_link_changes_ric(
            'link', 'target', 'newtarget')

    def test_last_modified_rev_after_content_unicode_link_changes_ric(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        self._test_last_mod_rev_after_content_link_changes_ric(
            u'li\u1234nk', u'targ\N{Euro Sign}t', u'n\N{Euro Sign}wtarget',

            file_id=u'li\u1234nk'.encode('UTF-8'))

    def _commit_sprout(self, tree, name):
        tree.add([name], [name + 'id'])
        rev_id = tree.commit('')
        return rev_id, tree.bzrdir.sprout('t2').open_workingtree()

    def _rename_in_tree(self, tree, name):
        tree.rename_one(name, 'new_' + name)
        return tree.commit('')

    def _commit_sprout_rename_merge(self, tree1, name, expect_fs_hash=False,
        mini_commit=None):
        """Do a rename in both trees."""
        rev1, tree2 = self._commit_sprout(tree1, name)
        # change both sides equally
        rev2 = self._rename_in_tree(tree1, name)
        rev3 = self._rename_in_tree(tree2, name)
        tree1.merge_from_branch(tree2.branch)
        if mini_commit is None:
            mini_commit = self.mini_commit
        rev4 = mini_commit(tree1, 'new_' + name, 'new_' + name,
            expect_fs_hash=expect_fs_hash)
        tree3, = self._get_revtrees(tree1, [rev4])
        self.assertEqual(rev4, tree3.get_file_revision(name + 'id'))
        file_id = name + 'id'
        expected_graph = {}
        expected_graph[(file_id, rev1)] = ()
        expected_graph[(file_id, rev2)] = ((file_id, rev1),)
        expected_graph[(file_id, rev3)] = ((file_id, rev1),)
        expected_graph[(file_id, rev4)] = ((file_id, rev2), (file_id, rev3),)
        self.assertFileGraph(expected_graph, tree1, (file_id, rev4))

    def test_last_modified_revision_after_merge_dir_changes(self):
        # merge a dir changes the last modified.
        tree1 = self.make_branch_and_tree('t1')
        self.build_tree(['t1/dir/'])
        self._commit_sprout_rename_merge(tree1, 'dir')

    def test_last_modified_revision_after_merge_dir_changes_ric(self):
        # merge a dir changes the last modified.
        tree1 = self.make_branch_and_tree('t1')
        self.build_tree(['t1/dir/'])
        self._commit_sprout_rename_merge(tree1, 'dir',
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_merge_file_changes(self):
        # merge a file changes the last modified.
        tree1 = self.make_branch_and_tree('t1')
        self.build_tree(['t1/file'])
        self._commit_sprout_rename_merge(tree1, 'file', expect_fs_hash=True)

    def test_last_modified_revision_after_merge_file_changes_ric(self):
        # merge a file changes the last modified.
        tree1 = self.make_branch_and_tree('t1')
        self.build_tree(['t1/file'])
        self._commit_sprout_rename_merge(tree1, 'file', expect_fs_hash=True,
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_merge_link_changes(self):
        # merge a link changes the last modified.
        self.requireFeature(features.SymlinkFeature)
        tree1 = self.make_branch_and_tree('t1')
        os.symlink('target', 't1/link')
        self._commit_sprout_rename_merge(tree1, 'link')

    def test_last_modified_revision_after_merge_link_changes_ric(self):
        # merge a link changes the last modified.
        self.requireFeature(features.SymlinkFeature)
        tree1 = self.make_branch_and_tree('t1')
        os.symlink('target', 't1/link')
        self._commit_sprout_rename_merge(tree1, 'link',
            mini_commit=self.mini_commit_record_iter_changes)

    def _commit_sprout_rename_merge_converged(self, tree1, name,
        mini_commit=None):
        # Make a merge which just incorporates a change from a branch:
        # The per-file graph is straight line, and no alteration occurs
        # in the inventory.
        # Part 1: change in the merged branch.
        rev1, tree2 = self._commit_sprout(tree1, name)
        # change on the other side to merge back
        rev2 = self._rename_in_tree(tree2, name)
        tree1.merge_from_branch(tree2.branch)
        if mini_commit is None:
            mini_commit = self.mini_commit
        def _check_graph(in_tree, changed_in_tree):
            rev3 = mini_commit(in_tree, name, 'new_' + name, False,
                delta_against_basis=changed_in_tree)
            tree3, = self._get_revtrees(in_tree, [rev2])
            self.assertEqual(rev2, tree3.get_file_revision(name + 'id'))
            file_id = name + 'id'
            expected_graph = {}
            expected_graph[(file_id, rev1)] = ()
            expected_graph[(file_id, rev2)] = ((file_id, rev1),)
            self.assertFileGraph(expected_graph, in_tree, (file_id, rev2))
        _check_graph(tree1, True)
        # Part 2: change in the merged into branch - we use tree2 that has a
        # change to name, branch tree1 and give it an unrelated change, then
        # merge that to t2.
        other_tree = tree1.bzrdir.sprout('t3').open_workingtree()
        other_rev = other_tree.commit('')
        tree2.merge_from_branch(other_tree.branch)
        _check_graph(tree2, False)

    def _commit_sprout_make_merge(self, tree1, make, mini_commit=None):
        # Make a merge which incorporates the addition of a new object to
        # another branch. The per-file graph shows no additional change
        # in the merge because its a straight line.
        rev1 = tree1.commit('')
        tree2 = tree1.bzrdir.sprout('t2').open_workingtree()
        # make and commit on the other side to merge back
        make('t2/name')
        file_id = 'nameid'
        tree2.add(['name'], [file_id])
        rev2 = tree2.commit('')
        tree1.merge_from_branch(tree2.branch)
        if mini_commit is None:
            mini_commit = self.mini_commit
        rev3 = mini_commit(tree1, None, 'name', False)
        tree3, = self._get_revtrees(tree1, [rev2])
        # in rev2, name should be only changed in rev2
        self.assertEqual(rev2, tree3.get_file_revision(file_id))
        expected_graph = {}
        expected_graph[(file_id, rev2)] = ()
        self.assertFileGraph(expected_graph, tree1, (file_id, rev2))

    def test_last_modified_revision_after_converged_merge_dir_unchanged(self):
        # merge a dir that changed preserves the last modified.
        tree1 = self.make_branch_and_tree('t1')
        self.build_tree(['t1/dir/'])
        self._commit_sprout_rename_merge_converged(tree1, 'dir')

    def test_last_modified_revision_after_converged_merge_dir_unchanged_ric(self):
        # merge a dir that changed preserves the last modified.
        tree1 = self.make_branch_and_tree('t1')
        self.build_tree(['t1/dir/'])
        self._commit_sprout_rename_merge_converged(tree1, 'dir',
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_converged_merge_file_unchanged(self):
        # merge a file that changed preserves the last modified.
        tree1 = self.make_branch_and_tree('t1')
        self.build_tree(['t1/file'])
        self._commit_sprout_rename_merge_converged(tree1, 'file')

    def test_last_modified_revision_after_converged_merge_file_unchanged_ric(self):
        # merge a file that changed preserves the last modified.
        tree1 = self.make_branch_and_tree('t1')
        self.build_tree(['t1/file'])
        self._commit_sprout_rename_merge_converged(tree1, 'file',
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_converged_merge_link_unchanged(self):
        # merge a link that changed preserves the last modified.
        self.requireFeature(features.SymlinkFeature)
        tree1 = self.make_branch_and_tree('t1')
        os.symlink('target', 't1/link')
        self._commit_sprout_rename_merge_converged(tree1, 'link')

    def test_last_modified_revision_after_converged_merge_link_unchanged_ric(self):
        # merge a link that changed preserves the last modified.
        self.requireFeature(features.SymlinkFeature)
        tree1 = self.make_branch_and_tree('t1')
        os.symlink('target', 't1/link')
        self._commit_sprout_rename_merge_converged(tree1, 'link',
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_merge_new_dir_unchanged(self):
        # merge a new dir does not change the last modified.
        tree1 = self.make_branch_and_tree('t1')
        self._commit_sprout_make_merge(tree1, self.make_dir)

    def test_last_modified_revision_after_merge_new_dir_unchanged_ric(self):
        # merge a new dir does not change the last modified.
        tree1 = self.make_branch_and_tree('t1')
        self._commit_sprout_make_merge(tree1, self.make_dir,
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_merge_new_file_unchanged(self):
        # merge a new file does not change the last modified.
        tree1 = self.make_branch_and_tree('t1')
        self._commit_sprout_make_merge(tree1, self.make_file)

    def test_last_modified_revision_after_merge_new_file_unchanged_ric(self):
        # merge a new file does not change the last modified.
        tree1 = self.make_branch_and_tree('t1')
        self._commit_sprout_make_merge(tree1, self.make_file,
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_revision_after_merge_new_link_unchanged(self):
        # merge a new link does not change the last modified.
        tree1 = self.make_branch_and_tree('t1')
        self._commit_sprout_make_merge(tree1, self.make_link)

    def test_last_modified_revision_after_merge_new_link_unchanged_ric(self):
        # merge a new link does not change the last modified.
        tree1 = self.make_branch_and_tree('t1')
        self._commit_sprout_make_merge(tree1, self.make_link,
            mini_commit=self.mini_commit_record_iter_changes)

    def make_dir(self, name):
        self.build_tree([name + '/'])

    def make_file(self, name):
        self.build_tree([name])

    def make_link(self, name):
        self.requireFeature(features.SymlinkFeature)
        os.symlink('target', name)

    def make_reference(self, name):
        tree = self.make_branch_and_tree(name, format='1.9-rich-root')
        tree.commit('foo')
        return tree

    def _check_kind_change(self, make_before, make_after, expect_fs_hash=False,
        mini_commit=None):
        tree = self.make_branch_and_tree('.')
        path = 'name'
        make_before(path)

        def change_kind():
            if osutils.file_kind(path) == "directory":
                osutils.rmtree(path)
            else:
                osutils.delete_any(path)
            make_after(path)

        self._add_commit_change_check_changed(tree, path, change_kind,
            expect_fs_hash=expect_fs_hash, mini_commit=mini_commit)

    def test_last_modified_dir_file(self):
        self._check_kind_change(self.make_dir, self.make_file,
            expect_fs_hash=True)

    def test_last_modified_dir_file_ric(self):
        try:
            self._check_kind_change(self.make_dir, self.make_file,
                expect_fs_hash=True,
                mini_commit=self.mini_commit_record_iter_changes)
        except errors.UnsupportedKindChange:
            raise tests.TestSkipped(
                "tree does not support changing entry kind from "
                "directory to file")

    def test_last_modified_dir_link(self):
        self._check_kind_change(self.make_dir, self.make_link)

    def test_last_modified_dir_link_ric(self):
        try:
            self._check_kind_change(self.make_dir, self.make_link,
                mini_commit=self.mini_commit_record_iter_changes)
        except errors.UnsupportedKindChange:
            raise tests.TestSkipped(
                "tree does not support changing entry kind from "
                "directory to link")

    def test_last_modified_link_file(self):
        self._check_kind_change(self.make_link, self.make_file,
            expect_fs_hash=True)

    def test_last_modified_link_file_ric(self):
        self._check_kind_change(self.make_link, self.make_file,
            expect_fs_hash=True,
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_link_dir(self):
        self._check_kind_change(self.make_link, self.make_dir)

    def test_last_modified_link_dir_ric(self):
        self._check_kind_change(self.make_link, self.make_dir,
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_file_dir(self):
        self._check_kind_change(self.make_file, self.make_dir)

    def test_last_modified_file_dir_ric(self):
        self._check_kind_change(self.make_file, self.make_dir,
            mini_commit=self.mini_commit_record_iter_changes)

    def test_last_modified_file_link(self):
        self._check_kind_change(self.make_file, self.make_link)

    def test_last_modified_file_link_ric(self):
        self._check_kind_change(self.make_file, self.make_link,
            mini_commit=self.mini_commit_record_iter_changes)

    def test_get_commit_builder_with_invalid_revprops(self):
        branch = self.make_branch('.')
        branch.repository.lock_write()
        self.addCleanup(branch.repository.unlock)
        self.assertRaises(ValueError, branch.repository.get_commit_builder,
            branch, [], branch.get_config_stack(),
            revprops={'invalid': u'property\rwith\r\ninvalid chars'})

    def test_commit_builder_commit_with_invalid_message(self):
        branch = self.make_branch('.')
        branch.repository.lock_write()
        self.addCleanup(branch.repository.unlock)
        builder = branch.repository.get_commit_builder(branch, [],
            branch.get_config_stack())
        self.addCleanup(branch.repository.abort_write_group)
        self.assertRaises(ValueError, builder.commit,
            u'Invalid\r\ncommit message\r\n')

    def test_non_ascii_str_committer_rejected(self):
        """Ensure an error is raised on a non-ascii byte string committer"""
        branch = self.make_branch('.')
        branch.repository.lock_write()
        self.addCleanup(branch.repository.unlock)
        self.assertRaises(UnicodeDecodeError,
            branch.repository.get_commit_builder,
            branch, [], branch.get_config_stack(),
            committer="Erik B\xe5gfors <erik@example.com>")

    def test_stacked_repositories_reject_commit_builder(self):
        # As per bug 375013, committing to stacked repositories is currently
        # broken if we aren't in a chk repository. So old repositories with
        # fallbacks refuse to hand out a commit builder.
        repo_basis = self.make_repository('basis')
        branch = self.make_branch('local')
        repo_local = branch.repository
        try:
            repo_local.add_fallback_repository(repo_basis)
        except errors.UnstackableRepositoryFormat:
            raise tests.TestNotApplicable("not a stackable format.")
        self.addCleanup(repo_local.lock_write().unlock)
        if not repo_local._format.supports_chks:
            self.assertRaises(errors.BzrError, repo_local.get_commit_builder,
                branch, [], branch.get_config_stack())
        else:
            builder = repo_local.get_commit_builder(branch, [],
                                                    branch.get_config_stack())
            builder.abort()

    def test_committer_no_username(self):
        # Ensure that when no username is available but a committer is
        # supplied, commit works.
        self.overrideEnv('EMAIL', None)
        self.overrideEnv('BZR_EMAIL', None)
        # Also, make sure that it's not inferred from mailname.
        self.overrideAttr(config, '_auto_user_id',
            lambda: (None, None))
        tree = self.make_branch_and_tree(".")
        tree.lock_write()
        try:
            # Make sure no username is available.
            self.assertRaises(errors.NoWhoami, tree.branch.get_commit_builder,
                              [])
            builder = tree.branch.get_commit_builder(
                [], committer='me@example.com')
            try:
                list(builder.record_iter_changes(tree, tree.last_revision(),
                    tree.iter_changes(tree.basis_tree())))
                builder.finish_inventory()
            except:
                builder.abort()
                raise
            repo = tree.branch.repository
            repo.commit_write_group()
        finally:
            tree.unlock()

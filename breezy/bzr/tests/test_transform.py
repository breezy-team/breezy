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

import codecs
import os
import time

from ...tests import features
from ... import errors, filters, osutils, rules
from ...controldir import ControlDir
from ..conflicts import DuplicateEntry
from ..transform import build_tree

from . import TestCaseWithTransport


class TestInventoryAltered(TestCaseWithTransport):

    def test_inventory_altered_unchanged(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo'])
        tree.add('foo', ids=b'foo-id')
        with tree.preview_transform() as tt:
            self.assertEqual([], tt._inventory_altered())

    def test_inventory_altered_changed_parent_id(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo'])
        tree.add('foo', ids=b'foo-id')
        with tree.preview_transform() as tt:
            tt.unversion_file(tt.root)
            tt.version_file(tt.root, file_id=b'new-id')
            foo_trans_id = tt.trans_id_tree_path('foo')
            foo_tuple = ('foo', foo_trans_id)
            root_tuple = ('', tt.root)
            self.assertEqual([root_tuple, foo_tuple], tt._inventory_altered())

    def test_inventory_altered_noop_changed_parent_id(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo'])
        tree.add('foo', ids=b'foo-id')
        with tree.preview_transform() as tt:
            tt.unversion_file(tt.root)
            tt.version_file(tt.root, file_id=tree.path2id(''))
            tt.trans_id_tree_path('foo')
            self.assertEqual([], tt._inventory_altered())


class TestBuildTree(TestCaseWithTransport):

    def test_build_tree_with_symlinks(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        os.mkdir('a')
        a = ControlDir.create_standalone_workingtree('a')
        os.mkdir('a/foo')
        with open('a/foo/bar', 'wb') as f:
            f.write(b'contents')
        os.symlink('a/foo/bar', 'a/foo/baz')
        a.add(['foo', 'foo/bar', 'foo/baz'])
        a.commit('initial commit')
        b = ControlDir.create_standalone_workingtree('b')
        basis = a.basis_tree()
        basis.lock_read()
        self.addCleanup(basis.unlock)
        build_tree(basis, b)
        self.assertIs(os.path.isdir('b/foo'), True)
        with open('b/foo/bar', 'rb') as f:
            self.assertEqual(f.read(), b"contents")
        self.assertEqual(os.readlink('b/foo/baz'), 'a/foo/bar')

    def test_build_with_references(self):
        tree = self.make_branch_and_tree('source',
                                         format='development-subtree')
        subtree = self.make_branch_and_tree('source/subtree',
                                            format='development-subtree')
        tree.add_reference(subtree)
        tree.commit('a revision')
        tree.branch.create_checkout('target')
        self.assertPathExists('target')
        self.assertPathExists('target/subtree')

    def test_file_conflict_handling(self):
        """Ensure that when building trees, conflict handling is done"""
        source = self.make_branch_and_tree('source')
        target = self.make_branch_and_tree('target')
        self.build_tree(['source/file', 'target/file'])
        source.add('file', ids=b'new-file')
        source.commit('added file')
        build_tree(source.basis_tree(), target)
        self.assertEqual(
            [DuplicateEntry('Moved existing file to', 'file.moved',
                            'file', None, 'new-file')],
            target.conflicts())
        target2 = self.make_branch_and_tree('target2')
        with open('target2/file', 'wb') as target_file, \
                open('source/file', 'rb') as source_file:
            target_file.write(source_file.read())
        build_tree(source.basis_tree(), target2)
        self.assertEqual([], target2.conflicts())

    def test_symlink_conflict_handling(self):
        """Ensure that when building trees, conflict handling is done"""
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        source = self.make_branch_and_tree('source')
        os.symlink('foo', 'source/symlink')
        source.add('symlink', ids=b'new-symlink')
        source.commit('added file')
        target = self.make_branch_and_tree('target')
        os.symlink('bar', 'target/symlink')
        build_tree(source.basis_tree(), target)
        self.assertEqual(
            [DuplicateEntry('Moved existing file to', 'symlink.moved',
                            'symlink', None, 'new-symlink')],
            target.conflicts())
        target = self.make_branch_and_tree('target2')
        os.symlink('foo', 'target2/symlink')
        build_tree(source.basis_tree(), target)
        self.assertEqual([], target.conflicts())

    def test_directory_conflict_handling(self):
        """Ensure that when building trees, conflict handling is done"""
        source = self.make_branch_and_tree('source')
        target = self.make_branch_and_tree('target')
        self.build_tree(['source/dir1/', 'source/dir1/file', 'target/dir1/'])
        source.add(['dir1', 'dir1/file'], ids=[b'new-dir1', b'new-file'])
        source.commit('added file')
        build_tree(source.basis_tree(), target)
        self.assertEqual([], target.conflicts())
        self.assertPathExists('target/dir1/file')

        # Ensure contents are merged
        target = self.make_branch_and_tree('target2')
        self.build_tree(['target2/dir1/', 'target2/dir1/file2'])
        build_tree(source.basis_tree(), target)
        self.assertEqual([], target.conflicts())
        self.assertPathExists('target2/dir1/file2')
        self.assertPathExists('target2/dir1/file')

        # Ensure new contents are suppressed for existing branches
        target = self.make_branch_and_tree('target3')
        self.make_branch('target3/dir1')
        self.build_tree(['target3/dir1/file2'])
        build_tree(source.basis_tree(), target)
        self.assertPathDoesNotExist('target3/dir1/file')
        self.assertPathExists('target3/dir1/file2')
        self.assertPathExists('target3/dir1.diverted/file')
        self.assertEqual(
            [DuplicateEntry('Diverted to', 'dir1.diverted',
                            'dir1', 'new-dir1', None)],
            target.conflicts())

        target = self.make_branch_and_tree('target4')
        self.build_tree(['target4/dir1/'])
        self.make_branch('target4/dir1/file')
        build_tree(source.basis_tree(), target)
        self.assertPathExists('target4/dir1/file')
        self.assertEqual('directory', osutils.file_kind('target4/dir1/file'))
        self.assertPathExists('target4/dir1/file.diverted')
        self.assertEqual(
            [DuplicateEntry('Diverted to', 'dir1/file.diverted',
                            'dir1/file', 'new-file', None)],
            target.conflicts())

    def test_mixed_conflict_handling(self):
        """Ensure that when building trees, conflict handling is done"""
        source = self.make_branch_and_tree('source')
        target = self.make_branch_and_tree('target')
        self.build_tree(['source/name', 'target/name/'])
        source.add('name', ids=b'new-name')
        source.commit('added file')
        build_tree(source.basis_tree(), target)
        self.assertEqual(
            [DuplicateEntry('Moved existing file to',
                            'name.moved', 'name', None, 'new-name')],
            target.conflicts())

    def test_raises_in_populated(self):
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/name'])
        source.add('name')
        source.commit('added name')
        target = self.make_branch_and_tree('target')
        self.build_tree(['target/name'])
        target.add('name')
        self.assertRaises(errors.WorkingTreeAlreadyPopulated,
                          build_tree, source.basis_tree(), target)

    def test_build_tree_rename_count(self):
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/file1', 'source/dir1/'])
        source.add(['file1', 'dir1'])
        source.commit('add1')
        target1 = self.make_branch_and_tree('target1')
        transform_result = build_tree(source.basis_tree(), target1)
        self.assertEqual(2, transform_result.rename_count)

        self.build_tree(['source/dir1/file2'])
        source.add(['dir1/file2'])
        source.commit('add3')
        target2 = self.make_branch_and_tree('target2')
        transform_result = build_tree(source.basis_tree(), target2)
        # children of non-root directories should not be renamed
        self.assertEqual(2, transform_result.rename_count)

    def create_ab_tree(self):
        """Create a committed test tree with two files"""
        source = self.make_branch_and_tree('source')
        self.build_tree_contents([('source/file1', b'A')])
        self.build_tree_contents([('source/file2', b'B')])
        source.add(['file1', 'file2'], ids=[b'file1-id', b'file2-id'])
        source.commit('commit files')
        source.lock_write()
        self.addCleanup(source.unlock)
        return source

    def test_build_tree_accelerator_tree(self):
        source = self.create_ab_tree()
        self.build_tree_contents([('source/file2', b'C')])
        calls = []
        real_source_get_file = source.get_file

        def get_file(path):
            calls.append(path)
            return real_source_get_file(path)
        source.get_file = get_file
        target = self.make_branch_and_tree('target')
        revision_tree = source.basis_tree()
        revision_tree.lock_read()
        self.addCleanup(revision_tree.unlock)
        build_tree(revision_tree, target, source)
        self.assertEqual(['file1'], calls)
        target.lock_read()
        self.addCleanup(target.unlock)
        self.assertEqual([], list(target.iter_changes(revision_tree)))

    def test_build_tree_accelerator_tree_observes_sha1(self):
        source = self.create_ab_tree()
        sha1 = osutils.sha_string(b'A')
        target = self.make_branch_and_tree('target')
        target.lock_write()
        self.addCleanup(target.unlock)
        state = target.current_dirstate()
        state._cutoff_time = time.time() + 60
        build_tree(source.basis_tree(), target, source)
        entry = state._get_entry(0, path_utf8=b'file1')
        self.assertEqual(sha1, entry[1][0][1])

    def test_build_tree_accelerator_tree_missing_file(self):
        source = self.create_ab_tree()
        os.unlink('source/file1')
        source.remove(['file2'])
        target = self.make_branch_and_tree('target')
        revision_tree = source.basis_tree()
        revision_tree.lock_read()
        self.addCleanup(revision_tree.unlock)
        build_tree(revision_tree, target, source)
        target.lock_read()
        self.addCleanup(target.unlock)
        self.assertEqual([], list(target.iter_changes(revision_tree)))

    def test_build_tree_accelerator_wrong_kind(self):
        self.requireFeature(features.SymlinkFeature(self.test_dir))
        source = self.make_branch_and_tree('source')
        self.build_tree_contents([('source/file1', b'')])
        self.build_tree_contents([('source/file2', b'')])
        source.add(['file1', 'file2'], ids=[b'file1-id', b'file2-id'])
        source.commit('commit files')
        os.unlink('source/file2')
        self.build_tree_contents([('source/file2/', b'C')])
        os.unlink('source/file1')
        os.symlink('file2', 'source/file1')
        calls = []
        real_source_get_file = source.get_file

        def get_file(path):
            calls.append(path)
            return real_source_get_file(path)
        source.get_file = get_file
        target = self.make_branch_and_tree('target')
        revision_tree = source.basis_tree()
        revision_tree.lock_read()
        self.addCleanup(revision_tree.unlock)
        build_tree(revision_tree, target, source)
        self.assertEqual([], calls)
        target.lock_read()
        self.addCleanup(target.unlock)
        self.assertEqual([], list(target.iter_changes(revision_tree)))

    def test_build_tree_hardlink(self):
        self.requireFeature(features.HardlinkFeature(self.test_dir))
        source = self.create_ab_tree()
        target = self.make_branch_and_tree('target')
        revision_tree = source.basis_tree()
        revision_tree.lock_read()
        self.addCleanup(revision_tree.unlock)
        build_tree(revision_tree, target, source, hardlink=True)
        target.lock_read()
        self.addCleanup(target.unlock)
        self.assertEqual([], list(target.iter_changes(revision_tree)))
        source_stat = os.stat('source/file1')
        target_stat = os.stat('target/file1')
        self.assertEqual(source_stat, target_stat)

        # Explicitly disallowing hardlinks should prevent them.
        target2 = self.make_branch_and_tree('target2')
        build_tree(revision_tree, target2, source, hardlink=False)
        target2.lock_read()
        self.addCleanup(target2.unlock)
        self.assertEqual([], list(target2.iter_changes(revision_tree)))
        source_stat = os.stat('source/file1')
        target2_stat = os.stat('target2/file1')
        self.assertNotEqual(source_stat, target2_stat)

    def test_build_tree_accelerator_tree_moved(self):
        source = self.make_branch_and_tree('source')
        self.build_tree_contents([('source/file1', b'A')])
        source.add(['file1'], ids=[b'file1-id'])
        source.commit('commit files')
        source.rename_one('file1', 'file2')
        source.lock_read()
        self.addCleanup(source.unlock)
        target = self.make_branch_and_tree('target')
        revision_tree = source.basis_tree()
        revision_tree.lock_read()
        self.addCleanup(revision_tree.unlock)
        build_tree(revision_tree, target, source)
        target.lock_read()
        self.addCleanup(target.unlock)
        self.assertEqual([], list(target.iter_changes(revision_tree)))

    def test_build_tree_hardlinks_preserve_execute(self):
        self.requireFeature(features.HardlinkFeature(self.test_dir))
        source = self.create_ab_tree()
        tt = source.transform()
        trans_id = tt.trans_id_tree_path('file1')
        tt.set_executability(True, trans_id)
        tt.apply()
        self.assertTrue(source.is_executable('file1'))
        target = self.make_branch_and_tree('target')
        revision_tree = source.basis_tree()
        revision_tree.lock_read()
        self.addCleanup(revision_tree.unlock)
        build_tree(revision_tree, target, source, hardlink=True)
        target.lock_read()
        self.addCleanup(target.unlock)
        self.assertEqual([], list(target.iter_changes(revision_tree)))
        self.assertTrue(source.is_executable('file1'))

    def install_rot13_content_filter(self, pattern):
        # We could use
        # self.addCleanup(filters._reset_registry, filters._reset_registry())
        # below, but that looks a bit... hard to read even if it's exactly
        # the same thing.
        original_registry = filters._reset_registry()

        def restore_registry():
            filters._reset_registry(original_registry)
        self.addCleanup(restore_registry)

        def rot13(chunks, context=None):
            return [
                codecs.encode(chunk.decode('ascii'), 'rot13').encode('ascii')
                for chunk in chunks]
        rot13filter = filters.ContentFilter(rot13, rot13)
        filters.filter_stacks_registry.register(
            'rot13', {'yes': [rot13filter]}.get)
        os.mkdir(self.test_home_dir + '/.bazaar')
        rules_filename = self.test_home_dir + '/.bazaar/rules'
        with open(rules_filename, 'wb') as f:
            f.write(b'[name %s]\nrot13=yes\n' % (pattern,))

        def uninstall_rules():
            os.remove(rules_filename)
            rules.reset_rules()
        self.addCleanup(uninstall_rules)
        rules.reset_rules()

    def test_build_tree_content_filtered_files_are_not_hardlinked(self):
        """build_tree will not hardlink files that have content filtering rules
        applied to them (but will still hardlink other files from the same tree
        if it can).
        """
        self.requireFeature(features.HardlinkFeature(self.test_dir))
        self.install_rot13_content_filter(b'file1')
        source = self.create_ab_tree()
        target = self.make_branch_and_tree('target')
        revision_tree = source.basis_tree()
        revision_tree.lock_read()
        self.addCleanup(revision_tree.unlock)
        build_tree(revision_tree, target, source, hardlink=True)
        target.lock_read()
        self.addCleanup(target.unlock)
        self.assertEqual([], list(target.iter_changes(revision_tree)))
        source_stat = os.stat('source/file1')
        target_stat = os.stat('target/file1')
        self.assertNotEqual(source_stat, target_stat)
        source_stat = os.stat('source/file2')
        target_stat = os.stat('target/file2')
        self.assertEqualStat(source_stat, target_stat)

    def test_case_insensitive_build_tree_inventory(self):
        if (features.CaseInsensitiveFilesystemFeature.available()
                or features.CaseInsCasePresFilenameFeature.available()):
            raise tests.UnavailableFeature('Fully case sensitive filesystem')
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/file', 'source/FILE'])
        source.add(['file', 'FILE'], ids=[b'lower-id', b'upper-id'])
        source.commit('added files')
        # Don't try this at home, kids!
        # Force the tree to report that it is case insensitive
        target = self.make_branch_and_tree('target')
        target.case_sensitive = False
        build_tree(source.basis_tree(), target, source, delta_from_tree=True)
        self.assertEqual('file.moved', target.id2path(b'lower-id'))
        self.assertEqual('FILE', target.id2path(b'upper-id'))

    def test_build_tree_observes_sha(self):
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/file1', 'source/dir/', 'source/dir/file2'])
        source.add(['file1', 'dir', 'dir/file2'],
                   ids=[b'file1-id', b'dir-id', b'file2-id'])
        source.commit('new files')
        target = self.make_branch_and_tree('target')
        target.lock_write()
        self.addCleanup(target.unlock)
        # We make use of the fact that DirState caches its cutoff time. So we
        # set the 'safe' time to one minute in the future.
        state = target.current_dirstate()
        state._cutoff_time = time.time() + 60
        build_tree(source.basis_tree(), target)
        entry1_sha = osutils.sha_file_by_name('source/file1')
        entry2_sha = osutils.sha_file_by_name('source/dir/file2')
        # entry[1] is the state information, entry[1][0] is the state of the
        # working tree, entry[1][0][1] is the sha value for the current working
        # tree
        entry1 = state._get_entry(0, path_utf8=b'file1')
        self.assertEqual(entry1_sha, entry1[1][0][1])
        # The 'size' field must also be set.
        self.assertEqual(25, entry1[1][0][2])
        entry1_state = entry1[1][0]
        entry2 = state._get_entry(0, path_utf8=b'dir/file2')
        self.assertEqual(entry2_sha, entry2[1][0][1])
        self.assertEqual(29, entry2[1][0][2])
        entry2_state = entry2[1][0]
        # Now, make sure that we don't have to re-read the content. The
        # packed_stat should match exactly.
        self.assertEqual(entry1_sha, target.get_file_sha1('file1'))
        self.assertEqual(entry2_sha, target.get_file_sha1('dir/file2'))
        self.assertEqual(entry1_state, entry1[1][0])
        self.assertEqual(entry2_state, entry2[1][0])

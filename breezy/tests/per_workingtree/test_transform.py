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

import errno
from io import BytesIO
import os
import sys
import time

from ... import (
    osutils,
    tests,
    trace,
    transform,
    urlutils,
    )
from ...transport import FileExists
from ...tree import TreeChange
from ...bzr.conflicts import (
    DeletingParent,
    DuplicateEntry,
    DuplicateID,
    MissingParent,
    NonDirectoryParent,
    ParentLoop,
    UnversionedParent,
)
from ...errors import (
    DuplicateKey,
    ExistingLimbo,
    ExistingPendingDeletion,
    ImmortalPendingDeletion,
    LockError,
)
from ...osutils import (
    file_kind,
    pathjoin,
)
from .. import (
    features,
    TestSkipped,
    )
from ..features import (
    HardlinkFeature,
    SymlinkFeature,
    )
from ...transform import (
    create_from_tree,
    FinalPaths,
    resolve_conflicts,
    ROOT_PARENT,
    ImmortalLimbo,
    MalformedTransform,
    NoFinalPath,
    ReusingTransform,
    TransformRenameFailed,
)

from breezy.bzr.transform import resolve_checkout

from breezy.tests.per_workingtree import TestCaseWithWorkingTree
from breezy.tests.matchers import MatchesTreeChanges



class TestTreeTransform(TestCaseWithWorkingTree):

    def setUp(self):
        super(TestTreeTransform, self).setUp()
        self.wt = self.make_branch_and_tree('wt')

    def transform(self):
        transform = self.wt.transform()
        self.addCleanup(transform.finalize)
        return transform, transform.root

    def transform_for_sha1_test(self):
        trans, root = self.transform()
        if getattr(self.wt, '_observed_sha1', None) is None:
            raise tests.TestNotApplicable(
                'wt format does not use _observed_sha1')
        self.wt.lock_tree_write()
        self.addCleanup(self.wt.unlock)
        contents = [b'just some content\n']
        sha1 = osutils.sha_strings(contents)
        # Roll back the clock
        trans._creation_mtime = time.time() - 20.0
        return trans, root, contents, sha1

    def test_existing_limbo(self):
        transform, root = self.transform()
        limbo_name = transform._limbodir
        deletion_path = transform._deletiondir
        os.mkdir(pathjoin(limbo_name, 'hehe'))
        self.assertRaises(ImmortalLimbo, transform.apply)
        self.assertRaises(LockError, self.wt.unlock)
        self.assertRaises(ExistingLimbo, self.transform)
        self.assertRaises(LockError, self.wt.unlock)
        os.rmdir(pathjoin(limbo_name, 'hehe'))
        os.rmdir(limbo_name)
        os.rmdir(deletion_path)
        transform, root = self.transform()
        transform.apply()

    def test_existing_pending_deletion(self):
        transform, root = self.transform()
        deletion_path = self._limbodir = urlutils.local_path_from_url(
            transform._tree._transport.abspath('pending-deletion'))
        os.mkdir(pathjoin(deletion_path, 'blocking-directory'))
        self.assertRaises(ImmortalPendingDeletion, transform.apply)
        self.assertRaises(LockError, self.wt.unlock)
        self.assertRaises(ExistingPendingDeletion, self.transform)

    def test_build(self):
        transform, root = self.transform()
        self.wt.lock_tree_write()
        self.addCleanup(self.wt.unlock)
        self.assertIs(transform.get_tree_parent(root), ROOT_PARENT)
        imaginary_id = transform.trans_id_tree_path('imaginary')
        imaginary_id2 = transform.trans_id_tree_path('imaginary/')
        self.assertEqual(imaginary_id, imaginary_id2)
        self.assertEqual(root, transform.get_tree_parent(imaginary_id))
        self.assertEqual('directory', transform.final_kind(root))
        if self.wt.supports_setting_file_ids():
            self.assertEqual(self.wt.path2id(''), transform.final_file_id(root))
        trans_id = transform.create_path('name', root)
        if self.wt.supports_setting_file_ids():
            self.assertIs(transform.final_file_id(trans_id), None)
        self.assertFalse(transform.final_is_versioned(trans_id))
        self.assertIs(None, transform.final_kind(trans_id))
        transform.create_file([b'contents'], trans_id)
        transform.set_executability(True, trans_id)
        transform.version_file(trans_id, file_id=b'my_pretties')
        self.assertRaises(DuplicateKey, transform.version_file,
                          trans_id, file_id=b'my_pretties')
        if self.wt.supports_setting_file_ids():
            self.assertEqual(transform.final_file_id(trans_id), b'my_pretties')
        self.assertTrue(transform.final_is_versioned(trans_id))
        self.assertEqual(transform.final_parent(trans_id), root)
        self.assertIs(transform.final_parent(root), ROOT_PARENT)
        self.assertIs(transform.get_tree_parent(root), ROOT_PARENT)
        oz_id = transform.create_path('oz', root)
        transform.create_directory(oz_id)
        transform.version_file(oz_id, file_id=b'ozzie')
        trans_id2 = transform.create_path('name2', root)
        transform.create_file([b'contents'], trans_id2)
        transform.set_executability(False, trans_id2)
        transform.version_file(trans_id2, file_id=b'my_pretties2')
        modified_paths = transform.apply().modified_paths
        with self.wt.get_file('name') as f:
            self.assertEqual(b'contents', f.read())
        if self.wt.supports_setting_file_ids():
            self.assertEqual(self.wt.path2id('name'), b'my_pretties')
        self.assertIs(self.wt.is_executable('name'), True)
        self.assertIs(self.wt.is_executable('name2'), False)
        self.assertEqual('directory', file_kind(self.wt.abspath('oz')))
        self.assertEqual(len(modified_paths), 3)
        if self.wt.supports_setting_file_ids():
            tree_mod_paths = [self.wt.abspath(self.wt.id2path(f)) for f in
                              (b'ozzie', b'my_pretties', b'my_pretties2')]
            self.assertSubset(tree_mod_paths, modified_paths)
        # is it safe to finalize repeatedly?
        transform.finalize()
        transform.finalize()

    def test_apply_informs_tree_of_observed_sha1(self):
        trans, root, contents, sha1 = self.transform_for_sha1_test()
        from ...bzr.workingtree import InventoryWorkingTree
        if not isinstance(self.wt, InventoryWorkingTree):
            self.skipTest('not a bzr working tree')
        trans_id = trans.new_file('file1', root, contents, file_id=b'file1-id',
                                  sha1=sha1)
        calls = []
        orig = self.wt._observed_sha1

        def _observed_sha1(*args):
            calls.append(args)
            orig(*args)
        self.wt._observed_sha1 = _observed_sha1
        trans.apply()
        self.assertEqual([('file1', trans._observed_sha1s[trans_id])],
                         calls)

    def test_create_file_caches_sha1(self):
        trans, root, contents, sha1 = self.transform_for_sha1_test()
        trans_id = trans.create_path('file1', root)
        trans.create_file(contents, trans_id, sha1=sha1)
        st_val = osutils.lstat(trans._limbo_name(trans_id))
        o_sha1, o_st_val = trans._observed_sha1s[trans_id]
        self.assertEqual(o_sha1, sha1)
        self.assertEqualStat(o_st_val, st_val)

    def test__apply_insertions_updates_sha1(self):
        trans, root, contents, sha1 = self.transform_for_sha1_test()
        trans_id = trans.create_path('file1', root)
        trans.create_file(contents, trans_id, sha1=sha1)
        st_val = osutils.lstat(trans._limbo_name(trans_id))
        o_sha1, o_st_val = trans._observed_sha1s[trans_id]
        self.assertEqual(o_sha1, sha1)
        self.assertEqualStat(o_st_val, st_val)
        creation_mtime = trans._creation_mtime + 10.0
        # We fake a time difference from when the file was created until now it
        # is being renamed by using os.utime. Note that the change we actually
        # want to see is the real ctime change from 'os.rename()', but as long
        # as we observe a new stat value, we should be fine.
        os.utime(trans._limbo_name(trans_id), (creation_mtime, creation_mtime))
        trans.apply()
        new_st_val = osutils.lstat(self.wt.abspath('file1'))
        o_sha1, o_st_val = trans._observed_sha1s[trans_id]
        self.assertEqual(o_sha1, sha1)
        self.assertEqualStat(o_st_val, new_st_val)
        self.assertNotEqual(st_val.st_mtime, new_st_val.st_mtime)

    def test_new_file_caches_sha1(self):
        trans, root, contents, sha1 = self.transform_for_sha1_test()
        trans_id = trans.new_file('file1', root, contents, file_id=b'file1-id',
                                  sha1=sha1)
        st_val = osutils.lstat(trans._limbo_name(trans_id))
        o_sha1, o_st_val = trans._observed_sha1s[trans_id]
        self.assertEqual(o_sha1, sha1)
        self.assertEqualStat(o_st_val, st_val)

    def test_cancel_creation_removes_observed_sha1(self):
        trans, root, contents, sha1 = self.transform_for_sha1_test()
        trans_id = trans.new_file('file1', root, contents, file_id=b'file1-id',
                                  sha1=sha1)
        self.assertTrue(trans_id in trans._observed_sha1s)
        trans.cancel_creation(trans_id)
        self.assertFalse(trans_id in trans._observed_sha1s)

    def test_create_files_same_timestamp(self):
        transform, root = self.transform()
        self.wt.lock_tree_write()
        self.addCleanup(self.wt.unlock)
        # Roll back the clock, so that we know everything is being set to the
        # exact time
        transform._creation_mtime = creation_mtime = time.time() - 20.0
        transform.create_file([b'content-one'],
                              transform.create_path('one', root))
        time.sleep(1)  # *ugly*
        transform.create_file([b'content-two'],
                              transform.create_path('two', root))
        transform.apply()
        fo, st1 = self.wt.get_file_with_stat('one', filtered=False)
        fo.close()
        fo, st2 = self.wt.get_file_with_stat('two', filtered=False)
        fo.close()
        # We only guarantee 2s resolution
        self.assertTrue(
            abs(creation_mtime - st1.st_mtime) < 2.0,
            "%s != %s within 2 seconds" % (creation_mtime, st1.st_mtime))
        # But if we have more than that, all files should get the same result
        self.assertEqual(st1.st_mtime, st2.st_mtime)

    def test_change_root_id(self):
        if not self.workingtree_format.supports_setting_file_ids:
            raise tests.TestNotApplicable(
                'format does not support setting file ids')
        transform, root = self.transform()
        self.assertNotEqual(b'new-root-id', self.wt.path2id(''))
        transform.new_directory('', ROOT_PARENT, b'new-root-id')
        transform.delete_contents(root)
        transform.unversion_file(root)
        transform.fixup_new_roots()
        transform.apply()
        self.assertEqual(b'new-root-id', self.wt.path2id(''))

    def test_replace_root(self):
        transform, root = self.transform()
        transform.new_directory('', ROOT_PARENT, b'new-root-id')
        transform.delete_contents(root)
        transform.unversion_file(root)
        transform.fixup_new_roots()
        transform.apply()

    def test_change_root_id_add_files(self):
        if not self.workingtree_format.supports_setting_file_ids:
            raise tests.TestNotApplicable(
                'format does not support setting file ids')
        transform, root = self.transform()
        self.assertNotEqual(b'new-root-id', self.wt.path2id(''))
        new_trans_id = transform.new_directory('', ROOT_PARENT, b'new-root-id')
        transform.new_file('file', new_trans_id, [b'new-contents\n'],
                           b'new-file-id')
        transform.delete_contents(root)
        transform.unversion_file(root)
        transform.fixup_new_roots()
        transform.apply()
        self.assertEqual(b'new-root-id', self.wt.path2id(''))
        self.assertEqual(b'new-file-id', self.wt.path2id('file'))
        self.assertFileEqual(b'new-contents\n', self.wt.abspath('file'))

    def test_add_two_roots(self):
        transform, root = self.transform()
        transform.new_directory('', ROOT_PARENT, b'new-root-id')
        transform.new_directory('', ROOT_PARENT, b'alt-root-id')
        self.assertRaises(ValueError, transform.fixup_new_roots)

    def test_retain_existing_root(self):
        tt, root = self.transform()
        with tt:
            tt.new_directory('', ROOT_PARENT, b'new-root-id')
            tt.fixup_new_roots()
            if self.wt.has_versioned_directories():
                self.assertTrue(tt.final_is_versioned(tt.root))
            if self.wt.supports_setting_file_ids():
                self.assertNotEqual(b'new-root-id', tt.final_file_id(tt.root))

    def test_retain_existing_root_added_file(self):
        tt, root = self.transform()
        new_trans_id = tt.new_directory('', ROOT_PARENT, b'new-root-id')
        child = tt.new_directory('child', new_trans_id, b'child-id')
        tt.fixup_new_roots()
        self.assertEqual(tt.root, tt.final_parent(child))

    def test_add_unversioned_root(self):
        transform, root = self.transform()
        transform.new_directory('', ROOT_PARENT, None)
        transform.delete_contents(transform.root)
        transform.fixup_new_roots()
        self.assertNotIn(transform.root, getattr(transform, '_new_id', []))

    def test_remove_root_fixup(self):
        transform, root = self.transform()
        if not self.wt.supports_setting_file_ids():
            self.skipTest('format does not support file ids')
        old_root_id = self.wt.path2id('')
        self.assertNotEqual(b'new-root-id', old_root_id)
        transform.delete_contents(root)
        transform.unversion_file(root)
        transform.fixup_new_roots()
        transform.apply()
        self.assertEqual(old_root_id, self.wt.path2id(''))

        transform, root = self.transform()
        transform.new_directory('', ROOT_PARENT, b'new-root-id')
        transform.new_directory('', ROOT_PARENT, b'alt-root-id')
        self.assertRaises(ValueError, transform.fixup_new_roots)

    def test_fixup_new_roots_permits_empty_tree(self):
        transform, root = self.transform()
        transform.delete_contents(root)
        transform.unversion_file(root)
        transform.fixup_new_roots()
        self.assertIs(None, transform.final_kind(root))
        if self.wt.supports_setting_file_ids():
            self.assertIs(None, transform.final_file_id(root))

    def test_apply_retains_root_directory(self):
        # Do not attempt to delete the physical root directory, because that
        # is impossible.
        transform, root = self.transform()
        with transform:
            transform.delete_contents(root)
            e = self.assertRaises(AssertionError, self.assertRaises,
                                  TransformRenameFailed,
                                  transform.apply)
        self.assertContainsRe('TransformRenameFailed not raised', str(e))

    def test_apply_retains_file_id(self):
        transform, root = self.transform()
        if not self.wt.supports_setting_file_ids():
            self.skipTest('format does not support file ids')
        old_root_id = transform.tree_file_id(root)
        transform.unversion_file(root)
        transform.apply()
        self.assertEqual(old_root_id, self.wt.path2id(''))

    def test_hardlink(self):
        self.requireFeature(HardlinkFeature(self.test_dir))
        transform, root = self.transform()
        transform.new_file('file1', root, [b'contents'])
        transform.apply()
        target = self.make_branch_and_tree('target')
        target_transform = target.transform()
        trans_id = target_transform.create_path('file1', target_transform.root)
        target_transform.create_hardlink(self.wt.abspath('file1'), trans_id)
        target_transform.apply()
        self.assertPathExists('target/file1')
        source_stat = os.stat(self.wt.abspath('file1'))
        target_stat = os.stat('target/file1')
        self.assertEqual(source_stat, target_stat)

    def test_convenience(self):
        transform, root = self.transform()
        self.wt.lock_tree_write()
        self.addCleanup(self.wt.unlock)
        transform.new_file('name', root, [b'contents'], b'my_pretties', True)
        oz = transform.new_directory('oz', root, b'oz-id')
        dorothy = transform.new_directory('dorothy', oz, b'dorothy-id')
        transform.new_file('toto', dorothy, [b'toto-contents'], b'toto-id',
                           False)

        self.assertEqual(len(transform.find_raw_conflicts()), 0)
        transform.apply()
        self.assertRaises(ReusingTransform, transform.find_raw_conflicts)
        with open(self.wt.abspath('name'), 'r') as f:
            self.assertEqual('contents', f.read())
        self.assertIs(self.wt.is_executable('name'), True)
        self.assertTrue(self.wt.is_versioned('name'))
        self.assertTrue(self.wt.is_versioned('oz'))
        self.assertTrue(self.wt.is_versioned('oz/dorothy'))
        self.assertTrue(self.wt.is_versioned('oz/dorothy/toto'))
        if self.wt.supports_setting_file_ids():
            self.assertEqual(self.wt.path2id('name'), b'my_pretties')
            self.assertEqual(self.wt.path2id('oz'), b'oz-id')
            self.assertEqual(self.wt.path2id('oz/dorothy'), b'dorothy-id')
            self.assertEqual(self.wt.path2id('oz/dorothy/toto'), b'toto-id')

        with self.wt.get_file('oz/dorothy/toto') as f:
            self.assertEqual(b'toto-contents', f.read())
        self.assertIs(self.wt.is_executable('oz/dorothy/toto'), False)

    def test_tree_reference(self):
        transform, root = self.transform()
        tree = transform._tree
        if not tree.supports_tree_reference():
            raise tests.TestNotApplicable(
                'Tree format does not support references')
        nested_tree = self.make_branch_and_tree('nested')
        nested_revid = nested_tree.commit('commit')

        trans_id = transform.new_directory('reference', root, b'subtree-id')
        transform.set_tree_reference(nested_revid, trans_id)
        transform.apply()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(
            nested_revid,
            tree.get_reference_revision('reference'))

    def test_conflicts(self):
        transform, root = self.transform()
        trans_id = transform.new_file('name', root, [b'contents'],
                                      b'my_pretties')
        self.assertEqual(len(transform.find_raw_conflicts()), 0)
        trans_id2 = transform.new_file('name', root, [b'Crontents'], b'toto')
        self.assertEqual(transform.find_raw_conflicts(),
                         [('duplicate', trans_id, trans_id2, 'name')])
        self.assertRaises(MalformedTransform, transform.apply)
        transform.adjust_path('name', trans_id, trans_id2)
        self.assertEqual(transform.find_raw_conflicts(),
                         [('non-directory parent', trans_id)])
        tinman_id = transform.trans_id_tree_path('tinman')
        transform.adjust_path('name', tinman_id, trans_id2)
        if self.wt.has_versioned_directories():
            self.assertEqual(transform.find_raw_conflicts(),
                             [('unversioned parent', tinman_id),
                              ('missing parent', tinman_id)])
        else:
            self.assertEqual(transform.find_raw_conflicts(),
                             [('missing parent', tinman_id)])
        lion_id = transform.create_path('lion', root)
        if self.wt.has_versioned_directories():
            self.assertEqual(transform.find_raw_conflicts(),
                             [('unversioned parent', tinman_id),
                              ('missing parent', tinman_id)])
        else:
            self.assertEqual(transform.find_raw_conflicts(),
                             [('missing parent', tinman_id)])
        transform.adjust_path('name', lion_id, trans_id2)
        if self.wt.has_versioned_directories():
            self.assertEqual(transform.find_raw_conflicts(),
                             [('unversioned parent', lion_id),
                              ('missing parent', lion_id)])
        else:
            self.assertEqual(transform.find_raw_conflicts(),
                             [('missing parent', lion_id)])
        transform.version_file(lion_id, file_id=b"Courage")
        self.assertEqual(transform.find_raw_conflicts(),
                         [('missing parent', lion_id),
                          ('versioning no contents', lion_id)])
        transform.adjust_path('name2', root, trans_id2)
        self.assertEqual(transform.find_raw_conflicts(),
                         [('versioning no contents', lion_id)])
        transform.create_file([b'Contents, okay?'], lion_id)
        transform.adjust_path('name2', trans_id2, trans_id2)
        self.assertEqual(transform.find_raw_conflicts(),
                         [('parent loop', trans_id2),
                          ('non-directory parent', trans_id2)])
        transform.adjust_path('name2', root, trans_id2)
        oz_id = transform.new_directory('oz', root)
        transform.set_executability(True, oz_id)
        self.assertEqual(transform.find_raw_conflicts(),
                         [('unversioned executability', oz_id)])
        transform.version_file(oz_id, file_id=b'oz-id')
        self.assertEqual(transform.find_raw_conflicts(),
                         [('non-file executability', oz_id)])
        transform.set_executability(None, oz_id)
        tip_id = transform.new_file('tip', oz_id, [b'ozma'], b'tip-id')
        transform.apply()
        if self.wt.supports_setting_file_ids():
            self.assertEqual(self.wt.path2id('name'), b'my_pretties')
        with open(self.wt.abspath('name'), 'rb') as f:
            self.assertEqual(b'contents', f.read())
        transform2, root = self.transform()
        oz_id = transform2.trans_id_tree_path('oz')
        newtip = transform2.new_file('tip', oz_id, [b'other'], b'tip-id')
        result = transform2.find_raw_conflicts()
        fp = FinalPaths(transform2)
        self.assertTrue('oz/tip' in transform2._tree_path_ids)
        self.assertEqual(fp.get_path(newtip), pathjoin('oz', 'tip'))
        if self.wt.supports_setting_file_ids():
            self.assertEqual(len(result), 2)
            self.assertEqual((result[1][0], result[1][2]),
                             ('duplicate id', newtip))
        else:
            self.assertEqual(len(result), 1)
        self.assertEqual((result[0][0], result[0][1]),
                         ('duplicate', newtip))
        transform2.finalize()
        transform3 = self.wt.transform()
        self.addCleanup(transform3.finalize)
        oz_id = transform3.trans_id_tree_path('oz')
        transform3.delete_contents(oz_id)
        self.assertEqual(transform3.find_raw_conflicts(),
                         [('missing parent', oz_id)])
        root_id = transform3.root
        tip_id = transform3.trans_id_tree_path('oz/tip')
        transform3.adjust_path('tip', root_id, tip_id)
        transform3.apply()

    def test_conflict_on_case_insensitive(self):
        tree = self.make_branch_and_tree('tree')
        # Don't try this at home, kids!
        # Force the tree to report that it is case sensitive, for conflict
        # resolution tests
        tree.case_sensitive = True
        transform = tree.transform()
        self.addCleanup(transform.finalize)
        transform.new_file('file', transform.root, [b'content'])
        transform.new_file('FiLe', transform.root, [b'content'])
        result = transform.find_raw_conflicts()
        self.assertEqual([], result)
        transform.finalize()
        # Force the tree to report that it is case insensitive, for conflict
        # generation tests
        tree.case_sensitive = False
        transform = tree.transform()
        self.addCleanup(transform.finalize)
        transform.new_file('file', transform.root, [b'content'])
        transform.new_file('FiLe', transform.root, [b'content'])
        result = transform.find_raw_conflicts()
        self.assertEqual([('duplicate', 'new-1', 'new-2', 'file')], result)

    def test_conflict_on_case_insensitive_existing(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/FiLe'])
        # Don't try this at home, kids!
        # Force the tree to report that it is case sensitive, for conflict
        # resolution tests
        tree.case_sensitive = True
        transform = tree.transform()
        self.addCleanup(transform.finalize)
        transform.new_file('file', transform.root, [b'content'])
        result = transform.find_raw_conflicts()
        self.assertEqual([], result)
        transform.finalize()
        # Force the tree to report that it is case insensitive, for conflict
        # generation tests
        tree.case_sensitive = False
        transform = tree.transform()
        self.addCleanup(transform.finalize)
        transform.new_file('file', transform.root, [b'content'])
        result = transform.find_raw_conflicts()
        self.assertEqual([('duplicate', 'new-1', 'new-2', 'file')], result)

    def test_resolve_case_insensitive_conflict(self):
        tree = self.make_branch_and_tree('tree')
        # Don't try this at home, kids!
        # Force the tree to report that it is case insensitive, for conflict
        # resolution tests
        tree.case_sensitive = False
        transform = tree.transform()
        self.addCleanup(transform.finalize)
        transform.new_file('file', transform.root, [b'content'])
        transform.new_file('FiLe', transform.root, [b'content'])
        resolve_conflicts(transform)
        transform.apply()
        self.assertPathExists('tree/file')
        self.assertPathExists('tree/FiLe.moved')

    def test_resolve_checkout_case_conflict(self):
        tree = self.make_branch_and_tree('tree')
        # Don't try this at home, kids!
        # Force the tree to report that it is case insensitive, for conflict
        # resolution tests
        tree.case_sensitive = False
        transform = tree.transform()
        self.addCleanup(transform.finalize)
        transform.new_file('file', transform.root, [b'content'])
        transform.new_file('FiLe', transform.root, [b'content'])
        resolve_conflicts(transform,
                          pass_func=lambda t, c: resolve_checkout(t, c, []))
        transform.apply()
        self.assertPathExists('tree/file')
        self.assertPathExists('tree/FiLe.moved')

    def test_apply_case_conflict(self):
        """Ensure that a transform with case conflicts can always be applied"""
        tree = self.make_branch_and_tree('tree')
        transform = tree.transform()
        self.addCleanup(transform.finalize)
        transform.new_file('file', transform.root, [b'content'])
        transform.new_file('FiLe', transform.root, [b'content'])
        dir = transform.new_directory('dir', transform.root)
        transform.new_file('dirfile', dir, [b'content'])
        transform.new_file('dirFiLe', dir, [b'content'])
        resolve_conflicts(transform)
        transform.apply()
        self.assertPathExists('tree/file')
        if not os.path.exists('tree/FiLe.moved'):
            self.assertPathExists('tree/FiLe')
        self.assertPathExists('tree/dir/dirfile')
        if not os.path.exists('tree/dir/dirFiLe.moved'):
            self.assertPathExists('tree/dir/dirFiLe')

    def test_case_insensitive_limbo(self):
        tree = self.make_branch_and_tree('tree')
        # Don't try this at home, kids!
        # Force the tree to report that it is case insensitive
        tree.case_sensitive = False
        transform = tree.transform()
        self.addCleanup(transform.finalize)
        dir = transform.new_directory('dir', transform.root)
        first = transform.new_file('file', dir, [b'content'])
        second = transform.new_file('FiLe', dir, [b'content'])
        self.assertContainsRe(transform._limbo_name(first), 'new-1/file')
        self.assertNotContainsRe(transform._limbo_name(second), 'new-1/FiLe')

    def test_adjust_path_updates_child_limbo_names(self):
        tree = self.make_branch_and_tree('tree')
        transform = tree.transform()
        self.addCleanup(transform.finalize)
        foo_id = transform.new_directory('foo', transform.root)
        bar_id = transform.new_directory('bar', foo_id)
        baz_id = transform.new_directory('baz', bar_id)
        qux_id = transform.new_directory('qux', baz_id)
        transform.adjust_path('quxx', foo_id, bar_id)
        self.assertStartsWith(transform._limbo_name(qux_id),
                              transform._limbo_name(bar_id))

    def test_add_del(self):
        start, root = self.transform()
        start.new_directory('a', root, b'a')
        start.apply()
        transform, root = self.transform()
        transform.delete_versioned(transform.trans_id_tree_path('a'))
        transform.new_directory('a', root, b'a')
        transform.apply()

    def test_unversioning(self):
        create_tree, root = self.transform()
        parent_id = create_tree.new_directory('parent', root, b'parent-id')
        create_tree.new_file('child', parent_id, [b'child'], b'child-id')
        create_tree.apply()
        unversion = self.wt.transform()
        self.addCleanup(unversion.finalize)
        parent = unversion.trans_id_tree_path('parent')
        unversion.unversion_file(parent)
        if self.wt.has_versioned_directories():
            self.assertEqual(unversion.find_raw_conflicts(),
                             [('unversioned parent', parent_id)])
        else:
            self.assertEqual(unversion.find_raw_conflicts(), [])
        file_id = unversion.trans_id_tree_path('parent/child')
        unversion.unversion_file(file_id)
        unversion.apply()

    def test_name_invariants(self):
        create_tree, root = self.transform()
        # prepare tree
        root = create_tree.root
        create_tree.new_file('name1', root, [b'hello1'], b'name1')
        create_tree.new_file('name2', root, [b'hello2'], b'name2')
        ddir = create_tree.new_directory('dying_directory', root, b'ddir')
        create_tree.new_file('dying_file', ddir, [b'goodbye1'], b'dfile')
        create_tree.new_file('moving_file', ddir, [b'later1'], b'mfile')
        create_tree.new_file('moving_file2', root, [b'later2'], b'mfile2')
        create_tree.apply()

        mangle_tree, root = self.transform()
        root = mangle_tree.root
        # swap names
        name1 = mangle_tree.trans_id_tree_path('name1')
        name2 = mangle_tree.trans_id_tree_path('name2')
        mangle_tree.adjust_path('name2', root, name1)
        mangle_tree.adjust_path('name1', root, name2)

        # tests for deleting parent directories
        ddir = mangle_tree.trans_id_tree_path('dying_directory')
        mangle_tree.delete_contents(ddir)
        dfile = mangle_tree.trans_id_tree_path('dying_directory/dying_file')
        mangle_tree.delete_versioned(dfile)
        mangle_tree.unversion_file(dfile)
        mfile = mangle_tree.trans_id_tree_path('dying_directory/moving_file')
        mangle_tree.adjust_path('mfile', root, mfile)

        # tests for adding parent directories
        newdir = mangle_tree.new_directory('new_directory', root, b'newdir')
        mfile2 = mangle_tree.trans_id_tree_path('moving_file2')
        mangle_tree.adjust_path('mfile2', newdir, mfile2)
        mangle_tree.new_file('newfile', newdir, [b'hello3'], b'dfile')
        if self.wt.supports_setting_file_ids():
            self.assertEqual(mangle_tree.final_file_id(mfile2), b'mfile2')
        self.assertEqual(mangle_tree.final_parent(mfile2), newdir)
        mangle_tree.apply()
        with open(self.wt.abspath('name1'), 'r') as f:
            self.assertEqual(f.read(), 'hello2')
        with open(self.wt.abspath('name2'), 'r') as f:
            self.assertEqual(f.read(), 'hello1')
        mfile2_path = self.wt.abspath(pathjoin('new_directory', 'mfile2'))
        self.assertEqual(mangle_tree.final_parent(mfile2), newdir)
        with open(mfile2_path, 'r') as f:
            self.assertEqual(f.read(), 'later2')
        if self.wt.supports_setting_file_ids():
            self.assertEqual(self.wt.id2path(b'mfile2'), 'new_directory/mfile2')
            self.assertEqual(self.wt.path2id('new_directory/mfile2'), b'mfile2')
        newfile_path = self.wt.abspath(pathjoin('new_directory', 'newfile'))
        with open(newfile_path, 'r') as f:
            self.assertEqual(f.read(), 'hello3')
        if self.wt.supports_setting_file_ids():
            self.assertEqual(self.wt.path2id('dying_directory'), b'ddir')
            self.assertIs(self.wt.path2id('dying_directory/dying_file'), None)
        mfile2_path = self.wt.abspath(pathjoin('new_directory', 'mfile2'))

    def test_both_rename(self):
        create_tree, root = self.transform()
        newdir = create_tree.new_directory('selftest', root, b'selftest-id')
        create_tree.new_file('blackbox.py', newdir, [
                             b'hello1'], b'blackbox-id')
        create_tree.apply()
        mangle_tree, root = self.transform()
        selftest = mangle_tree.trans_id_tree_path('selftest')
        blackbox = mangle_tree.trans_id_tree_path('selftest/blackbox.py')
        mangle_tree.adjust_path('test', root, selftest)
        mangle_tree.adjust_path('test_too_much', root, selftest)
        mangle_tree.set_executability(True, blackbox)
        mangle_tree.apply()

    def test_both_rename2(self):
        create_tree, root = self.transform()
        breezy = create_tree.new_directory('breezy', root, b'breezy-id')
        tests = create_tree.new_directory('tests', breezy, b'tests-id')
        blackbox = create_tree.new_directory('blackbox', tests, b'blackbox-id')
        create_tree.new_file('test_too_much.py', blackbox, [b'hello1'],
                             b'test_too_much-id')
        create_tree.apply()
        mangle_tree, root = self.transform()
        breezy = mangle_tree.trans_id_tree_path('breezy')
        tests = mangle_tree.trans_id_tree_path('breezy/tests')
        test_too_much = mangle_tree.trans_id_tree_path(
            'breezy/tests/blackbox/test_too_much.py')
        mangle_tree.adjust_path('selftest', breezy, tests)
        mangle_tree.adjust_path('blackbox.py', tests, test_too_much)
        mangle_tree.set_executability(True, test_too_much)
        mangle_tree.apply()

    def test_both_rename3(self):
        create_tree, root = self.transform()
        tests = create_tree.new_directory('tests', root, b'tests-id')
        create_tree.new_file('test_too_much.py', tests, [b'hello1'],
                             b'test_too_much-id')
        create_tree.apply()
        mangle_tree, root = self.transform()
        tests = mangle_tree.trans_id_tree_path('tests')
        test_too_much = mangle_tree.trans_id_tree_path(
            'tests/test_too_much.py')
        mangle_tree.adjust_path('selftest', root, tests)
        mangle_tree.adjust_path('blackbox.py', tests, test_too_much)
        mangle_tree.set_executability(True, test_too_much)
        mangle_tree.apply()

    def test_move_dangling_ie(self):
        create_tree, root = self.transform()
        # prepare tree
        root = create_tree.root
        create_tree.new_file('name1', root, [b'hello1'], b'name1')
        create_tree.apply()
        delete_contents, root = self.transform()
        file = delete_contents.trans_id_tree_path('name1')
        delete_contents.delete_contents(file)
        delete_contents.apply()
        move_id, root = self.transform()
        name1 = move_id.trans_id_tree_path('name1')
        newdir = move_id.new_directory('dir', root, b'newdir')
        move_id.adjust_path('name2', newdir, name1)
        move_id.apply()

    def test_replace_dangling_ie(self):
        create_tree, root = self.transform()
        # prepare tree
        root = create_tree.root
        create_tree.new_file('name1', root, [b'hello1'], b'name1')
        create_tree.apply()
        delete_contents = self.wt.transform()
        self.addCleanup(delete_contents.finalize)
        file = delete_contents.trans_id_tree_path('name1')
        delete_contents.delete_contents(file)
        delete_contents.apply()
        delete_contents.finalize()
        replace = self.wt.transform()
        self.addCleanup(replace.finalize)
        name2 = replace.new_file('name2', root, [b'hello2'], b'name1')
        conflicts = replace.find_raw_conflicts()
        name1 = replace.trans_id_tree_path('name1')
        if self.wt.supports_setting_file_ids():
            self.assertEqual(conflicts, [('duplicate id', name1, name2)])
        else:
            self.assertEqual(conflicts, [])
        resolve_conflicts(replace)
        replace.apply()

    def _test_symlinks(self, link_name1, link_target1,
                       link_name2, link_target2):

        def ozpath(p):
            return 'oz/' + p

        self.requireFeature(SymlinkFeature(self.test_dir))
        transform, root = self.transform()
        oz_id = transform.new_directory('oz', root, b'oz-id')
        transform.new_symlink(link_name1, oz_id, link_target1, b'wizard-id')
        wiz_id = transform.create_path(link_name2, oz_id)
        transform.create_symlink(link_target2, wiz_id)
        transform.version_file(wiz_id, file_id=b'wiz-id2')
        transform.set_executability(True, wiz_id)
        self.assertEqual(transform.find_raw_conflicts(),
                         [('non-file executability', wiz_id)])
        transform.set_executability(None, wiz_id)
        transform.apply()
        if self.wt.supports_setting_file_ids():
            self.assertEqual(self.wt.path2id(ozpath(link_name1)), b'wizard-id')
        self.assertEqual('symlink',
                         file_kind(self.wt.abspath(ozpath(link_name1))))
        self.assertEqual(link_target2,
                         osutils.readlink(self.wt.abspath(ozpath(link_name2))))
        self.assertEqual(link_target1,
                         osutils.readlink(self.wt.abspath(ozpath(link_name1))))

    def test_symlinks(self):
        self._test_symlinks('wizard', 'wizard-target',
                            'wizard2', 'behind_curtain')

    def test_symlinks_unicode(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        self._test_symlinks(u'\N{Euro Sign}wizard',
                            u'wizard-targ\N{Euro Sign}t',
                            u'\N{Euro Sign}wizard2',
                            u'b\N{Euro Sign}hind_curtain')

    def test_unsupported_symlink_no_conflict(self):
        def tt_helper():
            wt = self.make_branch_and_tree('.')
            tt = wt.transform()
            self.addCleanup(tt.finalize)
            tt.new_symlink('foo', tt.root, 'bar')
            result = tt.find_raw_conflicts()
            self.assertEqual([], result)
        os_symlink = getattr(os, 'symlink', None)
        os.symlink = None
        try:
            tt_helper()
        finally:
            if os_symlink:
                os.symlink = os_symlink

    def get_conflicted(self):
        create, root = self.transform()
        create.new_file('dorothy', root, [b'dorothy'], b'dorothy-id')
        oz = create.new_directory('oz', root, b'oz-id')
        create.new_directory('emeraldcity', oz, b'emerald-id')
        create.apply()
        conflicts, root = self.transform()
        # set up duplicate entry, duplicate id
        new_dorothy = conflicts.new_file('dorothy', root, [b'dorothy'],
                                         b'dorothy-id')
        old_dorothy = conflicts.trans_id_tree_path('dorothy')
        oz = conflicts.trans_id_tree_path('oz')
        # set up DeletedParent parent conflict
        conflicts.delete_versioned(oz)
        emerald = conflicts.trans_id_tree_path('oz/emeraldcity')
        # set up MissingParent conflict
        if conflicts._tree.supports_setting_file_ids():
            munchkincity = conflicts.trans_id_file_id(b'munchkincity-id')
        else:
            munchkincity = conflicts.assign_id()
        conflicts.adjust_path('munchkincity', root, munchkincity)
        conflicts.new_directory('auntem', munchkincity, b'auntem-id')
        # set up parent loop
        conflicts.adjust_path('emeraldcity', emerald, emerald)
        return conflicts, emerald, oz, old_dorothy, new_dorothy, munchkincity

    def test_conflict_resolution(self):
        conflicts, emerald, oz, old_dorothy, new_dorothy, munchkincity =\
            self.get_conflicted()
        resolve_conflicts(conflicts)
        self.assertEqual(conflicts.final_name(old_dorothy), 'dorothy.moved')
        if self.wt.supports_setting_file_ids():
            self.assertIs(conflicts.final_file_id(old_dorothy), None)
            self.assertEqual(conflicts.final_file_id(new_dorothy), b'dorothy-id')
        self.assertEqual(conflicts.final_name(new_dorothy), 'dorothy')
        self.assertEqual(conflicts.final_parent(emerald), oz)
        conflicts.apply()

    def test_cook_conflicts(self):
        tt, emerald, oz, old_dorothy, new_dorothy, munchkincity = self.get_conflicted()
        raw_conflicts = resolve_conflicts(tt)
        cooked_conflicts = list(tt.cook_conflicts(raw_conflicts))
        if self.wt.supports_setting_file_ids():
            duplicate = DuplicateEntry('Moved existing file to', 'dorothy.moved',
                                       'dorothy', None, b'dorothy-id')
            self.assertEqual(cooked_conflicts[0], duplicate)
            duplicate_id = DuplicateID('Unversioned existing file',
                                       'dorothy.moved', 'dorothy', None,
                                       b'dorothy-id')
            self.assertEqual(cooked_conflicts[1], duplicate_id)
            missing_parent = MissingParent('Created directory', 'munchkincity',
                                           b'munchkincity-id')
            deleted_parent = DeletingParent('Not deleting', 'oz', b'oz-id')
            self.assertEqual(cooked_conflicts[2], missing_parent)
            unversioned_parent = UnversionedParent('Versioned directory',
                                                   'munchkincity',
                                                   b'munchkincity-id')
            unversioned_parent2 = UnversionedParent('Versioned directory', 'oz',
                                                    b'oz-id')
            self.assertEqual(cooked_conflicts[3], unversioned_parent)
            parent_loop = ParentLoop(
                'Cancelled move', 'oz/emeraldcity',
                'oz/emeraldcity', b'emerald-id', b'emerald-id')
            self.assertEqual(cooked_conflicts[4], deleted_parent)
            self.assertEqual(cooked_conflicts[5], unversioned_parent2)
            self.assertEqual(cooked_conflicts[6], parent_loop)
            self.assertEqual(len(cooked_conflicts), 7)
        else:
            self.assertEqual(
                set([c.path for c in cooked_conflicts]),
                set(['oz/emeraldcity', 'oz', 'munchkincity', 'dorothy.moved']))
        tt.finalize()

    def test_string_conflicts(self):
        tt, emerald, oz, old_dorothy, new_dorothy, munchkincity = self.get_conflicted()
        raw_conflicts = resolve_conflicts(tt)
        cooked_conflicts = list(tt.cook_conflicts(raw_conflicts))
        tt.finalize()
        conflicts_s = [str(c) for c in cooked_conflicts]
        self.assertEqual(len(cooked_conflicts), len(conflicts_s))
        if self.wt.supports_setting_file_ids():
            self.assertEqual(conflicts_s[0], 'Conflict adding file dorothy.  '
                                             'Moved existing file to '
                                             'dorothy.moved.')
            self.assertEqual(conflicts_s[1], 'Conflict adding id to dorothy.  '
                                             'Unversioned existing file '
                                             'dorothy.moved.')
            self.assertEqual(conflicts_s[2], 'Conflict adding files to'
                                             ' munchkincity.  Created directory.')
            self.assertEqual(conflicts_s[3], 'Conflict because munchkincity is not'
                                             ' versioned, but has versioned'
                                             ' children.  Versioned directory.')
            self.assertEqualDiff(
                conflicts_s[4], "Conflict: can't delete oz because it"
                                " is not empty.  Not deleting.")
            self.assertEqual(conflicts_s[5], 'Conflict because oz is not'
                                             ' versioned, but has versioned'
                                             ' children.  Versioned directory.')
            self.assertEqual(conflicts_s[6], 'Conflict moving oz/emeraldcity into'
                                             ' oz/emeraldcity. Cancelled move.')
        else:
            self.assertEqual(
                {'Text conflict in dorothy.moved',
                 'Text conflict in munchkincity',
                 'Text conflict in oz',
                 'Text conflict in oz/emeraldcity'},
                set([c for c in conflicts_s]))

    def prepare_wrong_parent_kind(self):
        tt, root = self.transform()
        tt.new_file('parent', root, [b'contents'], b'parent-id')
        tt.apply()
        tt, root = self.transform()
        parent_id = tt.trans_id_tree_path('parent')
        tt.new_file('child,', parent_id, [b'contents2'], b'file-id')
        return tt

    def test_find_raw_conflicts_wrong_parent_kind(self):
        tt = self.prepare_wrong_parent_kind()
        tt.find_raw_conflicts()

    def test_resolve_conflicts_wrong_existing_parent_kind(self):
        tt = self.prepare_wrong_parent_kind()
        raw_conflicts = resolve_conflicts(tt)
        self.assertEqual({('non-directory parent', 'Created directory',
                           'new-3')}, raw_conflicts)
        cooked_conflicts = list(tt.cook_conflicts(raw_conflicts))
        from ...bzr.workingtree import InventoryWorkingTree
        if isinstance(tt._tree, InventoryWorkingTree):
            self.assertEqual([NonDirectoryParent('Created directory', 'parent.new',
                                                 b'parent-id')], cooked_conflicts)
        else:
            self.assertEqual(1, len(cooked_conflicts))
            self.assertEqual('parent.new', cooked_conflicts[0].path)
        tt.apply()
        if self.wt.has_versioned_directories():
            self.assertFalse(self.wt.is_versioned('parent'))
        if self.wt.supports_setting_file_ids():
            self.assertEqual(b'parent-id', self.wt.path2id('parent.new'))

    def test_resolve_conflicts_wrong_new_parent_kind(self):
        tt, root = self.transform()
        parent_id = tt.new_directory('parent', root, b'parent-id')
        tt.new_file('child,', parent_id, [b'contents2'], b'file-id')
        tt.apply()
        tt, root = self.transform()
        parent_id = tt.trans_id_tree_path('parent')
        tt.delete_contents(parent_id)
        tt.create_file([b'contents'], parent_id)
        raw_conflicts = resolve_conflicts(tt)
        self.assertEqual({('non-directory parent', 'Created directory',
                           'new-3')}, raw_conflicts)
        tt.apply()
        if self.wt.has_versioned_directories():
            self.assertFalse(self.wt.is_versioned('parent'))
            self.assertTrue(self.wt.is_versioned('parent.new'))
        if self.wt.supports_setting_file_ids():
            self.assertEqual(b'parent-id', self.wt.path2id('parent.new'))

    def test_resolve_conflicts_wrong_parent_kind_unversioned(self):
        tt, root = self.transform()
        parent_id = tt.new_directory('parent', root)
        tt.new_file('child,', parent_id, [b'contents2'])
        tt.apply()
        tt, root = self.transform()
        parent_id = tt.trans_id_tree_path('parent')
        tt.delete_contents(parent_id)
        tt.create_file([b'contents'], parent_id)
        resolve_conflicts(tt)
        tt.apply()
        if self.wt.has_versioned_directories():
            self.assertFalse(self.wt.is_versioned('parent'))
            self.assertFalse(self.wt.is_versioned('parent.new'))

    def test_resolve_conflicts_missing_parent(self):
        wt = self.make_branch_and_tree('.')
        tt = wt.transform()
        self.addCleanup(tt.finalize)
        parent = tt.assign_id()
        tt.new_file('file', parent, [b'Contents'])
        raw_conflicts = resolve_conflicts(tt)
        # Since the directory doesn't exist it's seen as 'missing'.  So
        # 'resolve_conflicts' create a conflict asking for it to be created.
        self.assertLength(1, raw_conflicts)
        self.assertEqual(('missing parent', 'Created directory', 'new-1'),
                         raw_conflicts.pop())
        # apply fail since the missing directory doesn't exist
        self.assertRaises(NoFinalPath, tt.apply)

    def test_moving_versioned_directories(self):
        create, root = self.transform()
        kansas = create.new_directory('kansas', root, b'kansas-id')
        create.new_directory('house', kansas, b'house-id')
        create.new_directory('oz', root, b'oz-id')
        create.apply()
        cyclone, root = self.transform()
        oz = cyclone.trans_id_tree_path('oz')
        house = cyclone.trans_id_tree_path('house')
        cyclone.adjust_path('house', oz, house)
        cyclone.apply()

    def test_moving_root(self):
        create, root = self.transform()
        fun = create.new_directory('fun', root, b'fun-id')
        create.new_directory('sun', root, b'sun-id')
        create.new_directory('moon', root, b'moon')
        create.apply()
        transform, root = self.transform()
        transform.adjust_root_path('oldroot', fun)
        new_root = transform.trans_id_tree_path('')
        transform.version_file(new_root, file_id=b'new-root')
        transform.apply()

    def test_renames(self):
        create, root = self.transform()
        old = create.new_directory('old-parent', root, b'old-id')
        intermediate = create.new_directory('intermediate', old, b'im-id')
        myfile = create.new_file('myfile', intermediate, [b'myfile-text'],
                                 b'myfile-id')
        create.apply()
        rename, root = self.transform()
        old = rename.trans_id_tree_path('old-parent')
        rename.adjust_path('new', root, old)
        myfile = rename.trans_id_tree_path('old-parent/intermediate/myfile')
        rename.set_executability(True, myfile)
        rename.apply()

    def test_rename_fails(self):
        self.requireFeature(features.not_running_as_root)
        # see https://bugs.launchpad.net/bzr/+bug/491763
        create, root_id = self.transform()
        create.new_directory('first-dir', root_id, b'first-id')
        create.new_file('myfile', root_id, [b'myfile-text'], b'myfile-id')
        create.apply()
        if os.name == "posix" and sys.platform != "cygwin":
            # posix filesystems fail on renaming if the readonly bit is set
            osutils.make_readonly(self.wt.abspath('first-dir'))
        elif os.name == "nt":
            # windows filesystems fail on renaming open files
            self.addCleanup(open(self.wt.abspath('myfile')).close)
        else:
            self.skipTest("Can't force a permissions error on rename")
        # now transform to rename
        rename_transform, root_id = self.transform()
        file_trans_id = rename_transform.trans_id_tree_path('myfile')
        dir_id = rename_transform.trans_id_tree_path('first-dir')
        rename_transform.adjust_path('newname', dir_id, file_trans_id)
        e = self.assertRaises(TransformRenameFailed,
                              rename_transform.apply)
        # On nix looks like:
        # "Failed to rename .../work/.bzr/checkout/limbo/new-1
        # to .../first-dir/newname: [Errno 13] Permission denied"
        # On windows looks like:
        # "Failed to rename .../work/myfile to
        # .../work/.bzr/checkout/limbo/new-1: [Errno 13] Permission denied"
        # This test isn't concerned with exactly what the error looks like,
        # and the strerror will vary across OS and locales, but the assert
        # that the exeception attributes are what we expect
        self.assertEqual(e.errno, errno.EACCES)
        if os.name == "posix":
            self.assertEndsWith(e.to_path, "/first-dir/newname")
        else:
            self.assertEqual(os.path.basename(e.from_path), "myfile")

    def test_set_executability_order(self):
        """Ensure that executability behaves the same, no matter what order.

        - create file and set executability simultaneously
        - create file and set executability afterward
        - unsetting the executability of a file whose executability has not
          been
        declared should throw an exception (this may happen when a
        merge attempts to create a file with a duplicate ID)
        """
        transform, root = self.transform()
        wt = transform._tree
        wt.lock_read()
        self.addCleanup(wt.unlock)
        transform.new_file('set_on_creation', root, [b'Set on creation'],
                           b'soc', True)
        sac = transform.new_file('set_after_creation', root,
                                 [b'Set after creation'], b'sac')
        transform.set_executability(True, sac)
        uws = transform.new_file('unset_without_set', root, [b'Unset badly'],
                                 b'uws')
        self.assertRaises(KeyError, transform.set_executability, None, uws)
        transform.apply()
        self.assertTrue(wt.is_executable('set_on_creation'))
        self.assertTrue(wt.is_executable('set_after_creation'))

    def test_preserve_mode(self):
        """File mode is preserved when replacing content"""
        if sys.platform == 'win32':
            raise TestSkipped('chmod has no effect on win32')
        transform, root = self.transform()
        transform.new_file('file1', root, [b'contents'], b'file1-id', True)
        transform.apply()
        self.wt.lock_write()
        self.addCleanup(self.wt.unlock)
        self.assertTrue(self.wt.is_executable('file1'))
        transform, root = self.transform()
        file1_id = transform.trans_id_tree_path('file1')
        transform.delete_contents(file1_id)
        transform.create_file([b'contents2'], file1_id)
        transform.apply()
        self.assertTrue(self.wt.is_executable('file1'))

    def test__set_mode_stats_correctly(self):
        """_set_mode stats to determine file mode."""
        if sys.platform == 'win32':
            raise TestSkipped('chmod has no effect on win32')

        stat_paths = []
        real_stat = os.stat

        def instrumented_stat(path):
            stat_paths.append(path)
            return real_stat(path)

        transform, root = self.transform()

        bar1_id = transform.new_file('bar', root, [b'bar contents 1\n'],
                                     file_id=b'bar-id-1', executable=False)
        transform.apply()

        transform, root = self.transform()
        bar1_id = transform.trans_id_tree_path('bar')
        bar2_id = transform.trans_id_tree_path('bar2')
        try:
            os.stat = instrumented_stat
            transform.create_file([b'bar2 contents\n'],
                                  bar2_id, mode_id=bar1_id)
        finally:
            os.stat = real_stat
            transform.finalize()

        bar1_abspath = self.wt.abspath('bar')
        self.assertEqual([bar1_abspath], stat_paths)

    def test_iter_changes(self):
        transform, root = self.transform()
        transform.new_file('old', root, [b'blah'], b'id-1', True)
        transform.apply()
        transform, root = self.transform()
        try:
            self.assertTreeChanges(transform, [])
            old = transform.trans_id_tree_path('old')
            transform.unversion_file(old)
            self.assertTreeChanges(
                transform, [
                    TreeChange(
                        ('old', None), False, (True, False),
                        ('old', 'old'), ('file', 'file'),
                        (True, True), False)])
            transform.new_directory('new', root, b'id-1')
            if transform._tree.supports_setting_file_ids():
                self.assertTreeChanges(
                    transform,
                    [TreeChange(
                        ('old', 'new'), True, (True, True),
                        ('old', 'new'),
                        ('file', 'directory'),
                        (True, False), False)])
            else:
                self.assertTreeChanges(
                    transform,
                    [TreeChange(
                        (None, 'new'), False, (False, True),
                        (None, 'new'), (None, 'directory'),
                        (False, False), False),
                     TreeChange(
                        ('old', None), False, (True, False),
                        ('old', 'old'), ('file', 'file'),
                        (True, True), False)])
        finally:
            transform.finalize()

    def test_iter_changes_new(self):
        if self.wt.supports_setting_file_ids():
            root_id = self.wt.path2id('')
        transform, root = self.transform()
        transform.new_file('old', root, [b'blah'])
        transform.apply()
        transform, root = self.transform()
        try:
            old = transform.trans_id_tree_path('old')
            transform.version_file(old, file_id=b'id-1')
            changes = list(transform.iter_changes())
            self.assertEqual(1, len(changes))
            self.assertEqual((None, 'old'), changes[0].path)
            self.assertEqual(False, changes[0].changed_content)
            self.assertEqual((False, True), changes[0].versioned)
            self.assertEqual((False, False), changes[0].executable)
            if self.wt.supports_setting_file_ids():
                self.assertEqual((root_id, root_id), changes[0].parent_id)
                self.assertEqual(b'id-1', changes[0].file_id)
        finally:
            transform.finalize()

    def test_iter_changes_modifications(self):
        transform, root = self.transform()
        transform.new_file('old', root, [b'blah'], b'id-1')
        transform.new_file('new', root, [b'blah'])
        transform.new_directory('subdir', root, b'subdir-id')
        transform.apply()
        transform, root = self.transform()
        try:
            old = transform.trans_id_tree_path('old')
            subdir = transform.trans_id_tree_path('subdir')
            new = transform.trans_id_tree_path('new')
            self.assertTreeChanges(transform, [])

            # content deletion
            transform.delete_contents(old)
            self.assertTreeChanges(
                transform,
                [TreeChange(
                    ('old', 'old'), True, (True, True),
                    ('old', 'old'), ('file', None),
                    (False, False), False)])

            # content change
            transform.create_file([b'blah'], old)
            self.assertTreeChanges(
                transform,
                [TreeChange(
                    ('old', 'old'), True, (True, True),
                    ('old', 'old'), ('file', 'file'),
                    (False, False), False)])
            transform.cancel_deletion(old)
            self.assertTreeChanges(
                transform,
                [TreeChange(
                    ('old', 'old'), True, (True, True),
                    ('old', 'old'), ('file', 'file'),
                    (False, False), False)])
            transform.cancel_creation(old)

            # move file_id to a different file
            self.assertTreeChanges(transform, [])
            transform.unversion_file(old)
            transform.version_file(new, file_id=b'id-1')
            transform.adjust_path('old', root, new)
            if transform._tree.supports_setting_file_ids():
                self.assertTreeChanges(
                    transform,
                    [TreeChange(
                        ('old', 'old'), True, (True, True),
                        ('old', 'old'), ('file', 'file'),
                        (False, False), False)])
            else:
                self.assertTreeChanges(
                    transform,
                    [TreeChange(
                        (None, 'old'), False, (False, True),
                        (None, 'old'), (None, 'file'), (False, False), False),
                     TreeChange(
                         ('old', None), False, (True, False), ('old', 'old'),
                         ('file', 'file'), (False, False), False)])

            transform.cancel_versioning(new)
            transform._removed_id = set()

            # execute bit
            self.assertTreeChanges(transform, [])
            transform.set_executability(True, old)
            self.assertTreeChanges(
                transform,
                [TreeChange(
                    ('old', 'old'), False, (True, True),
                    ('old', 'old'), ('file', 'file'),
                    (False, True), False)])
            transform.set_executability(None, old)

            # filename
            self.assertTreeChanges(transform, [])
            transform.adjust_path('new', root, old)
            transform._new_parent = {}
            self.assertTreeChanges(
                transform,
                [TreeChange(
                    ('old', 'new'), False, (True, True),
                    ('old', 'new'), ('file', 'file'),
                    (False, False), False)])
            transform._new_name = {}

            # parent directory
            self.assertTreeChanges(transform, [])
            transform.adjust_path('new', subdir, old)
            transform._new_name = {}
            self.assertTreeChanges(
                transform, [
                    TreeChange(
                        ('old', 'subdir/old'), False,
                        (True, True), ('old', 'old'),
                        ('file', 'file'), (False, False), False)])
            transform._new_path = {}
        finally:
            transform.finalize()

    def assertTreeChanges(self, tt, expected):
        # TODO(jelmer): Turn this into a matcher?
        actual = list(tt.iter_changes())
        self.assertThat(actual, MatchesTreeChanges(tt._tree.basis_tree(), tt._tree, expected))

    def test_iter_changes_modified_bleed(self):
        """Modified flag should not bleed from one change to another"""
        # unfortunately, we have no guarantee that file1 (which is modified)
        # will be applied before file2.  And if it's applied after file2, it
        # obviously can't bleed into file2's change output.  But for now, it
        # works.
        transform, root = self.transform()
        transform.new_file('file1', root, [b'blah'], b'id-1')
        transform.new_file('file2', root, [b'blah'], b'id-2')
        transform.apply()
        transform, root = self.transform()
        try:
            transform.delete_contents(transform.trans_id_tree_path('file1'))
            transform.set_executability(True, transform.trans_id_tree_path('file2'))
            self.assertTreeChanges(transform, [
                TreeChange(
                    (u'file1', u'file1'), True, (True, True),
                    ('file1', u'file1'),
                    ('file', None), (False, False), False),
                TreeChange(
                    (u'file2', u'file2'), False, (True, True),
                    ('file2', u'file2'),
                    ('file', 'file'), (False, True), False)])
        finally:
            transform.finalize()

    def test_iter_changes_move_missing(self):
        """Test moving ids with no files around"""
        # Need two steps because versioning a non-existant file is a conflict.
        transform, root = self.transform()
        transform.new_directory('floater', root, b'floater-id')
        transform.apply()
        transform, root = self.transform()
        transform.delete_contents(transform.trans_id_tree_path('floater'))
        transform.apply()
        transform, root = self.transform()
        floater = transform.trans_id_tree_path('floater')
        try:
            transform.adjust_path('flitter', root, floater)
            if self.wt.has_versioned_directories():
                self.assertTreeChanges(
                    transform,
                    [TreeChange(
                        ('floater', 'flitter'), False,
                        (True, True),
                        ('floater', 'flitter'),
                        (None, None), (False, False), False)])
            else:
                self.assertTreeChanges(transform, [])
        finally:
            transform.finalize()

    def test_iter_changes_pointless(self):
        """Ensure that no-ops are not treated as modifications"""
        transform, root = self.transform()
        transform.new_file('old', root, [b'blah'], b'id-1')
        transform.new_directory('subdir', root, b'subdir-id')
        transform.apply()
        transform, root = self.transform()
        try:
            old = transform.trans_id_tree_path('old')
            subdir = transform.trans_id_tree_path('subdir')
            self.assertTreeChanges(transform, [])
            transform.delete_contents(subdir)
            transform.create_directory(subdir)
            transform.set_executability(False, old)
            transform.unversion_file(old)
            transform.version_file(old, file_id=b'id-1')
            transform.adjust_path('old', root, old)
            self.assertTreeChanges(transform, [])
        finally:
            transform.finalize()

    def test_rename_count(self):
        transform, root = self.transform()
        transform.new_file('name1', root, [b'contents'])
        result = transform.apply()
        self.assertEqual(result.rename_count, 1)
        transform2, root = self.transform()
        transform2.adjust_path('name2', root,
                               transform2.trans_id_tree_path('name1'))
        result = transform2.apply()
        self.assertEqual(result.rename_count, 2)

    def test_change_parent(self):
        """Ensure that after we change a parent, the results are still right.

        Renames and parent changes on pending transforms can happen as part
        of conflict resolution, and are explicitly permitted by the
        TreeTransform API.

        This test ensures they work correctly with the rename-avoidance
        optimization.
        """
        transform, root = self.transform()
        parent1 = transform.new_directory('parent1', root)
        child1 = transform.new_file('child1', parent1, [b'contents'])
        parent2 = transform.new_directory('parent2', root)
        transform.adjust_path('child1', parent2, child1)
        transform.apply()
        self.assertPathDoesNotExist(self.wt.abspath('parent1/child1'))
        self.assertPathExists(self.wt.abspath('parent2/child1'))
        # rename limbo/new-1 => parent1, rename limbo/new-3 => parent2
        # no rename for child1 (counting only renames during apply)
        self.assertEqual(2, transform.rename_count)

    def test_cancel_parent(self):
        """Cancelling a parent doesn't cause deletion of a non-empty directory

        This is like the test_change_parent, except that we cancel the parent
        before adjusting the path.  The transform must detect that the
        directory is non-empty, and move children to safe locations.
        """
        transform, root = self.transform()
        parent1 = transform.new_directory('parent1', root)
        child1 = transform.new_file('child1', parent1, [b'contents'])
        child2 = transform.new_file('child2', parent1, [b'contents'])
        try:
            transform.cancel_creation(parent1)
        except OSError:
            self.fail('Failed to move child1 before deleting parent1')
        transform.cancel_creation(child2)
        transform.create_directory(parent1)
        try:
            transform.cancel_creation(parent1)
        # If the transform incorrectly believes that child2 is still in
        # parent1's limbo directory, it will try to rename it and fail
        # because was already moved by the first cancel_creation.
        except OSError:
            self.fail('Transform still thinks child2 is a child of parent1')
        parent2 = transform.new_directory('parent2', root)
        transform.adjust_path('child1', parent2, child1)
        transform.apply()
        self.assertPathDoesNotExist(self.wt.abspath('parent1'))
        self.assertPathExists(self.wt.abspath('parent2/child1'))
        # rename limbo/new-3 => parent2, rename limbo/new-2 => child1
        self.assertEqual(2, transform.rename_count)

    def test_adjust_and_cancel(self):
        """Make sure adjust_path keeps track of limbo children properly"""
        transform, root = self.transform()
        parent1 = transform.new_directory('parent1', root)
        child1 = transform.new_file('child1', parent1, [b'contents'])
        parent2 = transform.new_directory('parent2', root)
        transform.adjust_path('child1', parent2, child1)
        transform.cancel_creation(child1)
        try:
            transform.cancel_creation(parent1)
        # if the transform thinks child1 is still in parent1's limbo
        # directory, it will attempt to move it and fail.
        except OSError:
            self.fail('Transform still thinks child1 is a child of parent1')
        transform.finalize()

    def test_noname_contents(self):
        """TreeTransform should permit deferring naming files."""
        transform, root = self.transform()
        parent = transform.trans_id_tree_path('parent')
        try:
            transform.create_directory(parent)
        except KeyError:
            self.fail("Can't handle contents with no name")
        transform.finalize()

    def test_noname_contents_nested(self):
        """TreeTransform should permit deferring naming files."""
        transform, root = self.transform()
        parent = transform.trans_id_tree_path('parent-early')
        try:
            transform.create_directory(parent)
        except KeyError:
            self.fail("Can't handle contents with no name")
        transform.new_directory('child', parent)
        transform.adjust_path('parent', root, parent)
        transform.apply()
        self.assertPathExists(self.wt.abspath('parent/child'))
        self.assertEqual(1, transform.rename_count)

    def test_reuse_name(self):
        """Avoid reusing the same limbo name for different files"""
        transform, root = self.transform()
        parent = transform.new_directory('parent', root)
        transform.new_directory('child', parent)
        try:
            child2 = transform.new_directory('child', parent)
        except OSError:
            self.fail('Tranform tried to use the same limbo name twice')
        transform.adjust_path('child2', parent, child2)
        transform.apply()
        # limbo/new-1 => parent, limbo/new-3 => parent/child2
        # child2 is put into top-level limbo because child1 has already
        # claimed the direct limbo path when child2 is created.  There is no
        # advantage in renaming files once they're in top-level limbo, except
        # as part of apply.
        self.assertEqual(2, transform.rename_count)

    def test_reuse_when_first_moved(self):
        """Don't avoid direct paths when it is safe to use them"""
        transform, root = self.transform()
        parent = transform.new_directory('parent', root)
        child1 = transform.new_directory('child', parent)
        transform.adjust_path('child1', parent, child1)
        transform.new_directory('child', parent)
        transform.apply()
        # limbo/new-1 => parent
        self.assertEqual(1, transform.rename_count)

    def test_reuse_after_cancel(self):
        """Don't avoid direct paths when it is safe to use them"""
        transform, root = self.transform()
        parent2 = transform.new_directory('parent2', root)
        child1 = transform.new_directory('child1', parent2)
        transform.cancel_creation(parent2)
        transform.create_directory(parent2)
        transform.new_directory('child1', parent2)
        transform.adjust_path('child2', parent2, child1)
        transform.apply()
        # limbo/new-1 => parent2, limbo/new-2 => parent2/child1
        self.assertEqual(2, transform.rename_count)

    def test_finalize_order(self):
        """Finalize must be done in child-to-parent order"""
        transform, root = self.transform()
        parent = transform.new_directory('parent', root)
        transform.new_directory('child', parent)
        try:
            transform.finalize()
        except OSError:
            self.fail('Tried to remove parent before child1')

    def test_cancel_with_cancelled_child_should_succeed(self):
        transform, root = self.transform()
        parent = transform.new_directory('parent', root)
        child = transform.new_directory('child', parent)
        transform.cancel_creation(child)
        transform.cancel_creation(parent)
        transform.finalize()

    def test_rollback_on_directory_clash(self):
        def tt_helper():
            wt = self.make_branch_and_tree('.')
            tt = wt.transform()  # TreeTransform obtains write lock
            try:
                foo = tt.new_directory('foo', tt.root)
                tt.new_file('bar', foo, [b'foobar'])
                baz = tt.new_directory('baz', tt.root)
                tt.new_file('qux', baz, [b'quux'])
                # Ask for a rename 'foo' -> 'baz'
                tt.adjust_path('baz', tt.root, foo)
                # Lie to tt that we've already resolved all conflicts.
                tt.apply(no_conflicts=True)
            except BaseException:
                wt.unlock()
                raise
        # The rename will fail because the target directory is not empty (but
        # raises FileExists anyway).
        err = self.assertRaises(FileExists, tt_helper)
        self.assertEndsWith(err.path, "/baz")

    def test_two_directories_clash(self):
        def tt_helper():
            wt = self.make_branch_and_tree('.')
            tt = wt.transform()  # TreeTransform obtains write lock
            try:
                foo_1 = tt.new_directory('foo', tt.root)
                tt.new_directory('bar', foo_1)
                # Adding the same directory with a different content
                foo_2 = tt.new_directory('foo', tt.root)
                tt.new_directory('baz', foo_2)
                # Lie to tt that we've already resolved all conflicts.
                tt.apply(no_conflicts=True)
            except BaseException:
                wt.unlock()
                raise
        err = self.assertRaises(FileExists, tt_helper)
        self.assertEndsWith(err.path, "/foo")

    def test_two_directories_clash_finalize(self):
        def tt_helper():
            wt = self.make_branch_and_tree('.')
            tt = wt.transform()  # TreeTransform obtains write lock
            try:
                foo_1 = tt.new_directory('foo', tt.root)
                tt.new_directory('bar', foo_1)
                # Adding the same directory with a different content
                foo_2 = tt.new_directory('foo', tt.root)
                tt.new_directory('baz', foo_2)
                # Lie to tt that we've already resolved all conflicts.
                tt.apply(no_conflicts=True)
            except BaseException:
                tt.finalize()
                raise
        err = self.assertRaises(FileExists, tt_helper)
        self.assertEndsWith(err.path, "/foo")

    def test_file_to_directory(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        wt.add(['foo'])
        wt.commit("one")
        tt = wt.transform()
        self.addCleanup(tt.finalize)
        foo_trans_id = tt.trans_id_tree_path("foo")
        tt.delete_contents(foo_trans_id)
        tt.create_directory(foo_trans_id)
        bar_trans_id = tt.trans_id_tree_path("foo/bar")
        tt.create_file([b"aa\n"], bar_trans_id)
        tt.version_file(bar_trans_id, file_id=b"bar-1")
        tt.apply()
        self.assertPathExists("foo/bar")
        with wt.lock_read():
            self.assertEqual(wt.kind("foo"), "directory")
        wt.commit("two")
        changes = wt.changes_from(wt.basis_tree())
        self.assertFalse(changes.has_changed(), changes)

    def test_file_to_symlink(self):
        self.requireFeature(SymlinkFeature(self.test_dir))
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        wt.add(['foo'])
        wt.commit("one")
        tt = wt.transform()
        self.addCleanup(tt.finalize)
        foo_trans_id = tt.trans_id_tree_path("foo")
        tt.delete_contents(foo_trans_id)
        tt.create_symlink("bar", foo_trans_id)
        tt.apply()
        self.assertPathExists("foo")
        wt.lock_read()
        self.addCleanup(wt.unlock)
        self.assertEqual(wt.kind("foo"), "symlink")

    def test_file_to_symlink_unsupported(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        wt.add(['foo'])
        wt.commit("one")
        self.overrideAttr(osutils, 'supports_symlinks', lambda p: False)
        tt = wt.transform()
        self.addCleanup(tt.finalize)
        foo_trans_id = tt.trans_id_tree_path("foo")
        tt.delete_contents(foo_trans_id)
        log = BytesIO()
        trace.push_log_file(log)
        tt.create_symlink("bar", foo_trans_id)
        tt.apply()
        self.assertContainsRe(
            log.getvalue(),
            b'Unable to create symlink "foo" on this filesystem')

    def test_dir_to_file(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo/', 'foo/bar'])
        wt.add(['foo', 'foo/bar'])
        wt.commit("one")
        tt = wt.transform()
        self.addCleanup(tt.finalize)
        foo_trans_id = tt.trans_id_tree_path("foo")
        bar_trans_id = tt.trans_id_tree_path("foo/bar")
        tt.delete_contents(foo_trans_id)
        tt.delete_versioned(bar_trans_id)
        tt.create_file([b"aa\n"], foo_trans_id)
        tt.apply()
        self.assertPathExists("foo")
        wt.lock_read()
        self.addCleanup(wt.unlock)
        self.assertEqual(wt.kind("foo"), "file")

    def test_dir_to_hardlink(self):
        self.requireFeature(HardlinkFeature(self.test_dir))
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo/', 'foo/bar'])
        wt.add(['foo', 'foo/bar'])
        wt.commit("one")
        tt = wt.transform()
        self.addCleanup(tt.finalize)
        foo_trans_id = tt.trans_id_tree_path("foo")
        bar_trans_id = tt.trans_id_tree_path("foo/bar")
        tt.delete_contents(foo_trans_id)
        tt.delete_versioned(bar_trans_id)
        self.build_tree(['baz'])
        tt.create_hardlink("baz", foo_trans_id)
        tt.apply()
        self.assertPathExists("foo")
        self.assertPathExists("baz")
        wt.lock_read()
        self.addCleanup(wt.unlock)
        self.assertEqual(wt.kind("foo"), "file")

    def test_no_final_path(self):
        transform, root = self.transform()
        trans_id = transform.trans_id_tree_path('foo')
        transform.create_file([b'bar'], trans_id)
        transform.cancel_creation(trans_id)
        transform.apply()

    def test_create_from_tree(self):
        tree1 = self.make_branch_and_tree('tree1')
        self.build_tree_contents([('tree1/foo/',), ('tree1/bar', b'baz')])
        tree1.add(['foo', 'bar'])
        tree2 = self.make_branch_and_tree('tree2')
        tt = tree2.transform()
        foo_trans_id = tt.create_path('foo', tt.root)
        create_from_tree(tt, foo_trans_id, tree1, 'foo')
        bar_trans_id = tt.create_path('bar', tt.root)
        create_from_tree(tt, bar_trans_id, tree1, 'bar')
        tt.apply()
        self.assertEqual('directory', osutils.file_kind('tree2/foo'))
        self.assertFileEqual(b'baz', 'tree2/bar')

    def test_create_from_tree_bytes(self):
        """Provided lines are used instead of tree content."""
        tree1 = self.make_branch_and_tree('tree1')
        self.build_tree_contents([('tree1/foo', b'bar'), ])
        tree1.add('foo')
        tree2 = self.make_branch_and_tree('tree2')
        tt = tree2.transform()
        foo_trans_id = tt.create_path('foo', tt.root)
        create_from_tree(tt, foo_trans_id, tree1, 'foo', chunks=[b'qux'])
        tt.apply()
        self.assertFileEqual(b'qux', 'tree2/foo')

    def test_create_from_tree_symlink(self):
        self.requireFeature(SymlinkFeature(self.test_dir))
        tree1 = self.make_branch_and_tree('tree1')
        os.symlink('bar', 'tree1/foo')
        tree1.add('foo')
        tt = self.make_branch_and_tree('tree2').transform()
        foo_trans_id = tt.create_path('foo', tt.root)
        create_from_tree(tt, foo_trans_id, tree1, 'foo')
        tt.apply()
        self.assertEqual('bar', os.readlink('tree2/foo'))

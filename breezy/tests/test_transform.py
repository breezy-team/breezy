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
import errno
import os
import sys
import time

from .. import (
    bencode,
    errors,
    filters,
    generate_ids,
    osutils,
    revision as _mod_revision,
    rules,
    tests,
    trace,
    transform,
    urlutils,
    )
from ..conflicts import (
    DeletingParent,
    DuplicateEntry,
    DuplicateID,
    MissingParent,
    NonDirectoryParent,
    ParentLoop,
    UnversionedParent,
)
from ..controldir import ControlDir
from ..diff import show_diff_trees
from ..errors import (
    DuplicateKey,
    ExistingLimbo,
    ExistingPendingDeletion,
    ImmortalLimbo,
    ImmortalPendingDeletion,
    LockError,
    MalformedTransform,
    ReusingTransform,
)
from ..osutils import (
    file_kind,
    pathjoin,
)
from ..merge import Merge3Merger, Merger
from ..mutabletree import MutableTree
from ..sixish import (
    BytesIO,
    PY3,
    text_type,
    )
from . import (
    features,
    TestCaseInTempDir,
    TestSkipped,
    )
from .features import (
    HardlinkFeature,
    SymlinkFeature,
    )
from ..transform import (
    build_tree,
    create_from_tree,
    cook_conflicts,
    _FileMover,
    FinalPaths,
    resolve_conflicts,
    resolve_checkout,
    ROOT_PARENT,
    TransformPreview,
    TreeTransform,
)


class TestTreeTransform(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestTreeTransform, self).setUp()
        self.wt = self.make_branch_and_tree('.', format='development-subtree')
        os.chdir('..')

    def get_transform(self):
        transform = TreeTransform(self.wt)
        self.addCleanup(transform.finalize)
        return transform, transform.root

    def get_transform_for_sha1_test(self):
        trans, root = self.get_transform()
        self.wt.lock_tree_write()
        self.addCleanup(self.wt.unlock)
        contents = [b'just some content\n']
        sha1 = osutils.sha_strings(contents)
        # Roll back the clock
        trans._creation_mtime = time.time() - 20.0
        return trans, root, contents, sha1

    def test_existing_limbo(self):
        transform, root = self.get_transform()
        limbo_name = transform._limbodir
        deletion_path = transform._deletiondir
        os.mkdir(pathjoin(limbo_name, 'hehe'))
        self.assertRaises(ImmortalLimbo, transform.apply)
        self.assertRaises(LockError, self.wt.unlock)
        self.assertRaises(ExistingLimbo, self.get_transform)
        self.assertRaises(LockError, self.wt.unlock)
        os.rmdir(pathjoin(limbo_name, 'hehe'))
        os.rmdir(limbo_name)
        os.rmdir(deletion_path)
        transform, root = self.get_transform()
        transform.apply()

    def test_existing_pending_deletion(self):
        transform, root = self.get_transform()
        deletion_path = self._limbodir = urlutils.local_path_from_url(
            transform._tree._transport.abspath('pending-deletion'))
        os.mkdir(pathjoin(deletion_path, 'blocking-directory'))
        self.assertRaises(ImmortalPendingDeletion, transform.apply)
        self.assertRaises(LockError, self.wt.unlock)
        self.assertRaises(ExistingPendingDeletion, self.get_transform)

    def test_build(self):
        transform, root = self.get_transform()
        self.wt.lock_tree_write()
        self.addCleanup(self.wt.unlock)
        self.assertIs(transform.get_tree_parent(root), ROOT_PARENT)
        imaginary_id = transform.trans_id_tree_path('imaginary')
        imaginary_id2 = transform.trans_id_tree_path('imaginary/')
        self.assertEqual(imaginary_id, imaginary_id2)
        self.assertEqual(root, transform.get_tree_parent(imaginary_id))
        self.assertEqual('directory', transform.final_kind(root))
        self.assertEqual(self.wt.get_root_id(), transform.final_file_id(root))
        trans_id = transform.create_path('name', root)
        self.assertIs(transform.final_file_id(trans_id), None)
        self.assertIs(None, transform.final_kind(trans_id))
        transform.create_file([b'contents'], trans_id)
        transform.set_executability(True, trans_id)
        transform.version_file(b'my_pretties', trans_id)
        self.assertRaises(DuplicateKey, transform.version_file,
                          b'my_pretties', trans_id)
        self.assertEqual(transform.final_file_id(trans_id), b'my_pretties')
        self.assertEqual(transform.final_parent(trans_id), root)
        self.assertIs(transform.final_parent(root), ROOT_PARENT)
        self.assertIs(transform.get_tree_parent(root), ROOT_PARENT)
        oz_id = transform.create_path('oz', root)
        transform.create_directory(oz_id)
        transform.version_file(b'ozzie', oz_id)
        trans_id2 = transform.create_path('name2', root)
        transform.create_file([b'contents'], trans_id2)
        transform.set_executability(False, trans_id2)
        transform.version_file(b'my_pretties2', trans_id2)
        modified_paths = transform.apply().modified_paths
        with self.wt.get_file('name') as f:
            self.assertEqual(b'contents', f.read())
        self.assertEqual(self.wt.path2id('name'), b'my_pretties')
        self.assertIs(self.wt.is_executable('name'), True)
        self.assertIs(self.wt.is_executable('name2'), False)
        self.assertEqual('directory', file_kind(self.wt.abspath('oz')))
        self.assertEqual(len(modified_paths), 3)
        tree_mod_paths = [self.wt.abspath(self.wt.id2path(f)) for f in
                          (b'ozzie', b'my_pretties', b'my_pretties2')]
        self.assertSubset(tree_mod_paths, modified_paths)
        # is it safe to finalize repeatedly?
        transform.finalize()
        transform.finalize()

    def test_apply_informs_tree_of_observed_sha1(self):
        trans, root, contents, sha1 = self.get_transform_for_sha1_test()
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
        trans, root, contents, sha1 = self.get_transform_for_sha1_test()
        trans_id = trans.create_path('file1', root)
        trans.create_file(contents, trans_id, sha1=sha1)
        st_val = osutils.lstat(trans._limbo_name(trans_id))
        o_sha1, o_st_val = trans._observed_sha1s[trans_id]
        self.assertEqual(o_sha1, sha1)
        self.assertEqualStat(o_st_val, st_val)

    def test__apply_insertions_updates_sha1(self):
        trans, root, contents, sha1 = self.get_transform_for_sha1_test()
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
        trans, root, contents, sha1 = self.get_transform_for_sha1_test()
        trans_id = trans.new_file('file1', root, contents, file_id=b'file1-id',
                                  sha1=sha1)
        st_val = osutils.lstat(trans._limbo_name(trans_id))
        o_sha1, o_st_val = trans._observed_sha1s[trans_id]
        self.assertEqual(o_sha1, sha1)
        self.assertEqualStat(o_st_val, st_val)

    def test_cancel_creation_removes_observed_sha1(self):
        trans, root, contents, sha1 = self.get_transform_for_sha1_test()
        trans_id = trans.new_file('file1', root, contents, file_id=b'file1-id',
                                  sha1=sha1)
        self.assertTrue(trans_id in trans._observed_sha1s)
        trans.cancel_creation(trans_id)
        self.assertFalse(trans_id in trans._observed_sha1s)

    def test_create_files_same_timestamp(self):
        transform, root = self.get_transform()
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
        transform, root = self.get_transform()
        self.assertNotEqual(b'new-root-id', self.wt.get_root_id())
        transform.new_directory('', ROOT_PARENT, b'new-root-id')
        transform.delete_contents(root)
        transform.unversion_file(root)
        transform.fixup_new_roots()
        transform.apply()
        self.assertEqual(b'new-root-id', self.wt.get_root_id())

    def test_change_root_id_add_files(self):
        transform, root = self.get_transform()
        self.assertNotEqual(b'new-root-id', self.wt.get_root_id())
        new_trans_id = transform.new_directory('', ROOT_PARENT, b'new-root-id')
        transform.new_file('file', new_trans_id, [b'new-contents\n'],
                           b'new-file-id')
        transform.delete_contents(root)
        transform.unversion_file(root)
        transform.fixup_new_roots()
        transform.apply()
        self.assertEqual(b'new-root-id', self.wt.get_root_id())
        self.assertEqual(b'new-file-id', self.wt.path2id('file'))
        self.assertFileEqual(b'new-contents\n', self.wt.abspath('file'))

    def test_add_two_roots(self):
        transform, root = self.get_transform()
        transform.new_directory('', ROOT_PARENT, b'new-root-id')
        transform.new_directory('', ROOT_PARENT, b'alt-root-id')
        self.assertRaises(ValueError, transform.fixup_new_roots)

    def test_retain_existing_root(self):
        tt, root = self.get_transform()
        with tt:
            tt.new_directory('', ROOT_PARENT, b'new-root-id')
            tt.fixup_new_roots()
            self.assertNotEqual(b'new-root-id', tt.final_file_id(tt.root))

    def test_retain_existing_root_added_file(self):
        tt, root = self.get_transform()
        new_trans_id = tt.new_directory('', ROOT_PARENT, b'new-root-id')
        child = tt.new_directory('child', new_trans_id, b'child-id')
        tt.fixup_new_roots()
        self.assertEqual(tt.root, tt.final_parent(child))

    def test_add_unversioned_root(self):
        transform, root = self.get_transform()
        transform.new_directory('', ROOT_PARENT, None)
        transform.delete_contents(transform.root)
        transform.fixup_new_roots()
        self.assertNotIn(transform.root, transform._new_id)

    def test_remove_root_fixup(self):
        transform, root = self.get_transform()
        old_root_id = self.wt.get_root_id()
        self.assertNotEqual(b'new-root-id', old_root_id)
        transform.delete_contents(root)
        transform.unversion_file(root)
        transform.fixup_new_roots()
        transform.apply()
        self.assertEqual(old_root_id, self.wt.get_root_id())

        transform, root = self.get_transform()
        transform.new_directory('', ROOT_PARENT, b'new-root-id')
        transform.new_directory('', ROOT_PARENT, b'alt-root-id')
        self.assertRaises(ValueError, transform.fixup_new_roots)

    def test_fixup_new_roots_permits_empty_tree(self):
        transform, root = self.get_transform()
        transform.delete_contents(root)
        transform.unversion_file(root)
        transform.fixup_new_roots()
        self.assertIs(None, transform.final_kind(root))
        self.assertIs(None, transform.final_file_id(root))

    def test_apply_retains_root_directory(self):
        # Do not attempt to delete the physical root directory, because that
        # is impossible.
        transform, root = self.get_transform()
        with transform:
            transform.delete_contents(root)
            e = self.assertRaises(AssertionError, self.assertRaises,
                                  errors.TransformRenameFailed,
                                  transform.apply)
        self.assertContainsRe('TransformRenameFailed not raised', str(e))

    def test_apply_retains_file_id(self):
        transform, root = self.get_transform()
        old_root_id = transform.tree_file_id(root)
        transform.unversion_file(root)
        transform.apply()
        self.assertEqual(old_root_id, self.wt.get_root_id())

    def test_hardlink(self):
        self.requireFeature(HardlinkFeature)
        transform, root = self.get_transform()
        transform.new_file('file1', root, [b'contents'])
        transform.apply()
        target = self.make_branch_and_tree('target')
        target_transform = TreeTransform(target)
        trans_id = target_transform.create_path('file1', target_transform.root)
        target_transform.create_hardlink(self.wt.abspath('file1'), trans_id)
        target_transform.apply()
        self.assertPathExists('target/file1')
        source_stat = os.stat(self.wt.abspath('file1'))
        target_stat = os.stat('target/file1')
        self.assertEqual(source_stat, target_stat)

    def test_convenience(self):
        transform, root = self.get_transform()
        self.wt.lock_tree_write()
        self.addCleanup(self.wt.unlock)
        transform.new_file('name', root, [b'contents'], b'my_pretties', True)
        oz = transform.new_directory('oz', root, b'oz-id')
        dorothy = transform.new_directory('dorothy', oz, b'dorothy-id')
        transform.new_file('toto', dorothy, [b'toto-contents'], b'toto-id',
                           False)

        self.assertEqual(len(transform.find_conflicts()), 0)
        transform.apply()
        self.assertRaises(ReusingTransform, transform.find_conflicts)
        with open(self.wt.abspath('name'), 'r') as f:
            self.assertEqual('contents', f.read())
        self.assertEqual(self.wt.path2id('name'), b'my_pretties')
        self.assertIs(self.wt.is_executable('name'), True)
        self.assertEqual(self.wt.path2id('oz'), b'oz-id')
        self.assertEqual(self.wt.path2id('oz/dorothy'), b'dorothy-id')
        self.assertEqual(self.wt.path2id('oz/dorothy/toto'), b'toto-id')

        self.assertEqual(b'toto-contents',
                         self.wt.get_file('oz/dorothy/toto').read())
        self.assertIs(self.wt.is_executable('oz/dorothy/toto'), False)

    def test_tree_reference(self):
        transform, root = self.get_transform()
        tree = transform._tree
        trans_id = transform.new_directory('reference', root, b'subtree-id')
        transform.set_tree_reference(b'subtree-revision', trans_id)
        transform.apply()
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(
            b'subtree-revision',
            tree.root_inventory.get_entry(b'subtree-id').reference_revision)

    def test_conflicts(self):
        transform, root = self.get_transform()
        trans_id = transform.new_file('name', root, [b'contents'],
                                      b'my_pretties')
        self.assertEqual(len(transform.find_conflicts()), 0)
        trans_id2 = transform.new_file('name', root, [b'Crontents'], b'toto')
        self.assertEqual(transform.find_conflicts(),
                         [('duplicate', trans_id, trans_id2, 'name')])
        self.assertRaises(MalformedTransform, transform.apply)
        transform.adjust_path('name', trans_id, trans_id2)
        self.assertEqual(transform.find_conflicts(),
                         [('non-directory parent', trans_id)])
        tinman_id = transform.trans_id_tree_path('tinman')
        transform.adjust_path('name', tinman_id, trans_id2)
        self.assertEqual(transform.find_conflicts(),
                         [('unversioned parent', tinman_id),
                          ('missing parent', tinman_id)])
        lion_id = transform.create_path('lion', root)
        self.assertEqual(transform.find_conflicts(),
                         [('unversioned parent', tinman_id),
                          ('missing parent', tinman_id)])
        transform.adjust_path('name', lion_id, trans_id2)
        self.assertEqual(transform.find_conflicts(),
                         [('unversioned parent', lion_id),
                          ('missing parent', lion_id)])
        transform.version_file(b"Courage", lion_id)
        self.assertEqual(transform.find_conflicts(),
                         [('missing parent', lion_id),
                          ('versioning no contents', lion_id)])
        transform.adjust_path('name2', root, trans_id2)
        self.assertEqual(transform.find_conflicts(),
                         [('versioning no contents', lion_id)])
        transform.create_file([b'Contents, okay?'], lion_id)
        transform.adjust_path('name2', trans_id2, trans_id2)
        self.assertEqual(transform.find_conflicts(),
                         [('parent loop', trans_id2),
                          ('non-directory parent', trans_id2)])
        transform.adjust_path('name2', root, trans_id2)
        oz_id = transform.new_directory('oz', root)
        transform.set_executability(True, oz_id)
        self.assertEqual(transform.find_conflicts(),
                         [('unversioned executability', oz_id)])
        transform.version_file(b'oz-id', oz_id)
        self.assertEqual(transform.find_conflicts(),
                         [('non-file executability', oz_id)])
        transform.set_executability(None, oz_id)
        tip_id = transform.new_file('tip', oz_id, [b'ozma'], b'tip-id')
        transform.apply()
        self.assertEqual(self.wt.path2id('name'), b'my_pretties')
        with open(self.wt.abspath('name'), 'rb') as f:
            self.assertEqual(b'contents', f.read())
        transform2, root = self.get_transform()
        oz_id = transform2.trans_id_tree_path('oz')
        newtip = transform2.new_file('tip', oz_id, [b'other'], b'tip-id')
        result = transform2.find_conflicts()
        fp = FinalPaths(transform2)
        self.assertTrue('oz/tip' in transform2._tree_path_ids)
        self.assertEqual(fp.get_path(newtip), pathjoin('oz', 'tip'))
        self.assertEqual(len(result), 2)
        self.assertEqual((result[0][0], result[0][1]),
                         ('duplicate', newtip))
        self.assertEqual((result[1][0], result[1][2]),
                         ('duplicate id', newtip))
        transform2.finalize()
        transform3 = TreeTransform(self.wt)
        self.addCleanup(transform3.finalize)
        oz_id = transform3.trans_id_tree_path('oz')
        transform3.delete_contents(oz_id)
        self.assertEqual(transform3.find_conflicts(),
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
        transform = TreeTransform(tree)
        self.addCleanup(transform.finalize)
        transform.new_file('file', transform.root, [b'content'])
        transform.new_file('FiLe', transform.root, [b'content'])
        result = transform.find_conflicts()
        self.assertEqual([], result)
        transform.finalize()
        # Force the tree to report that it is case insensitive, for conflict
        # generation tests
        tree.case_sensitive = False
        transform = TreeTransform(tree)
        self.addCleanup(transform.finalize)
        transform.new_file('file', transform.root, [b'content'])
        transform.new_file('FiLe', transform.root, [b'content'])
        result = transform.find_conflicts()
        self.assertEqual([('duplicate', 'new-1', 'new-2', 'file')], result)

    def test_conflict_on_case_insensitive_existing(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/FiLe'])
        # Don't try this at home, kids!
        # Force the tree to report that it is case sensitive, for conflict
        # resolution tests
        tree.case_sensitive = True
        transform = TreeTransform(tree)
        self.addCleanup(transform.finalize)
        transform.new_file('file', transform.root, [b'content'])
        result = transform.find_conflicts()
        self.assertEqual([], result)
        transform.finalize()
        # Force the tree to report that it is case insensitive, for conflict
        # generation tests
        tree.case_sensitive = False
        transform = TreeTransform(tree)
        self.addCleanup(transform.finalize)
        transform.new_file('file', transform.root, [b'content'])
        result = transform.find_conflicts()
        self.assertEqual([('duplicate', 'new-1', 'new-2', 'file')], result)

    def test_resolve_case_insensitive_conflict(self):
        tree = self.make_branch_and_tree('tree')
        # Don't try this at home, kids!
        # Force the tree to report that it is case insensitive, for conflict
        # resolution tests
        tree.case_sensitive = False
        transform = TreeTransform(tree)
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
        transform = TreeTransform(tree)
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
        transform = TreeTransform(tree)
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
        transform = TreeTransform(tree)
        self.addCleanup(transform.finalize)
        dir = transform.new_directory('dir', transform.root)
        first = transform.new_file('file', dir, [b'content'])
        second = transform.new_file('FiLe', dir, [b'content'])
        self.assertContainsRe(transform._limbo_name(first), 'new-1/file')
        self.assertNotContainsRe(transform._limbo_name(second), 'new-1/FiLe')

    def test_adjust_path_updates_child_limbo_names(self):
        tree = self.make_branch_and_tree('tree')
        transform = TreeTransform(tree)
        self.addCleanup(transform.finalize)
        foo_id = transform.new_directory('foo', transform.root)
        bar_id = transform.new_directory('bar', foo_id)
        baz_id = transform.new_directory('baz', bar_id)
        qux_id = transform.new_directory('qux', baz_id)
        transform.adjust_path('quxx', foo_id, bar_id)
        self.assertStartsWith(transform._limbo_name(qux_id),
                              transform._limbo_name(bar_id))

    def test_add_del(self):
        start, root = self.get_transform()
        start.new_directory('a', root, b'a')
        start.apply()
        transform, root = self.get_transform()
        transform.delete_versioned(transform.trans_id_tree_path('a'))
        transform.new_directory('a', root, b'a')
        transform.apply()

    def test_unversioning(self):
        create_tree, root = self.get_transform()
        parent_id = create_tree.new_directory('parent', root, b'parent-id')
        create_tree.new_file('child', parent_id, [b'child'], b'child-id')
        create_tree.apply()
        unversion = TreeTransform(self.wt)
        self.addCleanup(unversion.finalize)
        parent = unversion.trans_id_tree_path('parent')
        unversion.unversion_file(parent)
        self.assertEqual(unversion.find_conflicts(),
                         [('unversioned parent', parent_id)])
        file_id = unversion.trans_id_tree_path('parent/child')
        unversion.unversion_file(file_id)
        unversion.apply()

    def test_name_invariants(self):
        create_tree, root = self.get_transform()
        # prepare tree
        root = create_tree.root
        create_tree.new_file('name1', root, [b'hello1'], b'name1')
        create_tree.new_file('name2', root, [b'hello2'], b'name2')
        ddir = create_tree.new_directory('dying_directory', root, b'ddir')
        create_tree.new_file('dying_file', ddir, [b'goodbye1'], b'dfile')
        create_tree.new_file('moving_file', ddir, [b'later1'], b'mfile')
        create_tree.new_file('moving_file2', root, [b'later2'], b'mfile2')
        create_tree.apply()

        mangle_tree, root = self.get_transform()
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
        self.assertEqual(mangle_tree.final_file_id(mfile2), b'mfile2')
        self.assertEqual(mangle_tree.final_parent(mfile2), newdir)
        self.assertEqual(mangle_tree.final_file_id(mfile2), b'mfile2')
        mangle_tree.apply()
        with open(self.wt.abspath('name1'), 'r') as f:
            self.assertEqual(f.read(), 'hello2')
        with open(self.wt.abspath('name2'), 'r') as f:
            self.assertEqual(f.read(), 'hello1')
        mfile2_path = self.wt.abspath(pathjoin('new_directory', 'mfile2'))
        self.assertEqual(mangle_tree.final_parent(mfile2), newdir)
        with open(mfile2_path, 'r') as f:
            self.assertEqual(f.read(), 'later2')
        self.assertEqual(self.wt.id2path(b'mfile2'), 'new_directory/mfile2')
        self.assertEqual(self.wt.path2id('new_directory/mfile2'), b'mfile2')
        newfile_path = self.wt.abspath(pathjoin('new_directory', 'newfile'))
        with open(newfile_path, 'r') as f:
            self.assertEqual(f.read(), 'hello3')
        self.assertEqual(self.wt.path2id('dying_directory'), b'ddir')
        self.assertIs(self.wt.path2id('dying_directory/dying_file'), None)
        mfile2_path = self.wt.abspath(pathjoin('new_directory', 'mfile2'))

    def test_both_rename(self):
        create_tree, root = self.get_transform()
        newdir = create_tree.new_directory('selftest', root, b'selftest-id')
        create_tree.new_file('blackbox.py', newdir, [
                             b'hello1'], b'blackbox-id')
        create_tree.apply()
        mangle_tree, root = self.get_transform()
        selftest = mangle_tree.trans_id_tree_path('selftest')
        blackbox = mangle_tree.trans_id_tree_path('selftest/blackbox.py')
        mangle_tree.adjust_path('test', root, selftest)
        mangle_tree.adjust_path('test_too_much', root, selftest)
        mangle_tree.set_executability(True, blackbox)
        mangle_tree.apply()

    def test_both_rename2(self):
        create_tree, root = self.get_transform()
        breezy = create_tree.new_directory('breezy', root, b'breezy-id')
        tests = create_tree.new_directory('tests', breezy, b'tests-id')
        blackbox = create_tree.new_directory('blackbox', tests, b'blackbox-id')
        create_tree.new_file('test_too_much.py', blackbox, [b'hello1'],
                             b'test_too_much-id')
        create_tree.apply()
        mangle_tree, root = self.get_transform()
        breezy = mangle_tree.trans_id_tree_path('breezy')
        tests = mangle_tree.trans_id_tree_path('breezy/tests')
        test_too_much = mangle_tree.trans_id_tree_path(
            'breezy/tests/blackbox/test_too_much.py')
        mangle_tree.adjust_path('selftest', breezy, tests)
        mangle_tree.adjust_path('blackbox.py', tests, test_too_much)
        mangle_tree.set_executability(True, test_too_much)
        mangle_tree.apply()

    def test_both_rename3(self):
        create_tree, root = self.get_transform()
        tests = create_tree.new_directory('tests', root, b'tests-id')
        create_tree.new_file('test_too_much.py', tests, [b'hello1'],
                             b'test_too_much-id')
        create_tree.apply()
        mangle_tree, root = self.get_transform()
        tests = mangle_tree.trans_id_tree_path('tests')
        test_too_much = mangle_tree.trans_id_tree_path(
            'tests/test_too_much.py')
        mangle_tree.adjust_path('selftest', root, tests)
        mangle_tree.adjust_path('blackbox.py', tests, test_too_much)
        mangle_tree.set_executability(True, test_too_much)
        mangle_tree.apply()

    def test_move_dangling_ie(self):
        create_tree, root = self.get_transform()
        # prepare tree
        root = create_tree.root
        create_tree.new_file('name1', root, [b'hello1'], b'name1')
        create_tree.apply()
        delete_contents, root = self.get_transform()
        file = delete_contents.trans_id_tree_path('name1')
        delete_contents.delete_contents(file)
        delete_contents.apply()
        move_id, root = self.get_transform()
        name1 = move_id.trans_id_tree_path('name1')
        newdir = move_id.new_directory('dir', root, b'newdir')
        move_id.adjust_path('name2', newdir, name1)
        move_id.apply()

    def test_replace_dangling_ie(self):
        create_tree, root = self.get_transform()
        # prepare tree
        root = create_tree.root
        create_tree.new_file('name1', root, [b'hello1'], b'name1')
        create_tree.apply()
        delete_contents = TreeTransform(self.wt)
        self.addCleanup(delete_contents.finalize)
        file = delete_contents.trans_id_tree_path('name1')
        delete_contents.delete_contents(file)
        delete_contents.apply()
        delete_contents.finalize()
        replace = TreeTransform(self.wt)
        self.addCleanup(replace.finalize)
        name2 = replace.new_file('name2', root, [b'hello2'], b'name1')
        conflicts = replace.find_conflicts()
        name1 = replace.trans_id_tree_path('name1')
        self.assertEqual(conflicts, [('duplicate id', name1, name2)])
        resolve_conflicts(replace)
        replace.apply()

    def _test_symlinks(self, link_name1, link_target1,
                       link_name2, link_target2):

        def ozpath(p):
            return 'oz/' + p

        self.requireFeature(SymlinkFeature)
        transform, root = self.get_transform()
        oz_id = transform.new_directory('oz', root, b'oz-id')
        transform.new_symlink(link_name1, oz_id, link_target1, b'wizard-id')
        wiz_id = transform.create_path(link_name2, oz_id)
        transform.create_symlink(link_target2, wiz_id)
        transform.version_file(b'wiz-id2', wiz_id)
        transform.set_executability(True, wiz_id)
        self.assertEqual(transform.find_conflicts(),
                         [('non-file executability', wiz_id)])
        transform.set_executability(None, wiz_id)
        transform.apply()
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

    def test_unable_create_symlink(self):
        def tt_helper():
            wt = self.make_branch_and_tree('.')
            tt = TreeTransform(wt)  # TreeTransform obtains write lock
            try:
                tt.new_symlink('foo', tt.root, 'bar')
                tt.apply()
            finally:
                wt.unlock()
        os_symlink = getattr(os, 'symlink', None)
        os.symlink = None
        try:
            err = self.assertRaises(errors.UnableCreateSymlink, tt_helper)
            self.assertEqual(
                "Unable to create symlink 'foo' on this platform",
                str(err))
        finally:
            if os_symlink:
                os.symlink = os_symlink

    def get_conflicted(self):
        create, root = self.get_transform()
        create.new_file('dorothy', root, [b'dorothy'], b'dorothy-id')
        oz = create.new_directory('oz', root, b'oz-id')
        create.new_directory('emeraldcity', oz, b'emerald-id')
        create.apply()
        conflicts, root = self.get_transform()
        # set up duplicate entry, duplicate id
        new_dorothy = conflicts.new_file('dorothy', root, [b'dorothy'],
                                         b'dorothy-id')
        old_dorothy = conflicts.trans_id_tree_path('dorothy')
        oz = conflicts.trans_id_tree_path('oz')
        # set up DeletedParent parent conflict
        conflicts.delete_versioned(oz)
        emerald = conflicts.trans_id_tree_path('oz/emeraldcity')
        # set up MissingParent conflict
        munchkincity = conflicts.trans_id_file_id(b'munchkincity-id')
        conflicts.adjust_path('munchkincity', root, munchkincity)
        conflicts.new_directory('auntem', munchkincity, b'auntem-id')
        # set up parent loop
        conflicts.adjust_path('emeraldcity', emerald, emerald)
        return conflicts, emerald, oz, old_dorothy, new_dorothy

    def test_conflict_resolution(self):
        conflicts, emerald, oz, old_dorothy, new_dorothy =\
            self.get_conflicted()
        resolve_conflicts(conflicts)
        self.assertEqual(conflicts.final_name(old_dorothy), 'dorothy.moved')
        self.assertIs(conflicts.final_file_id(old_dorothy), None)
        self.assertEqual(conflicts.final_name(new_dorothy), 'dorothy')
        self.assertEqual(conflicts.final_file_id(new_dorothy), b'dorothy-id')
        self.assertEqual(conflicts.final_parent(emerald), oz)
        conflicts.apply()

    def test_cook_conflicts(self):
        tt, emerald, oz, old_dorothy, new_dorothy = self.get_conflicted()
        raw_conflicts = resolve_conflicts(tt)
        cooked_conflicts = cook_conflicts(raw_conflicts, tt)
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
        tt.finalize()

    def test_string_conflicts(self):
        tt, emerald, oz, old_dorothy, new_dorothy = self.get_conflicted()
        raw_conflicts = resolve_conflicts(tt)
        cooked_conflicts = cook_conflicts(raw_conflicts, tt)
        tt.finalize()
        conflicts_s = [text_type(c) for c in cooked_conflicts]
        self.assertEqual(len(cooked_conflicts), len(conflicts_s))
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

    def prepare_wrong_parent_kind(self):
        tt, root = self.get_transform()
        tt.new_file('parent', root, [b'contents'], b'parent-id')
        tt.apply()
        tt, root = self.get_transform()
        parent_id = tt.trans_id_file_id(b'parent-id')
        tt.new_file('child,', parent_id, [b'contents2'], b'file-id')
        return tt

    def test_find_conflicts_wrong_parent_kind(self):
        tt = self.prepare_wrong_parent_kind()
        tt.find_conflicts()

    def test_resolve_conflicts_wrong_existing_parent_kind(self):
        tt = self.prepare_wrong_parent_kind()
        raw_conflicts = resolve_conflicts(tt)
        self.assertEqual({('non-directory parent', 'Created directory',
                           'new-3')}, raw_conflicts)
        cooked_conflicts = cook_conflicts(raw_conflicts, tt)
        self.assertEqual([NonDirectoryParent('Created directory', 'parent.new',
                                             b'parent-id')], cooked_conflicts)
        tt.apply()
        self.assertFalse(self.wt.is_versioned('parent'))
        self.assertEqual(b'parent-id', self.wt.path2id('parent.new'))

    def test_resolve_conflicts_wrong_new_parent_kind(self):
        tt, root = self.get_transform()
        parent_id = tt.new_directory('parent', root, b'parent-id')
        tt.new_file('child,', parent_id, [b'contents2'], b'file-id')
        tt.apply()
        tt, root = self.get_transform()
        parent_id = tt.trans_id_file_id(b'parent-id')
        tt.delete_contents(parent_id)
        tt.create_file([b'contents'], parent_id)
        raw_conflicts = resolve_conflicts(tt)
        self.assertEqual({('non-directory parent', 'Created directory',
                           'new-3')}, raw_conflicts)
        tt.apply()
        self.assertFalse(self.wt.is_versioned('parent'))
        self.assertEqual(b'parent-id', self.wt.path2id('parent.new'))

    def test_resolve_conflicts_wrong_parent_kind_unversioned(self):
        tt, root = self.get_transform()
        parent_id = tt.new_directory('parent', root)
        tt.new_file('child,', parent_id, [b'contents2'])
        tt.apply()
        tt, root = self.get_transform()
        parent_id = tt.trans_id_tree_path('parent')
        tt.delete_contents(parent_id)
        tt.create_file([b'contents'], parent_id)
        resolve_conflicts(tt)
        tt.apply()
        self.assertFalse(self.wt.is_versioned('parent'))
        self.assertFalse(self.wt.is_versioned('parent.new'))

    def test_resolve_conflicts_missing_parent(self):
        wt = self.make_branch_and_tree('.')
        tt = TreeTransform(wt)
        self.addCleanup(tt.finalize)
        parent = tt.trans_id_file_id(b'parent-id')
        tt.new_file('file', parent, [b'Contents'])
        raw_conflicts = resolve_conflicts(tt)
        # Since the directory doesn't exist it's seen as 'missing'.  So
        # 'resolve_conflicts' create a conflict asking for it to be created.
        self.assertLength(1, raw_conflicts)
        self.assertEqual(('missing parent', 'Created directory', 'new-1'),
                         raw_conflicts.pop())
        # apply fail since the missing directory doesn't exist
        self.assertRaises(errors.NoFinalPath, tt.apply)

    def test_moving_versioned_directories(self):
        create, root = self.get_transform()
        kansas = create.new_directory('kansas', root, b'kansas-id')
        create.new_directory('house', kansas, b'house-id')
        create.new_directory('oz', root, b'oz-id')
        create.apply()
        cyclone, root = self.get_transform()
        oz = cyclone.trans_id_tree_path('oz')
        house = cyclone.trans_id_tree_path('house')
        cyclone.adjust_path('house', oz, house)
        cyclone.apply()

    def test_moving_root(self):
        create, root = self.get_transform()
        fun = create.new_directory('fun', root, b'fun-id')
        create.new_directory('sun', root, b'sun-id')
        create.new_directory('moon', root, b'moon')
        create.apply()
        transform, root = self.get_transform()
        transform.adjust_root_path('oldroot', fun)
        new_root = transform.trans_id_tree_path('')
        transform.version_file(b'new-root', new_root)
        transform.apply()

    def test_renames(self):
        create, root = self.get_transform()
        old = create.new_directory('old-parent', root, b'old-id')
        intermediate = create.new_directory('intermediate', old, b'im-id')
        myfile = create.new_file('myfile', intermediate, [b'myfile-text'],
                                 b'myfile-id')
        create.apply()
        rename, root = self.get_transform()
        old = rename.trans_id_file_id(b'old-id')
        rename.adjust_path('new', root, old)
        myfile = rename.trans_id_file_id(b'myfile-id')
        rename.set_executability(True, myfile)
        rename.apply()

    def test_rename_fails(self):
        self.requireFeature(features.not_running_as_root)
        # see https://bugs.launchpad.net/bzr/+bug/491763
        create, root_id = self.get_transform()
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
        rename_transform, root_id = self.get_transform()
        file_trans_id = rename_transform.trans_id_file_id(b'myfile-id')
        dir_id = rename_transform.trans_id_file_id(b'first-id')
        rename_transform.adjust_path('newname', dir_id, file_trans_id)
        e = self.assertRaises(errors.TransformRenameFailed,
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
        transform, root = self.get_transform()
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
        transform, root = self.get_transform()
        transform.new_file('file1', root, [b'contents'], b'file1-id', True)
        transform.apply()
        self.wt.lock_write()
        self.addCleanup(self.wt.unlock)
        self.assertTrue(self.wt.is_executable('file1'))
        transform, root = self.get_transform()
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

        transform, root = self.get_transform()

        bar1_id = transform.new_file('bar', root, [b'bar contents 1\n'],
                                     file_id=b'bar-id-1', executable=False)
        transform.apply()

        transform, root = self.get_transform()
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
        self.wt.set_root_id(b'eert_toor')
        transform, root = self.get_transform()
        transform.new_file('old', root, [b'blah'], b'id-1', True)
        transform.apply()
        transform, root = self.get_transform()
        try:
            self.assertEqual([], list(transform.iter_changes()))
            old = transform.trans_id_tree_path('old')
            transform.unversion_file(old)
            self.assertEqual([(b'id-1', ('old', None), False, (True, False),
                               (b'eert_toor', b'eert_toor'),
                               ('old', 'old'), ('file', 'file'),
                               (True, True))], list(transform.iter_changes()))
            transform.new_directory('new', root, b'id-1')
            self.assertEqual([(b'id-1', ('old', 'new'), True, (True, True),
                               (b'eert_toor', b'eert_toor'), ('old', 'new'),
                               ('file', 'directory'),
                               (True, False))], list(transform.iter_changes()))
        finally:
            transform.finalize()

    def test_iter_changes_new(self):
        self.wt.set_root_id(b'eert_toor')
        transform, root = self.get_transform()
        transform.new_file('old', root, [b'blah'])
        transform.apply()
        transform, root = self.get_transform()
        try:
            old = transform.trans_id_tree_path('old')
            transform.version_file(b'id-1', old)
            self.assertEqual([(b'id-1', (None, 'old'), False, (False, True),
                               (b'eert_toor', b'eert_toor'),
                               ('old', 'old'), ('file', 'file'),
                               (False, False))],
                             list(transform.iter_changes()))
        finally:
            transform.finalize()

    def test_iter_changes_modifications(self):
        self.wt.set_root_id(b'eert_toor')
        transform, root = self.get_transform()
        transform.new_file('old', root, [b'blah'], b'id-1')
        transform.new_file('new', root, [b'blah'])
        transform.new_directory('subdir', root, b'subdir-id')
        transform.apply()
        transform, root = self.get_transform()
        try:
            old = transform.trans_id_tree_path('old')
            subdir = transform.trans_id_tree_path('subdir')
            new = transform.trans_id_tree_path('new')
            self.assertEqual([], list(transform.iter_changes()))

            # content deletion
            transform.delete_contents(old)
            self.assertEqual([(b'id-1', ('old', 'old'), True, (True, True),
                               (b'eert_toor', b'eert_toor'),
                               ('old', 'old'), ('file', None),
                               (False, False))],
                             list(transform.iter_changes()))

            # content change
            transform.create_file([b'blah'], old)
            self.assertEqual([(b'id-1', ('old', 'old'), True, (True, True),
                               (b'eert_toor', b'eert_toor'),
                               ('old', 'old'), ('file', 'file'),
                               (False, False))],
                             list(transform.iter_changes()))
            transform.cancel_deletion(old)
            self.assertEqual([(b'id-1', ('old', 'old'), True, (True, True),
                               (b'eert_toor', b'eert_toor'),
                               ('old', 'old'), ('file', 'file'),
                               (False, False))],
                             list(transform.iter_changes()))
            transform.cancel_creation(old)

            # move file_id to a different file
            self.assertEqual([], list(transform.iter_changes()))
            transform.unversion_file(old)
            transform.version_file(b'id-1', new)
            transform.adjust_path('old', root, new)
            self.assertEqual([(b'id-1', ('old', 'old'), True, (True, True),
                               (b'eert_toor', b'eert_toor'),
                               ('old', 'old'), ('file', 'file'),
                               (False, False))],
                             list(transform.iter_changes()))
            transform.cancel_versioning(new)
            transform._removed_id = set()

            # execute bit
            self.assertEqual([], list(transform.iter_changes()))
            transform.set_executability(True, old)
            self.assertEqual([(b'id-1', ('old', 'old'), False, (True, True),
                               (b'eert_toor', b'eert_toor'),
                               ('old', 'old'), ('file', 'file'),
                               (False, True))],
                             list(transform.iter_changes()))
            transform.set_executability(None, old)

            # filename
            self.assertEqual([], list(transform.iter_changes()))
            transform.adjust_path('new', root, old)
            transform._new_parent = {}
            self.assertEqual([(b'id-1', ('old', 'new'), False, (True, True),
                               (b'eert_toor', b'eert_toor'),
                               ('old', 'new'), ('file', 'file'),
                               (False, False))],
                             list(transform.iter_changes()))
            transform._new_name = {}

            # parent directory
            self.assertEqual([], list(transform.iter_changes()))
            transform.adjust_path('new', subdir, old)
            transform._new_name = {}
            self.assertEqual([(b'id-1', ('old', 'subdir/old'), False,
                               (True, True), (b'eert_toor',
                                              b'subdir-id'), ('old', 'old'),
                               ('file', 'file'), (False, False))],
                             list(transform.iter_changes()))
            transform._new_path = {}

        finally:
            transform.finalize()

    def test_iter_changes_modified_bleed(self):
        self.wt.set_root_id(b'eert_toor')
        """Modified flag should not bleed from one change to another"""
        # unfortunately, we have no guarantee that file1 (which is modified)
        # will be applied before file2.  And if it's applied after file2, it
        # obviously can't bleed into file2's change output.  But for now, it
        # works.
        transform, root = self.get_transform()
        transform.new_file('file1', root, [b'blah'], b'id-1')
        transform.new_file('file2', root, [b'blah'], b'id-2')
        transform.apply()
        transform, root = self.get_transform()
        try:
            transform.delete_contents(transform.trans_id_file_id(b'id-1'))
            transform.set_executability(True,
                                        transform.trans_id_file_id(b'id-2'))
            self.assertEqual(
                [(b'id-1', (u'file1', u'file1'), True, (True, True),
                 (b'eert_toor', b'eert_toor'), ('file1', u'file1'),
                 ('file', None), (False, False)),
                 (b'id-2', (u'file2', u'file2'), False, (True, True),
                 (b'eert_toor', b'eert_toor'), ('file2', u'file2'),
                 ('file', 'file'), (False, True))],
                list(transform.iter_changes()))
        finally:
            transform.finalize()

    def test_iter_changes_move_missing(self):
        """Test moving ids with no files around"""
        self.wt.set_root_id(b'toor_eert')
        # Need two steps because versioning a non-existant file is a conflict.
        transform, root = self.get_transform()
        transform.new_directory('floater', root, b'floater-id')
        transform.apply()
        transform, root = self.get_transform()
        transform.delete_contents(transform.trans_id_tree_path('floater'))
        transform.apply()
        transform, root = self.get_transform()
        floater = transform.trans_id_tree_path('floater')
        try:
            transform.adjust_path('flitter', root, floater)
            self.assertEqual([(b'floater-id', ('floater', 'flitter'), False,
                               (True, True),
                               (b'toor_eert', b'toor_eert'),
                               ('floater', 'flitter'),
                               (None, None), (False, False))],
                             list(transform.iter_changes()))
        finally:
            transform.finalize()

    def test_iter_changes_pointless(self):
        """Ensure that no-ops are not treated as modifications"""
        self.wt.set_root_id(b'eert_toor')
        transform, root = self.get_transform()
        transform.new_file('old', root, [b'blah'], b'id-1')
        transform.new_directory('subdir', root, b'subdir-id')
        transform.apply()
        transform, root = self.get_transform()
        try:
            old = transform.trans_id_tree_path('old')
            subdir = transform.trans_id_tree_path('subdir')
            self.assertEqual([], list(transform.iter_changes()))
            transform.delete_contents(subdir)
            transform.create_directory(subdir)
            transform.set_executability(False, old)
            transform.unversion_file(old)
            transform.version_file(b'id-1', old)
            transform.adjust_path('old', root, old)
            self.assertEqual([], list(transform.iter_changes()))
        finally:
            transform.finalize()

    def test_rename_count(self):
        transform, root = self.get_transform()
        transform.new_file('name1', root, [b'contents'])
        self.assertEqual(transform.rename_count, 0)
        transform.apply()
        self.assertEqual(transform.rename_count, 1)
        transform2, root = self.get_transform()
        transform2.adjust_path('name2', root,
                               transform2.trans_id_tree_path('name1'))
        self.assertEqual(transform2.rename_count, 0)
        transform2.apply()
        self.assertEqual(transform2.rename_count, 2)

    def test_change_parent(self):
        """Ensure that after we change a parent, the results are still right.

        Renames and parent changes on pending transforms can happen as part
        of conflict resolution, and are explicitly permitted by the
        TreeTransform API.

        This test ensures they work correctly with the rename-avoidance
        optimization.
        """
        transform, root = self.get_transform()
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
        transform, root = self.get_transform()
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
        transform, root = self.get_transform()
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
        transform, root = self.get_transform()
        parent = transform.trans_id_file_id(b'parent-id')
        try:
            transform.create_directory(parent)
        except KeyError:
            self.fail("Can't handle contents with no name")
        transform.finalize()

    def test_noname_contents_nested(self):
        """TreeTransform should permit deferring naming files."""
        transform, root = self.get_transform()
        parent = transform.trans_id_file_id(b'parent-id')
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
        transform, root = self.get_transform()
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
        transform, root = self.get_transform()
        parent = transform.new_directory('parent', root)
        child1 = transform.new_directory('child', parent)
        transform.adjust_path('child1', parent, child1)
        transform.new_directory('child', parent)
        transform.apply()
        # limbo/new-1 => parent
        self.assertEqual(1, transform.rename_count)

    def test_reuse_after_cancel(self):
        """Don't avoid direct paths when it is safe to use them"""
        transform, root = self.get_transform()
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
        transform, root = self.get_transform()
        parent = transform.new_directory('parent', root)
        transform.new_directory('child', parent)
        try:
            transform.finalize()
        except OSError:
            self.fail('Tried to remove parent before child1')

    def test_cancel_with_cancelled_child_should_succeed(self):
        transform, root = self.get_transform()
        parent = transform.new_directory('parent', root)
        child = transform.new_directory('child', parent)
        transform.cancel_creation(child)
        transform.cancel_creation(parent)
        transform.finalize()

    def test_rollback_on_directory_clash(self):
        def tt_helper():
            wt = self.make_branch_and_tree('.')
            tt = TreeTransform(wt)  # TreeTransform obtains write lock
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
        err = self.assertRaises(errors.FileExists, tt_helper)
        self.assertEndsWith(err.path, "/baz")

    def test_two_directories_clash(self):
        def tt_helper():
            wt = self.make_branch_and_tree('.')
            tt = TreeTransform(wt)  # TreeTransform obtains write lock
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
        err = self.assertRaises(errors.FileExists, tt_helper)
        self.assertEndsWith(err.path, "/foo")

    def test_two_directories_clash_finalize(self):
        def tt_helper():
            wt = self.make_branch_and_tree('.')
            tt = TreeTransform(wt)  # TreeTransform obtains write lock
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
        err = self.assertRaises(errors.FileExists, tt_helper)
        self.assertEndsWith(err.path, "/foo")

    def test_file_to_directory(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        wt.add(['foo'])
        wt.commit("one")
        tt = TreeTransform(wt)
        self.addCleanup(tt.finalize)
        foo_trans_id = tt.trans_id_tree_path("foo")
        tt.delete_contents(foo_trans_id)
        tt.create_directory(foo_trans_id)
        bar_trans_id = tt.trans_id_tree_path("foo/bar")
        tt.create_file([b"aa\n"], bar_trans_id)
        tt.version_file(b"bar-1", bar_trans_id)
        tt.apply()
        self.assertPathExists("foo/bar")
        wt.lock_read()
        try:
            self.assertEqual(wt.kind("foo"), "directory")
        finally:
            wt.unlock()
        wt.commit("two")
        changes = wt.changes_from(wt.basis_tree())
        self.assertFalse(changes.has_changed(), changes)

    def test_file_to_symlink(self):
        self.requireFeature(SymlinkFeature)
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        wt.add(['foo'])
        wt.commit("one")
        tt = TreeTransform(wt)
        self.addCleanup(tt.finalize)
        foo_trans_id = tt.trans_id_tree_path("foo")
        tt.delete_contents(foo_trans_id)
        tt.create_symlink("bar", foo_trans_id)
        tt.apply()
        self.assertPathExists("foo")
        wt.lock_read()
        self.addCleanup(wt.unlock)
        self.assertEqual(wt.kind("foo"), "symlink")

    def test_dir_to_file(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo/', 'foo/bar'])
        wt.add(['foo', 'foo/bar'])
        wt.commit("one")
        tt = TreeTransform(wt)
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
        self.requireFeature(HardlinkFeature)
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo/', 'foo/bar'])
        wt.add(['foo', 'foo/bar'])
        wt.commit("one")
        tt = TreeTransform(wt)
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
        transform, root = self.get_transform()
        trans_id = transform.trans_id_file_id(b'foo')
        transform.create_file([b'bar'], trans_id)
        transform.cancel_creation(trans_id)
        transform.apply()

    def test_create_from_tree(self):
        tree1 = self.make_branch_and_tree('tree1')
        self.build_tree_contents([('tree1/foo/',), ('tree1/bar', b'baz')])
        tree1.add(['foo', 'bar'], [b'foo-id', b'bar-id'])
        tree2 = self.make_branch_and_tree('tree2')
        tt = TreeTransform(tree2)
        foo_trans_id = tt.create_path('foo', tt.root)
        create_from_tree(tt, foo_trans_id, tree1, 'foo', file_id=b'foo-id')
        bar_trans_id = tt.create_path('bar', tt.root)
        create_from_tree(tt, bar_trans_id, tree1, 'bar', file_id=b'bar-id')
        tt.apply()
        self.assertEqual('directory', osutils.file_kind('tree2/foo'))
        self.assertFileEqual(b'baz', 'tree2/bar')

    def test_create_from_tree_bytes(self):
        """Provided lines are used instead of tree content."""
        tree1 = self.make_branch_and_tree('tree1')
        self.build_tree_contents([('tree1/foo', b'bar'), ])
        tree1.add('foo', b'foo-id')
        tree2 = self.make_branch_and_tree('tree2')
        tt = TreeTransform(tree2)
        foo_trans_id = tt.create_path('foo', tt.root)
        create_from_tree(tt, foo_trans_id, tree1, 'foo', file_id=b'foo-id',
                         chunks=[b'qux'])
        tt.apply()
        self.assertFileEqual(b'qux', 'tree2/foo')

    def test_create_from_tree_symlink(self):
        self.requireFeature(SymlinkFeature)
        tree1 = self.make_branch_and_tree('tree1')
        os.symlink('bar', 'tree1/foo')
        tree1.add('foo', b'foo-id')
        tt = TreeTransform(self.make_branch_and_tree('tree2'))
        foo_trans_id = tt.create_path('foo', tt.root)
        create_from_tree(tt, foo_trans_id, tree1, 'foo', file_id=b'foo-id')
        tt.apply()
        self.assertEqual('bar', os.readlink('tree2/foo'))


class TransformGroup(object):

    def __init__(self, dirname, root_id):
        self.name = dirname
        os.mkdir(dirname)
        self.wt = ControlDir.create_standalone_workingtree(dirname)
        self.wt.set_root_id(root_id)
        self.b = self.wt.branch
        self.tt = TreeTransform(self.wt)
        self.root = self.tt.trans_id_tree_path('')


def conflict_text(tree, merge):
    template = b'%s TREE\n%s%s\n%s%s MERGE-SOURCE\n'
    return template % (b'<' * 7, tree, b'=' * 7, merge, b'>' * 7)


class TestInventoryAltered(tests.TestCaseWithTransport):

    def test_inventory_altered_unchanged(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo'])
        tree.add('foo', b'foo-id')
        with TransformPreview(tree) as tt:
            self.assertEqual([], tt._inventory_altered())

    def test_inventory_altered_changed_parent_id(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo'])
        tree.add('foo', b'foo-id')
        with TransformPreview(tree) as tt:
            tt.unversion_file(tt.root)
            tt.version_file(b'new-id', tt.root)
            foo_trans_id = tt.trans_id_tree_path('foo')
            foo_tuple = ('foo', foo_trans_id)
            root_tuple = ('', tt.root)
            self.assertEqual([root_tuple, foo_tuple], tt._inventory_altered())

    def test_inventory_altered_noop_changed_parent_id(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo'])
        tree.add('foo', b'foo-id')
        with TransformPreview(tree) as tt:
            tt.unversion_file(tt.root)
            tt.version_file(tree.get_root_id(), tt.root)
            tt.trans_id_tree_path('foo')
            self.assertEqual([], tt._inventory_altered())


class TestTransformMerge(TestCaseInTempDir):

    def test_text_merge(self):
        root_id = generate_ids.gen_root_id()
        base = TransformGroup("base", root_id)
        base.tt.new_file('a', base.root, [b'a\nb\nc\nd\be\n'], b'a')
        base.tt.new_file('b', base.root, [b'b1'], b'b')
        base.tt.new_file('c', base.root, [b'c'], b'c')
        base.tt.new_file('d', base.root, [b'd'], b'd')
        base.tt.new_file('e', base.root, [b'e'], b'e')
        base.tt.new_file('f', base.root, [b'f'], b'f')
        base.tt.new_directory('g', base.root, b'g')
        base.tt.new_directory('h', base.root, b'h')
        base.tt.apply()
        other = TransformGroup("other", root_id)
        other.tt.new_file('a', other.root, [b'y\nb\nc\nd\be\n'], b'a')
        other.tt.new_file('b', other.root, [b'b2'], b'b')
        other.tt.new_file('c', other.root, [b'c2'], b'c')
        other.tt.new_file('d', other.root, [b'd'], b'd')
        other.tt.new_file('e', other.root, [b'e2'], b'e')
        other.tt.new_file('f', other.root, [b'f'], b'f')
        other.tt.new_file('g', other.root, [b'g'], b'g')
        other.tt.new_file('h', other.root, [b'h\ni\nj\nk\n'], b'h')
        other.tt.new_file('i', other.root, [b'h\ni\nj\nk\n'], b'i')
        other.tt.apply()
        this = TransformGroup("this", root_id)
        this.tt.new_file('a', this.root, [b'a\nb\nc\nd\bz\n'], b'a')
        this.tt.new_file('b', this.root, [b'b'], b'b')
        this.tt.new_file('c', this.root, [b'c'], b'c')
        this.tt.new_file('d', this.root, [b'd2'], b'd')
        this.tt.new_file('e', this.root, [b'e2'], b'e')
        this.tt.new_file('f', this.root, [b'f'], b'f')
        this.tt.new_file('g', this.root, [b'g'], b'g')
        this.tt.new_file('h', this.root, [b'1\n2\n3\n4\n'], b'h')
        this.tt.new_file('i', this.root, [b'1\n2\n3\n4\n'], b'i')
        this.tt.apply()
        Merge3Merger(this.wt, this.wt, base.wt, other.wt)

        # textual merge
        with this.wt.get_file(this.wt.id2path(b'a')) as f:
            self.assertEqual(f.read(), b'y\nb\nc\nd\bz\n')
        # three-way text conflict
        with this.wt.get_file(this.wt.id2path(b'b')) as f:
            self.assertEqual(f.read(), conflict_text(b'b', b'b2'))
        # OTHER wins
        self.assertEqual(this.wt.get_file(this.wt.id2path(b'c')).read(), b'c2')
        # THIS wins
        self.assertEqual(this.wt.get_file(this.wt.id2path(b'd')).read(), b'd2')
        # Ambigious clean merge
        self.assertEqual(this.wt.get_file(this.wt.id2path(b'e')).read(), b'e2')
        # No change
        self.assertEqual(this.wt.get_file(this.wt.id2path(b'f')).read(), b'f')
        # Correct correct results when THIS == OTHER
        self.assertEqual(this.wt.get_file(this.wt.id2path(b'g')).read(), b'g')
        # Text conflict when THIS & OTHER are text and BASE is dir
        self.assertEqual(this.wt.get_file(this.wt.id2path(b'h')).read(),
                         conflict_text(b'1\n2\n3\n4\n', b'h\ni\nj\nk\n'))
        self.assertEqual(this.wt.get_file('h.THIS').read(),
                         b'1\n2\n3\n4\n')
        self.assertEqual(this.wt.get_file('h.OTHER').read(),
                         b'h\ni\nj\nk\n')
        self.assertEqual(file_kind(this.wt.abspath('h.BASE')), 'directory')
        self.assertEqual(this.wt.get_file(this.wt.id2path(b'i')).read(),
                         conflict_text(b'1\n2\n3\n4\n', b'h\ni\nj\nk\n'))
        self.assertEqual(this.wt.get_file('i.THIS').read(),
                         b'1\n2\n3\n4\n')
        self.assertEqual(this.wt.get_file('i.OTHER').read(),
                         b'h\ni\nj\nk\n')
        self.assertEqual(os.path.exists(this.wt.abspath('i.BASE')), False)
        modified = [b'a', b'b', b'c', b'h', b'i']
        merge_modified = this.wt.merge_modified()
        self.assertSubset(merge_modified, modified)
        self.assertEqual(len(merge_modified), len(modified))
        with open(this.wt.abspath(this.wt.id2path(b'a')), 'wb') as f:
            f.write(b'booga')
        modified.pop(0)
        merge_modified = this.wt.merge_modified()
        self.assertSubset(merge_modified, modified)
        self.assertEqual(len(merge_modified), len(modified))
        this.wt.remove('b')
        this.wt.revert()

    def test_file_merge(self):
        self.requireFeature(SymlinkFeature)
        root_id = generate_ids.gen_root_id()
        base = TransformGroup("BASE", root_id)
        this = TransformGroup("THIS", root_id)
        other = TransformGroup("OTHER", root_id)
        for tg in this, base, other:
            tg.tt.new_directory('a', tg.root, b'a')
            tg.tt.new_symlink('b', tg.root, 'b', b'b')
            tg.tt.new_file('c', tg.root, [b'c'], b'c')
            tg.tt.new_symlink('d', tg.root, tg.name, b'd')
        targets = ((base, 'base-e', 'base-f', None, None),
                   (this, 'other-e', 'this-f', 'other-g', 'this-h'),
                   (other, 'other-e', None, 'other-g', 'other-h'))
        for tg, e_target, f_target, g_target, h_target in targets:
            for link, target in (('e', e_target), ('f', f_target),
                                 ('g', g_target), ('h', h_target)):
                if target is not None:
                    tg.tt.new_symlink(link, tg.root, target,
                                      link.encode('ascii'))

        for tg in this, base, other:
            tg.tt.apply()
        Merge3Merger(this.wt, this.wt, base.wt, other.wt)
        self.assertIs(os.path.isdir(this.wt.abspath('a')), True)
        self.assertIs(os.path.islink(this.wt.abspath('b')), True)
        self.assertIs(os.path.isfile(this.wt.abspath('c')), True)
        for suffix in ('THIS', 'BASE', 'OTHER'):
            self.assertEqual(os.readlink(
                this.wt.abspath('d.' + suffix)), suffix)
        self.assertIs(os.path.lexists(this.wt.abspath('d')), False)
        self.assertEqual(this.wt.id2path(b'd'), 'd.OTHER')
        self.assertEqual(this.wt.id2path(b'f'), 'f.THIS')
        self.assertEqual(os.readlink(this.wt.abspath('e')), 'other-e')
        self.assertIs(os.path.lexists(this.wt.abspath('e.THIS')), False)
        self.assertIs(os.path.lexists(this.wt.abspath('e.OTHER')), False)
        self.assertIs(os.path.lexists(this.wt.abspath('e.BASE')), False)
        self.assertIs(os.path.lexists(this.wt.abspath('g')), True)
        self.assertIs(os.path.lexists(this.wt.abspath('g.BASE')), False)
        self.assertIs(os.path.lexists(this.wt.abspath('h')), False)
        self.assertIs(os.path.lexists(this.wt.abspath('h.BASE')), False)
        self.assertIs(os.path.lexists(this.wt.abspath('h.THIS')), True)
        self.assertIs(os.path.lexists(this.wt.abspath('h.OTHER')), True)

    def test_filename_merge(self):
        root_id = generate_ids.gen_root_id()
        base = TransformGroup("BASE", root_id)
        this = TransformGroup("THIS", root_id)
        other = TransformGroup("OTHER", root_id)
        base_a, this_a, other_a = [t.tt.new_directory('a', t.root, b'a')
                                   for t in [base, this, other]]
        base_b, this_b, other_b = [t.tt.new_directory('b', t.root, b'b')
                                   for t in [base, this, other]]
        base.tt.new_directory('c', base_a, b'c')
        this.tt.new_directory('c1', this_a, b'c')
        other.tt.new_directory('c', other_b, b'c')

        base.tt.new_directory('d', base_a, b'd')
        this.tt.new_directory('d1', this_b, b'd')
        other.tt.new_directory('d', other_a, b'd')

        base.tt.new_directory('e', base_a, b'e')
        this.tt.new_directory('e', this_a, b'e')
        other.tt.new_directory('e1', other_b, b'e')

        base.tt.new_directory('f', base_a, b'f')
        this.tt.new_directory('f1', this_b, b'f')
        other.tt.new_directory('f1', other_b, b'f')

        for tg in [this, base, other]:
            tg.tt.apply()
        Merge3Merger(this.wt, this.wt, base.wt, other.wt)
        self.assertEqual(this.wt.id2path(b'c'), pathjoin('b/c1'))
        self.assertEqual(this.wt.id2path(b'd'), pathjoin('b/d1'))
        self.assertEqual(this.wt.id2path(b'e'), pathjoin('b/e1'))
        self.assertEqual(this.wt.id2path(b'f'), pathjoin('b/f1'))

    def test_filename_merge_conflicts(self):
        root_id = generate_ids.gen_root_id()
        base = TransformGroup("BASE", root_id)
        this = TransformGroup("THIS", root_id)
        other = TransformGroup("OTHER", root_id)
        base_a, this_a, other_a = [t.tt.new_directory('a', t.root, b'a')
                                   for t in [base, this, other]]
        base_b, this_b, other_b = [t.tt.new_directory('b', t.root, b'b')
                                   for t in [base, this, other]]

        base.tt.new_file('g', base_a, [b'g'], b'g')
        other.tt.new_file('g1', other_b, [b'g1'], b'g')

        base.tt.new_file('h', base_a, [b'h'], b'h')
        this.tt.new_file('h1', this_b, [b'h1'], b'h')

        base.tt.new_file('i', base.root, [b'i'], b'i')
        other.tt.new_directory('i1', this_b, b'i')

        for tg in [this, base, other]:
            tg.tt.apply()
        Merge3Merger(this.wt, this.wt, base.wt, other.wt)

        self.assertEqual(this.wt.id2path(b'g'), pathjoin('b/g1.OTHER'))
        self.assertIs(os.path.lexists(this.wt.abspath('b/g1.BASE')), True)
        self.assertIs(os.path.lexists(this.wt.abspath('b/g1.THIS')), False)
        self.assertEqual(this.wt.id2path(b'h'), pathjoin('b/h1.THIS'))
        self.assertIs(os.path.lexists(this.wt.abspath('b/h1.BASE')), True)
        self.assertIs(os.path.lexists(this.wt.abspath('b/h1.OTHER')), False)
        self.assertEqual(this.wt.id2path(b'i'), pathjoin('b/i1.OTHER'))


class TestBuildTree(tests.TestCaseWithTransport):

    def test_build_tree_with_symlinks(self):
        self.requireFeature(SymlinkFeature)
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
        source.add('file', b'new-file')
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
        self.requireFeature(SymlinkFeature)
        source = self.make_branch_and_tree('source')
        os.symlink('foo', 'source/symlink')
        source.add('symlink', b'new-symlink')
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
        source.add(['dir1', 'dir1/file'], [b'new-dir1', b'new-file'])
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
        self.assertEqual('directory', file_kind('target4/dir1/file'))
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
        source.add('name', b'new-name')
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
        source.add(['file1', 'file2'], [b'file1-id', b'file2-id'])
        source.commit('commit files')
        source.lock_write()
        self.addCleanup(source.unlock)
        return source

    def test_build_tree_accelerator_tree(self):
        source = self.create_ab_tree()
        self.build_tree_contents([('source/file2', b'C')])
        calls = []
        real_source_get_file = source.get_file

        def get_file(path, file_id=None):
            calls.append(file_id)
            return real_source_get_file(path, file_id)
        source.get_file = get_file
        target = self.make_branch_and_tree('target')
        revision_tree = source.basis_tree()
        revision_tree.lock_read()
        self.addCleanup(revision_tree.unlock)
        build_tree(revision_tree, target, source)
        self.assertEqual([b'file1-id'], calls)
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
        self.requireFeature(SymlinkFeature)
        source = self.make_branch_and_tree('source')
        self.build_tree_contents([('source/file1', b'')])
        self.build_tree_contents([('source/file2', b'')])
        source.add(['file1', 'file2'], [b'file1-id', b'file2-id'])
        source.commit('commit files')
        os.unlink('source/file2')
        self.build_tree_contents([('source/file2/', b'C')])
        os.unlink('source/file1')
        os.symlink('file2', 'source/file1')
        calls = []
        real_source_get_file = source.get_file

        def get_file(path, file_id=None):
            calls.append(file_id)
            return real_source_get_file(path, file_id)
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
        self.requireFeature(HardlinkFeature)
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
        source.add(['file1'], [b'file1-id'])
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
        self.requireFeature(HardlinkFeature)
        source = self.create_ab_tree()
        tt = TreeTransform(source)
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
        self.requireFeature(HardlinkFeature)
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
        source.add(['file', 'FILE'], [b'lower-id', b'upper-id'])
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
                   [b'file1-id', b'dir-id', b'file2-id'])
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


class TestCommitTransform(tests.TestCaseWithTransport):

    def get_branch(self):
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit('empty commit')
        return tree.branch

    def get_branch_and_transform(self):
        branch = self.get_branch()
        tt = TransformPreview(branch.basis_tree())
        self.addCleanup(tt.finalize)
        return branch, tt

    def test_commit_wrong_basis(self):
        branch = self.get_branch()
        basis = branch.repository.revision_tree(
            _mod_revision.NULL_REVISION)
        tt = TransformPreview(basis)
        self.addCleanup(tt.finalize)
        e = self.assertRaises(ValueError, tt.commit, branch, '')
        self.assertEqual('TreeTransform not based on branch basis: null:',
                         str(e))

    def test_empy_commit(self):
        branch, tt = self.get_branch_and_transform()
        rev = tt.commit(branch, 'my message')
        self.assertEqual(2, branch.revno())
        repo = branch.repository
        self.assertEqual('my message', repo.get_revision(rev).message)

    def test_merge_parents(self):
        branch, tt = self.get_branch_and_transform()
        tt.commit(branch, 'my message', [b'rev1b', b'rev1c'])
        self.assertEqual([b'rev1b', b'rev1c'],
                         branch.basis_tree().get_parent_ids()[1:])

    def test_first_commit(self):
        branch = self.make_branch('branch')
        branch.lock_write()
        self.addCleanup(branch.unlock)
        tt = TransformPreview(branch.basis_tree())
        self.addCleanup(tt.finalize)
        tt.new_directory('', ROOT_PARENT, b'TREE_ROOT')
        tt.commit(branch, 'my message')
        self.assertEqual([], branch.basis_tree().get_parent_ids())
        self.assertNotEqual(_mod_revision.NULL_REVISION,
                            branch.last_revision())

    def test_first_commit_with_merge_parents(self):
        branch = self.make_branch('branch')
        branch.lock_write()
        self.addCleanup(branch.unlock)
        tt = TransformPreview(branch.basis_tree())
        self.addCleanup(tt.finalize)
        e = self.assertRaises(ValueError, tt.commit, branch,
                              'my message', [b'rev1b-id'])
        self.assertEqual('Cannot supply merge parents for first commit.',
                         str(e))
        self.assertEqual(_mod_revision.NULL_REVISION, branch.last_revision())

    def test_add_files(self):
        branch, tt = self.get_branch_and_transform()
        tt.new_file('file', tt.root, [b'contents'], b'file-id')
        trans_id = tt.new_directory('dir', tt.root, b'dir-id')
        if SymlinkFeature.available():
            tt.new_symlink('symlink', trans_id, 'target', b'symlink-id')
        tt.commit(branch, 'message')
        tree = branch.basis_tree()
        self.assertEqual('file', tree.id2path(b'file-id'))
        self.assertEqual(b'contents', tree.get_file_text('file'))
        self.assertEqual('dir', tree.id2path(b'dir-id'))
        if SymlinkFeature.available():
            self.assertEqual('dir/symlink', tree.id2path(b'symlink-id'))
            self.assertEqual('target', tree.get_symlink_target('dir/symlink'))

    def test_add_unversioned(self):
        branch, tt = self.get_branch_and_transform()
        tt.new_file('file', tt.root, [b'contents'])
        self.assertRaises(errors.StrictCommitFailed, tt.commit, branch,
                          'message', strict=True)

    def test_modify_strict(self):
        branch, tt = self.get_branch_and_transform()
        tt.new_file('file', tt.root, [b'contents'], b'file-id')
        tt.commit(branch, 'message', strict=True)
        tt = TransformPreview(branch.basis_tree())
        self.addCleanup(tt.finalize)
        trans_id = tt.trans_id_file_id(b'file-id')
        tt.delete_contents(trans_id)
        tt.create_file([b'contents'], trans_id)
        tt.commit(branch, 'message', strict=True)

    def test_commit_malformed(self):
        """Committing a malformed transform should raise an exception.

        In this case, we are adding a file without adding its parent.
        """
        branch, tt = self.get_branch_and_transform()
        parent_id = tt.trans_id_file_id(b'parent-id')
        tt.new_file('file', parent_id, [b'contents'], b'file-id')
        self.assertRaises(errors.MalformedTransform, tt.commit, branch,
                          'message')

    def test_commit_rich_revision_data(self):
        branch, tt = self.get_branch_and_transform()
        rev_id = tt.commit(branch, 'message', timestamp=1, timezone=43201,
                           committer='me <me@example.com>',
                           revprops={u'foo': 'bar'}, revision_id=b'revid-1',
                           authors=['Author1 <author1@example.com>',
                                    'Author2 <author2@example.com>',
                                    ])
        self.assertEqual(b'revid-1', rev_id)
        revision = branch.repository.get_revision(rev_id)
        self.assertEqual(1, revision.timestamp)
        self.assertEqual(43201, revision.timezone)
        self.assertEqual('me <me@example.com>', revision.committer)
        self.assertEqual(['Author1 <author1@example.com>',
                          'Author2 <author2@example.com>'],
                         revision.get_apparent_authors())
        del revision.properties['authors']
        self.assertEqual({'foo': 'bar',
                          'branch-nick': 'tree'},
                         revision.properties)

    def test_no_explicit_revprops(self):
        branch, tt = self.get_branch_and_transform()
        rev_id = tt.commit(branch, 'message', authors=[
            'Author1 <author1@example.com>',
            'Author2 <author2@example.com>', ])
        revision = branch.repository.get_revision(rev_id)
        self.assertEqual(['Author1 <author1@example.com>',
                          'Author2 <author2@example.com>'],
                         revision.get_apparent_authors())
        self.assertEqual('tree', revision.properties['branch-nick'])


class TestFileMover(tests.TestCaseWithTransport):

    def test_file_mover(self):
        self.build_tree(['a/', 'a/b', 'c/', 'c/d'])
        mover = _FileMover()
        mover.rename('a', 'q')
        self.assertPathExists('q')
        self.assertPathDoesNotExist('a')
        self.assertPathExists('q/b')
        self.assertPathExists('c')
        self.assertPathExists('c/d')

    def test_pre_delete_rollback(self):
        self.build_tree(['a/'])
        mover = _FileMover()
        mover.pre_delete('a', 'q')
        self.assertPathExists('q')
        self.assertPathDoesNotExist('a')
        mover.rollback()
        self.assertPathDoesNotExist('q')
        self.assertPathExists('a')

    def test_apply_deletions(self):
        self.build_tree(['a/', 'b/'])
        mover = _FileMover()
        mover.pre_delete('a', 'q')
        mover.pre_delete('b', 'r')
        self.assertPathExists('q')
        self.assertPathExists('r')
        self.assertPathDoesNotExist('a')
        self.assertPathDoesNotExist('b')
        mover.apply_deletions()
        self.assertPathDoesNotExist('q')
        self.assertPathDoesNotExist('r')
        self.assertPathDoesNotExist('a')
        self.assertPathDoesNotExist('b')

    def test_file_mover_rollback(self):
        self.build_tree(['a/', 'a/b', 'c/', 'c/d/', 'c/e/'])
        mover = _FileMover()
        mover.rename('c/d', 'c/f')
        mover.rename('c/e', 'c/d')
        try:
            mover.rename('a', 'c')
        except errors.FileExists:
            mover.rollback()
        self.assertPathExists('a')
        self.assertPathExists('c/d')


class Bogus(Exception):
    pass


class TestTransformRollback(tests.TestCaseWithTransport):

    class ExceptionFileMover(_FileMover):

        def __init__(self, bad_source=None, bad_target=None):
            _FileMover.__init__(self)
            self.bad_source = bad_source
            self.bad_target = bad_target

        def rename(self, source, target):
            if (self.bad_source is not None and
                    source.endswith(self.bad_source)):
                raise Bogus
            elif (self.bad_target is not None and
                  target.endswith(self.bad_target)):
                raise Bogus
            else:
                _FileMover.rename(self, source, target)

    def test_rollback_rename(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b'])
        tt = TreeTransform(tree)
        self.addCleanup(tt.finalize)
        a_id = tt.trans_id_tree_path('a')
        tt.adjust_path('c', tt.root, a_id)
        tt.adjust_path('d', a_id, tt.trans_id_tree_path('a/b'))
        self.assertRaises(Bogus, tt.apply,
                          _mover=self.ExceptionFileMover(bad_source='a'))
        self.assertPathExists('a')
        self.assertPathExists('a/b')
        tt.apply()
        self.assertPathExists('c')
        self.assertPathExists('c/d')

    def test_rollback_rename_into_place(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b'])
        tt = TreeTransform(tree)
        self.addCleanup(tt.finalize)
        a_id = tt.trans_id_tree_path('a')
        tt.adjust_path('c', tt.root, a_id)
        tt.adjust_path('d', a_id, tt.trans_id_tree_path('a/b'))
        self.assertRaises(Bogus, tt.apply,
                          _mover=self.ExceptionFileMover(bad_target='c/d'))
        self.assertPathExists('a')
        self.assertPathExists('a/b')
        tt.apply()
        self.assertPathExists('c')
        self.assertPathExists('c/d')

    def test_rollback_deletion(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a/', 'a/b'])
        tt = TreeTransform(tree)
        self.addCleanup(tt.finalize)
        a_id = tt.trans_id_tree_path('a')
        tt.delete_contents(a_id)
        tt.adjust_path('d', tt.root, tt.trans_id_tree_path('a/b'))
        self.assertRaises(Bogus, tt.apply,
                          _mover=self.ExceptionFileMover(bad_target='d'))
        self.assertPathExists('a')
        self.assertPathExists('a/b')


class TestFinalizeRobustness(tests.TestCaseWithTransport):
    """Ensure treetransform creation errors can be safely cleaned up after"""

    def _override_globals_in_method(self, instance, method_name, globals):
        """Replace method on instance with one with updated globals"""
        import types
        func = getattr(instance, method_name).__func__
        new_globals = dict(func.__globals__)
        new_globals.update(globals)
        new_func = types.FunctionType(func.__code__, new_globals,
                                      func.__name__, func.__defaults__)
        if PY3:
            setattr(instance, method_name,
                    types.MethodType(new_func, instance))
        else:
            setattr(instance, method_name,
                    types.MethodType(new_func, instance, instance.__class__))
        self.addCleanup(delattr, instance, method_name)

    @staticmethod
    def _fake_open_raises_before(name, mode):
        """Like open() but raises before doing anything"""
        raise RuntimeError

    @staticmethod
    def _fake_open_raises_after(name, mode):
        """Like open() but raises after creating file without returning"""
        open(name, mode).close()
        raise RuntimeError

    def create_transform_and_root_trans_id(self):
        """Setup a transform creating a file in limbo"""
        tree = self.make_branch_and_tree('.')
        tt = TreeTransform(tree)
        return tt, tt.create_path("a", tt.root)

    def create_transform_and_subdir_trans_id(self):
        """Setup a transform creating a directory containing a file in limbo"""
        tree = self.make_branch_and_tree('.')
        tt = TreeTransform(tree)
        d_trans_id = tt.create_path("d", tt.root)
        tt.create_directory(d_trans_id)
        f_trans_id = tt.create_path("a", d_trans_id)
        tt.adjust_path("a", d_trans_id, f_trans_id)
        return tt, f_trans_id

    def test_root_create_file_open_raises_before_creation(self):
        tt, trans_id = self.create_transform_and_root_trans_id()
        self._override_globals_in_method(
            tt, "create_file", {"open": self._fake_open_raises_before})
        self.assertRaises(RuntimeError, tt.create_file,
                          [b"contents"], trans_id)
        path = tt._limbo_name(trans_id)
        self.assertPathDoesNotExist(path)
        tt.finalize()
        self.assertPathDoesNotExist(tt._limbodir)

    def test_root_create_file_open_raises_after_creation(self):
        tt, trans_id = self.create_transform_and_root_trans_id()
        self._override_globals_in_method(
            tt, "create_file", {"open": self._fake_open_raises_after})
        self.assertRaises(RuntimeError, tt.create_file,
                          [b"contents"], trans_id)
        path = tt._limbo_name(trans_id)
        self.assertPathExists(path)
        tt.finalize()
        self.assertPathDoesNotExist(path)
        self.assertPathDoesNotExist(tt._limbodir)

    def test_subdir_create_file_open_raises_before_creation(self):
        tt, trans_id = self.create_transform_and_subdir_trans_id()
        self._override_globals_in_method(
            tt, "create_file", {"open": self._fake_open_raises_before})
        self.assertRaises(RuntimeError, tt.create_file,
                          [b"contents"], trans_id)
        path = tt._limbo_name(trans_id)
        self.assertPathDoesNotExist(path)
        tt.finalize()
        self.assertPathDoesNotExist(tt._limbodir)

    def test_subdir_create_file_open_raises_after_creation(self):
        tt, trans_id = self.create_transform_and_subdir_trans_id()
        self._override_globals_in_method(
            tt, "create_file", {"open": self._fake_open_raises_after})
        self.assertRaises(RuntimeError, tt.create_file,
                          [b"contents"], trans_id)
        path = tt._limbo_name(trans_id)
        self.assertPathExists(path)
        tt.finalize()
        self.assertPathDoesNotExist(path)
        self.assertPathDoesNotExist(tt._limbodir)

    def test_rename_in_limbo_rename_raises_after_rename(self):
        tt, trans_id = self.create_transform_and_root_trans_id()
        parent1 = tt.new_directory('parent1', tt.root)
        child1 = tt.new_file('child1', parent1, [b'contents'])
        parent2 = tt.new_directory('parent2', tt.root)

        class FakeOSModule(object):
            def rename(self, old, new):
                os.rename(old, new)
                raise RuntimeError
        self._override_globals_in_method(tt, "_rename_in_limbo",
                                         {"os": FakeOSModule()})
        self.assertRaises(
            RuntimeError, tt.adjust_path, "child1", parent2, child1)
        path = osutils.pathjoin(tt._limbo_name(parent2), "child1")
        self.assertPathExists(path)
        tt.finalize()
        self.assertPathDoesNotExist(path)
        self.assertPathDoesNotExist(tt._limbodir)

    def test_rename_in_limbo_rename_raises_before_rename(self):
        tt, trans_id = self.create_transform_and_root_trans_id()
        parent1 = tt.new_directory('parent1', tt.root)
        child1 = tt.new_file('child1', parent1, [b'contents'])
        parent2 = tt.new_directory('parent2', tt.root)

        class FakeOSModule(object):
            def rename(self, old, new):
                raise RuntimeError
        self._override_globals_in_method(tt, "_rename_in_limbo",
                                         {"os": FakeOSModule()})
        self.assertRaises(
            RuntimeError, tt.adjust_path, "child1", parent2, child1)
        path = osutils.pathjoin(tt._limbo_name(parent1), "child1")
        self.assertPathExists(path)
        tt.finalize()
        self.assertPathDoesNotExist(path)
        self.assertPathDoesNotExist(tt._limbodir)


class TestTransformMissingParent(tests.TestCaseWithTransport):

    def make_tt_with_versioned_dir(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['dir/', ])
        wt.add(['dir'], [b'dir-id'])
        wt.commit('Create dir')
        tt = TreeTransform(wt)
        self.addCleanup(tt.finalize)
        return wt, tt

    def test_resolve_create_parent_for_versioned_file(self):
        wt, tt = self.make_tt_with_versioned_dir()
        dir_tid = tt.trans_id_tree_path('dir')
        tt.new_file('file', dir_tid, [b'Contents'], file_id=b'file-id')
        tt.delete_contents(dir_tid)
        tt.unversion_file(dir_tid)
        conflicts = resolve_conflicts(tt)
        # one conflict for the missing directory, one for the unversioned
        # parent
        self.assertLength(2, conflicts)

    def test_non_versioned_file_create_conflict(self):
        wt, tt = self.make_tt_with_versioned_dir()
        dir_tid = tt.trans_id_tree_path('dir')
        tt.new_file('file', dir_tid, [b'Contents'])
        tt.delete_contents(dir_tid)
        tt.unversion_file(dir_tid)
        conflicts = resolve_conflicts(tt)
        # no conflicts or rather: orphaning 'file' resolve the 'dir' conflict
        self.assertLength(1, conflicts)
        self.assertEqual(('deleting parent', 'Not deleting', 'new-1'),
                         conflicts.pop())


A_ENTRY = (b'a-id', ('a', 'a'), True, (True, True),
           (b'TREE_ROOT', b'TREE_ROOT'), ('a', 'a'), ('file', 'file'),
           (False, False))
ROOT_ENTRY = (b'TREE_ROOT', ('', ''), False, (True, True), (None, None),
              ('', ''), ('directory', 'directory'), (False, False))


class TestTransformPreview(tests.TestCaseWithTransport):

    def create_tree(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree_contents([('a', b'content 1')])
        tree.set_root_id(b'TREE_ROOT')
        tree.add('a', b'a-id')
        tree.commit('rev1', rev_id=b'rev1')
        return tree.branch.repository.revision_tree(b'rev1')

    def get_empty_preview(self):
        repository = self.make_repository('repo')
        tree = repository.revision_tree(_mod_revision.NULL_REVISION)
        preview = TransformPreview(tree)
        self.addCleanup(preview.finalize)
        return preview

    def test_transform_preview(self):
        revision_tree = self.create_tree()
        preview = TransformPreview(revision_tree)
        self.addCleanup(preview.finalize)

    def test_transform_preview_tree(self):
        revision_tree = self.create_tree()
        preview = TransformPreview(revision_tree)
        self.addCleanup(preview.finalize)
        preview.get_preview_tree()

    def test_transform_new_file(self):
        revision_tree = self.create_tree()
        preview = TransformPreview(revision_tree)
        self.addCleanup(preview.finalize)
        preview.new_file('file2', preview.root, [b'content B\n'], b'file2-id')
        preview_tree = preview.get_preview_tree()
        self.assertEqual(preview_tree.kind('file2'), 'file')
        with preview_tree.get_file('file2') as f:
            self.assertEqual(f.read(), b'content B\n')

    def test_diff_preview_tree(self):
        revision_tree = self.create_tree()
        preview = TransformPreview(revision_tree)
        self.addCleanup(preview.finalize)
        preview.new_file('file2', preview.root, [b'content B\n'], b'file2-id')
        preview_tree = preview.get_preview_tree()
        out = BytesIO()
        show_diff_trees(revision_tree, preview_tree, out)
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], b"=== added file 'file2'")
        # 3 lines of diff administrivia
        self.assertEqual(lines[4], b"+content B")

    def test_transform_conflicts(self):
        revision_tree = self.create_tree()
        preview = TransformPreview(revision_tree)
        self.addCleanup(preview.finalize)
        preview.new_file('a', preview.root, [b'content 2'])
        resolve_conflicts(preview)
        trans_id = preview.trans_id_file_id(b'a-id')
        self.assertEqual('a.moved', preview.final_name(trans_id))

    def get_tree_and_preview_tree(self):
        revision_tree = self.create_tree()
        preview = TransformPreview(revision_tree)
        self.addCleanup(preview.finalize)
        a_trans_id = preview.trans_id_file_id(b'a-id')
        preview.delete_contents(a_trans_id)
        preview.create_file([b'b content'], a_trans_id)
        preview_tree = preview.get_preview_tree()
        return revision_tree, preview_tree

    def test_iter_changes(self):
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        root = revision_tree.get_root_id()
        self.assertEqual([(b'a-id', ('a', 'a'), True, (True, True),
                           (root, root), ('a', 'a'), ('file', 'file'),
                           (False, False))],
                         list(preview_tree.iter_changes(revision_tree)))

    def test_include_unchanged_succeeds(self):
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        changes = preview_tree.iter_changes(revision_tree,
                                            include_unchanged=True)
        self.assertEqual([ROOT_ENTRY, A_ENTRY], list(changes))

    def test_specific_files(self):
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        changes = preview_tree.iter_changes(revision_tree,
                                            specific_files=[''])
        self.assertEqual([A_ENTRY], list(changes))

    def test_want_unversioned(self):
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        changes = preview_tree.iter_changes(revision_tree,
                                            want_unversioned=True)
        self.assertEqual([A_ENTRY], list(changes))

    def test_ignore_extra_trees_no_specific_files(self):
        # extra_trees is harmless without specific_files, so we'll silently
        # accept it, even though we won't use it.
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        preview_tree.iter_changes(revision_tree, extra_trees=[preview_tree])

    def test_ignore_require_versioned_no_specific_files(self):
        # require_versioned is meaningless without specific_files.
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        preview_tree.iter_changes(revision_tree, require_versioned=False)

    def test_ignore_pb(self):
        # pb could be supported, but TT.iter_changes doesn't support it.
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        preview_tree.iter_changes(revision_tree)

    def test_kind(self):
        revision_tree = self.create_tree()
        preview = TransformPreview(revision_tree)
        self.addCleanup(preview.finalize)
        preview.new_file('file', preview.root, [b'contents'], b'file-id')
        preview.new_directory('directory', preview.root, b'dir-id')
        preview_tree = preview.get_preview_tree()
        self.assertEqual('file', preview_tree.kind('file'))
        self.assertEqual('directory', preview_tree.kind('directory'))

    def test_get_file_mtime(self):
        preview = self.get_empty_preview()
        file_trans_id = preview.new_file('file', preview.root, [b'contents'],
                                         b'file-id')
        limbo_path = preview._limbo_name(file_trans_id)
        preview_tree = preview.get_preview_tree()
        self.assertEqual(os.stat(limbo_path).st_mtime,
                         preview_tree.get_file_mtime('file'))

    def test_get_file_mtime_renamed(self):
        work_tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        work_tree.add('file', b'file-id')
        preview = TransformPreview(work_tree)
        self.addCleanup(preview.finalize)
        file_trans_id = preview.trans_id_tree_path('file')
        preview.adjust_path('renamed', preview.root, file_trans_id)
        preview_tree = preview.get_preview_tree()
        preview_mtime = preview_tree.get_file_mtime('renamed')
        work_mtime = work_tree.get_file_mtime('file')

    def test_get_file_size(self):
        work_tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/old', b'old')])
        work_tree.add('old', b'old-id')
        preview = TransformPreview(work_tree)
        self.addCleanup(preview.finalize)
        preview.new_file('name', preview.root, [b'contents'], b'new-id',
                         'executable')
        tree = preview.get_preview_tree()
        self.assertEqual(len('old'), tree.get_file_size('old'))
        self.assertEqual(len('contents'), tree.get_file_size('name'))

    def test_get_file(self):
        preview = self.get_empty_preview()
        preview.new_file('file', preview.root, [b'contents'], b'file-id')
        preview_tree = preview.get_preview_tree()
        with preview_tree.get_file('file') as tree_file:
            self.assertEqual(b'contents', tree_file.read())

    def test_get_symlink_target(self):
        self.requireFeature(SymlinkFeature)
        preview = self.get_empty_preview()
        preview.new_symlink('symlink', preview.root, 'target', b'symlink-id')
        preview_tree = preview.get_preview_tree()
        self.assertEqual('target',
                         preview_tree.get_symlink_target('symlink'))

    def test_all_file_ids(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a', 'tree/b', 'tree/c'])
        tree.add(['a', 'b', 'c'], [b'a-id', b'b-id', b'c-id'])
        preview = TransformPreview(tree)
        self.addCleanup(preview.finalize)
        preview.unversion_file(preview.trans_id_file_id(b'b-id'))
        c_trans_id = preview.trans_id_file_id(b'c-id')
        preview.unversion_file(c_trans_id)
        preview.version_file(b'c-id', c_trans_id)
        preview_tree = preview.get_preview_tree()
        self.assertEqual({b'a-id', b'c-id', tree.get_root_id()},
                         preview_tree.all_file_ids())

    def test_path2id_deleted_unchanged(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/unchanged', 'tree/deleted'])
        tree.add(['unchanged', 'deleted'], [b'unchanged-id', b'deleted-id'])
        preview = TransformPreview(tree)
        self.addCleanup(preview.finalize)
        preview.unversion_file(preview.trans_id_file_id(b'deleted-id'))
        preview_tree = preview.get_preview_tree()
        self.assertEqual(b'unchanged-id', preview_tree.path2id('unchanged'))
        self.assertFalse(preview_tree.is_versioned('deleted'))

    def test_path2id_created(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/unchanged'])
        tree.add(['unchanged'], [b'unchanged-id'])
        preview = TransformPreview(tree)
        self.addCleanup(preview.finalize)
        preview.new_file('new', preview.trans_id_file_id(b'unchanged-id'),
                         [b'contents'], b'new-id')
        preview_tree = preview.get_preview_tree()
        self.assertEqual(b'new-id', preview_tree.path2id('unchanged/new'))

    def test_path2id_moved(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/old_parent/', 'tree/old_parent/child'])
        tree.add(['old_parent', 'old_parent/child'],
                 [b'old_parent-id', b'child-id'])
        preview = TransformPreview(tree)
        self.addCleanup(preview.finalize)
        new_parent = preview.new_directory('new_parent', preview.root,
                                           b'new_parent-id')
        preview.adjust_path('child', new_parent,
                            preview.trans_id_file_id(b'child-id'))
        preview_tree = preview.get_preview_tree()
        self.assertFalse(preview_tree.is_versioned('old_parent/child'))
        self.assertEqual(b'child-id', preview_tree.path2id('new_parent/child'))

    def test_path2id_renamed_parent(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/old_name/', 'tree/old_name/child'])
        tree.add(['old_name', 'old_name/child'],
                 [b'parent-id', b'child-id'])
        preview = TransformPreview(tree)
        self.addCleanup(preview.finalize)
        preview.adjust_path('new_name', preview.root,
                            preview.trans_id_file_id(b'parent-id'))
        preview_tree = preview.get_preview_tree()
        self.assertFalse(preview_tree.is_versioned('old_name/child'))
        self.assertEqual(b'child-id', preview_tree.path2id('new_name/child'))

    def assertMatchingIterEntries(self, tt, specific_files=None):
        preview_tree = tt.get_preview_tree()
        preview_result = list(preview_tree.iter_entries_by_dir(
                              specific_files=specific_files))
        tree = tt._tree
        tt.apply()
        actual_result = list(tree.iter_entries_by_dir(
            specific_files=specific_files))
        self.assertEqual(actual_result, preview_result)

    def test_iter_entries_by_dir_new(self):
        tree = self.make_branch_and_tree('tree')
        tt = TreeTransform(tree)
        tt.new_file('new', tt.root, [b'contents'], b'new-id')
        self.assertMatchingIterEntries(tt)

    def test_iter_entries_by_dir_deleted(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/deleted'])
        tree.add('deleted', b'deleted-id')
        tt = TreeTransform(tree)
        tt.delete_contents(tt.trans_id_file_id(b'deleted-id'))
        self.assertMatchingIterEntries(tt)

    def test_iter_entries_by_dir_unversioned(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/removed'])
        tree.add('removed', b'removed-id')
        tt = TreeTransform(tree)
        tt.unversion_file(tt.trans_id_file_id(b'removed-id'))
        self.assertMatchingIterEntries(tt)

    def test_iter_entries_by_dir_moved(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/moved', 'tree/new_parent/'])
        tree.add(['moved', 'new_parent'], [b'moved-id', b'new_parent-id'])
        tt = TreeTransform(tree)
        tt.adjust_path('moved', tt.trans_id_file_id(b'new_parent-id'),
                       tt.trans_id_file_id(b'moved-id'))
        self.assertMatchingIterEntries(tt)

    def test_iter_entries_by_dir_specific_files(self):
        tree = self.make_branch_and_tree('tree')
        tree.set_root_id(b'tree-root-id')
        self.build_tree(['tree/parent/', 'tree/parent/child'])
        tree.add(['parent', 'parent/child'], [b'parent-id', b'child-id'])
        tt = TreeTransform(tree)
        self.assertMatchingIterEntries(tt, ['', 'parent/child'])

    def test_symlink_content_summary(self):
        self.requireFeature(SymlinkFeature)
        preview = self.get_empty_preview()
        preview.new_symlink('path', preview.root, 'target', b'path-id')
        summary = preview.get_preview_tree().path_content_summary('path')
        self.assertEqual(('symlink', None, None, 'target'), summary)

    def test_missing_content_summary(self):
        preview = self.get_empty_preview()
        summary = preview.get_preview_tree().path_content_summary('path')
        self.assertEqual(('missing', None, None, None), summary)

    def test_deleted_content_summary(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/path/'])
        tree.add('path')
        preview = TransformPreview(tree)
        self.addCleanup(preview.finalize)
        preview.delete_contents(preview.trans_id_tree_path('path'))
        summary = preview.get_preview_tree().path_content_summary('path')
        self.assertEqual(('missing', None, None, None), summary)

    def test_file_content_summary_executable(self):
        preview = self.get_empty_preview()
        path_id = preview.new_file('path', preview.root, [
                                   b'contents'], b'path-id')
        preview.set_executability(True, path_id)
        summary = preview.get_preview_tree().path_content_summary('path')
        self.assertEqual(4, len(summary))
        self.assertEqual('file', summary[0])
        # size must be known
        self.assertEqual(len('contents'), summary[1])
        # executable
        self.assertEqual(True, summary[2])
        # will not have hash (not cheap to determine)
        self.assertIs(None, summary[3])

    def test_change_executability(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/path'])
        tree.add('path')
        preview = TransformPreview(tree)
        self.addCleanup(preview.finalize)
        path_id = preview.trans_id_tree_path('path')
        preview.set_executability(True, path_id)
        summary = preview.get_preview_tree().path_content_summary('path')
        self.assertEqual(True, summary[2])

    def test_file_content_summary_non_exec(self):
        preview = self.get_empty_preview()
        preview.new_file('path', preview.root, [b'contents'], b'path-id')
        summary = preview.get_preview_tree().path_content_summary('path')
        self.assertEqual(4, len(summary))
        self.assertEqual('file', summary[0])
        # size must be known
        self.assertEqual(len('contents'), summary[1])
        # not executable
        self.assertEqual(False, summary[2])
        # will not have hash (not cheap to determine)
        self.assertIs(None, summary[3])

    def test_dir_content_summary(self):
        preview = self.get_empty_preview()
        preview.new_directory('path', preview.root, b'path-id')
        summary = preview.get_preview_tree().path_content_summary('path')
        self.assertEqual(('directory', None, None, None), summary)

    def test_tree_content_summary(self):
        preview = self.get_empty_preview()
        path = preview.new_directory('path', preview.root, b'path-id')
        preview.set_tree_reference(b'rev-1', path)
        summary = preview.get_preview_tree().path_content_summary('path')
        self.assertEqual(4, len(summary))
        self.assertEqual('tree-reference', summary[0])

    def test_annotate(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', b'a\n')])
        tree.add('file', b'file-id')
        tree.commit('a', rev_id=b'one')
        self.build_tree_contents([('tree/file', b'a\nb\n')])
        preview = TransformPreview(tree)
        self.addCleanup(preview.finalize)
        file_trans_id = preview.trans_id_file_id(b'file-id')
        preview.delete_contents(file_trans_id)
        preview.create_file([b'a\nb\nc\n'], file_trans_id)
        preview_tree = preview.get_preview_tree()
        expected = [
            (b'one', b'a\n'),
            (b'me:', b'b\n'),
            (b'me:', b'c\n'),
        ]
        annotation = preview_tree.annotate_iter(
            'file', default_revision=b'me:')
        self.assertEqual(expected, annotation)

    def test_annotate_missing(self):
        preview = self.get_empty_preview()
        preview.new_file('file', preview.root, [b'a\nb\nc\n'], b'file-id')
        preview_tree = preview.get_preview_tree()
        expected = [
            (b'me:', b'a\n'),
            (b'me:', b'b\n'),
            (b'me:', b'c\n'),
            ]
        annotation = preview_tree.annotate_iter(
            'file', default_revision=b'me:')
        self.assertEqual(expected, annotation)

    def test_annotate_rename(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', b'a\n')])
        tree.add('file', b'file-id')
        tree.commit('a', rev_id=b'one')
        preview = TransformPreview(tree)
        self.addCleanup(preview.finalize)
        file_trans_id = preview.trans_id_file_id(b'file-id')
        preview.adjust_path('newname', preview.root, file_trans_id)
        preview_tree = preview.get_preview_tree()
        expected = [
            (b'one', b'a\n'),
        ]
        annotation = preview_tree.annotate_iter(
            'file', default_revision=b'me:')
        self.assertEqual(expected, annotation)

    def test_annotate_deleted(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', b'a\n')])
        tree.add('file', b'file-id')
        tree.commit('a', rev_id=b'one')
        self.build_tree_contents([('tree/file', b'a\nb\n')])
        preview = TransformPreview(tree)
        self.addCleanup(preview.finalize)
        file_trans_id = preview.trans_id_file_id(b'file-id')
        preview.delete_contents(file_trans_id)
        preview_tree = preview.get_preview_tree()
        annotation = preview_tree.annotate_iter(
            'file', default_revision=b'me:')
        self.assertIs(None, annotation)

    def test_stored_kind(self):
        preview = self.get_empty_preview()
        preview.new_file('file', preview.root, [b'a\nb\nc\n'], b'file-id')
        preview_tree = preview.get_preview_tree()
        self.assertEqual('file', preview_tree.stored_kind('file'))

    def test_is_executable(self):
        preview = self.get_empty_preview()
        preview.new_file('file', preview.root, [b'a\nb\nc\n'], b'file-id')
        preview.set_executability(True, preview.trans_id_file_id(b'file-id'))
        preview_tree = preview.get_preview_tree()
        self.assertEqual(True, preview_tree.is_executable('file'))

    def test_get_set_parent_ids(self):
        revision_tree, preview_tree = self.get_tree_and_preview_tree()
        self.assertEqual([], preview_tree.get_parent_ids())
        preview_tree.set_parent_ids([b'rev-1'])
        self.assertEqual([b'rev-1'], preview_tree.get_parent_ids())

    def test_plan_file_merge(self):
        work_a = self.make_branch_and_tree('wta')
        self.build_tree_contents([('wta/file', b'a\nb\nc\nd\n')])
        work_a.add('file', b'file-id')
        base_id = work_a.commit('base version')
        tree_b = work_a.controldir.sprout('wtb').open_workingtree()
        preview = TransformPreview(work_a)
        self.addCleanup(preview.finalize)
        trans_id = preview.trans_id_file_id(b'file-id')
        preview.delete_contents(trans_id)
        preview.create_file([b'b\nc\nd\ne\n'], trans_id)
        self.build_tree_contents([('wtb/file', b'a\nc\nd\nf\n')])
        tree_a = preview.get_preview_tree()
        tree_a.set_parent_ids([base_id])
        self.assertEqual([
            ('killed-a', b'a\n'),
            ('killed-b', b'b\n'),
            ('unchanged', b'c\n'),
            ('unchanged', b'd\n'),
            ('new-a', b'e\n'),
            ('new-b', b'f\n'),
        ], list(tree_a.plan_file_merge(b'file-id', tree_b)))

    def test_plan_file_merge_revision_tree(self):
        work_a = self.make_branch_and_tree('wta')
        self.build_tree_contents([('wta/file', b'a\nb\nc\nd\n')])
        work_a.add('file', b'file-id')
        base_id = work_a.commit('base version')
        tree_b = work_a.controldir.sprout('wtb').open_workingtree()
        preview = TransformPreview(work_a.basis_tree())
        self.addCleanup(preview.finalize)
        trans_id = preview.trans_id_file_id(b'file-id')
        preview.delete_contents(trans_id)
        preview.create_file([b'b\nc\nd\ne\n'], trans_id)
        self.build_tree_contents([('wtb/file', b'a\nc\nd\nf\n')])
        tree_a = preview.get_preview_tree()
        tree_a.set_parent_ids([base_id])
        self.assertEqual([
            ('killed-a', b'a\n'),
            ('killed-b', b'b\n'),
            ('unchanged', b'c\n'),
            ('unchanged', b'd\n'),
            ('new-a', b'e\n'),
            ('new-b', b'f\n'),
        ], list(tree_a.plan_file_merge(b'file-id', tree_b)))

    def test_walkdirs(self):
        preview = self.get_empty_preview()
        preview.new_directory('', ROOT_PARENT, b'tree-root')
        # FIXME: new_directory should mark root.
        preview.fixup_new_roots()
        preview_tree = preview.get_preview_tree()
        preview.new_file('a', preview.root, [b'contents'], b'a-id')
        expected = [(('', b'tree-root'),
                     [('a', 'a', 'file', None, b'a-id', 'file')])]
        self.assertEqual(expected, list(preview_tree.walkdirs()))

    def test_extras(self):
        work_tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/removed-file', 'tree/existing-file',
                         'tree/not-removed-file'])
        work_tree.add(['removed-file', 'not-removed-file'])
        preview = TransformPreview(work_tree)
        self.addCleanup(preview.finalize)
        preview.new_file('new-file', preview.root, [b'contents'])
        preview.new_file('new-versioned-file', preview.root, [b'contents'],
                         b'new-versioned-id')
        tree = preview.get_preview_tree()
        preview.unversion_file(preview.trans_id_tree_path('removed-file'))
        self.assertEqual({'new-file', 'removed-file', 'existing-file'},
                         set(tree.extras()))

    def test_merge_into_preview(self):
        work_tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', b'b\n')])
        work_tree.add('file', b'file-id')
        work_tree.commit('first commit')
        child_tree = work_tree.controldir.sprout('child').open_workingtree()
        self.build_tree_contents([('child/file', b'b\nc\n')])
        child_tree.commit('child commit')
        child_tree.lock_write()
        self.addCleanup(child_tree.unlock)
        work_tree.lock_write()
        self.addCleanup(work_tree.unlock)
        preview = TransformPreview(work_tree)
        self.addCleanup(preview.finalize)
        file_trans_id = preview.trans_id_file_id(b'file-id')
        preview.delete_contents(file_trans_id)
        preview.create_file([b'a\nb\n'], file_trans_id)
        preview_tree = preview.get_preview_tree()
        merger = Merger.from_revision_ids(preview_tree,
                                          child_tree.branch.last_revision(),
                                          other_branch=child_tree.branch,
                                          tree_branch=work_tree.branch)
        merger.merge_type = Merge3Merger
        tt = merger.make_merger().make_preview_transform()
        self.addCleanup(tt.finalize)
        final_tree = tt.get_preview_tree()
        self.assertEqual(
            b'a\nb\nc\n',
            final_tree.get_file_text(final_tree.id2path(b'file-id')))

    def test_merge_preview_into_workingtree(self):
        tree = self.make_branch_and_tree('tree')
        tree.set_root_id(b'TREE_ROOT')
        tt = TransformPreview(tree)
        self.addCleanup(tt.finalize)
        tt.new_file('name', tt.root, [b'content'], b'file-id')
        tree2 = self.make_branch_and_tree('tree2')
        tree2.set_root_id(b'TREE_ROOT')
        merger = Merger.from_uncommitted(tree2, tt.get_preview_tree(),
                                         tree.basis_tree())
        merger.merge_type = Merge3Merger
        merger.do_merge()

    def test_merge_preview_into_workingtree_handles_conflicts(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/foo', b'bar')])
        tree.add('foo', b'foo-id')
        tree.commit('foo')
        tt = TransformPreview(tree)
        self.addCleanup(tt.finalize)
        trans_id = tt.trans_id_file_id(b'foo-id')
        tt.delete_contents(trans_id)
        tt.create_file([b'baz'], trans_id)
        tree2 = tree.controldir.sprout('tree2').open_workingtree()
        self.build_tree_contents([('tree2/foo', b'qux')])
        merger = Merger.from_uncommitted(tree2, tt.get_preview_tree(),
                                         tree.basis_tree())
        merger.merge_type = Merge3Merger
        merger.do_merge()

    def test_has_filename(self):
        wt = self.make_branch_and_tree('tree')
        self.build_tree(['tree/unmodified', 'tree/removed', 'tree/modified'])
        tt = TransformPreview(wt)
        removed_id = tt.trans_id_tree_path('removed')
        tt.delete_contents(removed_id)
        tt.new_file('new', tt.root, [b'contents'])
        modified_id = tt.trans_id_tree_path('modified')
        tt.delete_contents(modified_id)
        tt.create_file([b'modified-contents'], modified_id)
        self.addCleanup(tt.finalize)
        tree = tt.get_preview_tree()
        self.assertTrue(tree.has_filename('unmodified'))
        self.assertFalse(tree.has_filename('not-present'))
        self.assertFalse(tree.has_filename('removed'))
        self.assertTrue(tree.has_filename('new'))
        self.assertTrue(tree.has_filename('modified'))

    def test_is_executable(self):
        tree = self.make_branch_and_tree('tree')
        preview = TransformPreview(tree)
        self.addCleanup(preview.finalize)
        preview.new_file('foo', preview.root, [b'bar'], b'baz-id')
        preview_tree = preview.get_preview_tree()
        self.assertEqual(False, preview_tree.is_executable('tree/foo'))

    def test_commit_preview_tree(self):
        tree = self.make_branch_and_tree('tree')
        rev_id = tree.commit('rev1')
        tree.branch.lock_write()
        self.addCleanup(tree.branch.unlock)
        tt = TransformPreview(tree)
        tt.new_file('file', tt.root, [b'contents'], b'file_id')
        self.addCleanup(tt.finalize)
        preview = tt.get_preview_tree()
        preview.set_parent_ids([rev_id])
        builder = tree.branch.get_commit_builder([rev_id])
        list(builder.record_iter_changes(preview, rev_id, tt.iter_changes()))
        builder.finish_inventory()
        rev2_id = builder.commit('rev2')
        rev2_tree = tree.branch.repository.revision_tree(rev2_id)
        self.assertEqual(b'contents', rev2_tree.get_file_text('file'))

    def test_ascii_limbo_paths(self):
        self.requireFeature(features.UnicodeFilenameFeature)
        branch = self.make_branch('any')
        tree = branch.repository.revision_tree(_mod_revision.NULL_REVISION)
        tt = TransformPreview(tree)
        self.addCleanup(tt.finalize)
        foo_id = tt.new_directory('', ROOT_PARENT)
        bar_id = tt.new_file(u'\u1234bar', foo_id, [b'contents'])
        limbo_path = tt._limbo_name(bar_id)
        self.assertEqual(limbo_path, limbo_path)


class FakeSerializer(object):
    """Serializer implementation that simply returns the input.

    The input is returned in the order used by pack.ContainerPushParser.
    """
    @staticmethod
    def bytes_record(bytes, names):
        return names, bytes


class TestSerializeTransform(tests.TestCaseWithTransport):

    _test_needs_features = [features.UnicodeFilenameFeature]

    def get_preview(self, tree=None):
        if tree is None:
            tree = self.make_branch_and_tree('tree')
        tt = TransformPreview(tree)
        self.addCleanup(tt.finalize)
        return tt

    def assertSerializesTo(self, expected, tt):
        records = list(tt.serialize(FakeSerializer()))
        self.assertEqual(expected, records)

    @staticmethod
    def default_attribs():
        return {
            b'_id_number': 1,
            b'_new_name': {},
            b'_new_parent': {},
            b'_new_executability': {},
            b'_new_id': {},
            b'_tree_path_ids': {b'': b'new-0'},
            b'_removed_id': [],
            b'_removed_contents': [],
            b'_non_present_ids': {},
            }

    def make_records(self, attribs, contents):
        records = [
            ((((b'attribs'),),), bencode.bencode(attribs))]
        records.extend([(((n, k),), c) for n, k, c in contents])
        return records

    def creation_records(self):
        attribs = self.default_attribs()
        attribs[b'_id_number'] = 3
        attribs[b'_new_name'] = {
            b'new-1': u'foo\u1234'.encode('utf-8'), b'new-2': b'qux'}
        attribs[b'_new_id'] = {b'new-1': b'baz', b'new-2': b'quxx'}
        attribs[b'_new_parent'] = {b'new-1': b'new-0', b'new-2': b'new-0'}
        attribs[b'_new_executability'] = {b'new-1': 1}
        contents = [
            (b'new-1', b'file', b'i 1\nbar\n'),
            (b'new-2', b'directory', b''),
            ]
        return self.make_records(attribs, contents)

    def test_serialize_creation(self):
        tt = self.get_preview()
        tt.new_file(u'foo\u1234', tt.root, [b'bar'], b'baz', True)
        tt.new_directory('qux', tt.root, b'quxx')
        self.assertSerializesTo(self.creation_records(), tt)

    def test_deserialize_creation(self):
        tt = self.get_preview()
        tt.deserialize(iter(self.creation_records()))
        self.assertEqual(3, tt._id_number)
        self.assertEqual({'new-1': u'foo\u1234',
                          'new-2': 'qux'}, tt._new_name)
        self.assertEqual({'new-1': b'baz', 'new-2': b'quxx'}, tt._new_id)
        self.assertEqual({'new-1': tt.root, 'new-2': tt.root}, tt._new_parent)
        self.assertEqual({b'baz': 'new-1', b'quxx': 'new-2'}, tt._r_new_id)
        self.assertEqual({'new-1': True}, tt._new_executability)
        self.assertEqual({'new-1': 'file',
                          'new-2': 'directory'}, tt._new_contents)
        foo_limbo = open(tt._limbo_name('new-1'), 'rb')
        try:
            foo_content = foo_limbo.read()
        finally:
            foo_limbo.close()
        self.assertEqual(b'bar', foo_content)

    def symlink_creation_records(self):
        attribs = self.default_attribs()
        attribs[b'_id_number'] = 2
        attribs[b'_new_name'] = {b'new-1': u'foo\u1234'.encode('utf-8')}
        attribs[b'_new_parent'] = {b'new-1': b'new-0'}
        contents = [(b'new-1', b'symlink', u'bar\u1234'.encode('utf-8'))]
        return self.make_records(attribs, contents)

    def test_serialize_symlink_creation(self):
        self.requireFeature(features.SymlinkFeature)
        tt = self.get_preview()
        tt.new_symlink(u'foo\u1234', tt.root, u'bar\u1234')
        self.assertSerializesTo(self.symlink_creation_records(), tt)

    def test_deserialize_symlink_creation(self):
        self.requireFeature(features.SymlinkFeature)
        tt = self.get_preview()
        tt.deserialize(iter(self.symlink_creation_records()))
        abspath = tt._limbo_name('new-1')
        foo_content = osutils.readlink(abspath)
        self.assertEqual(u'bar\u1234', foo_content)

    def make_destruction_preview(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree([u'foo\u1234', 'bar'])
        tree.add([u'foo\u1234', 'bar'], [b'foo-id', b'bar-id'])
        return self.get_preview(tree)

    def destruction_records(self):
        attribs = self.default_attribs()
        attribs[b'_id_number'] = 3
        attribs[b'_removed_id'] = [b'new-1']
        attribs[b'_removed_contents'] = [b'new-2']
        attribs[b'_tree_path_ids'] = {
            b'': b'new-0',
            u'foo\u1234'.encode('utf-8'): b'new-1',
            b'bar': b'new-2',
            }
        return self.make_records(attribs, [])

    def test_serialize_destruction(self):
        tt = self.make_destruction_preview()
        foo_trans_id = tt.trans_id_tree_path(u'foo\u1234')
        tt.unversion_file(foo_trans_id)
        bar_trans_id = tt.trans_id_tree_path('bar')
        tt.delete_contents(bar_trans_id)
        self.assertSerializesTo(self.destruction_records(), tt)

    def test_deserialize_destruction(self):
        tt = self.make_destruction_preview()
        tt.deserialize(iter(self.destruction_records()))
        self.assertEqual({u'foo\u1234': 'new-1',
                          'bar': 'new-2',
                          '': tt.root}, tt._tree_path_ids)
        self.assertEqual({'new-1': u'foo\u1234',
                          'new-2': 'bar',
                          tt.root: ''}, tt._tree_id_paths)
        self.assertEqual({'new-1'}, tt._removed_id)
        self.assertEqual({'new-2'}, tt._removed_contents)

    def missing_records(self):
        attribs = self.default_attribs()
        attribs[b'_id_number'] = 2
        attribs[b'_non_present_ids'] = {
            b'boo': b'new-1', }
        return self.make_records(attribs, [])

    def test_serialize_missing(self):
        tt = self.get_preview()
        tt.trans_id_file_id(b'boo')
        self.assertSerializesTo(self.missing_records(), tt)

    def test_deserialize_missing(self):
        tt = self.get_preview()
        tt.deserialize(iter(self.missing_records()))
        self.assertEqual({b'boo': 'new-1'}, tt._non_present_ids)

    def make_modification_preview(self):
        LINES_ONE = b'aa\nbb\ncc\ndd\n'
        LINES_TWO = b'z\nbb\nx\ndd\n'
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', LINES_ONE)])
        tree.add('file', b'file-id')
        return self.get_preview(tree), [LINES_TWO]

    def modification_records(self):
        attribs = self.default_attribs()
        attribs[b'_id_number'] = 2
        attribs[b'_tree_path_ids'] = {
            b'file': b'new-1',
            b'': b'new-0', }
        attribs[b'_removed_contents'] = [b'new-1']
        contents = [(b'new-1', b'file',
                     b'i 1\nz\n\nc 0 1 1 1\ni 1\nx\n\nc 0 3 3 1\n')]
        return self.make_records(attribs, contents)

    def test_serialize_modification(self):
        tt, LINES = self.make_modification_preview()
        trans_id = tt.trans_id_file_id(b'file-id')
        tt.delete_contents(trans_id)
        tt.create_file(LINES, trans_id)
        self.assertSerializesTo(self.modification_records(), tt)

    def test_deserialize_modification(self):
        tt, LINES = self.make_modification_preview()
        tt.deserialize(iter(self.modification_records()))
        self.assertFileEqual(b''.join(LINES), tt._limbo_name('new-1'))

    def make_kind_change_preview(self):
        LINES = b'a\nb\nc\nd\n'
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo/'])
        tree.add('foo', b'foo-id')
        return self.get_preview(tree), [LINES]

    def kind_change_records(self):
        attribs = self.default_attribs()
        attribs[b'_id_number'] = 2
        attribs[b'_tree_path_ids'] = {
            b'foo': b'new-1',
            b'': b'new-0', }
        attribs[b'_removed_contents'] = [b'new-1']
        contents = [(b'new-1', b'file',
                     b'i 4\na\nb\nc\nd\n\n')]
        return self.make_records(attribs, contents)

    def test_serialize_kind_change(self):
        tt, LINES = self.make_kind_change_preview()
        trans_id = tt.trans_id_file_id(b'foo-id')
        tt.delete_contents(trans_id)
        tt.create_file(LINES, trans_id)
        self.assertSerializesTo(self.kind_change_records(), tt)

    def test_deserialize_kind_change(self):
        tt, LINES = self.make_kind_change_preview()
        tt.deserialize(iter(self.kind_change_records()))
        self.assertFileEqual(b''.join(LINES), tt._limbo_name('new-1'))

    def make_add_contents_preview(self):
        LINES = b'a\nb\nc\nd\n'
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo'])
        tree.add('foo')
        os.unlink('tree/foo')
        return self.get_preview(tree), LINES

    def add_contents_records(self):
        attribs = self.default_attribs()
        attribs[b'_id_number'] = 2
        attribs[b'_tree_path_ids'] = {
            b'foo': b'new-1',
            b'': b'new-0', }
        contents = [(b'new-1', b'file',
                     b'i 4\na\nb\nc\nd\n\n')]
        return self.make_records(attribs, contents)

    def test_serialize_add_contents(self):
        tt, LINES = self.make_add_contents_preview()
        trans_id = tt.trans_id_tree_path('foo')
        tt.create_file([LINES], trans_id)
        self.assertSerializesTo(self.add_contents_records(), tt)

    def test_deserialize_add_contents(self):
        tt, LINES = self.make_add_contents_preview()
        tt.deserialize(iter(self.add_contents_records()))
        self.assertFileEqual(LINES, tt._limbo_name('new-1'))

    def test_get_parents_lines(self):
        LINES_ONE = b'aa\nbb\ncc\ndd\n'
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', LINES_ONE)])
        tree.add('file', b'file-id')
        tt = self.get_preview(tree)
        trans_id = tt.trans_id_tree_path('file')
        self.assertEqual(([b'aa\n', b'bb\n', b'cc\n', b'dd\n'],),
                         tt._get_parents_lines(trans_id))

    def test_get_parents_texts(self):
        LINES_ONE = b'aa\nbb\ncc\ndd\n'
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file', LINES_ONE)])
        tree.add('file', b'file-id')
        tt = self.get_preview(tree)
        trans_id = tt.trans_id_tree_path('file')
        self.assertEqual((LINES_ONE,),
                         tt._get_parents_texts(trans_id))


class TestOrphan(tests.TestCaseWithTransport):

    def test_no_orphan_for_transform_preview(self):
        tree = self.make_branch_and_tree('tree')
        tt = transform.TransformPreview(tree)
        self.addCleanup(tt.finalize)
        self.assertRaises(NotImplementedError, tt.new_orphan, 'foo', 'bar')

    def _set_orphan_policy(self, wt, policy):
        wt.branch.get_config_stack().set('transform.orphan_policy',
                                         policy)

    def _prepare_orphan(self, wt):
        self.build_tree(['dir/', 'dir/file', 'dir/foo'])
        wt.add(['dir', 'dir/file'], [b'dir-id', b'file-id'])
        wt.commit('add dir and file ignoring foo')
        tt = transform.TreeTransform(wt)
        self.addCleanup(tt.finalize)
        # dir and bar are deleted
        dir_tid = tt.trans_id_tree_path('dir')
        file_tid = tt.trans_id_tree_path('dir/file')
        orphan_tid = tt.trans_id_tree_path('dir/foo')
        tt.delete_contents(file_tid)
        tt.unversion_file(file_tid)
        tt.delete_contents(dir_tid)
        tt.unversion_file(dir_tid)
        # There should be a conflict because dir still contain foo
        raw_conflicts = tt.find_conflicts()
        self.assertLength(1, raw_conflicts)
        self.assertEqual(('missing parent', 'new-1'), raw_conflicts[0])
        return tt, orphan_tid

    def test_new_orphan_created(self):
        wt = self.make_branch_and_tree('.')
        self._set_orphan_policy(wt, 'move')
        tt, orphan_tid = self._prepare_orphan(wt)
        warnings = []

        def warning(*args):
            warnings.append(args[0] % args[1:])
        self.overrideAttr(trace, 'warning', warning)
        remaining_conflicts = resolve_conflicts(tt)
        self.assertEqual(['dir/foo has been orphaned in brz-orphans'],
                         warnings)
        # Yeah for resolved conflicts !
        self.assertLength(0, remaining_conflicts)
        # We have a new orphan
        self.assertEqual('foo.~1~', tt.final_name(orphan_tid))
        self.assertEqual('brz-orphans',
                         tt.final_name(tt.final_parent(orphan_tid)))

    def test_never_orphan(self):
        wt = self.make_branch_and_tree('.')
        self._set_orphan_policy(wt, 'conflict')
        tt, orphan_tid = self._prepare_orphan(wt)
        remaining_conflicts = resolve_conflicts(tt)
        self.assertLength(1, remaining_conflicts)
        self.assertEqual(('deleting parent', 'Not deleting', 'new-1'),
                         remaining_conflicts.pop())

    def test_orphan_error(self):
        def bogus_orphan(tt, orphan_id, parent_id):
            raise transform.OrphaningError(tt.final_name(orphan_id),
                                           tt.final_name(parent_id))
        transform.orphaning_registry.register('bogus', bogus_orphan,
                                              'Raise an error when orphaning')
        wt = self.make_branch_and_tree('.')
        self._set_orphan_policy(wt, 'bogus')
        tt, orphan_tid = self._prepare_orphan(wt)
        remaining_conflicts = resolve_conflicts(tt)
        self.assertLength(1, remaining_conflicts)
        self.assertEqual(('deleting parent', 'Not deleting', 'new-1'),
                         remaining_conflicts.pop())

    def test_unknown_orphan_policy(self):
        wt = self.make_branch_and_tree('.')
        # Set a fictional policy nobody ever implemented
        self._set_orphan_policy(wt, 'donttouchmypreciouuus')
        tt, orphan_tid = self._prepare_orphan(wt)
        warnings = []

        def warning(*args):
            warnings.append(args[0] % args[1:])
        self.overrideAttr(trace, 'warning', warning)
        remaining_conflicts = resolve_conflicts(tt)
        # We fallback to the default policy which create a conflict
        self.assertLength(1, remaining_conflicts)
        self.assertEqual(('deleting parent', 'Not deleting', 'new-1'),
                         remaining_conflicts.pop())
        self.assertLength(1, warnings)
        self.assertStartsWith(warnings[0], 'Value "donttouchmypreciouuus" ')


class TestTransformHooks(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestTransformHooks, self).setUp()
        self.wt = self.make_branch_and_tree('.')
        os.chdir('..')

    def get_transform(self):
        transform = TreeTransform(self.wt)
        self.addCleanup(transform.finalize)
        return transform, transform.root

    def test_pre_commit_hooks(self):
        calls = []

        def record_pre_transform(tree, tt):
            calls.append((tree, tt))
        MutableTree.hooks.install_named_hook(
            'pre_transform', record_pre_transform, "Pre transform")
        transform, root = self.get_transform()
        old_root_id = transform.tree_file_id(root)
        transform.apply()
        self.assertEqual(old_root_id, self.wt.get_root_id())
        self.assertEqual([(self.wt, transform)], calls)

    def test_post_commit_hooks(self):
        calls = []

        def record_post_transform(tree, tt):
            calls.append((tree, tt))
        MutableTree.hooks.install_named_hook(
            'post_transform', record_post_transform, "Post transform")
        transform, root = self.get_transform()
        old_root_id = transform.tree_file_id(root)
        transform.apply()
        self.assertEqual(old_root_id, self.wt.get_root_id())
        self.assertEqual([(self.wt, transform)], calls)


class TestLinkTree(tests.TestCaseWithTransport):

    _test_needs_features = [HardlinkFeature]

    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)
        self.parent_tree = self.make_branch_and_tree('parent')
        self.parent_tree.lock_write()
        self.addCleanup(self.parent_tree.unlock)
        self.build_tree_contents([('parent/foo', b'bar')])
        self.parent_tree.add('foo')
        self.parent_tree.commit('added foo')
        child_controldir = self.parent_tree.controldir.sprout('child')
        self.child_tree = child_controldir.open_workingtree()

    def hardlinked(self):
        parent_stat = os.lstat(self.parent_tree.abspath('foo'))
        child_stat = os.lstat(self.child_tree.abspath('foo'))
        return parent_stat.st_ino == child_stat.st_ino

    def test_link_fails_if_modified(self):
        """If the file to be linked has modified text, don't link."""
        self.build_tree_contents([('child/foo', b'baz')])
        transform.link_tree(self.child_tree, self.parent_tree)
        self.assertFalse(self.hardlinked())

    def test_link_fails_if_execute_bit_changed(self):
        """If the file to be linked has modified execute bit, don't link."""
        tt = TreeTransform(self.child_tree)
        try:
            trans_id = tt.trans_id_tree_path('foo')
            tt.set_executability(True, trans_id)
            tt.apply()
        finally:
            tt.finalize()
        transform.link_tree(self.child_tree, self.parent_tree)
        self.assertFalse(self.hardlinked())

    def test_link_succeeds_if_unmodified(self):
        """If the file to be linked is unmodified, link"""
        transform.link_tree(self.child_tree, self.parent_tree)
        self.assertTrue(self.hardlinked())

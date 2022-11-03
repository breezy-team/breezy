# Copyright (C) 2006-2012, 2016 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
#           and others
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
from io import StringIO
import os

from ... import (
    branch as _mod_branch,
    config,
    controldir,
    errors,
    merge,
    osutils,
    revision as _mod_revision,
    tests,
    trace,
    transport as _mod_transport,
    urlutils,
    )
from ...bzr import (
    bzrdir,
    )
from ...errors import (
    UnsupportedOperation,
    PathsNotVersionedError,
    )
from ...bzr.inventory import Inventory
from ...mutabletree import MutableTree
from ...osutils import pathjoin, getcwd, supports_symlinks
from .. import (
    features,
    TestSkipped,
    TestNotApplicable,
    )
from . import TestCaseWithWorkingTree
from ...bzr.workingtree import (
    InventoryWorkingTree,
    )
from ...tree import (
    TreeDirectory,
    TreeFile,
    TreeLink,
    )
from ...bzr.conflicts import ConflictList, TextConflict, ContentsConflict
from ...workingtree import (
    SettingFileIdUnsupported,
    WorkingTree,
    )


class TestWorkingTree(TestCaseWithWorkingTree):

    def requireBranchReference(self):
        test_branch = self.make_branch('test-branch')
        try:
            # if there is a working tree now, this is not supported.
            test_branch.controldir.open_workingtree()
            raise TestNotApplicable("only on trees that can be separate"
                                    " from their branch.")
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            pass

    def test_branch_builder(self):
        # Just a smoke test that we get a branch at the specified relpath
        builder = self.make_branch_builder('foobar')
        br = _mod_branch.Branch.open(self.get_url('foobar'))

    def test_list_files(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'file'])
        if supports_symlinks(self.test_dir):
            os.symlink('target', 'symlink')
        tree.lock_read()
        files = list(tree.list_files())
        tree.unlock()
        self.assertEqual(
            files.pop(0), ('dir', '?', 'directory', TreeDirectory()))
        self.assertEqual(files.pop(0), ('file', '?', 'file', TreeFile()))
        if supports_symlinks(self.test_dir):
            self.assertEqual(
                files.pop(0), ('symlink', '?', 'symlink', TreeLink()))

    def test_list_files_sorted(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'file', 'dir/file', 'dir/b',
                         'dir/subdir/', 'a', 'dir/subfile',
                         'zz_dir/', 'zz_dir/subfile'])
        with tree.lock_read():
            files = [(path, kind) for (path, v, kind, entry)
                     in tree.list_files()]
        self.assertEqual([
            ('a', 'file'),
            ('dir', 'directory'),
            ('file', 'file'),
            ('zz_dir', 'directory'),
            ], files)

        with tree.lock_write():
            if tree.has_versioned_directories():
                tree.add(['dir', 'zz_dir'])
                files = [(path, kind) for (path, v, kind, entry)
                         in tree.list_files()]
                self.assertEqual([
                    ('a', 'file'),
                    ('dir', 'directory'),
                    ('dir/b', 'file'),
                    ('dir/file', 'file'),
                    ('dir/subdir', 'directory'),
                    ('dir/subfile', 'file'),
                    ('file', 'file'),
                    ('zz_dir', 'directory'),
                    ('zz_dir/subfile', 'file'),
                    ], files)
            else:
                tree.add(['dir/b'])
                files = [(path, kind) for (path, v, kind, entry)
                         in tree.list_files()]
                self.assertEqual([
                    ('a', 'file'),
                    ('dir', 'directory'),
                    ('dir/b', 'file'),
                    ('dir/file', 'file'),
                    ('dir/subdir', 'directory'),
                    ('dir/subfile', 'file'),
                    ('file', 'file'),
                    ('zz_dir', 'directory'),
                    ], files)

    def test_transform(self):
        tree = self.make_branch_and_tree('tree')
        with tree.transform():
            pass

    def test_list_files_kind_change(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/filename'])
        tree.add('filename')
        os.unlink('tree/filename')
        self.build_tree(['tree/filename/'])
        tree.lock_read()
        self.addCleanup(tree.unlock)
        result = list(tree.list_files())
        self.assertEqual(1, len(result))
        if tree.has_versioned_directories():
            self.assertEqual(
                ('filename', 'V', 'directory'),
                (result[0][0], result[0][1], result[0][2]))
        else:
            self.assertEqual(
                ('filename', '?', 'directory'),
                (result[0][0], result[0][1], result[0][2]))

    def test_get_config_stack(self):
        # Smoke test that all working trees succeed getting a config
        wt = self.make_branch_and_tree('.')
        conf = wt.get_config_stack()
        self.assertIsInstance(conf, config.Stack)

    def test_open_containing(self):
        local_wt = self.make_branch_and_tree('.')
        local_url = local_wt.controldir.root_transport.base
        local_base = urlutils.local_path_from_url(local_url)
        del local_wt

        # Empty opens '.'
        wt, relpath = WorkingTree.open_containing()
        self.assertEqual('', relpath)
        self.assertEqual(wt.basedir + '/', local_base)

        # '.' opens this dir
        wt, relpath = WorkingTree.open_containing(u'.')
        self.assertEqual('', relpath)
        self.assertEqual(wt.basedir + '/', local_base)

        # './foo' finds '.' and a relpath of 'foo'
        wt, relpath = WorkingTree.open_containing('./foo')
        self.assertEqual('foo', relpath)
        self.assertEqual(wt.basedir + '/', local_base)

        # abspath(foo) finds '.' and relpath of 'foo'
        wt, relpath = WorkingTree.open_containing('./foo')
        wt, relpath = WorkingTree.open_containing(getcwd() + '/foo')
        self.assertEqual('foo', relpath)
        self.assertEqual(wt.basedir + '/', local_base)

        # can even be a url: finds '.' and relpath of 'foo'
        wt, relpath = WorkingTree.open_containing('./foo')
        wt, relpath = WorkingTree.open_containing(
            urlutils.local_path_to_url(getcwd() + '/foo'))
        self.assertEqual('foo', relpath)
        self.assertEqual(wt.basedir + '/', local_base)

    def test_basic_relpath(self):
        # for comprehensive relpath tests, see whitebox.py.
        tree = self.make_branch_and_tree('.')
        self.assertEqual('child',
                         tree.relpath(pathjoin(getcwd(), 'child')))

    def test_lock_locks_branch(self):
        tree = self.make_branch_and_tree('.')
        self.assertEqual(None, tree.branch.peek_lock_mode())
        with tree.lock_read():
            self.assertEqual('r', tree.branch.peek_lock_mode())
        self.assertEqual(None, tree.branch.peek_lock_mode())
        with tree.lock_write():
            self.assertEqual('w', tree.branch.peek_lock_mode())
        self.assertEqual(None, tree.branch.peek_lock_mode())

    def test_revert(self):
        """Test selected-file revert"""
        tree = self.make_branch_and_tree('.')

        self.build_tree(['hello.txt'])
        with open('hello.txt', 'w') as f:
            f.write('initial hello')

        self.assertRaises(PathsNotVersionedError,
                          tree.revert, ['hello.txt'])
        tree.add(['hello.txt'])
        tree.commit('create initial hello.txt')

        self.check_file_contents('hello.txt', b'initial hello')
        with open('hello.txt', 'w') as f:
            f.write('new hello')
        self.check_file_contents('hello.txt', b'new hello')

        # revert file modified since last revision
        tree.revert(['hello.txt'])
        self.check_file_contents('hello.txt', b'initial hello')
        self.check_file_contents('hello.txt.~1~', b'new hello')

        # reverting again does not clobber the backup
        tree.revert(['hello.txt'])
        self.check_file_contents('hello.txt', b'initial hello')
        self.check_file_contents('hello.txt.~1~', b'new hello')

        # backup files are numbered
        with open('hello.txt', 'w') as f:
            f.write('new hello2')
        tree.revert(['hello.txt'])
        self.check_file_contents('hello.txt', b'initial hello')
        self.check_file_contents('hello.txt.~1~', b'new hello')
        self.check_file_contents('hello.txt.~2~', b'new hello2')

    def test_revert_missing(self):
        # Revert a file that has been deleted since last commit
        tree = self.make_branch_and_tree('.')
        with open('hello.txt', 'w') as f:
            f.write('initial hello')
        tree.add('hello.txt')
        tree.commit('added hello.txt')
        os.unlink('hello.txt')
        tree.remove('hello.txt')
        tree.revert(['hello.txt'])
        self.assertPathExists('hello.txt')

    def test_versioned_files_not_unknown(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['hello.txt'])
        tree.add('hello.txt')
        self.assertEqual(list(tree.unknowns()),
                         [])

    def test_unknowns(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['hello.txt',
                         'hello.txt.~1~'])
        self.build_tree_contents([('.bzrignore', b'*.~*\n')])
        tree.add('.bzrignore')
        self.assertEqual(list(tree.unknowns()),
                         ['hello.txt'])

    def test_unknowns_empty_dir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['subdir/', 'subdir/somefile'])
        if tree.has_versioned_directories():
            self.assertEqual(list(tree.unknowns()), ['subdir'])
        else:
            self.assertEqual(list(tree.unknowns()), ['subdir/somefile'])

    def test_initialize(self):
        # initialize should create a working tree and branch in an existing dir
        t = self.make_branch_and_tree('.')
        b = _mod_branch.Branch.open('.')
        self.assertEqual(t.branch.base, b.base)
        t2 = WorkingTree.open('.')
        self.assertEqual(t.basedir, t2.basedir)
        self.assertEqual(b.base, t2.branch.base)
        # TODO maybe we should check the branch format? not sure if its
        # appropriate here.

    def test_rename_dirs(self):
        """Test renaming directories and the files within them."""
        wt = self.make_branch_and_tree('.')
        b = wt.branch
        self.build_tree(['dir/', 'dir/sub/', 'dir/sub/file'])
        wt.add(['dir', 'dir/sub', 'dir/sub/file'])

        wt.commit('create initial state')

        revid = b.last_revision()
        self.log('first revision_id is {%s}' % revid)

        tree = b.repository.revision_tree(revid)
        self.log('contents of tree: %r' % list(tree.iter_entries_by_dir()))

        self.check_tree_shape(tree, ['dir/', 'dir/sub/', 'dir/sub/file'])
        wt.rename_one('dir', 'newdir')

        wt.lock_read()
        self.check_tree_shape(wt,
                              ['newdir/', 'newdir/sub/', 'newdir/sub/file'])
        wt.unlock()
        wt.rename_one('newdir/sub', 'newdir/newsub')
        wt.lock_read()
        self.check_tree_shape(wt, ['newdir/', 'newdir/newsub/',
                                   'newdir/newsub/file'])
        wt.unlock()

    def test_add_in_unversioned(self):
        """Try to add a file in an unversioned directory.

        "bzr add" adds the parent as necessary, but simple working tree add
        doesn't do that.
        """
        from breezy.errors import NotVersionedError
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo/',
                         'foo/hello'])
        if not wt._format.supports_versioned_directories:
            wt.add('foo/hello')
        else:
            self.assertRaises(NotVersionedError,
                              wt.add,
                              'foo/hello')

    def test_add_missing(self):
        # adding a msising file -> NoSuchFile
        wt = self.make_branch_and_tree('.')
        self.assertRaises(_mod_transport.NoSuchFile, wt.add, 'fpp')

    def test_remove_verbose(self):
        # FIXME the remove api should not print or otherwise depend on the
        # text UI - RBC 20060124
        wt = self.make_branch_and_tree('.')
        self.build_tree(['hello'])
        wt.add(['hello'])
        wt.commit(message='add hello')
        stdout = StringIO()
        stderr = StringIO()
        self.assertEqual(None, self.apply_redirected(None, stdout, stderr,
                                                     wt.remove,
                                                     ['hello'],
                                                     verbose=True))
        self.assertEqual('?       hello\n', stdout.getvalue())
        self.assertEqual('', stderr.getvalue())

    def test_clone_trivial(self):
        wt = self.make_branch_and_tree('source')
        cloned_dir = wt.controldir.clone('target')
        cloned = cloned_dir.open_workingtree()
        self.assertEqual(cloned.get_parent_ids(), wt.get_parent_ids())

    def test_clone_empty(self):
        wt = self.make_branch_and_tree('source')
        cloned_dir = wt.controldir.clone(
            'target', revision_id=_mod_revision.NULL_REVISION)
        cloned = cloned_dir.open_workingtree()
        self.assertEqual(cloned.get_parent_ids(), wt.get_parent_ids())

    def test_last_revision(self):
        wt = self.make_branch_and_tree('source')
        self.assertEqual([], wt.get_parent_ids())
        a = wt.commit('A', allow_pointless=True)
        parent_ids = wt.get_parent_ids()
        self.assertEqual([a], parent_ids)
        for parent_id in parent_ids:
            self.assertIsInstance(parent_id, bytes)

    def test_set_last_revision(self):
        wt = self.make_branch_and_tree('source')
        # set last-revision to one not in the history
        if wt.branch.repository._format.supports_ghosts:
            wt.set_last_revision(b'A')
        # set it back to None for an empty tree.
        wt.set_last_revision(b'null:')
        a = wt.commit('A', allow_pointless=True)
        self.assertEqual([a], wt.get_parent_ids())
        # null: is aways in the branch
        wt.set_last_revision(b'null:')
        self.assertEqual([], wt.get_parent_ids())
        # and now we can set it to 'A'
        # because some formats mutate the branch to set it on the tree
        # we need to alter the branch to let this pass.
        if getattr(wt.branch, "_set_revision_history", None) is None:
            raise TestSkipped("Branch format does not permit arbitrary"
                              " history")
        wt.branch._set_revision_history([a, b'B'])
        wt.set_last_revision(a)
        self.assertEqual([a], wt.get_parent_ids())
        self.assertRaises(errors.ReservedId, wt.set_last_revision, b'A:')

    def test_set_last_revision_different_to_branch(self):
        # working tree formats from the meta-dir format and newer support
        # setting the last revision on a tree independently of that on the
        # branch. Its concievable that some future formats may want to
        # couple them again (i.e. because its really a smart server and
        # the working tree will always match the branch). So we test
        # that formats where initialising a branch does not initialise a
        # tree - and thus have separable entities - support skewing the
        # two things.
        self.requireBranchReference()
        wt = self.make_branch_and_tree('tree')
        a = wt.commit('A', allow_pointless=True)
        wt.set_last_revision(None)
        self.assertEqual([], wt.get_parent_ids())
        self.assertEqual(a, wt.branch.last_revision())
        # and now we can set it back to 'A'
        wt.set_last_revision(a)
        self.assertEqual([a], wt.get_parent_ids())
        self.assertEqual(a, wt.branch.last_revision())

    def test_clone_and_commit_preserves_last_revision(self):
        """Doing a commit into a clone tree does not affect the source."""
        wt = self.make_branch_and_tree('source')
        cloned_dir = wt.controldir.clone('target')
        wt.commit('A', allow_pointless=True)
        self.assertNotEqual(cloned_dir.open_workingtree().get_parent_ids(),
                            wt.get_parent_ids())

    def test_clone_preserves_content(self):
        wt = self.make_branch_and_tree('source')
        self.build_tree(['added', 'deleted', 'notadded'],
                        transport=wt.controldir.transport.clone('..'))
        wt.add('deleted')
        wt.commit('add deleted')
        wt.remove('deleted')
        wt.add('added')
        cloned_dir = wt.controldir.clone('target')
        cloned = cloned_dir.open_workingtree()
        cloned_transport = cloned.controldir.transport.clone('..')
        self.assertFalse(cloned_transport.has('deleted'))
        self.assertTrue(cloned_transport.has('added'))
        self.assertFalse(cloned_transport.has('notadded'))
        self.assertTrue(cloned.is_versioned('added'))
        self.assertFalse(cloned.is_versioned('deleted'))
        self.assertFalse(cloned.is_versioned('notadded'))

    def test_basis_tree_returns_last_revision(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        wt.add('foo')
        a = wt.commit('A')
        wt.rename_one('foo', 'bar')
        b = wt.commit('B')
        wt.set_parent_ids([b])
        tree = wt.basis_tree()
        tree.lock_read()
        self.assertTrue(tree.has_filename('bar'))
        tree.unlock()
        wt.set_parent_ids([a])
        tree = wt.basis_tree()
        tree.lock_read()
        self.assertTrue(tree.has_filename('foo'))
        tree.unlock()

    def test_clone_tree_revision(self):
        # make a tree with a last-revision,
        # and clone it with a different last-revision, this should switch
        # do it.
        #
        # also test that the content is merged
        # and conflicts recorded.
        # This should merge between the trees - local edits should be preserved
        # but other changes occured.
        # we test this by having one file that does
        # not change between two revisions, and another that does -
        # if the changed one is not changed, fail,
        # if the one that did not change has lost a local change, fail.
        #
        raise TestSkipped('revision limiting is not implemented yet.')

    def test_initialize_with_revision_id(self):
        # a bzrdir can construct a working tree for itself @ a specific revision.
        source = self.make_branch_and_tree('source')
        a = source.commit('a', allow_pointless=True)
        source.commit('b', allow_pointless=True)
        self.build_tree(['new/'])
        made_control = self.bzrdir_format.initialize('new')
        source.branch.repository.clone(made_control)
        source.branch.clone(made_control)
        made_tree = self.workingtree_format.initialize(made_control,
                                                       revision_id=a)
        self.assertEqual([a], made_tree.get_parent_ids())

    def test_post_build_tree_hook(self):
        calls = []

        def track_post_build_tree(tree):
            calls.append(tree.last_revision())
        source = self.make_branch_and_tree('source')
        a = source.commit('a', allow_pointless=True)
        source.commit('b', allow_pointless=True)
        self.build_tree(['new/'])
        made_control = self.bzrdir_format.initialize('new')
        source.branch.repository.clone(made_control)
        source.branch.clone(made_control)
        MutableTree.hooks.install_named_hook("post_build_tree",
                                             track_post_build_tree, "Test")
        made_tree = self.workingtree_format.initialize(made_control,
                                                       revision_id=a)
        self.assertEqual([a], calls)

    def test_update_sets_last_revision(self):
        # working tree formats from the meta-dir format and newer support
        # setting the last revision on a tree independently of that on the
        # branch. Its concievable that some future formats may want to
        # couple them again (i.e. because its really a smart server and
        # the working tree will always match the branch). So we test
        # that formats where initialising a branch does not initialise a
        # tree - and thus have separable entities - support skewing the
        # two things.
        self.requireBranchReference()
        wt = self.make_branch_and_tree('tree')
        # create an out of date working tree by making a checkout in this
        # current format
        self.build_tree(['checkout/', 'tree/file'])
        checkout = bzrdir.BzrDirMetaFormat1().initialize('checkout')
        checkout.set_branch_reference(wt.branch)
        old_tree = self.workingtree_format.initialize(checkout)
        # now commit to 'tree'
        wt.add('file')
        a = wt.commit('A')
        # and update old_tree
        self.assertEqual(0, old_tree.update())
        self.assertPathExists('checkout/file')
        self.assertEqual([a], old_tree.get_parent_ids())

    def test_update_sets_root_id(self):
        """Ensure tree root is set properly by update.

        Since empty trees don't have root_ids, but workingtrees do,
        an update of a checkout of revision 0 to a new revision,  should set
        the root id.
        """
        wt = self.make_branch_and_tree('tree')
        main_branch = wt.branch
        # create an out of date working tree by making a checkout in this
        # current format
        self.build_tree(['checkout/', 'tree/file'])
        checkout = main_branch.create_checkout('checkout')
        # now commit to 'tree'
        wt.add('file')
        a = wt.commit('A')
        # and update checkout
        self.assertEqual(0, checkout.update())
        self.assertPathExists('checkout/file')
        if wt.supports_setting_file_ids():
            self.assertEqual(wt.path2id(''), checkout.path2id(''))
            self.assertNotEqual(None, wt.path2id(''))

    def test_update_sets_updated_root_id(self):
        wt = self.make_branch_and_tree('tree')
        if not wt.supports_setting_file_ids():
            self.assertRaises(SettingFileIdUnsupported, wt.set_root_id,
                              'first_root_id')
            return
        wt.set_root_id(b'first_root_id')
        self.assertEqual(b'first_root_id', wt.path2id(''))
        self.build_tree(['tree/file'])
        wt.add(['file'])
        wt.commit('first')
        co = wt.branch.create_checkout('checkout')
        wt.set_root_id(b'second_root_id')
        wt.commit('second')
        self.assertEqual(b'second_root_id', wt.path2id(''))
        self.assertEqual(0, co.update())
        self.assertEqual(b'second_root_id', co.path2id(''))

    def test_update_returns_conflict_count(self):
        # working tree formats from the meta-dir format and newer support
        # setting the last revision on a tree independently of that on the
        # branch. Its concievable that some future formats may want to
        # couple them again (i.e. because its really a smart server and
        # the working tree will always match the branch). So we test
        # that formats where initialising a branch does not initialise a
        # tree - and thus have separable entities - support skewing the
        # two things.
        self.requireBranchReference()
        wt = self.make_branch_and_tree('tree')
        # create an out of date working tree by making a checkout in this
        # current format
        self.build_tree(['checkout/', 'tree/file'])
        checkout = bzrdir.BzrDirMetaFormat1().initialize('checkout')
        checkout.set_branch_reference(wt.branch)
        old_tree = self.workingtree_format.initialize(checkout)
        # now commit to 'tree'
        wt.add('file')
        a = wt.commit('A')
        # and add a file file to the checkout
        self.build_tree(['checkout/file'])
        old_tree.add('file')
        # and update old_tree
        self.assertEqual(1, old_tree.update())
        self.assertEqual([a], old_tree.get_parent_ids())

    def test_merge_revert(self):
        from breezy.merge import merge_inner
        this = self.make_branch_and_tree('b1')
        self.build_tree_contents(
            [('b1/a', b'a test\n'), ('b1/b', b'b test\n')])
        this.add(['a', 'b'])
        this.commit(message='')
        base = this.controldir.clone('b2').open_workingtree()
        self.build_tree_contents([('b2/a', b'b test\n')])
        other = this.controldir.clone('b3').open_workingtree()
        self.build_tree_contents(
            [('b3/a', b'c test\n'), ('b3/c', b'c test\n')])
        other.add('c')

        self.build_tree_contents(
            [('b1/b', b'q test\n'), ('b1/d', b'd test\n')])
        # Note: If we don't lock this before calling merge_inner, then we get a
        #       lock-contention failure. This probably indicates something
        #       weird going on inside merge_inner. Probably something about
        #       calling bt = this_tree.basis_tree() in one lock, and then
        #       locking both this_tree and bt separately, causing a dirstate
        #       locking race.
        this.lock_write()
        self.addCleanup(this.unlock)
        merge_inner(this.branch, other, base, this_tree=this)
        with open('b1/a', 'rb') as a:
            self.assertNotEqual(a.read(), 'a test\n')
        this.revert()
        self.assertFileEqual(b'a test\n', 'b1/a')
        self.assertPathExists('b1/b.~1~')
        if this.supports_merge_modified():
            self.assertPathDoesNotExist('b1/c')
            self.assertPathDoesNotExist('b1/a.~1~')
        else:
            self.assertPathExists('b1/c')
            self.assertPathExists('b1/a.~1~')
        self.assertPathExists('b1/d')

    def test_update_updates_bound_branch_no_local_commits(self):
        # doing an update in a tree updates the branch its bound to too.
        master_tree = self.make_branch_and_tree('master')
        tree = self.make_branch_and_tree('tree')
        try:
            tree.branch.bind(master_tree.branch)
        except _mod_branch.BindingUnsupported:
            # legacy branches cannot bind
            return
        foo = master_tree.commit('foo', allow_pointless=True)
        tree.update()
        self.assertEqual([foo], tree.get_parent_ids())
        self.assertEqual(foo, tree.branch.last_revision())

    def test_update_turns_local_commit_into_merge(self):
        # doing an update with a few local commits and no master commits
        # makes pending-merges.
        # this is done so that 'bzr update; bzr revert' will always produce
        # an exact copy of the 'logical branch' - the referenced branch for
        # a checkout, and the master for a bound branch.
        # its possible that we should instead have 'bzr update' when there
        # is nothing new on the master leave the current commits intact and
        # alter 'revert' to revert to the master always. But for now, its
        # good.
        master_tree = self.make_branch_and_tree('master')
        master_tip = master_tree.commit('first master commit')
        tree = self.make_branch_and_tree('tree')
        try:
            tree.branch.bind(master_tree.branch)
        except _mod_branch.BindingUnsupported:
            # legacy branches cannot bind
            return
        # sync with master
        tree.update()
        # work locally
        tree.commit('foo', allow_pointless=True, local=True)
        bar = tree.commit('bar', allow_pointless=True, local=True)
        # sync with master prepatory to committing
        tree.update()
        # which should have pivoted the local tip into a merge
        self.assertEqual([master_tip, bar], tree.get_parent_ids())
        # and the local branch history should match the masters now.
        self.assertEqual(master_tree.branch.last_revision(),
                         tree.branch.last_revision())

    def test_update_takes_revision_parameter(self):
        wt = self.make_branch_and_tree('wt')
        self.build_tree_contents([('wt/a', b'old content')])
        wt.add(['a'])
        rev1 = wt.commit('first master commit')
        self.build_tree_contents([('wt/a', b'new content')])
        rev2 = wt.commit('second master commit')
        # https://bugs.launchpad.net/bzr/+bug/45719/comments/20
        # when adding 'update -r' we should make sure all wt formats support
        # it
        conflicts = wt.update(revision=rev1)
        self.assertFileEqual(b'old content', 'wt/a')
        self.assertEqual([rev1], wt.get_parent_ids())

    def test_merge_modified_detects_corruption(self):
        # FIXME: This doesn't really test that it works; also this is not
        # implementation-independent. mbp 20070226
        tree = self.make_branch_and_tree('master')
        if not isinstance(tree, InventoryWorkingTree):
            raise TestNotApplicable("merge-hashes is specific to bzr "
                                    "working trees")
        tree._transport.put_bytes('merge-hashes', b'asdfasdf')
        self.assertRaises(errors.MergeModifiedFormatError, tree.merge_modified)

    def test_merge_modified(self):
        # merge_modified stores a map from file id to hash
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/somefile', b'hello')])
        with tree.lock_write():
            tree.add(['somefile'])
            d = {'somefile': osutils.sha_string(b'hello')}
            if tree.supports_merge_modified():
                tree.set_merge_modified(d)
                mm = tree.merge_modified()
                self.assertEqual(mm, d)
            else:
                self.assertRaises(
                    errors.UnsupportedOperation,
                    tree.set_merge_modified, d)
                mm = tree.merge_modified()
                self.assertEqual(mm, {})
        if tree.supports_merge_modified():
            mm = tree.merge_modified()
            self.assertEqual(mm, d)
        else:
            mm = tree.merge_modified()
            self.assertEqual(mm, {})

    def test_conflicts(self):
        from breezy.tests.test_conflicts import example_conflicts
        tree = self.make_branch_and_tree('master')
        try:
            tree.set_conflicts(example_conflicts)
        except UnsupportedOperation:
            raise TestSkipped('set_conflicts not supported')

        tree2 = WorkingTree.open('master')
        self.assertEqual(tree2.conflicts(), example_conflicts)
        tree2._transport.put_bytes('conflicts', b'')
        self.assertRaises(errors.ConflictFormatError,
                          tree2.conflicts)
        tree2._transport.put_bytes('conflicts', b'a')
        self.assertRaises(errors.ConflictFormatError,
                          tree2.conflicts)

    def make_merge_conflicts(self):
        from breezy.merge import merge_inner
        tree = self.make_branch_and_tree('mine')
        with open('mine/bloo', 'wb') as f:
            f.write(b'one')
        with open('mine/blo', 'wb') as f:
            f.write(b'on')
        tree.add(['bloo', 'blo'])
        tree.commit("blah", allow_pointless=False)
        base = tree.branch.repository.revision_tree(tree.last_revision())
        controldir.ControlDir.open("mine").sprout("other")
        with open('other/bloo', 'wb') as f:
            f.write(b'two')
        othertree = WorkingTree.open('other')
        othertree.commit('blah', allow_pointless=False)
        with open('mine/bloo', 'wb') as f:
            f.write(b'three')
        tree.commit("blah", allow_pointless=False)
        merge_inner(tree.branch, othertree, base, this_tree=tree)
        return tree

    def test_merge_conflicts(self):
        tree = self.make_merge_conflicts()
        self.assertEqual(len(tree.conflicts()), 1)

    def test_clear_merge_conflicts(self):
        tree = self.make_merge_conflicts()
        self.assertEqual(len(tree.conflicts()), 1)
        try:
            tree.set_conflicts([])
        except UnsupportedOperation:
            raise TestSkipped('unsupported operation')
        self.assertEqual(tree.conflicts(), ConflictList())

    def test_add_conflicts(self):
        tree = self.make_branch_and_tree('tree')
        try:
            tree.add_conflicts([TextConflict('path_a')])
        except UnsupportedOperation:
            raise TestSkipped('unsupported operation')
        self.assertEqual(ConflictList([TextConflict('path_a')]),
                         tree.conflicts())
        tree.add_conflicts([TextConflict('path_a')])
        self.assertEqual(ConflictList([TextConflict('path_a')]),
                         tree.conflicts())
        tree.add_conflicts([ContentsConflict('path_a')])
        self.assertEqual(ConflictList([ContentsConflict('path_a'),
                                       TextConflict('path_a')]),
                         tree.conflicts())
        tree.add_conflicts([TextConflict('path_b')])
        self.assertEqual(ConflictList([ContentsConflict('path_a'),
                                       TextConflict('path_a'),
                                       TextConflict('path_b')]),
                         tree.conflicts())

    def test_revert_clear_conflicts(self):
        tree = self.make_merge_conflicts()
        self.assertEqual(len(tree.conflicts()), 1)
        tree.revert(["blo"])
        self.assertEqual(len(tree.conflicts()), 1)
        tree.revert(["bloo"])
        self.assertEqual(len(tree.conflicts()), 0)

    def test_revert_clear_conflicts2(self):
        tree = self.make_merge_conflicts()
        self.assertEqual(len(tree.conflicts()), 1)
        tree.revert()
        self.assertEqual(len(tree.conflicts()), 0)

    def test_format_description(self):
        tree = self.make_branch_and_tree('tree')
        text = tree._format.get_format_description()
        self.assertTrue(len(text))

    def test_format_leftmost_parent_id_as_ghost(self):
        tree = self.make_branch_and_tree('tree')
        self.assertIn(
            tree._format.supports_leftmost_parent_id_as_ghost, (True, False))

    def test_branch_attribute_is_not_settable(self):
        # the branch attribute is an aspect of the working tree, not a
        # configurable attribute
        tree = self.make_branch_and_tree('tree')

        def set_branch():
            tree.branch = tree.branch
        self.assertRaises(AttributeError, set_branch)

    def test_list_files_versioned_before_ignored(self):
        """A versioned file matching an ignore rule should not be ignored."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo.pyc'])
        # ensure that foo.pyc is ignored
        self.build_tree_contents([('.bzrignore', b'foo.pyc')])
        tree.add('foo.pyc')
        tree.lock_read()
        files = sorted(list(tree.list_files()))
        tree.unlock()
        self.assertEqual(
            (u'.bzrignore', '?', 'file', None),
            (files[0][0], files[0][1], files[0][2],
                getattr(files[0][3], 'file_id', None)))
        self.assertEqual(
            (u'foo.pyc', 'V', 'file'),
            (files[1][0], files[1][1], files[1][2]))
        self.assertEqual(2, len(files))

    def test_non_normalized_add_accessible(self):
        try:
            self.build_tree([u'a\u030a'])
        except UnicodeError:
            raise TestSkipped('Filesystem does not support unicode filenames')
        tree = self.make_branch_and_tree('.')
        orig = osutils.normalized_filename
        osutils.normalized_filename = osutils._accessible_normalized_filename
        try:
            tree.add([u'a\u030a'])
            with tree.lock_read():
                self.assertEqual([('', 'directory'), (u'\xe5', 'file')],
                                 [(path, ie.kind) for path, ie in
                                  tree.iter_entries_by_dir()])
        finally:
            osutils.normalized_filename = orig

    def test_non_normalized_add_inaccessible(self):
        try:
            self.build_tree([u'a\u030a'])
        except UnicodeError:
            raise TestSkipped('Filesystem does not support unicode filenames')
        tree = self.make_branch_and_tree('.')
        orig = osutils.normalized_filename
        osutils.normalized_filename = osutils._inaccessible_normalized_filename
        try:
            self.assertRaises(errors.InvalidNormalization,
                              tree.add, [u'a\u030a'])
        finally:
            osutils.normalized_filename = orig

    def test__write_inventory(self):
        # The private interface _write_inventory is currently used by
        # transform.
        tree = self.make_branch_and_tree('.')
        if not isinstance(tree, InventoryWorkingTree):
            raise TestNotApplicable("_write_inventory does not exist on "
                                    "non-inventory working trees")
        # if we write write an inventory then do a walkdirs we should get back
        # missing entries, and actual, and unknowns as appropriate.
        self.build_tree(['present', 'unknown'])
        inventory = Inventory(tree.path2id(''))
        inventory.add_path('missing', 'file', b'missing-id')
        inventory.add_path('present', 'file', b'present-id')
        # there is no point in being able to write an inventory to an unlocked
        # tree object - its a low level api not a convenience api.
        tree.lock_write()
        tree._write_inventory(inventory)
        tree.unlock()
        with tree.lock_read():
            present_stat = os.lstat('present')
            unknown_stat = os.lstat('unknown')
            expected_results = [
                ('',
                 [('missing', 'missing', 'unknown', None, 'file'),
                  ('present', 'present', 'file',
                   present_stat, 'file'),
                  ('unknown', 'unknown', 'file', unknown_stat, None),
                  ]
                 )]
            self.assertEqual(expected_results, list(tree.walkdirs()))

    def test_path2id(self):
        # smoke test for path2id
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        if tree.supports_setting_file_ids():
            tree.add(['foo'], ids=[b'foo-id'])
            self.assertEqual(b'foo-id', tree.path2id('foo'))
            # the next assertion is for backwards compatibility with
            # WorkingTree3, though its probably a bad idea, it makes things
            # work. Perhaps it should raise a deprecation warning?
            self.assertEqual(b'foo-id', tree.path2id('foo/'))
        else:
            tree.add(['foo'])
            if tree.branch.repository._format.supports_versioned_directories:
                self.assertIsInstance(str, tree.path2id('foo'))
            else:
                self.skipTest('format does not support versioning directories')

    def test_filter_unversioned_files(self):
        # smoke test for filter_unversioned_files
        tree = self.make_branch_and_tree('.')
        paths = ['here-and-versioned', 'here-and-not-versioned',
                 'not-here-and-versioned', 'not-here-and-not-versioned']
        tree.add(['here-and-versioned', 'not-here-and-versioned'],
                 kinds=['file', 'file'])
        self.build_tree(['here-and-versioned', 'here-and-not-versioned'])
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(
            {'not-here-and-not-versioned', 'here-and-not-versioned'},
            tree.filter_unversioned_files(paths))

    def test_detect_real_kind(self):
        # working trees report the real kind of the file on disk, not the kind
        # they had when they were first added
        # create one file of every interesting type
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['file', 'directory/'])
        names = ['file', 'directory']
        if supports_symlinks(self.test_dir):
            os.symlink('target', 'symlink')
            names.append('symlink')
        tree.add(names)
        # now when we first look, we should see everything with the same kind
        # with which they were initially added
        for n in names:
            actual_kind = tree.kind(n)
            self.assertEqual(n, actual_kind)
        # move them around so the names no longer correspond to the types
        os.rename(names[0], 'tmp')
        for i in range(1, len(names)):
            os.rename(names[i], names[i - 1])
        os.rename('tmp', names[-1])
        # now look and expect to see the correct types again
        for i in range(len(names)):
            actual_kind = tree.kind(names[i - 1])
            expected_kind = names[i]
            self.assertEqual(expected_kind, actual_kind)

    def test_stored_kind_with_missing(self):
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['tree/a', 'tree/b/'])
        tree.add(['a', 'b'])
        os.unlink('tree/a')
        os.rmdir('tree/b')
        self.assertEqual('file', tree.stored_kind('a'))
        if tree.branch.repository._format.supports_versioned_directories:
            self.assertEqual('directory', tree.stored_kind('b'))

    def test_stored_kind_nonexistent(self):
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.assertRaises(_mod_transport.NoSuchFile, tree.stored_kind, 'a')
        self.addCleanup(tree.unlock)
        self.build_tree(['tree/a'])
        self.assertRaises(_mod_transport.NoSuchFile, tree.stored_kind, 'a')
        tree.add(['a'])
        self.assertIs('file', tree.stored_kind('a'))

    def test_missing_file_sha1(self):
        """If a file is missing, its sha1 should be reported as None."""
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['file'])
        tree.add('file')
        tree.commit('file added')
        os.unlink('file')
        self.assertIs(None, tree.get_file_sha1('file'))

    def test_no_file_sha1(self):
        """If a file is not present, get_file_sha1 should raise NoSuchFile"""
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.assertRaises(_mod_transport.NoSuchFile, tree.get_file_sha1,
                          'nonexistant')
        self.build_tree(['file'])
        tree.add('file')
        tree.commit('foo')
        tree.remove('file')
        self.assertRaises(_mod_transport.NoSuchFile, tree.get_file_sha1,
                          'file')

    def test_case_sensitive(self):
        """If filesystem is case-sensitive, tree should report this.

        We check case-sensitivity by creating a file with a lowercase name,
        then testing whether it exists with an uppercase name.
        """
        self.build_tree(['filename'])
        if os.path.exists('FILENAME'):
            case_sensitive = False
        else:
            case_sensitive = True
        tree = self.make_branch_and_tree('test')
        self.assertEqual(case_sensitive, tree.case_sensitive)
        if not isinstance(tree, InventoryWorkingTree):
            raise TestNotApplicable("get_format_string is only available "
                                    "on bzr working trees")
        # now we cheat, and make a file that matches the case-sensitive name
        t = tree.controldir.get_workingtree_transport(None)
        try:
            content = tree._format.get_format_string()
        except NotImplementedError:
            # All-in-one formats didn't have a separate format string.
            content = tree.controldir._format.get_format_string()
        t.put_bytes(tree._format.case_sensitive_filename, content)
        tree = tree.controldir.open_workingtree()
        self.assertFalse(tree.case_sensitive)

    def test_supports_executable(self):
        self.build_tree(['filename'])
        tree = self.make_branch_and_tree('.')
        tree.add('filename')
        self.assertIsInstance(tree._supports_executable(), bool)
        if tree._supports_executable():
            tree.lock_read()
            try:
                self.assertFalse(tree.is_executable('filename'))
            finally:
                tree.unlock()
            os.chmod('filename', 0o755)
            self.addCleanup(tree.lock_read().unlock)
            self.assertTrue(tree.is_executable('filename'))
        else:
            self.addCleanup(tree.lock_read().unlock)
            self.assertFalse(tree.is_executable('filename'))

    def test_all_file_ids_with_missing(self):
        if not self.workingtree_format.supports_setting_file_ids:
            raise TestNotApplicable('does not support setting file ids')
        tree = self.make_branch_and_tree('tree')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        self.build_tree(['tree/a', 'tree/b'])
        tree.add(['a', 'b'])
        os.unlink('tree/a')
        self.assertEqual(
            {'a', 'b', ''},
            set(tree.all_versioned_paths()))

    def test_sprout_hardlink(self):
        real_os_link = getattr(os, 'link', None)
        if real_os_link is None:
            raise TestNotApplicable("This platform doesn't provide os.link")
        source = self.make_branch_and_tree('source')
        self.build_tree(['source/file'])
        source.add('file')
        source.commit('added file')

        def fake_link(source, target):
            raise OSError(errno.EPERM, 'Operation not permitted')
        os.link = fake_link
        try:
            # Hard-link support is optional, so supplying hardlink=True may
            # or may not raise an exception.  But if it does, it must be
            # HardLinkNotSupported
            try:
                source.controldir.sprout('target', accelerator_tree=source,
                                         hardlink=True)
            except errors.HardLinkNotSupported:
                pass
        finally:
            os.link = real_os_link


class TestWorkingTreeUpdate(TestCaseWithWorkingTree):

    def make_diverged_master_branch(self):
        """
        B: wt.branch.last_revision()
        M: wt.branch.get_master_branch().last_revision()
        W: wt.last_revision()


            1
            |\
          B-2 3
            | |
            4 5-M
            |
            W
        """
        format = self.workingtree_format.get_controldir_for_branch()
        builder = self.make_branch_builder(".", format=format)
        builder.start_series()
        revids = {}
        # mainline
        revids['1'] = builder.build_snapshot(
            None,
            [('add', ('', None, 'directory', '')),
             ('add', ('file1', None, 'file', b'file1 content\n'))])
        # branch
        revids['2'] = builder.build_snapshot([revids['1']], [])
        revids['4'] = builder.build_snapshot(
            [revids['1']],
            [('add', ('file4', None, 'file', b'file4 content\n'))])
        # master
        revids['3'] = builder.build_snapshot([revids['1']], [])
        revids['5'] = builder.build_snapshot(
            [revids['3']],
            [('add', ('file5', None, 'file', b'file5 content\n'))])
        builder.finish_series()
        return (builder, builder._branch.last_revision(), revids)

    def make_checkout_and_master(self, builder, wt_path, master_path, wt_revid,
                                 master_revid=None, branch_revid=None):
        """Build a lightweight checkout and its master branch."""
        if master_revid is None:
            master_revid = wt_revid
        if branch_revid is None:
            branch_revid = master_revid
        final_branch = builder.get_branch()
        # The master branch
        master = final_branch.controldir.sprout(master_path,
                                                master_revid).open_branch()
        # The checkout
        wt = self.make_branch_and_tree(wt_path)
        wt.pull(final_branch, stop_revision=wt_revid)
        wt.branch.pull(
            final_branch, stop_revision=branch_revid, overwrite=True)
        try:
            wt.branch.bind(master)
        except _mod_branch.BindingUnsupported:
            raise TestNotApplicable(
                "Can't bind %s" % wt.branch._format.__class__)
        return wt, master

    def test_update_remove_commit(self):
        """Update should remove revisions when the branch has removed
        some commits.

        We want to revert 4, so that strating with the
        make_diverged_master_branch() graph the final result should be
        equivalent to:

           1
           |\
           3 2
           | |\
        MB-5 | 4
           |/
           W

        And the changes in 4 have been removed from the WT.
        """
        builder, tip, revids = self.make_diverged_master_branch()
        wt, master = self.make_checkout_and_master(
            builder, 'checkout', 'master', revids['4'],
            master_revid=tip, branch_revid=revids['2'])
        # First update the branch
        old_tip = wt.branch.update()
        self.assertEqual(revids['2'], old_tip)
        # No conflicts should occur
        self.assertEqual(0, wt.update(old_tip=old_tip))
        # We are in sync with the master
        self.assertEqual(tip, wt.branch.last_revision())
        # We have the right parents ready to be committed
        self.assertEqual([revids['5'], revids['2']],
                         wt.get_parent_ids())

    def test_update_revision(self):
        builder, tip, revids = self.make_diverged_master_branch()
        wt, master = self.make_checkout_and_master(
            builder, 'checkout', 'master', revids['4'],
            master_revid=tip, branch_revid=revids['2'])
        self.assertEqual(0, wt.update(revision=revids['1']))
        self.assertEqual(revids['1'], wt.last_revision())
        self.assertEqual(tip, wt.branch.last_revision())
        self.assertPathExists('checkout/file1')
        self.assertPathDoesNotExist('checkout/file4')
        self.assertPathDoesNotExist('checkout/file5')


class TestIllegalPaths(TestCaseWithWorkingTree):

    def test_bad_fs_path(self):
        if osutils.normalizes_filenames():
            # You *can't* create an illegal filename on OSX.
            raise tests.TestNotApplicable('OSX normalizes filenames')
        self.requireFeature(features.UTF8Filesystem)
        # We require a UTF8 filesystem, because otherwise we would need to get
        # tricky to figure out how to create an illegal filename.
        # \xb5 is an illegal path because it should be \xc2\xb5 for UTF-8
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/subdir/', 'tree/subdir/somefile'])
        tree.add(['subdir', 'subdir/somefile'])

        with open(b'tree/subdir/m\xb5', 'wb') as f:
            f.write(b'trivial\n')

        tree.lock_read()
        self.addCleanup(tree.unlock)
        basis = tree.basis_tree()
        basis.lock_read()
        self.addCleanup(basis.unlock)

        changes = list(tree.iter_changes(tree.basis_tree(), want_unversioned=True))
        self.assertIn('subdir/m\udcb5', [c.path[1] for c in changes])


class TestControlComponent(TestCaseWithWorkingTree):
    """WorkingTree implementations adequately implement ControlComponent."""

    def test_urls(self):
        wt = self.make_branch_and_tree('wt')
        self.assertIsInstance(wt.user_url, str)
        self.assertEqual(wt.user_url, wt.user_transport.base)
        self.assertEqual(wt.control_url, wt.control_transport.base)


class TestWorthSavingLimit(TestCaseWithWorkingTree):

    def make_wt_with_worth_saving_limit(self):
        wt = self.make_branch_and_tree('wt')
        if getattr(wt, '_worth_saving_limit', None) is None:
            raise tests.TestNotApplicable('no _worth_saving_limit for'
                                          ' this tree type')
        wt.lock_write()
        self.addCleanup(wt.unlock)
        return wt

    def test_not_set(self):
        # Default should be 10
        wt = self.make_wt_with_worth_saving_limit()
        self.assertEqual(10, wt._worth_saving_limit())
        ds = wt.current_dirstate()
        self.assertEqual(10, ds._worth_saving_limit)

    def test_set_in_branch(self):
        wt = self.make_wt_with_worth_saving_limit()
        conf = wt.get_config_stack()
        conf.set('bzr.workingtree.worth_saving_limit', '20')
        self.assertEqual(20, wt._worth_saving_limit())
        ds = wt.current_dirstate()
        self.assertEqual(10, ds._worth_saving_limit)

    def test_invalid(self):
        wt = self.make_wt_with_worth_saving_limit()
        conf = wt.get_config_stack()
        conf.set('bzr.workingtree.worth_saving_limit', 'a')
        # If the config entry is invalid, default to 10
        warnings = []

        def warning(*args):
            warnings.append(args[0] % args[1:])
        self.overrideAttr(trace, 'warning', warning)
        self.assertEqual(10, wt._worth_saving_limit())
        self.assertLength(1, warnings)
        self.assertEqual('Value "a" is not valid for'
                         ' "bzr.workingtree.worth_saving_limit"',
                         warnings[0])


class TestFormatAttributes(TestCaseWithWorkingTree):

    def test_versioned_directories(self):
        self.assertSubset(
            [self.workingtree_format.supports_versioned_directories],
            (True, False))

    def test_supports_setting_file_ids(self):
        self.assertSubset(
            [self.workingtree_format.supports_setting_file_ids],
            (True, False))

    def test_supports_store_uncommitted(self):
        self.assertSubset(
            [self.workingtree_format.supports_store_uncommitted],
            (True, False))


class TestReferenceLocation(TestCaseWithWorkingTree):

    def test_reference_parent(self):
        tree = self.make_branch_and_tree('tree')
        subtree = self.make_branch_and_tree('tree/subtree')
        subtree.commit('a change')
        try:
            tree.add_reference(subtree)
        except errors.UnsupportedOperation:
            raise tests.TestNotApplicable('Tree cannot hold references.')
        if not getattr(tree.branch._format, 'supports_reference_locations', False):
            raise tests.TestNotApplicable('Branch cannot hold reference locations.')
        tree.commit('Add reference.')
        reference_parent = tree.reference_parent(
            urlutils.relative_url(
                urlutils.strip_segment_parameters(tree.branch.user_url),
                urlutils.strip_segment_parameters(subtree.branch.user_url)))
        self.assertEqual(subtree.branch.user_url, reference_parent.user_url)

    def test_reference_parent_accepts_possible_transports(self):
        tree = self.make_branch_and_tree('tree')
        subtree = self.make_branch_and_tree('tree/subtree')
        subtree.commit('a change')
        try:
            tree.add_reference(subtree)
        except errors.UnsupportedOperation:
            raise tests.TestNotApplicable('Tree cannot hold references.')
        if not getattr(tree.branch._format, 'supports_reference_locations', False):
            raise tests.TestNotApplicable('Branch cannot hold reference locations.')
        tree.commit('Add reference')
        reference_parent = tree.reference_parent(
            urlutils.relative_url(
                urlutils.strip_segment_parameters(tree.branch.user_url),
                urlutils.strip_segment_parameters(subtree.branch.user_url)),
            possible_transports=[subtree.controldir.root_transport])

    def test_get_reference_info(self):
        tree = self.make_branch_and_tree('branch')
        try:
            loc = tree.get_reference_info('file')
        except errors.UnsupportedOperation:
            raise tests.TestNotApplicable('Branch cannot hold references.')
        self.assertIs(None, loc)

    def test_set_reference_info(self):
        self.make_tree_with_reference('branch', 'path/to/location')

    def test_set_get_reference_info(self):
        tree = self.make_tree_with_reference('branch', 'path/to/location')
        # Create a new instance to ensure storage is permanent
        tree = WorkingTree.open('branch')
        branch_location = tree.get_reference_info('path/to/file')
        self.assertEqual(
            urlutils.join(urlutils.strip_segment_parameters(tree.branch.user_url), 'path/to/location'),
            urlutils.join(urlutils.strip_segment_parameters(tree.branch.user_url), branch_location))

    def test_set_null_reference_info(self):
        tree = self.make_branch_and_tree('branch')
        self.build_tree(['branch/file'])
        tree.add(['file'])
        try:
            tree.set_reference_info('file', 'path/to/location')
        except errors.UnsupportedOperation:
            raise tests.TestNotApplicable('Branch cannot hold references.')
        tree.set_reference_info('file', None)
        branch_location = tree.get_reference_info('file')
        self.assertIs(None, branch_location)

    def test_set_null_reference_info_when_null(self):
        tree = self.make_branch_and_tree('branch')
        try:
            branch_location = tree.get_reference_info('file')
        except errors.UnsupportedOperation:
            raise tests.TestNotApplicable('Branch cannot hold references.')
        self.assertIs(None, branch_location)
        self.build_tree(['branch/file'])
        tree.add(['file'])
        try:
            tree.set_reference_info('file', None)
        except errors.UnsupportedOperation:
            raise tests.TestNotApplicable('Branch cannot hold references.')

    def make_tree_with_reference(self, location, reference_location):
        tree = self.make_branch_and_tree(location)
        self.build_tree(
            [os.path.join(location, name)
             for name in ['path/', 'path/to/', 'path/to/file']])
        tree.add(['path', 'path/to', 'path/to/file'])
        try:
            tree.set_reference_info('path/to/file', reference_location)
        except errors.UnsupportedOperation:
            raise tests.TestNotApplicable('Branch cannot hold references.')
        tree.commit('commit reference')
        return tree

    def test_reference_parent_from_reference_info_(self):
        referenced_branch = self.make_branch('reference_branch')
        tree = self.make_tree_with_reference('branch', referenced_branch.base)
        parent = tree.reference_parent('path/to/file')
        self.assertEqual(parent.base, referenced_branch.base)

    def test_branch_relative_reference_location(self):
        tree = self.make_tree_with_reference('branch', '../reference_branch')
        referenced_branch = self.make_branch('reference_branch')
        parent = tree.reference_parent('path/to/file')
        self.assertEqual(parent.base, referenced_branch.base)

    def test_sprout_copies_reference_location(self):
        tree = self.make_tree_with_reference('branch', '../reference')
        new_tree = tree.branch.controldir.sprout('new-branch').open_workingtree()
        self.assertEqual(
            urlutils.join(urlutils.strip_segment_parameters(tree.branch.user_url),
                          '../reference'),
            urlutils.join(urlutils.strip_segment_parameters(new_tree.branch.user_url),
                          new_tree.get_reference_info('path/to/file')))

    def test_clone_copies_reference_location(self):
        tree = self.make_tree_with_reference('branch', '../reference')
        new_tree = tree.controldir.clone('new-branch').open_workingtree()
        self.assertEqual(
            urlutils.join(urlutils.strip_segment_parameters(tree.branch.user_url), '../reference'),
            urlutils.join(urlutils.strip_segment_parameters(new_tree.branch.user_url),
                          new_tree.get_reference_info('path/to/file')))

    def test_copied_locations_are_rebased(self):
        tree = self.make_tree_with_reference('branch', 'reference')
        new_tree = tree.controldir.sprout(
            'branch/new-branch').open_workingtree()
        self.assertEqual(
            urlutils.join(urlutils.strip_segment_parameters(tree.branch.user_url),
                          'reference'),
            urlutils.join(urlutils.strip_segment_parameters(new_tree.branch.user_url),
                          new_tree.get_reference_info('path/to/file')))

    def test_update_references_retains_old_references(self):
        tree = self.make_tree_with_reference('branch', 'reference')
        new_tree = self.make_tree_with_reference(
            'new_branch', 'reference2')
        new_tree.branch.update_references(tree.branch)
        self.assertEqual(
            urlutils.join(
                urlutils.strip_segment_parameters(tree.branch.user_url),
                'reference'),
            urlutils.join(
                urlutils.strip_segment_parameters(tree.branch.user_url),
                tree.get_reference_info('path/to/file')))

    def test_update_references_retains_known_references(self):
        tree = self.make_tree_with_reference('branch', 'reference')
        new_tree = self.make_tree_with_reference(
            'new_branch', 'reference2')
        new_tree.branch.update_references(tree.branch)
        self.assertEqual(
            urlutils.join(
                urlutils.strip_segment_parameters(tree.branch.user_url),
                'reference'),
            urlutils.join(
                urlutils.strip_segment_parameters(tree.branch.user_url),
                tree.get_reference_info('path/to/file')))

    def test_update_references_skips_known_references(self):
        tree = self.make_tree_with_reference('branch', 'reference')
        new_tree = tree.controldir.sprout(
            'branch/new-branch').open_workingtree()
        self.build_tree(['branch/new-branch/foo'])
        new_tree.add('foo')
        new_tree.set_reference_info('foo', '../foo')
        new_tree.branch.update_references(tree.branch)
        self.assertEqual(
            urlutils.join(
                urlutils.strip_segment_parameters(tree.branch.user_url),
                'reference'),
            urlutils.join(
                urlutils.strip_segment_parameters(tree.branch.user_url),
                tree.get_reference_info('path/to/file')))

    def test_pull_updates_references(self):
        tree = self.make_tree_with_reference('branch', 'reference')
        new_tree = tree.controldir.sprout(
            'branch/new-branch').open_workingtree()
        self.build_tree(['branch/new-branch/foo'])
        new_tree.add('foo')
        new_tree.set_reference_info('foo', '../foo')
        new_tree.commit('set reference')
        tree.pull(new_tree.branch)
        self.assertEqual(
            urlutils.join(urlutils.strip_segment_parameters(new_tree.branch.user_url), '../foo'),
            urlutils.join(tree.branch.user_url, tree.get_reference_info('foo')))

    def test_push_updates_references(self):
        tree = self.make_tree_with_reference('branch', 'reference')
        new_tree = tree.controldir.sprout(
            'branch/new-branch').open_workingtree()
        self.build_tree(['branch/new-branch/foo'])
        new_tree.add(['foo'])
        new_tree.set_reference_info('foo', '../foo')
        new_tree.commit('add reference')
        tree.pull(new_tree.branch)
        tree.update()
        self.assertEqual(
            urlutils.join(urlutils.strip_segment_parameters(new_tree.branch.user_url), '../foo'),
            urlutils.join(urlutils.strip_segment_parameters(tree.branch.user_url), tree.get_reference_info('foo')))

    def test_merge_updates_references(self):
        orig_tree = self.make_tree_with_reference('branch', 'reference')
        tree = orig_tree.controldir.sprout('tree').open_workingtree()
        tree.commit('foo')
        orig_tree.pull(tree.branch)
        checkout = orig_tree.branch.create_checkout('checkout', lightweight=True)
        checkout.commit('bar')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        merger = merge.Merger.from_revision_ids(tree,
                                                orig_tree.branch.last_revision(),
                                                other_branch=orig_tree.branch)
        merger.merge_type = merge.Merge3Merger
        merger.do_merge()
        self.assertEqual(
            urlutils.join(urlutils.strip_segment_parameters(orig_tree.branch.user_url), 'reference'),
            urlutils.join(urlutils.strip_segment_parameters(tree.branch.user_url), tree.get_reference_info('path/to/file')))

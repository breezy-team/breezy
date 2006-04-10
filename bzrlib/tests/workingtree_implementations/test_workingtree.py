# (C) 2005,2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

from cStringIO import StringIO
import os

import bzrlib
import bzrlib.branch
from bzrlib.branch import Branch
import bzrlib.bzrdir as bzrdir
from bzrlib.bzrdir import BzrDir
import bzrlib.errors as errors
from bzrlib.errors import (NotBranchError, NotVersionedError, 
                           UnsupportedOperation)
from bzrlib.osutils import pathjoin, getcwd, has_symlinks
from bzrlib.tests import TestSkipped
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib.trace import mutter
import bzrlib.workingtree as workingtree
from bzrlib.workingtree import (TreeEntry, TreeDirectory, TreeFile, TreeLink,
                                WorkingTree)


class TestWorkingTree(TestCaseWithWorkingTree):

    def test_listfiles(self):
        tree = self.make_branch_and_tree('.')
        os.mkdir('dir')
        print >> open('file', 'w'), "content"
        if has_symlinks():
            os.symlink('target', 'symlink')
        files = list(tree.list_files())
        self.assertEqual(files[0], ('dir', '?', 'directory', None, TreeDirectory()))
        self.assertEqual(files[1], ('file', '?', 'file', None, TreeFile()))
        if has_symlinks():
            self.assertEqual(files[2], ('symlink', '?', 'symlink', None, TreeLink()))

    def test_open_containing(self):
        branch = self.make_branch_and_tree('.').branch
        wt, relpath = WorkingTree.open_containing()
        self.assertEqual('', relpath)
        self.assertEqual(wt.basedir + '/', branch.base)
        wt, relpath = WorkingTree.open_containing(u'.')
        self.assertEqual('', relpath)
        self.assertEqual(wt.basedir + '/', branch.base)
        wt, relpath = WorkingTree.open_containing('./foo')
        self.assertEqual('foo', relpath)
        self.assertEqual(wt.basedir + '/', branch.base)
        wt, relpath = WorkingTree.open_containing('file://' + getcwd() + '/foo')
        self.assertEqual('foo', relpath)
        self.assertEqual(wt.basedir + '/', branch.base)

    def test_basic_relpath(self):
        # for comprehensive relpath tests, see whitebox.py.
        tree = self.make_branch_and_tree('.')
        self.assertEqual('child',
                         tree.relpath(pathjoin(getcwd(), 'child')))

    def test_lock_locks_branch(self):
        tree = self.make_branch_and_tree('.')
        tree.lock_read()
        self.assertEqual('r', tree.branch.peek_lock_mode())
        tree.unlock()
        self.assertEqual(None, tree.branch.peek_lock_mode())
        tree.lock_write()
        self.assertEqual('w', tree.branch.peek_lock_mode())
        tree.unlock()
        self.assertEqual(None, tree.branch.peek_lock_mode())
 
    def test_revert(self):
        """Test selected-file revert"""
        tree = self.make_branch_and_tree('.')

        self.build_tree(['hello.txt'])
        file('hello.txt', 'w').write('initial hello')

        self.assertRaises(NotVersionedError,
                          tree.revert, ['hello.txt'])
        tree.add(['hello.txt'])
        tree.commit('create initial hello.txt')

        self.check_file_contents('hello.txt', 'initial hello')
        file('hello.txt', 'w').write('new hello')
        self.check_file_contents('hello.txt', 'new hello')

        # revert file modified since last revision
        tree.revert(['hello.txt'])
        self.check_file_contents('hello.txt', 'initial hello')
        self.check_file_contents('hello.txt.~1~', 'new hello')

        # reverting again does not clobber the backup
        tree.revert(['hello.txt'])
        self.check_file_contents('hello.txt', 'initial hello')
        self.check_file_contents('hello.txt.~1~', 'new hello')
        
        # backup files are numbered
        file('hello.txt', 'w').write('new hello2')
        tree.revert(['hello.txt'])
        self.check_file_contents('hello.txt', 'initial hello')
        self.check_file_contents('hello.txt.~1~', 'new hello')
        self.check_file_contents('hello.txt.~2~', 'new hello2')

    def test_unknowns(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['hello.txt',
                         'hello.txt.~1~'])
        self.assertEquals(list(tree.unknowns()),
                          ['hello.txt'])

    def test_hashcache(self):
        from bzrlib.tests.test_hashcache import pause
        tree = self.make_branch_and_tree('.')
        self.build_tree(['hello.txt',
                         'hello.txt.~1~'])
        tree.add('hello.txt')
        pause()
        sha = tree.get_file_sha1(tree.path2id('hello.txt'))
        self.assertEqual(1, tree._hashcache.miss_count)
        tree2 = WorkingTree.open('.')
        sha2 = tree2.get_file_sha1(tree2.path2id('hello.txt'))
        self.assertEqual(0, tree2._hashcache.miss_count)
        self.assertEqual(1, tree2._hashcache.hit_count)

    def test_initialize(self):
        # initialize should create a working tree and branch in an existing dir
        t = self.make_branch_and_tree('.')
        b = Branch.open('.')
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

        revid = b.revision_history()[0]
        self.log('first revision_id is {%s}' % revid)
        
        inv = b.repository.get_revision_inventory(revid)
        self.log('contents of inventory: %r' % inv.entries())

        self.check_inventory_shape(inv,
                                   ['dir', 'dir/sub', 'dir/sub/file'])

        wt.rename_one('dir', 'newdir')

        self.check_inventory_shape(wt.read_working_inventory(),
                                   ['newdir', 'newdir/sub', 'newdir/sub/file'])

        wt.rename_one('newdir/sub', 'newdir/newsub')
        self.check_inventory_shape(wt.read_working_inventory(),
                                   ['newdir', 'newdir/newsub',
                                    'newdir/newsub/file'])

    def test_add_in_unversioned(self):
        """Try to add a file in an unversioned directory.

        "bzr add" adds the parent as necessary, but simple working tree add
        doesn't do that.
        """
        from bzrlib.errors import NotVersionedError
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo/',
                         'foo/hello'])
        self.assertRaises(NotVersionedError,
                          wt.add,
                          'foo/hello')

    def test_add_missing(self):
        # adding a msising file -> NoSuchFile
        wt = self.make_branch_and_tree('.')
        self.assertRaises(errors.NoSuchFile, wt.add, 'fpp')

    def test_remove_verbose(self):
        #FIXME the remove api should not print or otherwise depend on the
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
        cloned_dir = wt.bzrdir.clone('target')
        cloned = cloned_dir.open_workingtree()
        self.assertEqual(cloned.last_revision(), wt.last_revision())

    def test_last_revision(self):
        wt = self.make_branch_and_tree('source')
        self.assertEqual(None, wt.last_revision())
        wt.commit('A', allow_pointless=True, rev_id='A')
        self.assertEqual('A', wt.last_revision())

    def test_set_last_revision(self):
        wt = self.make_branch_and_tree('source')
        self.assertEqual(None, wt.last_revision())
        # cannot set the last revision to one not in the branch history.
        self.assertRaises(errors.NoSuchRevision, wt.set_last_revision, 'A')
        wt.commit('A', allow_pointless=True, rev_id='A')
        self.assertEqual('A', wt.last_revision())
        # None is aways in the branch
        wt.set_last_revision(None)
        self.assertEqual(None, wt.last_revision())
        # and now we can set it to 'A'
        # because some formats mutate the branch to set it on the tree
        # we need to alter the branch to let this pass.
        wt.branch.set_revision_history(['A', 'B'])
        wt.set_last_revision('A')
        self.assertEqual('A', wt.last_revision())

    def test_set_last_revision_different_to_branch(self):
        # working tree formats from the meta-dir format and newer support
        # setting the last revision on a tree independently of that on the 
        # branch. Its concievable that some future formats may want to 
        # couple them again (i.e. because its really a smart server and
        # the working tree will always match the branch). So we test
        # that formats where initialising a branch does not initialise a 
        # tree - and thus have separable entities - support skewing the 
        # two things.
        branch = self.make_branch('tree')
        try:
            # if there is a working tree now, this is not supported.
            branch.bzrdir.open_workingtree()
            return
        except errors.NoWorkingTree:
            pass
        wt = branch.bzrdir.create_workingtree()
        wt.commit('A', allow_pointless=True, rev_id='A')
        wt.set_last_revision(None)
        self.assertEqual(None, wt.last_revision())
        self.assertEqual('A', wt.branch.last_revision())
        # and now we can set it back to 'A'
        wt.set_last_revision('A')
        self.assertEqual('A', wt.last_revision())
        self.assertEqual('A', wt.branch.last_revision())

    def test_clone_and_commit_preserves_last_revision(self):
        wt = self.make_branch_and_tree('source')
        cloned_dir = wt.bzrdir.clone('target')
        wt.commit('A', allow_pointless=True, rev_id='A')
        self.assertNotEqual(cloned_dir.open_workingtree().last_revision(),
                            wt.last_revision())

    def test_clone_preserves_content(self):
        wt = self.make_branch_and_tree('source')
        self.build_tree(['added', 'deleted', 'notadded'], transport=wt.bzrdir.transport.clone('..'))
        wt.add('deleted', 'deleted')
        wt.commit('add deleted')
        wt.remove('deleted')
        wt.add('added', 'added')
        cloned_dir = wt.bzrdir.clone('target')
        cloned = cloned_dir.open_workingtree()
        cloned_transport = cloned.bzrdir.transport.clone('..')
        self.assertFalse(cloned_transport.has('deleted'))
        self.assertTrue(cloned_transport.has('added'))
        self.assertFalse(cloned_transport.has('notadded'))
        self.assertEqual('added', cloned.path2id('added'))
        self.assertEqual(None, cloned.path2id('deleted'))
        self.assertEqual(None, cloned.path2id('notadded'))
        
    def test_basis_tree_returns_last_revision(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        wt.add('foo', 'foo-id')
        wt.commit('A', rev_id='A')
        wt.rename_one('foo', 'bar')
        wt.commit('B', rev_id='B')
        wt.set_last_revision('B')
        tree = wt.basis_tree()
        self.failUnless(tree.has_filename('bar'))
        wt.set_last_revision('A')
        tree = wt.basis_tree()
        self.failUnless(tree.has_filename('foo'))

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
        source.commit('a', rev_id='a', allow_pointless=True)
        source.commit('b', rev_id='b', allow_pointless=True)
        self.build_tree(['new/'])
        made_control = self.bzrdir_format.initialize('new')
        source.branch.repository.clone(made_control)
        source.branch.clone(made_control)
        made_tree = self.workingtree_format.initialize(made_control, revision_id='a')
        self.assertEqual('a', made_tree.last_revision())

    def test_commit_sets_last_revision(self):
        tree = self.make_branch_and_tree('tree')
        tree.commit('foo', rev_id='foo', allow_pointless=True)
        self.assertEqual('foo', tree.last_revision())

    def test_commit_local_unbound(self):
        # using the library api to do a local commit on unbound branches is 
        # also an error
        tree = self.make_branch_and_tree('tree')
        self.assertRaises(errors.LocalRequiresBoundBranch,
                          tree.commit,
                          'foo',
                          local=True)
 
    def test_local_commit_ignores_master(self):
        # a --local commit does not require access to the master branch
        # at all, or even for it to exist.
        # we test this by setting up a bound branch and then corrupting
        # the master.
        master = self.make_branch('master')
        tree = self.make_branch_and_tree('tree')
        try:
            tree.branch.bind(master)
        except errors.UpgradeRequired:
            # older format.
            return
        master.bzrdir.transport.put('branch-format', StringIO('garbage'))
        del master
        # check its corrupted.
        self.assertRaises(errors.UnknownFormatError,
                          bzrdir.BzrDir.open,
                          'master')
        tree.commit('foo', rev_id='foo', local=True)
 
    def test_local_commit_does_not_push_to_master(self):
        # a --local commit does not require access to the master branch
        # at all, or even for it to exist.
        # we test that even when its available it does not push to it.
        master = self.make_branch('master')
        tree = self.make_branch_and_tree('tree')
        try:
            tree.branch.bind(master)
        except errors.UpgradeRequired:
            # older format.
            return
        tree.commit('foo', rev_id='foo', local=True)
        self.failIf(master.repository.has_revision('foo'))
        self.assertEqual(None, master.last_revision())
        
    def test_update_sets_last_revision(self):
        # working tree formats from the meta-dir format and newer support
        # setting the last revision on a tree independently of that on the 
        # branch. Its concievable that some future formats may want to 
        # couple them again (i.e. because its really a smart server and
        # the working tree will always match the branch). So we test
        # that formats where initialising a branch does not initialise a 
        # tree - and thus have separable entities - support skewing the 
        # two things.
        main_branch = self.make_branch('tree')
        try:
            # if there is a working tree now, this is not supported.
            main_branch.bzrdir.open_workingtree()
            return
        except errors.NoWorkingTree:
            pass
        wt = main_branch.bzrdir.create_workingtree()
        # create an out of date working tree by making a checkout in this
        # current format
        self.build_tree(['checkout/', 'tree/file'])
        checkout = bzrdir.BzrDirMetaFormat1().initialize('checkout')
        bzrlib.branch.BranchReferenceFormat().initialize(checkout, main_branch)
        old_tree = self.workingtree_format.initialize(checkout)
        # now commit to 'tree'
        wt.add('file')
        wt.commit('A', rev_id='A')
        # and update old_tree
        self.assertEqual(0, old_tree.update())
        self.failUnlessExists('checkout/file')
        self.assertEqual('A', old_tree.last_revision())

    def test_update_returns_conflict_count(self):
        # working tree formats from the meta-dir format and newer support
        # setting the last revision on a tree independently of that on the 
        # branch. Its concievable that some future formats may want to 
        # couple them again (i.e. because its really a smart server and
        # the working tree will always match the branch). So we test
        # that formats where initialising a branch does not initialise a 
        # tree - and thus have separable entities - support skewing the 
        # two things.
        main_branch = self.make_branch('tree')
        try:
            # if there is a working tree now, this is not supported.
            main_branch.bzrdir.open_workingtree()
            return
        except errors.NoWorkingTree:
            pass
        wt = main_branch.bzrdir.create_workingtree()
        # create an out of date working tree by making a checkout in this
        # current format
        self.build_tree(['checkout/', 'tree/file'])
        checkout = bzrdir.BzrDirMetaFormat1().initialize('checkout')
        bzrlib.branch.BranchReferenceFormat().initialize(checkout, main_branch)
        old_tree = self.workingtree_format.initialize(checkout)
        # now commit to 'tree'
        wt.add('file')
        wt.commit('A', rev_id='A')
        # and add a file file to the checkout
        self.build_tree(['checkout/file'])
        old_tree.add('file')
        # and update old_tree
        self.assertEqual(1, old_tree.update())
        self.assertEqual('A', old_tree.last_revision())

    def test_merge_revert(self):
        from bzrlib.merge import merge_inner
        this = self.make_branch_and_tree('b1')
        open('b1/a', 'wb').write('a test\n')
        this.add('a')
        open('b1/b', 'wb').write('b test\n')
        this.add('b')
        this.commit(message='')
        base = this.bzrdir.clone('b2').open_workingtree()
        open('b2/a', 'wb').write('b test\n')
        other = this.bzrdir.clone('b3').open_workingtree()
        open('b3/a', 'wb').write('c test\n')
        open('b3/c', 'wb').write('c test\n')
        other.add('c')

        open('b1/b', 'wb').write('q test\n')
        open('b1/d', 'wb').write('d test\n')
        merge_inner(this.branch, other, base, this_tree=this)
        self.assertNotEqual(open('b1/a', 'rb').read(), 'a test\n')
        this.revert([])
        self.assertEqual(open('b1/a', 'rb').read(), 'a test\n')
        self.assertIs(os.path.exists('b1/b.~1~'), True)
        self.assertIs(os.path.exists('b1/c'), False)
        self.assertIs(os.path.exists('b1/a.~1~'), False)
        self.assertIs(os.path.exists('b1/d'), True)

    def test_update_updates_bound_branch_no_local_commits(self):
        # doing an update in a tree updates the branch its bound to too.
        master_tree = self.make_branch_and_tree('master')
        tree = self.make_branch_and_tree('tree')
        try:
            tree.branch.bind(master_tree.branch)
        except errors.UpgradeRequired:
            # legacy branches cannot bind
            return
        master_tree.commit('foo', rev_id='foo', allow_pointless=True)
        tree.update()
        self.assertEqual('foo', tree.last_revision())
        self.assertEqual('foo', tree.branch.last_revision())

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
        tree = self.make_branch_and_tree('tree')
        try:
            tree.branch.bind(master_tree.branch)
        except errors.UpgradeRequired:
            # legacy branches cannot bind
            return
        tree.commit('foo', rev_id='foo', allow_pointless=True, local=True)
        tree.commit('bar', rev_id='bar', allow_pointless=True, local=True)
        tree.update()
        self.assertEqual(None, tree.last_revision())
        self.assertEqual([], tree.branch.revision_history())
        self.assertEqual(['bar'], tree.pending_merges())

    def test_merge_modified(self):
        tree = self.make_branch_and_tree('master')
        tree._control_files.put('merge-hashes', StringIO('asdfasdf'))
        self.assertRaises(errors.MergeModifiedFormatError, tree.merge_modified)

    def test_conflicts(self):
        from bzrlib.tests.test_conflicts import example_conflicts
        tree = self.make_branch_and_tree('master')
        try:
            tree.set_conflicts(example_conflicts)
        except UnsupportedOperation:
            raise TestSkipped('set_conflicts not supported')
            
        tree2 = WorkingTree.open('master')
        self.assertEqual(tree2.conflicts(), example_conflicts)
        tree2._control_files.put('conflicts', StringIO(''))
        self.assertRaises(errors.ConflictFormatError, 
                          tree2.conflicts)
        tree2._control_files.put('conflicts', StringIO('a'))
        self.assertRaises(errors.ConflictFormatError, 
                          tree2.conflicts)

    def make_merge_conflicts(self):
        from bzrlib.merge import merge_inner 
        tree = self.make_branch_and_tree('mine')
        file('mine/bloo', 'wb').write('one')
        tree.add('bloo')
        file('mine/blo', 'wb').write('on')
        tree.add('blo')
        tree.commit("blah", allow_pointless=False)
        base = tree.basis_tree()
        BzrDir.open("mine").sprout("other")
        file('other/bloo', 'wb').write('two')
        othertree = WorkingTree.open('other')
        othertree.commit('blah', allow_pointless=False)
        file('mine/bloo', 'wb').write('three')
        tree.commit("blah", allow_pointless=False)
        merge_inner(tree.branch, othertree, base, this_tree=tree)
        return tree

    def test_merge_conflicts(self):
        tree = self.make_merge_conflicts()
        self.assertEqual(len(tree.conflicts()), 1)

    def test_clear_merge_conflicts(self):
        from bzrlib.conflicts import ConflictList
        tree = self.make_merge_conflicts()
        self.assertEqual(len(tree.conflicts()), 1)
        try:
            tree.set_conflicts(ConflictList())
        except UnsupportedOperation:
            raise TestSkipped
        self.assertEqual(tree.conflicts(), ConflictList())

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
        tree.revert([])
        self.assertEqual(len(tree.conflicts()), 0)

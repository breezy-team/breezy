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
from bzrlib.branch import Branch
import bzrlib.bzrdir as bzrdir
from bzrlib.bzrdir import BzrDir
import bzrlib.errors as errors
from bzrlib.errors import NotBranchError, NotVersionedError
from bzrlib.osutils import pathjoin, getcwd, has_symlinks
from bzrlib.tests import TestCaseWithTransport, TestSkipped
from bzrlib.trace import mutter
from bzrlib.transport import get_transport
import bzrlib.workingtree as workingtree
from bzrlib.workingtree import (TreeEntry, TreeDirectory, TreeFile, TreeLink,
                                WorkingTree)


class TestCaseWithWorkingTree(TestCaseWithTransport):

    def make_bzrdir(self, relpath):
        # todo factor out into bzrdir-using-implementations-tests-base-class
        try:
            url = self.get_url(relpath)
            segments = url.split('/')
            if segments and segments[-1] not in ('', '.'):
                parent = '/'.join(segments[:-1])
                t = get_transport(parent)
                try:
                    t.mkdir(segments[-1])
                except errors.FileExists:
                    pass
            return self.bzrdir_format.initialize(url)
        except errors.UninitializableFormat:
            raise TestSkipped("Format %s is not initializable.")

    def make_branch_and_tree(self, relpath):
        made_control = self.make_bzrdir(relpath)
        made_control.create_repository()
        made_control.create_branch()
        return self.workingtree_format.initialize(made_control)


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

    def test_construct_with_branch(self):
        branch = self.make_branch_and_tree('.').branch
        tree = WorkingTree(branch.base, branch)
        self.assertEqual(branch, tree.branch)
        self.assertEqual(branch.base, tree.basedir + '/')
    
    def test_construct_without_branch(self):
        branch = self.make_branch_and_tree('.').branch
        tree = WorkingTree(branch.base)
        self.assertEqual(branch.base, tree.branch.base)
        self.assertEqual(branch.base, tree.basedir + '/')

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
 
    def get_pullable_trees(self):
        self.build_tree(['from/', 'from/file', 'to/'])
        tree = self.make_branch_and_tree('from')
        tree.add('file')
        tree.commit('foo', rev_id='A')
        tree_b = self.make_branch_and_tree('to')
        return tree, tree_b
 
    def test_pull(self):
        tree_a, tree_b = self.get_pullable_trees()
        tree_b.pull(tree_a.branch)
        self.failUnless(tree_b.branch.repository.has_revision('A'))
        self.assertEqual('A', tree_b.last_revision())

    def test_pull_overwrites(self):
        tree_a, tree_b = self.get_pullable_trees()
        tree_b.commit('foo', rev_id='B')
        self.assertEqual(['B'], tree_b.branch.revision_history())
        tree_b.pull(tree_a.branch, overwrite=True)
        self.failUnless(tree_b.branch.repository.has_revision('A'))
        self.failUnless(tree_b.branch.repository.has_revision('B'))
        self.assertEqual('A', tree_b.last_revision())

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
        self.check_file_contents('hello.txt~', 'new hello')

        # reverting again does not clobber the backup
        tree.revert(['hello.txt'])
        self.check_file_contents('hello.txt', 'initial hello')
        self.check_file_contents('hello.txt~', 'new hello')

    def test_unknowns(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['hello.txt',
                         'hello.txt~'])
        self.assertEquals(list(tree.unknowns()),
                          ['hello.txt'])

    def test_hashcache(self):
        from bzrlib.tests.test_hashcache import pause
        tree = self.make_branch_and_tree('.')
        self.build_tree(['hello.txt',
                         'hello.txt~'])
        tree.add('hello.txt')
        pause()
        sha = tree.get_file_sha1(tree.path2id('hello.txt'))
        self.assertEqual(1, tree._hashcache.miss_count)
        tree2 = WorkingTree('.', tree.branch)
        sha2 = tree2.get_file_sha1(tree2.path2id('hello.txt'))
        self.assertEqual(0, tree2._hashcache.miss_count)
        self.assertEqual(1, tree2._hashcache.hit_count)

    def test_initialize(self):
        # initialize should create a working tree and branch in an existing dir
        t = self.make_branch_and_tree('.')
        b = Branch.open('.')
        self.assertEqual(t.branch.base, b.base)
        t2 = WorkingTree('.')
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
        # cannot set the last revision to one not in the branch
        self.assertRaises(errors.NoSuchRevision, wt.set_last_revision, 'A')
        wt.commit('A', allow_pointless=True, rev_id='A')
        self.assertEqual('A', wt.last_revision())
        # None is aways in the branch
        wt.set_last_revision(None)
        self.assertEqual(None, wt.last_revision())
        # and now we can set it to 'A'
        # because the current format mutates the branch to set it on the tree
        # we need to alter the branch to let this pass.
        wt.branch.set_revision_history(['A', 'B'])
        wt.set_last_revision('A')
        self.assertEqual('A', wt.last_revision())

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

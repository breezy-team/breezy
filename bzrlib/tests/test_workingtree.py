# (C) 2005 Canonical Ltd
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
from bzrlib.errors import NotBranchError, NotVersionedError
from bzrlib.tests import TestCaseWithTransport
from bzrlib.trace import mutter
from bzrlib.osutils import pathjoin, getcwd, has_symlinks
from bzrlib.workingtree import (TreeEntry, TreeDirectory, TreeFile, TreeLink,
                                WorkingTree)

class TestTreeDirectory(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeDirectory().kind_character(), '/')


class TestTreeEntry(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeEntry().kind_character(), '???')


class TestTreeFile(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeFile().kind_character(), '')


class TestTreeLink(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeLink().kind_character(), '')


class TestWorkingTree(TestCaseWithTransport):

    def test_listfiles(self):
        tree = WorkingTree.create_standalone('.')
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
        branch = WorkingTree.create_standalone('.').branch
        wt, relpath = WorkingTree.open_containing()
        self.assertEqual('', relpath)
        self.assertEqual(wt.basedir + '/', branch.base)
        wt, relpath = WorkingTree.open_containing(u'.')
        self.assertEqual('', relpath)
        self.assertEqual(wt.basedir + '/', branch.base)
        wt, relpath = WorkingTree.open_containing('./foo')
        self.assertEqual('foo', relpath)
        self.assertEqual(wt.basedir + '/', branch.base)
        # paths that are urls are just plain wrong for working trees.
        self.assertRaises(NotBranchError,
                          WorkingTree.open_containing, 
                          'file:///' + getcwd())

    def test_construct_with_branch(self):
        branch = WorkingTree.create_standalone('.').branch
        tree = WorkingTree(branch.base, branch)
        self.assertEqual(branch, tree.branch)
        self.assertEqual(branch.base, tree.basedir + '/')
    
    def test_construct_without_branch(self):
        branch = WorkingTree.create_standalone('.').branch
        tree = WorkingTree(branch.base)
        self.assertEqual(branch.base, tree.branch.base)
        self.assertEqual(branch.base, tree.basedir + '/')

    def test_basic_relpath(self):
        # for comprehensive relpath tests, see whitebox.py.
        tree = WorkingTree.create_standalone('.')
        self.assertEqual('child',
                         tree.relpath(pathjoin(getcwd(), 'child')))

    def test_lock_locks_branch(self):
        tree = WorkingTree.create_standalone('.')
        tree.lock_read()
        self.assertEqual(1, tree.branch._lock_count)
        self.assertEqual('r', tree.branch._lock_mode)
        tree.unlock()
        self.assertEqual(None, tree.branch._lock_count)
        tree.lock_write()
        self.assertEqual(1, tree.branch._lock_count)
        self.assertEqual('w', tree.branch._lock_mode)
        tree.unlock()
        self.assertEqual(None, tree.branch._lock_count)
 
    def get_pullable_trees(self):
        self.build_tree(['from/', 'from/file', 'to/'])
        tree = WorkingTree.create_standalone('from')
        tree.add('file')
        tree.commit('foo', rev_id='A')
        tree_b = WorkingTree.create_standalone('to')
        return tree, tree_b
 
    def test_pull(self):
        tree_a, tree_b = self.get_pullable_trees()
        tree_b.pull(tree_a.branch)
        self.failUnless(tree_b.branch.has_revision('A'))
        self.assertEqual(['A'], tree_b.branch.revision_history())

    def test_pull_overwrites(self):
        tree_a, tree_b = self.get_pullable_trees()
        tree_b.commit('foo', rev_id='B')
        self.assertEqual(['B'], tree_b.branch.revision_history())
        tree_b.pull(tree_a.branch, overwrite=True)
        self.failUnless(tree_b.branch.has_revision('A'))
        self.failUnless(tree_b.branch.has_revision('B'))
        self.assertEqual(['A'], tree_b.branch.revision_history())

    def test_revert(self):
        """Test selected-file revert"""
        tree = WorkingTree.create_standalone('.')

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
        tree = WorkingTree.create_standalone('.')
        self.build_tree(['hello.txt',
                         'hello.txt~'])
        self.assertEquals(list(tree.unknowns()),
                          ['hello.txt'])

    def test_hashcache(self):
        from bzrlib.tests.test_hashcache import pause
        tree = WorkingTree.create_standalone('.')
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

    def test_checkout(self):
        # at this point as we dont have checkout versions, checkout simply
        # populates the required files for a working tree at the dir.
        self.build_tree(['branch/'])
        b = Branch.create('branch')
        t = WorkingTree.create(b, 'tree')
        # as we are moving the ownership to working tree, we will check here
        # that its split out correctly
        self.failIfExists('branch/.bzr/inventory')
        self.failIfExists('branch/.bzr/pending-merges')
        sio = StringIO()
        bzrlib.xml5.serializer_v5.write_inventory(bzrlib.inventory.Inventory(),
                                                  sio)
        self.assertFileEqual(sio.getvalue(), 'tree/.bzr/inventory')
        self.assertFileEqual('', 'tree/.bzr/pending-merges')

    def test_initialize(self):
        # initialize should create a working tree and branch in an existing dir
        t = WorkingTree.create_standalone('.')
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
        
        inv = b.get_revision_inventory(revid)
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

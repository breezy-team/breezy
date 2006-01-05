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

import os
from bzrlib.branch import Branch
from bzrlib.errors import NotBranchError, NotVersionedError
from bzrlib.tests import TestCaseInTempDir
from bzrlib.trace import mutter
from bzrlib.osutils import pathjoin, getcwd, has_symlinks
from bzrlib.workingtree import (TreeEntry, TreeDirectory, TreeFile, TreeLink,
                                WorkingTree)

class TestTreeDirectory(TestCaseInTempDir):

    def test_kind_character(self):
        self.assertEqual(TreeDirectory().kind_character(), '/')


class TestTreeEntry(TestCaseInTempDir):

    def test_kind_character(self):
        self.assertEqual(TreeEntry().kind_character(), '???')


class TestTreeFile(TestCaseInTempDir):

    def test_kind_character(self):
        self.assertEqual(TreeFile().kind_character(), '')


class TestTreeLink(TestCaseInTempDir):

    def test_kind_character(self):
        self.assertEqual(TreeLink().kind_character(), '')


class TestWorkingTree(TestCaseInTempDir):

    def test_listfiles(self):
        branch = Branch.initialize(u'.')
        os.mkdir('dir')
        print >> open('file', 'w'), "content"
        if has_symlinks():
            os.symlink('target', 'symlink')
        tree = branch.working_tree()
        files = list(tree.list_files())
        self.assertEqual(files[0], ('dir', '?', 'directory', None, TreeDirectory()))
        self.assertEqual(files[1], ('file', '?', 'file', None, TreeFile()))
        if has_symlinks():
            self.assertEqual(files[2], ('symlink', '?', 'symlink', None, TreeLink()))

    def test_open_containing(self):
        branch = Branch.initialize(u'.')
        wt, relpath = WorkingTree.open_containing()
        self.assertEqual('', relpath)
        self.assertEqual(wt.basedir, branch.base)
        wt, relpath = WorkingTree.open_containing(u'.')
        self.assertEqual('', relpath)
        self.assertEqual(wt.basedir, branch.base)
        wt, relpath = WorkingTree.open_containing('./foo')
        self.assertEqual('foo', relpath)
        self.assertEqual(wt.basedir, branch.base)
        # paths that are urls are just plain wrong for working trees.
        self.assertRaises(NotBranchError,
                          WorkingTree.open_containing, 
                          'file:///' + getcwd())

    def test_construct_with_branch(self):
        branch = Branch.initialize(u'.')
        tree = WorkingTree(branch.base, branch)
        self.assertEqual(branch, tree.branch)
        self.assertEqual(branch.base, tree.basedir)
    
    def test_construct_without_branch(self):
        branch = Branch.initialize(u'.')
        tree = WorkingTree(branch.base)
        self.assertEqual(branch.base, tree.branch.base)
        self.assertEqual(branch.base, tree.basedir)

    def test_basic_relpath(self):
        # for comprehensive relpath tests, see whitebox.py.
        branch = Branch.initialize(u'.')
        tree = WorkingTree(branch.base)
        self.assertEqual('child',
                         tree.relpath(pathjoin(getcwd(), 'child')))

    def test_lock_locks_branch(self):
        # FIXME RBC 20060105 this should test that the branch
        # is locked without peeking at control files.
        # ie. via a mock branch.
        branch = Branch.initialize(u'.')
        tree = WorkingTree(branch.base)
        tree.lock_read()
        self.assertEqual(1, tree.branch.control_files._lock_count)
        self.assertEqual('r', tree.branch.control_files._lock_mode)
        tree.unlock()
        self.assertEqual(None, tree.branch.control_files._lock_count)
        tree.lock_write()
        self.assertEqual(1, tree.branch.control_files._lock_count)
        self.assertEqual('w', tree.branch.control_files._lock_mode)
        tree.unlock()
        self.assertEqual(None, tree.branch.control_files._lock_count)
 
    def get_pullable_branches(self):
        self.build_tree(['from/', 'from/file', 'to/'])
        br_a = Branch.initialize('from')
        tree = br_a.working_tree()
        tree.add('file')
        tree.commit('foo', rev_id='A')
        br_b = Branch.initialize('to')
        return br_a, br_b
 
    def test_pull(self):
        br_a, br_b = self.get_pullable_branches()
        br_b.working_tree().pull(br_a)
        self.failUnless(br_b.repository.has_revision('A'))
        self.assertEqual(['A'], br_b.revision_history())

    def test_pull_overwrites(self):
        br_a, br_b = self.get_pullable_branches()
        br_b.working_tree().commit('foo', rev_id='B')
        self.assertEqual(['B'], br_b.revision_history())
        br_b.working_tree().pull(br_a, overwrite=True)
        self.failUnless(br_b.repository.has_revision('A'))
        self.failUnless(br_b.repository.has_revision('B'))
        self.assertEqual(['A'], br_b.revision_history())

    def test_revert(self):
        """Test selected-file revert"""
        b = Branch.initialize(u'.')

        self.build_tree(['hello.txt'])
        file('hello.txt', 'w').write('initial hello')

        self.assertRaises(NotVersionedError,
                          b.working_tree().revert, ['hello.txt'])
        tree = WorkingTree(b.base, b)
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
        b = Branch.initialize(u'.')
        tree = WorkingTree(u'.', b)
        self.build_tree(['hello.txt',
                         'hello.txt~'])
        self.assertEquals(list(tree.unknowns()),
                          ['hello.txt'])

    def test_hashcache(self):
        from bzrlib.tests.test_hashcache import pause
        b = Branch.initialize(u'.')
        tree = WorkingTree(u'.', b)
        self.build_tree(['hello.txt',
                         'hello.txt~'])
        tree.add('hello.txt')
        pause()
        sha = tree.get_file_sha1(tree.path2id('hello.txt'))
        self.assertEqual(1, tree._hashcache.miss_count)
        tree2 = WorkingTree(u'.', b)
        sha2 = tree2.get_file_sha1(tree2.path2id('hello.txt'))
        self.assertEqual(0, tree2._hashcache.miss_count)
        self.assertEqual(1, tree2._hashcache.hit_count)

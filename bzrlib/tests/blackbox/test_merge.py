# Copyright (C) 2006 Canonical Ltd
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
#
# Author: Aaron Bentley <aaron.bentley@utoronto.ca>

"""Black-box tests for bzr merge.
"""

import os

from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.osutils import abspath
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree


class TestMerge(ExternalBase):

    def example_branch(test):
        test.runbzr('init')
        file('hello', 'wt').write('foo')
        test.runbzr('add hello')
        test.runbzr('commit -m setup hello')
        file('goodbye', 'wt').write('baz')
        test.runbzr('add goodbye')
        test.runbzr('commit -m setup goodbye')

    def test_merge_reprocess(self):
        d = BzrDir.create_standalone_workingtree('.')
        d.commit('h')
        self.run_bzr('merge', '.', '--reprocess', '--merge-type', 'weave')

    def test_merge(self):
        from bzrlib.branch import Branch
        
        os.mkdir('a')
        os.chdir('a')
        self.example_branch()
        os.chdir('..')
        self.runbzr('branch a b')
        os.chdir('b')
        file('goodbye', 'wt').write('quux')
        self.runbzr(['commit',  '-m',  "more u's are always good"])

        os.chdir('../a')
        file('hello', 'wt').write('quuux')
        # We can't merge when there are in-tree changes
        self.runbzr('merge ../b', retcode=3)
        self.runbzr(['commit', '-m', "Like an epidemic of u's"])
        self.runbzr('merge ../b -r last:1..last:1 --merge-type blooof',
                    retcode=3)
        self.runbzr('merge ../b -r last:1..last:1 --merge-type merge3')
        self.runbzr('revert --no-backup')
        self.runbzr('merge ../b -r last:1..last:1 --merge-type weave')
        self.runbzr('revert --no-backup')
        self.runbzr('merge ../b -r last:1..last:1 --reprocess')
        self.runbzr('revert --no-backup')
        self.runbzr('merge ../b -r last:1')
        self.check_file_contents('goodbye', 'quux')
        # Merging a branch pulls its revision into the tree
        a = WorkingTree.open('.')
        b = Branch.open('../b')
        a.branch.repository.get_revision_xml(b.last_revision())
        self.log('pending merges: %s', a.pending_merges())
        self.assertEquals(a.pending_merges(),
                          [b.last_revision()])
        self.runbzr('commit -m merged')
        self.runbzr('merge ../b -r last:1')
        self.assertEqual(a.pending_merges(), [])

    def test_merge_with_missing_file(self):
        """Merge handles missing file conflicts"""
        os.mkdir('a')
        os.chdir('a')
        os.mkdir('sub')
        print >> file('sub/a.txt', 'wb'), "hello"
        print >> file('b.txt', 'wb'), "hello"
        print >> file('sub/c.txt', 'wb'), "hello"
        self.runbzr('init')
        self.runbzr('add')
        self.runbzr(('commit', '-m', 'added a'))
        self.runbzr('branch . ../b')
        print >> file('sub/a.txt', 'ab'), "there"
        print >> file('b.txt', 'ab'), "there"
        print >> file('sub/c.txt', 'ab'), "there"
        self.runbzr(('commit', '-m', 'Added there'))
        os.unlink('sub/a.txt')
        os.unlink('sub/c.txt')
        os.rmdir('sub')
        os.unlink('b.txt')
        self.runbzr(('commit', '-m', 'Removed a.txt'))
        os.chdir('../b')
        print >> file('sub/a.txt', 'ab'), "something"
        print >> file('b.txt', 'ab'), "something"
        print >> file('sub/c.txt', 'ab'), "something"
        self.runbzr(('commit', '-m', 'Modified a.txt'))
        self.runbzr('merge ../a/', retcode=1)
        self.assert_(os.path.exists('sub/a.txt.THIS'))
        self.assert_(os.path.exists('sub/a.txt.BASE'))
        os.chdir('../a')
        self.runbzr('merge ../b/', retcode=1)
        self.assert_(os.path.exists('sub/a.txt.OTHER'))
        self.assert_(os.path.exists('sub/a.txt.BASE'))

    def test_merge_remember(self):
        """Merge changes from one branch to another and test parent location."""
        tree_a = self.make_branch_and_tree('branch_a')
        branch_a = tree_a.branch
        self.build_tree(['branch_a/a'])
        tree_a.add('a')
        tree_a.commit('commit a')
        branch_b = branch_a.bzrdir.sprout('branch_b').open_branch()
        tree_b = branch_b.bzrdir.open_workingtree()
        branch_c = branch_a.bzrdir.sprout('branch_c').open_branch()
        tree_c = branch_c.bzrdir.open_workingtree()
        self.build_tree(['branch_a/b'])
        tree_a.add('b')
        tree_a.commit('commit b')
        self.build_tree(['branch_c/c'])
        tree_c.add('c')
        tree_c.commit('commit c')
        # reset parent
        parent = branch_b.get_parent()
        branch_b.set_parent(None)
        self.assertEqual(None, branch_b.get_parent())
        # test merge for failure without parent set
        os.chdir('branch_b')
        out = self.runbzr('merge', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: No merge branch known or specified.\n'))
        # test implicit --remember when no parent set, this merge conflicts
        self.build_tree(['d'])
        tree_b.add('d')
        out = self.runbzr('merge ../branch_a', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: Working tree has uncommitted changes.\n'))
        self.assertEquals(abspath(branch_b.get_parent()), abspath(parent))
        # test implicit --remember after resolving conflict
        tree_b.commit('commit d')
        out, err = self.runbzr('merge')
        self.assertEquals(out, 'Using saved branch: ../branch_a\n')
        self.assertEquals(err, 'All changes applied successfully.\n')
        self.assertEquals(abspath(branch_b.get_parent()), abspath(parent))
        # re-open tree as external runbzr modified it
        tree_b = branch_b.bzrdir.open_workingtree()
        tree_b.commit('merge branch_a')
        # test explicit --remember
        out, err = self.runbzr('merge ../branch_c --remember')
        self.assertEquals(out, '')
        self.assertEquals(err, 'All changes applied successfully.\n')
        self.assertEquals(abspath(branch_b.get_parent()),
                          abspath(branch_c.bzrdir.root_transport.base))
        # re-open tree as external runbzr modified it
        tree_b = branch_b.bzrdir.open_workingtree()
        tree_b.commit('merge branch_c')

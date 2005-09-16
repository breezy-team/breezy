# Copyright (C) 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


import os

from bzrlib.selftest import TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.commit import Commit
from bzrlib.errors import PointlessCommit, BzrError


# TODO: Test commit with some added, and added-but-missing files

class TestCommit(TestCaseInTempDir):
    def test_simple_commit(self):
        """Commit and check two versions of a single file."""
        b = Branch('.', init=True)
        file('hello', 'w').write('hello world')
        b.add('hello')
        b.commit(message='add hello')
        file_id = b.working_tree().path2id('hello')

        file('hello', 'w').write('version 2')
        b.commit(message='commit 2')

        eq = self.assertEquals
        eq(b.revno(), 2)
        rh = b.revision_history()
        rev = b.get_revision(rh[0])
        eq(rev.message, 'add hello')

        tree1 = b.revision_tree(rh[0])
        text = tree1.get_file_text(file_id)
        eq(text, 'hello world')

        tree2 = b.revision_tree(rh[1])
        eq(tree2.get_file_text(file_id), 'version 2')


    def test_delete_commit(self):
        """Test a commit with a deleted file"""
        b = Branch('.', init=True)
        file('hello', 'w').write('hello world')
        b.add(['hello'], ['hello-id'])
        b.commit(message='add hello')

        os.remove('hello')
        b.commit('removed hello', rev_id='rev2')

        tree = b.revision_tree('rev2')
        self.assertFalse(tree.has_id('hello-id'))


    def test_pointless_commit(self):
        """Commit refuses unless there are changes or it's forced."""
        b = Branch('.', init=True)
        file('hello', 'w').write('hello')
        b.add(['hello'])
        b.commit(message='add hello')
        self.assertEquals(b.revno(), 1)
        self.assertRaises(PointlessCommit,
                          b.commit,
                          message='fails',
                          allow_pointless=False)
        self.assertEquals(b.revno(), 1)
        


    def test_commit_empty(self):
        """Commiting an empty tree works."""
        b = Branch('.', init=True)
        b.commit(message='empty tree', allow_pointless=True)
        self.assertRaises(PointlessCommit,
                          b.commit,
                          message='empty tree',
                          allow_pointless=False)
        b.commit(message='empty tree', allow_pointless=True)
        self.assertEquals(b.revno(), 2)


    def test_selective_delete(self):
        """Selective commit in tree with deletions"""
        b = Branch('.', init=True)
        file('hello', 'w').write('hello')
        file('buongia', 'w').write('buongia')
        b.add(['hello', 'buongia'],
              ['hello-id', 'buongia-id'])
        b.commit(message='add files',
                 rev_id='test@rev-1')
        
        os.remove('hello')
        file('buongia', 'w').write('new text')
        b.commit(message='update text',
                 specific_files=['buongia'],
                 allow_pointless=False,
                 rev_id='test@rev-2')

        b.commit(message='remove hello',
                 specific_files=['hello'],
                 allow_pointless=False,
                 rev_id='test@rev-3')

        eq = self.assertEquals
        eq(b.revno(), 3)

        tree2 = b.revision_tree('test@rev-2')
        self.assertTrue(tree2.has_filename('hello'))
        self.assertEquals(tree2.get_file_text('hello-id'), 'hello')
        self.assertEquals(tree2.get_file_text('buongia-id'), 'new text')
        
        tree3 = b.revision_tree('test@rev-3')
        self.assertFalse(tree3.has_filename('hello'))
        self.assertEquals(tree3.get_file_text('buongia-id'), 'new text')


    def test_commit_rename(self):
        """Test commit of a revision where a file is renamed."""
        b = Branch('.', init=True)
        self.build_tree(['hello'])
        b.add(['hello'], ['hello-id'])
        b.commit(message='one', rev_id='test@rev-1', allow_pointless=False)

        b.rename_one('hello', 'fruity')
        b.commit(message='renamed', rev_id='test@rev-2', allow_pointless=False)

        tree1 = b.revision_tree('test@rev-1')
        self.assertEquals(tree1.id2path('hello-id'), 'hello')
        self.assertEquals(tree1.get_file_text('hello-id'), 'contents of hello\n')
        self.assertFalse(tree1.has_filename('fruity'))
        self.check_inventory_shape(tree1.inventory, ['hello'])

        tree2 = b.revision_tree('test@rev-2')
        self.assertEquals(tree2.id2path('hello-id'), 'fruity')
        self.assertEquals(tree2.get_file_text('hello-id'), 'contents of hello\n')
        self.check_inventory_shape(tree2.inventory, ['fruity'])


    def test_reused_rev_id(self):
        """Test that a revision id cannot be reused in a branch"""
        b = Branch('.', init=True)
        b.commit('initial', rev_id='test@rev-1', allow_pointless=True)
        self.assertRaises(Exception,
                          b.commit,
                          message='reused id',
                          rev_id='test@rev-1',
                          allow_pointless=True)
                          


    def test_commit_move(self):
        """Test commit of revisions with moved files and directories"""
        b = Branch('.', init=True)
        self.build_tree(['hello', 'a/', 'b/'])
        b.add(['hello', 'a', 'b'], ['hello-id', 'a-id', 'b-id'])
        b.commit('initial', rev_id='test@rev-1', allow_pointless=False)

        b.move(['hello'], 'a')
        b.commit('two', rev_id='test@rev-2', allow_pointless=False)
        self.check_inventory_shape(b.inventory,
                                   ['a', 'a/hello', 'b'])

        b.move(['b'], 'a')
        b.commit('three', rev_id='test@rev-3', allow_pointless=False)
        self.check_inventory_shape(b.inventory,
                                   ['a', 'a/hello', 'a/b'])
        self.check_inventory_shape(b.get_revision_inventory('test@rev-3'),
                                   ['a', 'a/hello', 'a/b'])

        b.move([os.sep.join(['a', 'hello'])],
               os.sep.join(['a', 'b']))
        b.commit('four', rev_id='test@rev-4', allow_pointless=False)
        self.check_inventory_shape(b.inventory,
                                   ['a', 'a/b/hello', 'a/b'])
        
        
        

    def test_removed_commit(self):
        """Test a commit with a removed file"""
        b = Branch('.', init=True)
        file('hello', 'w').write('hello world')
        b.add(['hello'], ['hello-id'])
        b.commit(message='add hello')

        b.remove('hello')
        b.commit('removed hello', rev_id='rev2')

        tree = b.revision_tree('rev2')
        self.assertFalse(tree.has_id('hello-id'))


    def test_committed_ancestry(self):
        """Test commit appends revisions to ancestry."""
        b = Branch('.', init=True)
        rev_ids = []
        for i in range(4):
            file('hello', 'w').write((str(i) * 4) + '\n')
            if i == 0:
                b.add(['hello'], ['hello-id'])
            rev_id = 'test@rev-%d' % (i+1)
            rev_ids.append(rev_id)
            b.commit(message='rev %d' % (i+1),
                     rev_id=rev_id)
        eq = self.assertEquals
        eq(b.revision_history(), rev_ids)
        for i in range(4):
            anc = b.get_ancestry(rev_ids[i])
            eq(anc, rev_ids[:i+1])
            
        


if __name__ == '__main__':
    import unittest
    unittest.main()
    

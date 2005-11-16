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


"""Tests of simple versioning operations"""

# TODO: test trying to commit within a directory that is not yet added


import os

from bzrlib.selftest import BzrTestBase, TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.trace import mutter


class TestVersioning(TestCaseInTempDir):
    
    def test_mkdir(self): 
        """Basic 'bzr mkdir' operation"""

        self.run_bzr('init')
        self.run_bzr('mkdir', 'foo')
        self.assert_(os.path.isdir('foo'))

        self.run_bzr('mkdir', 'foo', retcode=3)

        from bzrlib.diff import compare_trees
        from bzrlib.branch import Branch
        b = Branch.open('.')
        
        delta = compare_trees(b.basis_tree(), b.working_tree())

        self.log('delta.added = %r' % delta.added)

        self.assertEquals(len(delta.added), 1)
        self.assertEquals(delta.added[0][0], 'foo')
        self.failIf(delta.modified)

    def test_branch_add_in_unversioned(self):
        """Try to add a file in an unversioned directory.

        "bzr add" adds the parent as necessary, but simple branch add
        doesn't do that.
        """
        from bzrlib.branch import Branch
        from bzrlib.errors import NotVersionedError

        b = Branch.initialize('.')

        self.build_tree(['foo/',
                         'foo/hello'])

        self.assertRaises(NotVersionedError,
                          b.add,
                          'foo/hello')
        
        self.check_branch()

    def test_add_in_unversioned(self):
        """Try to add a file in an unversioned directory.

        "bzr add" should add the parent(s) as necessary.
        """
        from bzrlib.branch import Branch
        eq = self.assertEqual

        b = Branch.initialize('.')

        self.build_tree(['inertiatic/', 'inertiatic/esp'])
        eq(list(b.unknowns()), ['inertiatic'])
        self.run_bzr('add', 'inertiatic/esp')
        eq(list(b.unknowns()), [])

        # Multiple unversioned parents
        self.build_tree(['veil/', 'veil/cerpin/', 'veil/cerpin/taxt'])
        eq(list(b.unknowns()), ['veil'])
        self.run_bzr('add', 'veil/cerpin/taxt')
        eq(list(b.unknowns()), [])

        # Check whacky paths work
        self.build_tree(['cicatriz/', 'cicatriz/esp'])
        eq(list(b.unknowns()), ['cicatriz'])
        self.run_bzr('add', 'inertiatic/../cicatriz/esp')
        eq(list(b.unknowns()), [])

    def test_add_in_versioned(self):
        """Try to add a file in a versioned directory.

        "bzr add" should do this happily.
        """
        from bzrlib.branch import Branch
        eq = self.assertEqual

        b = Branch.initialize('.')

        self.build_tree(['inertiatic/', 'inertiatic/esp'])
        eq(list(b.unknowns()), ['inertiatic'])
        self.run_bzr('add', '--no-recurse', 'inertiatic')
        eq(list(b.unknowns()), ['inertiatic'+os.sep+'esp'])
        self.run_bzr('add', 'inertiatic/esp')
        eq(list(b.unknowns()), [])

    def test_subdir_add(self):
        """Add in subdirectory should add only things from there down"""
        
        from bzrlib.branch import Branch
        
        eq = self.assertEqual
        ass = self.assert_
        chdir = os.chdir
        
        b = Branch.initialize('.')
        t = b.working_tree()
        self.build_tree(['src/', 'README'])
        
        eq(sorted(b.unknowns()),
           ['README', 'src'])
        
        self.run_bzr('add', 'src')
        
        self.build_tree(['src/foo.c'])
        
        chdir('src')
        self.run_bzr('add')
        
        eq(sorted(b.unknowns()), 
           ['README'])
        eq(len(t.read_working_inventory()), 3)
                
        chdir('..')
        self.run_bzr('add')
        eq(list(b.unknowns()), [])

        self.check_branch()

    def check_branch(self):
        """After all the above changes, run the check and upgrade commands.

        The upgrade should be a no-op."""
        b = Branch.open('.')
        mutter('branch has %d revisions', b.revno())
        
        mutter('check branch...')
        from bzrlib.check import check
        check(b, False)
        

        
class SubdirCommit(TestCaseInTempDir):

    def test_subdir_commit(self):
        """Test committing a subdirectory, and committing within a directory."""
        run_bzr = self.run_bzr
        eq = self.assertEqual

        self.build_tree(['a/', 'b/'])
        
        run_bzr('init')
        b = Branch.open('.')
        
        for fn in ('a/one', 'b/two', 'top'):
            file(fn, 'w').write('old contents')
            
        run_bzr('add')
        run_bzr('commit', '-m', 'first revision')
        
        for fn in ('a/one', 'b/two', 'top'):
            file(fn, 'w').write('new contents')
            
        mutter('start selective subdir commit')
        run_bzr('commit', 'a', '-m', 'commit a only')
        
        old = b.revision_tree(b.get_rev_id(1))
        new = b.revision_tree(b.get_rev_id(2))
        
        eq(new.get_file_by_path('b/two').read(), 'old contents')
        eq(new.get_file_by_path('top').read(), 'old contents')
        eq(new.get_file_by_path('a/one').read(), 'new contents')
        
        os.chdir('a')
        # commit from here should do nothing
        run_bzr('commit', '.', '-m', 'commit subdir only', '--unchanged')
        v3 = b.revision_tree(b.get_rev_id(3))
        eq(v3.get_file_by_path('b/two').read(), 'old contents')
        eq(v3.get_file_by_path('top').read(), 'old contents')
        eq(v3.get_file_by_path('a/one').read(), 'new contents')
                
        # commit in subdirectory commits whole tree
        run_bzr('commit', '-m', 'commit whole tree from subdir')
        v4 = b.revision_tree(b.get_rev_id(4))
        eq(v4.get_file_by_path('b/two').read(), 'new contents')        
        eq(v4.get_file_by_path('top').read(), 'new contents')
        
        # TODO: factor out some kind of assert_tree_state() method
        

if __name__ == '__main__':
    import unittest
    unittest.main()
    

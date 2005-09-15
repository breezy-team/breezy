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

# TODO: test adding a file whose directory is not versioned
# TODO: test trying to commit within a directory that is not yet added


import os

from bzrlib.selftest import BzrTestBase, TestCaseInTempDir
from bzrlib.branch import Branch

import logging
logger = logging.getLogger('bzr.test.versioning')
debug = logger.debug


class TestVersioning(TestCaseInTempDir):
    
    def test_mkdir(self): 
        """Basic 'bzr mkdir' operation"""
        from bzrlib.commands import run_bzr

        run_bzr(['init'])
        run_bzr(['mkdir', 'foo'])
        self.assert_(os.path.isdir('foo'))

        self.assertRaises(OSError, run_bzr, ['mkdir', 'foo'])

        from bzrlib.diff import compare_trees
        from bzrlib.branch import Branch
        b = Branch('.')
        
        delta = compare_trees(b.basis_tree(), b.working_tree())

        self.log('delta.added = %r' % delta.added)

        self.assertEquals(len(delta.added), 1)
        self.assertEquals(delta.added[0][0], 'foo')
        self.failIf(delta.modified)

    def test_add_in_unversioned(self):
        """Try to add a file in an unversioned directory.

        smart_add may eventually add the parent as necessary, but simple
        branch add doesn't do that.
        """
        from bzrlib.branch import Branch
        from bzrlib.errors import NotVersionedError

        b = Branch('.', init=True)

        self.build_tree(['foo/',
                         'foo/hello'])

        self.assertRaises(NotVersionedError,
                          b.add,
                          'foo/hello')
        
        self.check_and_upgrade()

        
    def test_subdir_add(self):
        """Add in subdirectory should add only things from there down"""
        
        from bzrlib.branch import Branch
        from bzrlib.commands import run_bzr
        
        eq = self.assertEqual
        ass = self.assert_
        chdir = os.chdir
        
        b = Branch('.', init=True)
        self.build_tree(['src/', 'README'])
        
        eq(sorted(b.unknowns()),
           ['README', 'src'])
        
        eq(run_bzr(['add', 'src']), 0)
        
        self.build_tree(['src/foo.c'])
        
        chdir('src')
        eq(run_bzr(['add']), 0)
        
        eq(sorted(b.unknowns()), 
           ['README'])
        eq(len(b.inventory), 3)
                
        chdir('..')
        eq(run_bzr(['add']), 0)
        eq(list(b.unknowns()), [])

        self.check_and_upgrade()


    def check_and_upgrade(self):
        """After all the above changes, run the check and upgrade commands.

        The upgrade should be a no-op."""
        b = Branch('.')
        debug('branch has %d revisions', b.revno())
        
        debug('check branch...')
        from bzrlib.check import check
        check(b)
        
        debug('upgrade branch...')
        from bzrlib.upgrade import upgrade
        upgrade(b)
        
        debug('check branch...')
        from bzrlib.check import check
        check(b)
        

        
        
class SubdirCommit(TestCaseInTempDir):

    def test_subdir_commit(self):
        """Test committing a subdirectory, and committing within a directory."""
        run_bzr = self.run_bzr
        eq = self.assertEqual

        self.build_tree(['a/', 'b/'])
        
        run_bzr('init')
        b = Branch('.')
        
        for fn in ('a/one', 'b/two', 'top'):
            file(fn, 'w').write('old contents')
            
        run_bzr('add')
        run_bzr('commit', '-m', 'first revision')
        
        for fn in ('a/one', 'b/two', 'top'):
            file(fn, 'w').write('new contents')
            
        debug('start selective subdir commit')
        run_bzr('commit', 'a', '-m', 'commit a only')
        
        old = b.revision_tree(b.lookup_revision(1))
        new = b.revision_tree(b.lookup_revision(2))
        
        eq(new.get_file_by_path('b/two').read(), 'old contents')
        eq(new.get_file_by_path('top').read(), 'old contents')
        eq(new.get_file_by_path('a/one').read(), 'new contents')
        
        os.chdir('a')
        # commit from here should do nothing
        run_bzr('commit', '.', '-m', 'commit subdir only', '--unchanged')
        v3 = b.revision_tree(b.lookup_revision(3))
        eq(v3.get_file_by_path('b/two').read(), 'old contents')
        eq(v3.get_file_by_path('top').read(), 'old contents')
        eq(v3.get_file_by_path('a/one').read(), 'new contents')
                
        # commit in subdirectory commits whole tree
        run_bzr('commit', '-m', 'commit whole tree from subdir')
        v4 = b.revision_tree(b.lookup_revision(4))
        eq(v4.get_file_by_path('b/two').read(), 'new contents')        
        eq(v4.get_file_by_path('top').read(), 'new contents')
        
        # TODO: factor out some kind of assert_tree_state() method
        

if __name__ == '__main__':
    import unittest
    unittest.main()
    

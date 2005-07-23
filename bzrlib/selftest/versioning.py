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


from bzrlib.selftest import InTempDir

class Mkdir(InTempDir):
    def runTest(self): 
        """Basic 'bzr mkdir' operation"""
        from bzrlib.commands import run_bzr
        import os

        run_bzr(['init'])
        run_bzr(['mkdir', 'foo'])
        self.assert_(os.path.isdir('foo'))

        self.assertRaises(OSError, run_bzr, ['mkdir', 'foo'])

        from bzrlib.diff import compare_trees, TreeDelta
        from bzrlib.branch import Branch
        b = Branch('.')
        
        delta = compare_trees(b.basis_tree(), b.working_tree())

        self.assertEquals(len(delta.added), 1)
        self.assertEquals(delta.added[0][0], 'foo')
        self.failIf(delta.modified)



class AddInUnversioned(InTempDir):
    def runTest(self):
        """Try to add a file in an unversioned directory.

        smart_add may eventually add the parent as necessary, but simple
        branch add doesn't do that.
        """
        from bzrlib.branch import Branch
        import os
        from bzrlib.errors import NotVersionedError

        b = Branch('.', init=True)

        self.build_tree(['foo/',
                         'foo/hello'])

        self.assertRaises(NotVersionedError,
                          b.add,
                          'foo/hello')
        
        
class SubdirCommit(InTempDir):
    def runTest(self):
        """Various commits from a subdirectory"""
        
        from bzrlib.branch import Branch
        from bzrlib.commands import run_bzr
        import os
        
        eq = self.assertEqual
        ass = self.assert_
        chdir = os.chdir
        
        b = Branch('.', init=True)
        self.build_tree(['src/', 'src/foo.c', 'README'])
        
        eq(sorted(b.unknowns()),
                         ['README', 'src'])
        
        eq(run_bzr(['version']), 0)
        
        eq(run_bzr(['add']), 0)
        
        eq(run_bzr(['commit', '-m', 'initial tree']), 0)
        
        inv = b.get_revision_inventory(b.lookup_revision(1))
        
        eq(len(inv), 4)   # including root

        file('toplevel', 'w').write('top level file')
        chdir('src')
        file('more.c', 'w').write('more content')
        eq(run_bzr(['add']), 0)
        
        ass(b.inventory.path2id('src/more.c'))
        eq(list(b.unknowns()), ['toplevel'])


TEST_CLASSES = [
    Mkdir,
    AddInUnversioned,
    ]

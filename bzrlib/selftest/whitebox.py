#! /usr/bin/python

import os
import unittest

from bzrlib.selftest import InTempDir, TestBase
from bzrlib.branch import ScratchBranch, Branch
from bzrlib.errors import NotBranchError, NotVersionedError


class Unknowns(InTempDir):
    def runTest(self):
        b = Branch('.', init=True)

        self.build_tree(['hello.txt',
                         'hello.txt~'])

        self.assertEquals(list(b.unknowns()),
                          ['hello.txt'])


class Revert(InTempDir):
    """Test selected-file revert"""
    def runTest(self):
        b = Branch('.', init=True)

        self.build_tree(['hello.txt'])
        file('hello.txt', 'w').write('initial hello')

        self.assertRaises(NotVersionedError,
                          b.revert, ['hello.txt'])
        
        b.add(['hello.txt'])
        b.commit('create initial hello.txt')

        self.check_file_contents('hello.txt', 'initial hello')
        file('hello.txt', 'w').write('new hello')
        self.check_file_contents('hello.txt', 'new hello')

        # revert file modified since last revision
        b.revert(['hello.txt'])
        self.check_file_contents('hello.txt', 'initial hello')

        # reverting again causes no change
        b.revert(['hello.txt'])
        self.check_file_contents('hello.txt', 'initial hello')



class RenameDirs(InTempDir):
    """Test renaming directories and the files within them."""
    def runTest(self):
        b = Branch('.', init=True)
        self.build_tree(['dir/', 'dir/sub/', 'dir/sub/file'])
        b.add(['dir', 'dir/sub', 'dir/sub/file'])

        b.commit('create initial state')

        # TODO: lift out to a test helper that checks the shape of
        # an inventory
        
        revid = b.revision_history()[0]
        self.log('first revision_id is {%s}' % revid)
        
        inv = b.get_revision_inventory(revid)
        self.log('contents of inventory: %r' % inv.entries())

        self.check_inventory_shape(inv,
                                   ['dir', 'dir/sub', 'dir/sub/file'])

        b.rename_one('dir', 'newdir')

        self.check_inventory_shape(b.inventory,
                                   ['newdir', 'newdir/sub', 'newdir/sub/file'])

        b.rename_one('newdir/sub', 'newdir/newsub')
        self.check_inventory_shape(b.inventory,
                                   ['newdir', 'newdir/newsub',
                                    'newdir/newsub/file'])

        


class BranchPathTestCase(TestBase):
    """test for branch path lookups

    Branch.relpath and bzrlib.branch._relpath do a simple but subtle
    job: given a path (either relative to cwd or absolute), work out
    if it is inside a branch and return the path relative to the base.
    """

    def runTest(self):
        from bzrlib.branch import _relpath
        import tempfile, shutil
        
        savedir = os.getcwdu()
        dtmp = tempfile.mkdtemp()

        def rp(p):
            return _relpath(dtmp, p)
        
        try:
            # check paths inside dtmp while standing outside it
            self.assertEqual(rp(os.path.join(dtmp, 'foo')), 'foo')

            # root = nothing
            self.assertEqual(rp(dtmp), '')

            self.assertRaises(NotBranchError,
                              rp,
                              '/etc')

            # now some near-miss operations -- note that
            # os.path.commonprefix gets these wrong!
            self.assertRaises(NotBranchError,
                              rp,
                              dtmp.rstrip('\\/') + '2')

            self.assertRaises(NotBranchError,
                              rp,
                              dtmp.rstrip('\\/') + '2/foo')

            # now operations based on relpath of files in current
            # directory, or nearby
            os.chdir(dtmp)

            self.assertEqual(rp('foo/bar/quux'), 'foo/bar/quux')

            self.assertEqual(rp('foo'), 'foo')

            self.assertEqual(rp('./foo'), 'foo')

            self.assertEqual(rp(os.path.abspath('foo')), 'foo')

            self.assertRaises(NotBranchError,
                              rp, '../foo')

        finally:
            os.chdir(savedir)
            shutil.rmtree(dtmp)

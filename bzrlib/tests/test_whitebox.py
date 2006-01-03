import os
import unittest

from bzrlib.tests import TestCaseInTempDir, TestCase
from bzrlib.branch import ScratchBranch, Branch
from bzrlib.errors import PathNotChild


class TestBranch(TestCaseInTempDir):

    def test_no_changes(self):
        from bzrlib.errors import PointlessCommit
        
        b = Branch.initialize(u'.')

        self.build_tree(['hello.txt'])

        self.assertRaises(PointlessCommit,
                          b.working_tree().commit,
                          'commit without adding',
                          allow_pointless=False)

        b.working_tree().commit('commit pointless tree',
                 allow_pointless=True)

        b.working_tree().add('hello.txt')
        
        b.working_tree().commit('commit first added file',
                 allow_pointless=False)
        
        self.assertRaises(PointlessCommit,
                          b.working_tree().commit,
                          'commit after adding file',
                          allow_pointless=False)
        
        b.working_tree().commit('commit pointless revision with one file',
                 allow_pointless=True)


class MoreTests(TestCaseInTempDir):

    def test_rename_dirs(self):
        """Test renaming directories and the files within them."""
        b = Branch.initialize(u'.')
        self.build_tree(['dir/', 'dir/sub/', 'dir/sub/file'])
        b.working_tree().add(['dir', 'dir/sub', 'dir/sub/file'])

        b.working_tree().commit('create initial state')

        # TODO: lift out to a test helper that checks the shape of
        # an inventory
        
        revid = b.revision_history()[0]
        self.log('first revision_id is {%s}' % revid)
        
        inv = b.repository.get_revision_inventory(revid)
        self.log('contents of inventory: %r' % inv.entries())

        self.check_inventory_shape(inv,
                                   ['dir', 'dir/sub', 'dir/sub/file'])

        b.working_tree().rename_one('dir', 'newdir')

        self.check_inventory_shape(b.working_tree().read_working_inventory(),
                                   ['newdir', 'newdir/sub', 'newdir/sub/file'])

        b.working_tree().rename_one('newdir/sub', 'newdir/newsub')
        self.check_inventory_shape(b.working_tree().read_working_inventory(),
                                   ['newdir', 'newdir/newsub',
                                    'newdir/newsub/file'])

    def test_relpath(self):
        """test for branch path lookups
    
        bzrlib.osutils._relpath do a simple but subtle
        job: given a path (either relative to cwd or absolute), work out
        if it is inside a branch and return the path relative to the base.
        """
        from bzrlib.osutils import relpath
        import tempfile, shutil
        
        savedir = os.getcwdu()
        dtmp = tempfile.mkdtemp()
        # On Mac OSX, /tmp actually expands to /private/tmp
        dtmp = os.path.realpath(dtmp)

        def rp(p):
            return relpath(dtmp, p)
        
        try:
            # check paths inside dtmp while standing outside it
            self.assertEqual(rp(os.path.join(dtmp, 'foo')), 'foo')

            # root = nothing
            self.assertEqual(rp(dtmp), '')

            self.assertRaises(PathNotChild,
                              rp,
                              '/etc')

            # now some near-miss operations -- note that
            # os.path.commonprefix gets these wrong!
            self.assertRaises(PathNotChild,
                              rp,
                              dtmp.rstrip('\\/') + '2')

            self.assertRaises(PathNotChild,
                              rp,
                              dtmp.rstrip('\\/') + '2/foo')

            # now operations based on relpath of files in current
            # directory, or nearby
            os.chdir(dtmp)

            FOO_BAR_QUUX = os.path.join('foo', 'bar', 'quux')
            self.assertEqual(rp('foo/bar/quux'), FOO_BAR_QUUX)

            self.assertEqual(rp('foo'), 'foo')

            self.assertEqual(rp('./foo'), 'foo')

            self.assertEqual(rp(os.path.abspath('foo')), 'foo')

            self.assertRaises(PathNotChild,
                              rp, '../foo')

        finally:
            os.chdir(savedir)
            shutil.rmtree(dtmp)

"""\
Test the uncommit command.
"""
from bzrlib.selftest import TestCaseInTempDir
from bzrlib.errors import BzrError

class TestUncommit(TestCaseInTempDir):
    def test_uncommit(self):
        """Test uncommit functionality."""
        bzr = self.capture 

        bzr('init')
        self.build_tree(['a', 'b', 'c'])

        bzr('add')
        bzr('commit -m initial')

        self.assertEquals(bzr('revno'), '1\n')

        open('a', 'wb').write('new contents of a\n')
        self.assertEquals(bzr('status'), 'modified:\n  a\n')
        bzr('commit -m second')

        self.assertEquals(bzr('status'), '')
        self.assertEquals(bzr('revno'), '2\n')

        txt = bzr('uncommit --dry-run --force')
        self.failIfEqual(txt.find('Dry-run'), -1)

        self.assertEquals(bzr('status'), '')
        self.assertEquals(bzr('revno'), '2\n')

        txt = bzr('uncommit --force')

        self.assertEquals(bzr('revno'), '1\n')
        self.assertEquals(bzr('status'), 'modified:\n  a\n')


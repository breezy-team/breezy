"""Black-box tests for bzr aliases.
"""

import os

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseInTempDir
from bzrlib.trace import mutter
from bzrlib.config import (config_dir, config_filename)

class TestAliases(TestCaseInTempDir):

    def test_aliases(self):

        def bzr(*args, **kwargs):
            return self.run_bzr(*args, **kwargs)[0]

        if os.path.isfile(config_filename()):
            # Something is wrong in environment, we risk overwriting users config 
            self.assert_(config_filename() + "exists, abort")
            
        os.mkdir(config_dir())
        open(config_filename(),'wb').write('[ALIASES]\nc=cat\nc1=cat -r 1')

        str = 'foo\n'

        bzr('init')
        open('a', 'wb').write(str)
        bzr('add', 'a')

        bzr('commit', '-m', '1')

        self.assertEquals(bzr('c', 'a'), str)

        open('a', 'wb').write('baz\n')
        bzr('commit', '-m', '2')

        self.assertEquals(bzr('c', 'a'), 'baz\n')
        self.assertEquals(bzr('c1', 'a'), str)

        # If --no-alias isn't working, we will not get retcode=3
        bzr('--no-aliases', 'c', 'a', retcode=3)




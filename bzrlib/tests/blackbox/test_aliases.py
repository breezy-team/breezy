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
        CONFIG=("[ALIASES]\n"
                "c=cat\n"
                "c1=cat -r 1\n"
                "c2=cat -r 1 -r2\n")

        open(config_filename(),'wb').write(CONFIG)


        str1 = 'foo\n'
        str2 = 'bar\n'

        bzr('init')
        open('a', 'wb').write(str1)
        bzr('add', 'a')

        bzr('commit', '-m', '1')

        self.assertEquals(bzr('c', 'a'), str1)

        open('a', 'wb').write(str2)
        bzr('commit', '-m', '2')

        self.assertEquals(bzr('c', 'a'), str2)
        self.assertEquals(bzr('c1', 'a'), str1)
        self.assertEquals(bzr('c1', '--revision', '2', 'a'), str2)

        # If --no-alias isn't working, we will not get retcode=3
        bzr('--no-aliases', 'c', 'a', retcode=3)

        bzr('c', '-r1', '-r2', retcode=3)
        bzr('c1', '-r1', '-r2', retcode=3)
        bzr('c2', retcode=3)
        bzr('c2', '-r1', retcode=3)
        bzr('c2', '-r1', retcode=3)

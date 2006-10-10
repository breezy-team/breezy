# Copyright (C) 2005, 2006 by Canonical Ltd
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

"""UI tests for bzr ignore."""


from cStringIO import StringIO
import os
import re
import sys

from bzrlib import ignores
import bzrlib
from bzrlib.branch import Branch
import bzrlib.bzrdir as bzrdir
from bzrlib.errors import BzrCommandError
from bzrlib.osutils import (
    has_symlinks,
    pathjoin,
    rmtree,
    terminal_width,
    )
from bzrlib.tests.HTTPTestUtil import TestCaseWithWebserver
from bzrlib.tests.test_sftp_transport import TestCaseWithSFTPServer
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree


class TestCommands(ExternalBase):

    def test_ignore_patterns(self):
        self.runbzr('init')
        self.assertEquals(self.capture('unknowns'), '')

        # is_ignored() will now create the user global ignore file
        # if it doesn't exist, so make sure we ignore it in our tests
        ignores._set_user_ignores(['*.tmp'])

        self.build_tree_contents(
            [('foo.tmp', '.tmp files are ignored by default'),
             ])
        self.assertEquals(self.capture('unknowns'), '')

        file('foo.c', 'wt').write('int main() {}')
        self.assertEquals(self.capture('unknowns'), 'foo.c\n')

        self.runbzr(['add', 'foo.c'])
        self.assertEquals(self.capture('unknowns'), '')

        # 'ignore' works when creating the .bzrignore file
        file('foo.blah', 'wt').write('blah')
        self.assertEquals(self.capture('unknowns'), 'foo.blah\n')
        self.runbzr('ignore *.blah')
        self.assertEquals(self.capture('unknowns'), '')
        self.assertEquals('*.blah\n', open('.bzrignore', 'rU').read())

        # 'ignore' works when then .bzrignore file already exists
        file('garh', 'wt').write('garh')
        self.assertEquals(self.capture('unknowns'), 'garh\n')
        self.runbzr('ignore garh')
        self.assertEquals(self.capture('unknowns'), '')
        self.assertEquals(file('.bzrignore', 'rU').read(), '*.blah\ngarh\n')
        
        # 'ignore' works with multiple arguments
        self.runbzr('ignore a b c')
        self.assertEquals(self.capture('unknowns'), '')
        self.assertEquals(file('.bzrignore', 'rU').read(), '*.blah\ngarh\na\nb\nc\n')
        
    def test_ignore_old_defaults(self):
        out, err = self.run_bzr('ignore', '--old-default-rules')
        self.assertContainsRe(out, 'CVS')
        self.assertEqual('', err)

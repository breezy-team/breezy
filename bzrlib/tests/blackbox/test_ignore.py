# Copyright (C) 2005, 2006 Canonical Ltd
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

from bzrlib import (
    ignores,
    osutils,
    )
import bzrlib
from bzrlib.branch import Branch
import bzrlib.bzrdir as bzrdir
from bzrlib.errors import BzrCommandError
from bzrlib.osutils import (
    has_symlinks,
    pathjoin,
    terminal_width,
    )
from bzrlib.tests.HTTPTestUtil import TestCaseWithWebserver
from bzrlib.tests.test_sftp_transport import TestCaseWithSFTPServer
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree


class TestCommands(ExternalBase):

    def test_ignore_absolutes(self):
        """'ignore' with an absolute path returns an error"""
        self.runbzr('init')
        self.run_bzr_error(('bzr: ERROR: NAME_PATTERN should not '
                            'be an absolute path\n',),
                           'ignore','/crud')
        
    def test_ignore_directories(self):
        """ignoring a directory should ignore directory tree.

        Also check that trailing slashes on directories are stripped.
        """
        self.runbzr('init')
        self.build_tree(['dir1/', 'dir1/foo',
                         'dir2/', 'dir2/bar',
                         'dir3/', 'dir3/baz'])
        self.runbzr('ignore dir1 dir2/')
        self.check_file_contents('.bzrignore', 'dir1\ndir2\n')
        self.assertEquals(self.capture('unknowns'), 'dir3\n')

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
        self.check_file_contents('.bzrignore', '*.blah\n')

        # 'ignore' works when then .bzrignore file already exists
        file('garh', 'wt').write('garh')
        self.assertEquals(self.capture('unknowns'), 'garh\n')
        self.runbzr('ignore garh')
        self.assertEquals(self.capture('unknowns'), '')
        self.check_file_contents('.bzrignore', '*.blah\ngarh\n')
       
    def test_ignore_multiple_arguments(self):
        """'ignore' works with multiple arguments"""
        self.runbzr('init')
        self.build_tree(['a','b','c','d'])
        self.assertEquals(self.capture('unknowns'), 'a\nb\nc\nd\n')
        self.runbzr('ignore a b c')
        self.assertEquals(self.capture('unknowns'), 'd\n')
        self.check_file_contents('.bzrignore', 'a\nb\nc\n')

    def test_ignore_no_arguments(self):
        """'ignore' with no arguments returns an error"""
        self.runbzr('init')
        self.run_bzr_error(('bzr: ERROR: ignore requires at least one '
                            'NAME_PATTERN or --old-default-rules\n',),
                           'ignore')

    def test_ignore_old_defaults(self):
        out, err = self.run_bzr('ignore', '--old-default-rules')
        self.assertContainsRe(out, 'CVS')
        self.assertEqual('', err)

